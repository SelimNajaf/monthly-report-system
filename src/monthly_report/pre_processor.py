"""Input pre-processing — PDF archiving, in-place sorting, quarantine, grouping.

Everything that touches the ``input/`` tree BEFORE aggregation lives here:

* STAGE -1 — :func:`archive_input_pdfs`: any ``.pdf`` dropped under ``input/`` is
  moved to ``input/PDF_ARCHIVE/``, where STAGE 1 reads it directly (ADR-003).
  :func:`pdf_sources` decides which archived PDFs a run reads.
* STAGE 0 — :func:`sort_input_files`: loose ``.docx`` at any depth are deep-
  sorted into their method folders; ASR/ARS files are quarantined on sight.
* Group discovery — :func:`discover_groups`: distinct ``(month, method,
  client)`` groups from the parsed cache, quarantining undatable files. Two
  passes: everything that leaves ``input/`` leaves in pass 1, so the corpus
  volume snapshot between the passes reflects what this run actually leaves
  behind — the group set is therefore stable across repeated runs.
* Housekeeping — :func:`prune_duplicate_docx`, :func:`prune_unsorted_redundant`,
  :func:`purge_replaced_quarantine`: self-healing cleanup of byte-identical
  duplicates, settled UnSorted leftovers, and quarantine copies a searchable
  report has replaced. Content-verified; redundant files move to ``input/_PRUNED/``.

All moves are no-clobber and Windows-lock-tolerant (:func:`move_to`).
"""

from __future__ import annotations

import errno
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import hashlib
import re

from . import date_detector, docx_reader, extractor, pdf_twin
from .console import progress_printer, safe_print
from .method_registry import (client_volume_ok, compile_sort_registry,
                              corpus_client_stats, detect_method,
                              is_active_client, is_allowed_standard,
                              is_excluded_client, min_total_client_volume,
                              resolve_client_by_field)
from .naming import PDF_ARCHIVE_DIR, PRUNED_DIR, QUARANTINE_DIR, UNSORTED_DIR
from .report_identity import (is_excluded, leading_token, report_key_of,
                              resolve_report_no)

#: Top-level folders under input/ that are NOT working report dirs and must be
#: skipped by every scan: the PDF archive, the quarantine, and the housekeeping
#: trash. A file parked in one of these is settled — never converted, sorted,
#: parsed or re-pruned.
SETTLED_DIRS = frozenset({PDF_ARCHIVE_DIR.casefold(),
                         QUARANTINE_DIR.casefold(),
                         PRUNED_DIR.casefold()})

#: Stage labels for the live progress counters. Kept here, next to the stages
#: they name, so the numbering in the operator's console matches the numbering in
#: this module's docstring and in main.py's stage comments.
#: Kept verbatim after ADR-003 removed the conversion: the label is what the
#: operator has learned to look for, and the GUI keys its stage off the
#: markers that follow it, not off this text. Only the verb on the lines
#: below it changed — "converting"/"converted" became "archiving"/"archived",
#: because that is what the stage now does.
STAGE_CONVERT = "Stage -1: PDF Convert"
STAGE_SORT = "Stage 0: Sorter"
STAGE_GROUP = "Stage 2: Grouping"


@dataclass(frozen=True)
class Scope:
    """A run's filter, in the pipeline's own vocabulary.

    ``month`` is a canonical ``YYYY-MM`` key (matching :func:`discover_groups`'s
    group key), or ``None`` for "any". ``method`` / ``client`` are upper-cased
    tokens or ``None``. Built by ``main.py`` from the CLI flags (or the GUI
    dropdowns) and threaded into the stages that must narrow their work.

    A default ``Scope()`` means "no filter", so every stage behaves exactly as it
    did before scoping existed.

    ``method`` is deliberately NOT part of :meth:`matches`. A compiled document is
    one month of one client across every method (ADR-004), so no discovered group
    is method-specific any more. The field survives because it still narrows real
    work upstream — ``archive_input_pdfs`` and ``pdf_sources`` read it — and it is
    applied as a ROW filter inside ``document_aggregator.build_monthly_report``.
    """

    month: str | None = None
    method: str | None = None
    client: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.month or self.method or self.client)

    def matches(self, month: str, client: str) -> bool:
        """True when a discovered ``(month, client)`` group is in scope.

        ``method`` is not consulted — see the class docstring.
        """
        return ((self.month is None or month == self.month)
                and (self.client is None or client.upper() == self.client))


def warn(message: str) -> None:
    """Print a warning in bold yellow, plain when the output is not a terminal.

    Redirected/piped runs (``python main.py > run.log``) must stay free of ANSI
    escapes so the log reads cleanly.
    """
    if sys.stdout.isatty():
        safe_print(f"\033[1;33m{message}\033[0m")
    else:
        safe_print(message)


def move_to(input_dir: Path, path: Path, folder: str, attempts: int = 4) -> bool:
    """Move a file into ``input/<folder>/`` (no-clobber).

    Returns True when moved, False when a same-named file already sits in the
    destination (left in place, never overwritten — no data loss).

    Retries briefly on a Windows sharing violation (``WinError 32``). A file that
    was just read or written is routinely still held for a moment by the AV
    scanner or the search indexer, and that lock clears on its own — failing on
    the first attempt would abort a move that succeeds 200 ms later. Raises
    ``OSError`` if the lock outlives the retries, so the caller decides.

    Uses ``os.replace`` rather than ``shutil.move`` deliberately. ``shutil.move``
    falls back to copy-then-unlink whenever ``os.rename`` raises ``OSError`` — and
    a locked file raises exactly that. The copy then succeeds (reading is allowed)
    and only the unlink fails, leaving the file in **both** places. ``os.replace``
    is atomic within a volume: it either moves the file or fails cleanly, never
    duplicating it. ``shutil.move`` stays as the fallback for a genuine
    cross-device move, where a copy is the only option.
    """
    dest_dir = input_dir / folder
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        return False
    for attempt in range(1, attempts + 1):
        try:
            try:
                os.replace(str(path), str(dest))
            except OSError as exc:
                if getattr(exc, "errno", None) != errno.EXDEV:
                    raise
                shutil.move(str(path), str(dest))   # different volume: copy is unavoidable
            return True
        except PermissionError:
            if attempt == attempts:
                raise
            time.sleep(0.5 * attempt)
    return False


def quarantine(input_dir: Path, path: Path) -> bool:
    """Move an unprocessable report into ``input/SKIPPED_REPORTS/`` (no-clobber)."""
    return move_to(input_dir, path, QUARANTINE_DIR)


def archive_input_pdfs(settings, method: str | None = None) -> dict[str, list]:
    """Pre-process: move every dropped ``.pdf`` into ``input/PDF_ARCHIVE/``.

    This stage used to convert PDFs to ``.docx`` with ``pdf2docx`` and archive the
    original. ADR-003 deleted the conversion: the pipeline now reads PDFs directly,
    so all that is left is to settle the file where the reader will find it. What
    took ~6.9 hours serially over the corpus is now a file move.

    Archiving happens **before** anything reads the file (operator's decision), which
    keeps ``main.py``'s invariant intact: only the stages ahead of group discovery
    mutate ``input/``. It also means the archive is the durable record of what
    arrived — a run killed after this stage loses nothing, because
    :func:`pdf_sources` finds the file there on the next run.

    Walks the whole ``input/`` tree except ``SETTLED_DIRS`` (a file already parked
    in the archive, the quarantine or the trash is settled). ``method`` scopes a run
    exactly as it did before: a PDF whose filename-detected method is a *known,
    different* method is left fully untouched, so a later unscoped run still picks
    it up. An indeterminate ``NDT`` filename is always archived — the real method
    lives inside the document.

    Returns ``{"archived", "skipped", "failed"}``. Never raises: a PDF that cannot
    be moved is reported and left in place, and the batch continues.
    """
    want_method = (method or "").upper() or None
    input_dir = Path(settings.input_dir)
    result: dict[str, list] = {"archived": [], "skipped": [], "failed": []}

    pdfs = [p for p in sorted(input_dir.rglob("*.pdf"))
            if not p.name.startswith("~$")
            and p.relative_to(input_dir).parts[0].casefold() not in SETTLED_DIRS]
    if not pdfs:
        return result

    in_scope: list[Path] = []
    out_of_scope = 0
    for pdf in pdfs:
        if want_method:
            detected = detect_method(leading_token(pdf.name), settings)
            if detected != "NDT" and detected != want_method:
                out_of_scope += 1
                continue
        in_scope.append(pdf)

    if out_of_scope:
        print(f"  [pdf] {out_of_scope} PDF(s) left untouched (outside "
              f"--method {want_method} scope)")
    if not in_scope:
        return result

    total = len(in_scope)
    safe_print(f"  [{STAGE_CONVERT}] [pdf] archiving {total} file(s) "
               f"across 1 core(s)...")

    # The ``[pdf] (done/total)`` token is load-bearing — the GUI matches it
    # (gui/services/progress.py) and its tests pin it. Kept exactly as the
    # conversion stage emitted it; only the verb changed, because the work did.
    # No pool: a file move is I/O the OS serialises anyway, so the denominator is
    # honest at one core rather than pretending to parallelism it cannot use.
    for done, pdf in enumerate(in_scope, 1):
        try:
            moved = move_to(input_dir, pdf, PDF_ARCHIVE_DIR)
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
            safe_print(f"  [{STAGE_CONVERT}] [pdf] ({done}/{total}) "
                       f"failed {pdf.name}: {error}")
            warn(f"[PDF Archive] {pdf.name} could not be archived ({error}). "
                 f"Left in place — it will be archived on the next run.")
            result["failed"].append((pdf.name, error))
            continue
        if moved:
            result["archived"].append(pdf.name)
            safe_print(f"  [{STAGE_CONVERT}] [pdf] ({done}/{total}) "
                       f"archived {pdf.name} -> input/{PDF_ARCHIVE_DIR}/")
        else:
            # A same-named PDF is already archived: this is the re-drop of a report
            # we hold. Left in place rather than overwriting the archived original.
            result["skipped"].append((pdf.name, "already archived"))
            safe_print(f"  [{STAGE_CONVERT}] [pdf] ({done}/{total}) "
                       f"archived {pdf.name} (name conflict — left in place)")
    return result


def pdf_sources(settings, method: str | None = None) -> list[Path]:
    """Which archived PDFs STAGE 1 should read this run.

    ``input/PDF_ARCHIVE/`` is deliberately in ``SETTLED_DIRS`` — no scan, sort or
    prune touches it. This is the one function that reads it, and it reads only
    ``*.pdf``: the archive holds originals, and since ADR-003 the original *is* the
    source. Nothing else about ``SETTLED_DIRS`` changes.

    Three exclusions, each one a rule the conversion stage already enforced:

    * **An existing ``.docx`` wins**, whether it is live or quarantined. Live: the
      aggregator dedupes twins by Report № and keeps the first path in sort order,
      so reading both would let machine-read output displace a hand-checked
      document. Quarantined: a report parked in ``SKIPPED_REPORTS/`` is one an
      operator has already been told about, and reading its PDF would silently
      resurrect it. Un-quarantining is an operator action, never a side effect of
      switching readers. Measured on the current corpus, this makes the stage
      inert — all 171 archived PDFs with no live ``.docx`` have a quarantined one,
      so nothing new enters until the migration removes those files deliberately.
    * **ASR/ARS is excluded pipeline-wide.** Reading one just to quarantine it
      seconds later is wasted work.
    * **Method scope**, on the same "known, different method" rule as archiving.

    Sorted, so a run is deterministic.
    """
    want_method = (method or "").upper() or None
    input_dir = Path(settings.input_dir)
    archive = input_dir / PDF_ARCHIVE_DIR
    if not archive.is_dir():
        return []

    # One pass for every .docx key we hold, not one scan per PDF. The archive and
    # the trash are excluded (a .docx in either is not a document we hold);
    # SKIPPED_REPORTS deliberately is NOT — see the docstring.
    settled = {PDF_ARCHIVE_DIR.casefold(), PRUNED_DIR.casefold()}
    held = {report_key_of(p.name) for p in input_dir.rglob("*.docx")
            if not p.name.startswith("~$")
            and p.relative_to(input_dir).parts[0].casefold() not in settled}

    sources: list[Path] = []
    for pdf in sorted(archive.glob("*.pdf")):
        if pdf.name.startswith("~$"):
            continue
        if is_excluded(pdf.name, ""):
            continue
        if report_key_of(pdf.name) in held:
            continue
        if want_method:
            detected = detect_method(leading_token(pdf.name), settings)
            if detected != "NDT" and detected != want_method:
                continue
        sources.append(pdf)
    return sources


def sort_input_files(settings, progress_every: int = 0) -> dict[str, list]:
    """Pre-process: consolidate loose .docx (at ANY depth) into method subfolders.

    Runs before any aggregation. Walks the WHOLE input/ tree (recursive) so reports
    dropped inside nested, client-named folders (input/UnSorted/KHAZAR/, ...) are
    collected too — not just the root. A file is left untouched when it already lives
    inside a method folder (its first path component under input/ is a registered
    folder, e.g. input/UT/... or input/RT/...); this makes the pass idempotent and
    honours the "don't touch already-sorted files" constraint. Every other loose file
    is matched against the config-driven registry; the first matching method decides
    the destination, which is created on demand. Moves are in place via shutil.move and
    never overwrite an existing destination (no data loss). Returns
    {"moved", "unmatched", "conflict"}.

    ``progress_every`` turns on the live ``[Stage 0: Sorter] [i/N]`` counter,
    printing every N-th candidate (1 = all of them). The denominator can only be
    known here, after the walk, which is why the stage builds its own printer
    instead of taking one. Default 0 keeps the pass silent, as it has always
    been, so every existing caller and test is unaffected.
    """
    input_dir = Path(settings.input_dir)
    compiled = compile_sort_registry(settings)
    # Registered top-level method folders (case-folded) — files already parked in
    # one of these are considered settled and are skipped. The archive/quarantine/
    # trash folders are settled too: never re-sort files out of them.
    method_folders = _method_folders(settings) | SETTLED_DIRS
    moved: list[tuple[str, str]] = []
    unmatched: list[str] = []
    conflict: list[str] = []
    quarantined: list[str] = []

    # Materialised, not streamed: the counter needs a denominator, and rglob has
    # to be drained into a list to be sorted anyway.
    candidates = [p for p in sorted(input_dir.rglob("*.docx"))    # DEEP — every level
                  if not p.name.startswith("~$")]                 # Word lock/temp artifact
    emit = progress_printer(STAGE_SORT, len(candidates), progress_every)

    for index, path in enumerate(candidates, 1):
        rel = path.relative_to(input_dir)
        # Already inside a method folder (input/<Method>/...) -> leave untouched.
        if len(rel.parts) > 1 and rel.parts[0].casefold() in method_folders:
            emit(index, f"already sorted, left in place: {path.name}")
            continue
        # ASR/ARS reports are excluded entirely: quarantine them in-place during
        # the sort so they never reach a working method folder.
        if is_excluded(path.name, ""):
            if quarantine(input_dir, path):
                quarantined.append(str(rel))
            emit(index, f"ASR/ARS quarantined: {path.name}")
            continue
        folder = next((f for _c, f, rx in compiled if rx.search(path.name)), None)
        if folder is None:
            unmatched.append(str(rel))
            emit(index, f"no method matched, left in place: {path.name}")
            continue
        target_dir = input_dir / folder
        target_dir.mkdir(parents=True, exist_ok=True)
        dest = target_dir / path.name
        if dest.exists():                                  # never clobber existing
            conflict.append(f"{rel} -> {folder}/ (already exists)")
            emit(index, f"name conflict, left in place: {path.name}")
            continue
        shutil.move(str(path), str(dest))
        moved.append((path.name, folder))
        emit(index, f"Sorting report into method folder: {path.name} -> input/{folder}/")
    return {"moved": moved, "unmatched": unmatched, "conflict": conflict,
            "quarantined": quarantined}


def discover_groups(settings, cache: dict[Path, list], scope: Scope | None = None,
                    progress_every: int = 0):
    """Discover distinct ``(YYYY-MM, client)`` groups from the ``cache``.

    Returns ``(groups, quarantined)`` where ``groups`` is a sorted list of
    ``(month, client_code, file_count, methods)`` and ``quarantined`` is a list of
    ``(name, reason)``. ``methods`` is the sorted tuple of NDT tokens the group's
    files carry — reporting only, never part of the key: one client-month is ONE
    compiled document covering every method it contains, and the method travels on
    each row instead (ADR-004). Files are **moved** to ``input/SKIPPED_REPORTS/``
    (and dropped from the cache) when they are ASR/ARS documents (excluded
    entirely), belong to an excluded client (settings.yaml ``excluded_clients``), or
    have no detectable inspection date. (Unreadable/corrupt files were already
    quarantined at the parallel-read stage.) Wrong-month / other-client files are
    NOT quarantined — they belong to another group.

    Two passes, and the split matters. Pass 1 classifies every file and quarantines
    everything unprocessable — it is the ONLY place a file leaves ``input/`` here.
    The corpus client-volume snapshot is then taken over what remains, and pass 2
    applies the volume gate and forms the groups. Snapshotting between the passes is
    what makes the pipeline a fixed point: the snapshot used to be taken before this
    run's quarantining and consumed after it, so a client sitting exactly on
    ``min_total_client_volume`` cleared the floor on the run that removed one of its
    files and failed it on the next.

    The source files behind each group are published on
    :attr:`discover_groups.last_members` (``{(month, client): [Path, ...]}``,
    covering every DISCOVERED group, not just the in-scope ones) so a caller can ask
    which files a group is built from without re-deriving the classification, and the
    volume snapshot on :attr:`discover_groups.last_client_stats` so a caller need not
    recompute (and risk disagreeing with) the numbers this call decided on. Same
    side-channel idiom as :attr:`parse_cache.read_many_cached.last_stats`; the return
    contract below is unchanged.

    ``scope`` narrows the **returned groups** to those matching a run's filter
    (see :class:`Scope`). Quarantine is deliberately NOT scoped: an ASR/ARS or
    dateless file is unprocessable under *any* filter, so moving it to
    ``SKIPPED_REPORTS/`` is correct cleanup regardless of what the user selected —
    and a dateless file has no month to scope by. Only which groups get *built*
    downstream is filtered; every out-of-scope, datable report is left exactly
    where it is.

    ``progress_every`` turns on the live ``[Stage 2: Grouping] [i/N]`` counter
    (see :func:`console.progress_printer`); 0 keeps the pass silent as before.
    """
    scope = scope or Scope()
    input_dir = Path(settings.input_dir)
    groups: dict[tuple[str, str], list[Path]] = {}
    #: Methods seen per group, in the same key space as ``groups``. Reporting only.
    group_methods: dict[tuple[str, str], set[str]] = {}
    quarantined: list[tuple[str, str]] = []
    #: Pass-1 survivors: ``(path, month, method, client_code)``. Classification is
    #: separated from grouping so the volume snapshot between them sees the corpus
    #: this run actually leaves behind — see below.
    classified: list[tuple[Path, str, str, str]] = []
    #: Every date this run reconstructed, for the audit main.py writes:
    #: ``(filename, report_no, raw cell, final date, DateRepair)``. Collected here
    #: because this is the only stage that sees the raw cell and the repair together.
    repairs: list[tuple] = []

    def _send_to_quarantine(path: Path, reason: str) -> None:
        if quarantine(input_dir, path):
            quarantined.append((path.name, reason))
            print(f"  [quarantine] {path.name}: {reason} -> input/{QUARANTINE_DIR}/")
        else:
            print(f"  [quarantine] {path.name}: {reason} (name conflict — left in place)")

    # PASS 1 — classify, and quarantine everything unprocessable. Every file that
    # leaves input/ in this run leaves it here, BEFORE the volume snapshot below.
    #
    # Snapshot the keys before iterating: the loop pops quarantined files out of
    # ``cache`` as it goes, and the counter needs a denominator that does not move.
    paths = sorted(cache, key=str)
    emit = progress_printer(STAGE_GROUP, len(paths), progress_every)

    for index, path in enumerate(paths, 1):
        emit(index, f"Classifying report: {path.name}")
        meta = extractor.extract_meta(cache[path])
        report_no, _drift = resolve_report_no(meta, path)
        if is_excluded(path.name, report_no):
            _send_to_quarantine(path, "ASR/ARS excluded")
            cache.pop(path, None)
            continue
        raw_date = meta.get("date", "")
        # ``report_no`` is resolved just above, which is what lets the parser repair a
        # truncated year off the report number (KB-1); the archived PDF original's
        # filename lets it repair a cell cut past its month (KB-1b). A cell that
        # survives neither is still undatable and still quarantines here — the parser
        # refuses to invent a month, so this branch also catches the cells dateutil
        # used to fill in from the system clock.
        date, repaired = date_detector.parse_inspection_date_ex(
            raw_date, settings.dayfirst, report_no,
            pdf_twin.names_for(path, settings))
        if date is None:
            # Reason text unchanged: gui/services/quarantine_reasons_service maps this
            # exact marker to the "Undatable" chip, and quarantine_service.REASON_HINTS
            # to its operator hint.
            _send_to_quarantine(path, "no detectable inspection date")
            cache.pop(path, None)   # moved on disk -> drop from the reuse cache
            continue
        if repaired:
            # Printed once per repaired file per run. Deliberately shaped to match
            # NO regex in gui/services/progress.py: it is indented, carries no
            # ``[quarantine]``/``[method]`` tag those parsers key on, and does not
            # end in ``.pdf`` — which is also why the twin is named by its DATE and
            # never by its filename. See tests/test_date_repair.py.
            if repaired.source == "serial":
                how = f"year from {report_no}"
            else:
                how = (f"month/year from PDF twin "
                       f"{repaired.filename_date.isoformat()}, "
                       f"day from {repaired.day_source}")
            print(f"  [date repair] {path.name}: {raw_date!r} -> "
                  f"{date.isoformat()} ({how})")
            repairs.append((path.name, report_no, raw_date, date, repaired))
        method = detect_method(report_no, settings)
        # Client is resolved INTERNALLY-FIRST (document Client: field), prefix as
        # fallback — so two clients sharing a report-number prefix are separated.
        client_code, _name = resolve_client_by_field(meta, report_no, settings)
        # Retired accounts never form a group. Two equivalent blacklist signals:
        # the legacy `excluded_clients` list and the inline `active: false` flag —
        # either retires the client. This is the only stage where the client is
        # known AND the file is still on disk and movable, so it is where the
        # blacklist has to bite: retired files are quarantined out of input/.
        if is_excluded_client(client_code, settings) or not is_active_client(client_code, settings):
            _send_to_quarantine(path, f"retired/inactive client {client_code}")
            cache.pop(path, None)
            continue
        # Allowed-standards guardrail. The Standart is read from the FILENAME only —
        # the authoritative, clean source. The in-body ACC-Standard/Specification
        # cell is deliberately NOT consulted here: across the real corpus it holds
        # project doc references ("Doc No: Q00255 criteria Table 5"), edition
        # suffixes ("EEMUA 158,Edition 3,Section 7.5.4") and typos ("ISOP 10675-1")
        # that are not normative standards, so gating on it mass-quarantines
        # legitimate reports. A blank filename standard passes (left to the
        # sibling/method-default fallback downstream); a non-blank filename standard
        # not on settings.yaml `allowed_standards` is quarantined.
        std = docx_reader.parse_filename_metadata(path)["standard"]
        if std and not is_allowed_standard(std, settings):
            warn(f"[Quarantine Warning] {path.name} has unsupported NDT standard "
                 f"'{std}'. Quarantining to {QUARANTINE_DIR}/...")
            _send_to_quarantine(path, f"unsupported standard '{std}'")
            cache.pop(path, None)
            continue
        classified.append((path, f"{date.year:04d}-{date.month:02d}",
                           method, client_code))

    # Corpus-wide client volume: cumulative report count + distinct months per
    # client across the WHOLE parsed corpus (the cache holds every .docx under
    # input/), so a client's total history — not one isolated month — decides
    # whether it is a throwaway one-off. See method_registry.corpus_client_stats /
    # client_volume_ok.
    #
    # Taken HERE, after pass 1, and that placement is the fix for a real bug: the
    # snapshot used to be computed before any of this run's quarantining, while the
    # decisions it feeds were consumed after it. A single-month client sitting exactly
    # on min_total_client_volume therefore cleared the floor on the run that removed
    # one of its files and failed it on the next — so consecutive runs reported 104,
    # 102, then 101 groups, and main.py's stale-output sweep deleted the difference.
    # Post-quarantine it is identical by construction to the snapshot
    # document_aggregator.build_monthly_report computes over this same cache, and that
    # agreement is what makes the pipeline a fixed point. The volume gate below moves
    # no files, so it cannot itself cascade into the next run.
    stats = corpus_client_stats(cache.items(), settings)
    discover_groups.last_client_stats = stats

    # PASS 2 — the volume gate, then grouping. Reads only; nothing leaves input/ here.
    for path, month, method, client_code in classified:
        # An ACTIVE client whose CUMULATIVE report count across the whole input/
        # history is below the floor AND whose reports fall in only one month is a
        # throwaway one-off: it is skipped (no group) but its file is deliberately
        # LEFT in place — never quarantined — so a later month's reports can
        # accumulate and push it over the floor. A client spanning >= 2 months is
        # recurring and kept regardless of count.
        if not client_volume_ok(client_code, stats, settings):
            count, months = stats.get(client_code, (0, set()))
            print(f"  [low-volume] {path.name}: client {client_code} has {count} corpus "
                  f"report(s) in {len(months)} month(s) "
                  f"(< {min_total_client_volume(settings)}, single month) — "
                  f"left in place, not grouped")
            continue
        groups.setdefault((month, client_code), []).append(path)
        # Reporting only — the method is NOT in the key. One client-month is one
        # compiled document; each row names its own method (ADR-004).
        group_methods.setdefault((month, client_code), set()).add(method)
    discovered = [(m, cl, len(paths), tuple(sorted(group_methods.get((m, cl), ()))))
                  for (m, cl), paths in sorted(groups.items())]
    discover_groups.last_members = groups
    discover_groups.last_repairs = repairs
    if scope.is_empty:
        return discovered, quarantined
    selected = [g for g in discovered if scope.matches(g[0], g[1])]
    print(f"  [scope] {len(selected)} of {len(discovered)} discovered group(s) "
          f"match the filter; every other group is left untouched.")
    return selected, quarantined


#: The date repairs (KB-1 / KB-1b) the most recent :func:`discover_groups` call made,
#: as ``(filename, report_no, raw cell, date, DateRepair)``. main.py turns them into
#: ``output/date_repair_audit_<date>.md`` so an operator can check a reconstructed
#: date against the source document — nothing downstream reads it.
discover_groups.last_repairs = []

#: Populated by the most recent :func:`discover_groups` call — the source paths behind
#: every discovered group, keyed ``(month, client)``. Lets a caller (main.py's
#: incremental compile skip) map "these files changed" onto "these groups are stale"
#: without re-running the per-file classification.
discover_groups.last_members = {}

#: The corpus client-volume snapshot the most recent :func:`discover_groups` call
#: actually decided on, taken AFTER that run's quarantining. main.py's stale-output
#: sweep reads it rather than recomputing one, so the sweep and the discovery cannot
#: disagree about which clients are admitted — recomputing it independently, over a
#: PRE-quarantine corpus, is exactly how the two drifted apart and deleted live output.
discover_groups.last_client_stats = {}


# --------------------------------------------------------------------------- #
# Housekeeping — self-healing input cleanup (all recoverable, never a delete)
#
# Three passes clear the cruft the pipeline accumulates in input/. Every one is
# content-verified: a file is pruned only when a byte-identical survivor is
# proven to exist elsewhere, and "pruned" means moved to input/_PRUNED/ (via the
# same no-clobber, lock-tolerant move_to the archive and quarantine use), never
# unlinked — a wrong call is reviewable and restorable. Housekeeping is global,
# not scoped: like sorting and quarantine, it is correct cleanup under any run
# filter (see discover_groups).
# --------------------------------------------------------------------------- #

_HASH_CHUNK = 1 << 20    # 1 MiB — same streaming block as upload_ledger.hash_report
#: A Windows "copy of" marker: a parenthesised number at the very END of the stem
#: (``report (1).docx``). Anchored deliberately — these reports carry job numbers
#: in mid-name parentheses (``KF-MT-26-001 (2165)  (EEMUA 158).docx``), and an
#: unanchored pattern would read those as copy markers.
_COPY_MARKER = re.compile(r"(?:\s*\(\d+\)|[ _-]copy)$", re.IGNORECASE)
_EN_SUFFIX = re.compile(r"(?:_en)+$", re.IGNORECASE)


def _method_folders(settings) -> set[str]:
    """Case-folded names of the registered top-level method folders (UT, MPI, ...).

    The working report dirs, as opposed to the settled ones (archive/quarantine/
    trash). A file whose first path component under input/ is one of these is
    "already sorted".
    """
    registry = settings.raw.get("ndt_methods", {}) or {}
    return {str((spec or {}).get("folder", code)).casefold()
            for code, spec in registry.items()}


def _sha256(path: Path) -> str | None:
    """Streaming SHA-256 of a file, or ``None`` if it cannot be read.

    Never raises — a locked/vanished file returns ``None`` so the caller simply
    skips it (a file it cannot hash is one it must not prune). Streams in 1 MiB
    blocks so a 300 MB scanned-image .docx never loads whole into memory.
    """
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(_HASH_CHUNK), b""):
                h.update(block)
    except OSError:
        return None
    return h.hexdigest()


def _send_to_pruned(input_dir: Path, path: Path, note: str) -> bool:
    """Move a redundant file into ``input/_PRUNED/`` (no-clobber). Returns True if moved.

    The single disposal seam for all three passes — mirrors discover_groups'
    ``_send_to_quarantine``. Never fatal: a locked file (or a name already taken
    in the trash) is left in place and reported, and the next run retries it.
    """
    try:
        moved = move_to(input_dir, path, PRUNED_DIR)
    except OSError as exc:
        warn(f"[Prune] {path.name}: {note}, but could not be moved to trash "
             f"({type(exc).__name__}: {exc}). Left in place — retried next run.")
        return False
    if moved:
        print(f"  [pruned] {path.name}: {note} -> input/{PRUNED_DIR}/")
    else:
        print(f"  [pruned] {path.name}: {note} (name conflict in trash — left in place)")
    return moved


def _keeper_rank(path: Path, method_folders: set[str], input_dir: Path) -> tuple:
    """Sort key for choosing which of several byte-identical files to KEEP (lowest wins).

    In order: a copy already correctly sorted into a method folder beats a loose
    one (never prune the sorted copy in favour of an UnSorted twin); then the
    cleanest name — no ``(1)`` copy marker, fewest ``_en`` suffixes, shortest
    stem; finally the case-folded stem as a deterministic tie-break.
    """
    rel = path.relative_to(input_dir)
    not_sorted = 0 if (len(rel.parts) > 1 and rel.parts[0].casefold() in method_folders) else 1
    stem = path.stem
    has_copy = 1 if _COPY_MARKER.search(stem) else 0
    en = _EN_SUFFIX.search(stem)
    en_count = (len(en.group()) // len("_en")) if en else 0
    return (not_sorted, has_copy, en_count, len(stem), stem.casefold())


def _scan_docx(input_dir: Path):
    """Every working .docx under input/ — settled dirs and Word temp files excluded."""
    for p in input_dir.rglob("*.docx"):
        if p.name.startswith("~$"):
            continue
        if p.relative_to(input_dir).parts[0].casefold() in SETTLED_DIRS:
            continue
        yield p


def prune_duplicate_docx(settings) -> list[tuple[str, str]]:
    """Prune byte-identical duplicate .docx, keeping the cleanest-named survivor.

    Curated exports arrive as ``KF-RT-26-070.docx``, ``…_en.docx``,
    ``…_en_en.docx``, ``…(1).docx`` — same bytes, different names — and pile up in
    the method folders. This groups every working .docx by SHA-256 and, for each
    group of true duplicates, keeps one (see :func:`_keeper_rank`: the sorted,
    barest-named copy) and moves the rest to ``input/_PRUNED/``.

    Content-verified, so it can never merge two genuinely different reports.
    Returns ``(pruned_name, keeper_name)`` pairs.
    """
    input_dir = Path(settings.input_dir)
    method_folders = _method_folders(settings)
    by_hash: dict[str, list[Path]] = {}
    for path in _scan_docx(input_dir):
        digest = _sha256(path)
        if digest is not None:
            by_hash.setdefault(digest, []).append(path)

    pruned: list[tuple[str, str]] = []
    for group in by_hash.values():
        if len(group) < 2:
            continue
        keeper = min(group, key=lambda p: _keeper_rank(p, method_folders, input_dir))
        for dup in group:
            if dup == keeper:
                continue
            warn(f"[Duplicate] {dup.name} is byte-identical to {keeper.name} — "
                 f"keeping the cleaner name.")
            if _send_to_pruned(input_dir, dup, f"duplicate of {keeper.name}"):
                pruned.append((dup.name, keeper.name))
    return pruned


def prune_unsorted_redundant(settings) -> list[tuple[str, str]]:
    """Prune UnSorted leftovers already settled elsewhere (byte-identical).

    ``sort_input_files`` / ``convert_input_pdfs`` move files out of
    ``input/UnSorted/`` but their no-clobber rule leaves a copy behind on a name
    clash. This deletes such a leftover only when a byte-identical copy is proven
    to already sit in a method folder (.docx) or ``input/PDF_ARCHIVE/`` (.pdf) —
    so a same-named but *different* report that lost the race is kept for a human.

    Returns ``(pruned_name, settled_location)`` pairs.
    """
    input_dir = Path(settings.input_dir)
    unsorted_dir = input_dir / UNSORTED_DIR
    if not unsorted_dir.is_dir():
        return []
    method_folders = _method_folders(settings)

    # Content index of everything already settled: sorted .docx + archived .pdf.
    settled: dict[str, Path] = {}
    for p in _scan_docx(input_dir):
        rel = p.relative_to(input_dir)
        if len(rel.parts) > 1 and rel.parts[0].casefold() in method_folders:
            digest = _sha256(p)
            if digest is not None:
                settled.setdefault(digest, rel)
    archive_dir = input_dir / PDF_ARCHIVE_DIR
    if archive_dir.is_dir():
        for p in archive_dir.rglob("*.pdf"):
            if p.name.startswith("~$"):
                continue
            digest = _sha256(p)
            if digest is not None:
                settled.setdefault(digest, p.relative_to(input_dir))

    pruned: list[tuple[str, str]] = []
    for path in sorted(unsorted_dir.rglob("*")):
        if path.name.startswith("~$") or path.suffix.lower() not in (".docx", ".pdf"):
            continue
        digest = _sha256(path)
        if digest is None:
            continue
        where = settled.get(digest)
        if where is None:
            continue
        if _send_to_pruned(input_dir, path, f"already settled at input/{where.as_posix()}"):
            pruned.append((path.name, where.as_posix()))
    return pruned


def purge_replaced_quarantine(settings, cache: dict[Path, list]) -> list[str]:
    """Self-heal: drop quarantine copies replaced by a searchable, sorted report.

    When a report that was quarantined as an unreadable scanned image is later
    re-supplied as a searchable file — converted, sorted into its method folder,
    and successfully parsed — the old image-only copy in ``SKIPPED_REPORTS/`` is
    dead weight. This moves it to ``input/_PRUNED/`` so quarantine keeps meaning
    "unresolved".

    "Replaced" is proven by identity, not content: the successfully-parsed report
    (present in ``cache``, under a method folder) shares the quarantined file's
    :func:`report_key_of`. A quarantined report with no such active twin is left
    exactly where it is. Returns the purged names.

    ASR/ARS documents in quarantine are never purged. They are there because they
    are excluded pipeline-wide, not because they were unreadable, and an ASR shares
    its leading report token with the ordinary report of the same number
    (``KF-RT-26-053R1 ASR (KF 2123).docx`` vs ``KF-RT-26-053R1.docx``). They are two
    different documents, so that active twin is not a "searchable replacement" and
    must not retire the ASR. Only a stale copy of the SAME document is healed away.
    """
    input_dir = Path(settings.input_dir)
    quarantine_dir = input_dir / QUARANTINE_DIR
    if not quarantine_dir.is_dir():
        return []
    method_folders = _method_folders(settings)

    active = set()
    for path in cache:
        rel = path.relative_to(input_dir)
        if len(rel.parts) > 1 and rel.parts[0].casefold() in method_folders:
            active.add(report_key_of(path.name))

    purged: list[str] = []
    for path in sorted(quarantine_dir.rglob("*.docx")):
        if path.name.startswith("~$") or is_excluded(path.name, ""):
            continue
        if report_key_of(path.name) in active:
            warn(f"[Self-heal] {path.name}: a searchable copy is now sorted and "
                 f"parsed — retiring the quarantined original.")
            if _send_to_pruned(input_dir, path, "replaced by a searchable report"):
                purged.append(path.name)
    return purged
