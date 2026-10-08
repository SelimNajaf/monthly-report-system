"""Aggregate in-month reports into one monthly model, with retest numbering.

This is the core business stage. It reads every ``.docx`` in the input folder,
keeps the reports whose detected inspection date falls in the target month, and
flattens their weld rows into a single ordered table. The distinctive logic is
**retest sub-numbering**: a repaired weld re-inspected in a retest report (marker
``R1``/``R2``) is grouped under its original parent weld and given a lettered
suffix — parent ``4`` -> first retest ``4a`` -> second ``4b``. Cross-month
parent lookup is delegated to :mod:`~monthly_report.retest_tracker`.

Reads only
----------
This stage never moves, renames or deletes a source file. It is the LAST stage, and
the group set it is rendering was already decided — and printed — by
:func:`pre_processor.discover_groups` upstream; a file removed here would therefore
shrink the corpus only in time for the NEXT run, which is exactly how consecutive
runs came to report 104, then 102, then 101 groups. Every filter here (retired
client, corpus volume, twin dedup, unapproved standard) omits a ROW and records why
in ``report.skipped``, leaving the file where it sits.

I/O contract
------------
build_monthly_report(settings, translator) -> MonthlyReport
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import Counter
from dataclasses import dataclass, field, replace as _dc_replace
from pathlib import Path

from . import (date_detector, docx_reader, duplicate_identity, extractor,
               pdf_twin, report_no_mismatch, retest_tracker)
from .inspector_registry import resolve_inspector
from .method_registry import (client_volume_ok, corpus_client_stats,
                              detect_method, is_active_client,
                              is_allowed_standard_lenient, is_excluded_client,
                              is_informational, resolve_client_by_field)
from .naming import QUARANTINE_DIR, document_number
from .report_identity import (is_excluded, report_key, resolve_report_no,
                              retest_rank, squash, strip_retest)
from .text_norm import collapse_spaces, fold, fold_typography

_REJECT_TOKENS = ("reject", "imtina", "yarasız", "yarasiz", "fail", "nok",
                  "n.ok", "not accept")

#: Stable prefix of the ``report.skipped`` reason recorded when the standard gate
#: drops a row. ``main.py`` filters its run-end summary on this token, so it is a
#: contract: reword the tail freely, never this prefix.
UNAPPROVED_STANDARD_REASON = "unapproved standard"


def reject_item_header_labels(settings) -> bool:
    """``filtering.reject_item_header_labels`` (default ``False``).

    ``True``: a column header read as the Item: value (``Qty``, ``S/N``,
    ``DetailNo``, ``Number of holes``) or the ``N/A`` placeholder is rejected,
    and the row falls back to Description, then the weld items, as for any other
    rejected value. Changes the Item of compiled rows — the operator's switch.
    """
    block = (getattr(settings, "raw", None) or {}).get("filtering") or {}
    return block.get("reject_item_header_labels", False) is True


def collapse_standard_spaces_enabled(settings) -> bool:
    """Read ``filtering.collapse_standard_spaces`` — ON when the key is absent.

    ON by default, unlike the other switches in this file, and the reason is that
    the behaviour it replaces is not one worth preserving: the corpus prints ONE
    normative document under two spellings that differ by a single extra blank,
    which reads as two documents on a sheet that goes to the state.

    Turning it on was measured first, on 2026-09-18. Every document carrying the
    two-blank spelling is AZF — 17 of them — and not one AZF document can be
    filed: all 21 of them name only ``Doc No: Q…`` standards, which
    ``match_portal_standard`` answers ``none`` for, and 10 of the 17 never even
    reach that gate (``PORTAL_UPLOAD_CUTOFF``). So the fix cannot change a
    document that uploads. The key stays so it can be turned off.
    """
    block = (getattr(settings, "raw", None) or {}).get("filtering") or {}
    return bool(block.get("collapse_standard_spaces", True))


def _aggregate_result(welds: list[dict[str, str]],
                      tables: list[list[list[str]]] | None = None) -> str:
    """Roll a document's weld verdicts into one token — never blank.

    ``"Unfit"`` when **any** row rejects, otherwise ``"Fit"``. The match is a
    case-insensitive substring test covering the wording drift across templates
    ("reject"/"rejected"/"İmtina"/"yarasız"/"fail"/"nok" all reject; a genuine
    reject always dominates). Matching runs through
    :func:`~monthly_report.text_norm.fold` rather than ``str.casefold`` because
    the dotted ``İ`` casefolds to ``i`` + a combining dot, which would slip past
    the ``"imtina"`` token and read a rejected weld as accepted.

    Whole-document safety net: some templates (PMI, atypical DP) are not parsed
    by the generic weld reader, so ``welds`` is empty. In that case we scan every
    cell for a reject verdict — guarding against the ``Accept/Reject`` *header*
    cell (which literally contains "reject") by ignoring any cell that also
    mentions "accept". **Bulletproof default:** when nothing rejects the document
    rolls up to ``"Fit"`` (Yararlı) rather than blank, so Nəticə is never empty.
    """
    for w in welds:
        r = fold(w.get("result", "") or "")
        if any(tok in r for tok in _REJECT_TOKENS):
            return "Unfit"
    if not welds and tables is not None:
        for table in tables:
            for row in table:
                for cell in row:
                    c = fold(cell or "")
                    if "accept" in c:
                        continue  # paired "Accept/Reject" header — not a verdict
                    if any(tok in c for tok in _REJECT_TOKENS):
                        return "Unfit"
    return "Fit"


def _fill_missing_standards(records: list["ReportRow"]) -> None:
    """Borrow a blank ``Standart`` cell from a sibling in the same batch.

    Any record whose extracted standard is blank inherits the batch's most common
    non-empty standard (the other successfully-parsed documents of the same month,
    method and client). When the ENTIRE batch is blank there is nothing to borrow,
    so those cells are left ``""`` — the extracted emptiness is preserved rather
    than papered over with a forced method default (e.g. a PMI report with no
    standard must NOT acquire ``ASTM E1476``). In-place.

    **The batch is per METHOD, and that is load-bearing.** Under ADR-004 one
    document carries every method of a client-month, so borrowing across the whole
    record list would let a DP row inherit an MT row's ``EEMUA 158`` — a standard
    that document's inspection was never performed against. That is exactly the
    substitution the zero-substitution rule forbids, and it would be printed on an
    official sheet. Grouping by ``r.method`` keeps the behaviour byte-identical to
    the pre-merge, one-method-per-document batches. A row with no method token at
    all forms its own batch rather than joining a real one.
    """
    batches: dict[str, list[ReportRow]] = {}
    for r in records:
        batches.setdefault(r.method or "", []).append(r)
    for batch in batches.values():
        present = [r.standard.strip() for r in batch if (r.standard or "").strip()]
        if not present:
            continue
        fallback = Counter(present).most_common(1)[0][0]
        for r in batch:
            if not (r.standard or "").strip():
                r.standard = fallback


@dataclass
class ReportRow:
    """One **document** row in the monthly summary directory (1 doc = 1 row)."""
    date: _dt.date
    date_str: str           # formatted inspection date, e.g. 14.01.2026
    report_no: str
    series_key: str
    retest_rank: int
    client: str
    document_name: str      # "[Report No] ([Job No])", e.g. KF-MT-26-001 (2165)
    standard: str           # from filename, else ACC Standard / Specification
    item_detail: str        # inspected item from the metadata header (Item:/Item Insp.)
    result: str             # aggregated verdict token: "Fit" / "Unfit" / ""
    equipment: str = ""     # instrument from the Equipment block; JSON sidecar only,
                            # never rendered in the PDF ("" when the method has no
                            # such field, e.g. DP)
    method: str = ""        # this document's own NDT method token (RT/MPI/UT/...).
                            # Rendered as the PDF's Üsul column and mirrored into
                            # the sidecar's items_table[].method, so both read the
                            # SAME value rather than each re-deriving it.
    match_key: tuple = ()
    source_order: tuple = ()
    seq: str = ""                       # "4" or "4a"
    sort_key: tuple = (0, 0)
    is_orphan_retest: bool = False
    is_pulled_parent: bool = False      # original imported from a PREVIOUS month
    # The file this row was read from. Internal only — never rendered, never in
    # the sidecar, never compared: retest_tracker reads the retest's own welds
    # through it (retest.pull_weld_check).
    source_path: object = field(default=None, compare=False, repr=False)


@dataclass
class MonthlyReport:
    month: str
    document_number: str
    title: str
    method: str = ""
    client_code: str = ""
    client_name: str = ""
    rows: list[ReportRow] = field(default_factory=list)
    signatures: dict[str, str] = field(default_factory=dict)
    source_reports: list[str] = field(default_factory=list)
    untranslated: list[str] = field(default_factory=list)
    retest_pairs: int = 0
    pulled_parents: int = 0   # cross-month originals imported for retest traceability
    skipped: list[tuple[str, str]] = field(default_factory=list)   # (file, reason)
    discrepancies: list[tuple[str, str, str]] = field(default_factory=list)  # (file, filename_no, internal_no)


#: Stable prefix of the ``report.skipped`` reason recorded for a source staged from a
#: share folder named ``delete`` (``filtering.exclude_delete_folder_sources``). The
#: coverage audit buckets on it; the tail names the share path.
DELETE_FOLDER_REASON = "from delete folder"


def exclude_delete_folder_sources(settings) -> bool:
    """``filtering.exclude_delete_folder_sources`` (default ``False``).

    ``True``: a local file whose bytes match a share file under a ``delete`` folder
    (ingestion manifest, any case) feeds no row. The file is left where it sits.
    """
    block = (getattr(settings, "raw", None) or {}).get("filtering") or {}
    return block.get("exclude_delete_folder_sources", False) is True


#: ``(path, size, mtime_ns) -> sha256`` for the files hashed by
#: :func:`delete_folder_sources`, so one run hashes each candidate once, not per group.
_DIGEST_MEMO: dict[tuple, str | None] = {}


def delete_folder_sources(settings, paths) -> dict[Path, str]:
    """``{local path: share path}`` for every path staged from a ``delete`` folder.

    The ingestion manifest records the SHA-256 of every share file it copied. A
    local file is "from a delete folder" when its content hash equals such a file's
    hash under a ``delete`` path segment, and equals no file outside one: identical
    bytes that also live in a working folder are not attributed to ``delete``.
    Only files whose size matches a delete-folder entry are hashed. A missing or
    unreadable manifest returns ``{}`` (nothing excluded).
    """
    from .parse_cache import content_hash
    from .services.ingestion_registry import DEFAULT_REGISTRY_REL, read_manifest
    from .services.network_ingestion import under_delete_folder
    files = read_manifest(Path(settings.project_root) / DEFAULT_REGISTRY_REL).get("files") or {}
    deleted: dict[str, str] = {}
    live: set[str] = set()
    sizes: set[int] = set()
    for rec in files.values():
        digest = rec.get("sha256")
        if not digest:
            continue
        unc = str(rec.get("unc_path") or "")
        if under_delete_folder(unc):
            deleted.setdefault(digest, unc)
            sizes.add(rec.get("size"))
        else:
            live.add(digest)
    for digest in live:
        deleted.pop(digest, None)
    if not deleted:
        return {}
    found: dict[Path, str] = {}
    for path in paths:
        path = Path(path)
        try:
            st = path.stat()
        except OSError:
            continue
        if st.st_size not in sizes:
            continue
        key = (str(path), st.st_size, st.st_mtime_ns)
        if key not in _DIGEST_MEMO:
            _DIGEST_MEMO[key] = content_hash(path)
        unc = deleted.get(_DIGEST_MEMO[key])
        if unc is not None:
            found[path] = unc
    return found


def _copy_block_reason(path, tables, meta: dict | None, items) -> str | None:
    """The ``report.skipped`` reason when ``path`` is a name/body-mismatched copy.

    ``None`` when the serials agree or no other file carries the same tables under
    the body's serial — only a copy is blocked, see :mod:`report_no_mismatch`.
    """
    pair = report_no_mismatch.mismatch_of(path, tables, meta)
    if pair is None:
        return None
    twins = report_no_mismatch.copy_siblings(path, tables, pair[1], items)
    if not twins:
        return None
    return (f"{report_no_mismatch.BLOCK_REASON}: ad {pair[0]} ≠ içəri {pair[1]}, "
            f"{twins[0].name} ilə eyni cədvəl — sətir buraxıldı")


def _row_from_doc(path, tables, meta: dict, report_no: str, date: _dt.date,
                  settings, method: str | None = None) -> ReportRow:
    """Build one :class:`ReportRow` from an already-parsed document.

    Shared by the in-month loop and the cross-month parent pull so both produce
    rows identically: filename-authoritative Document Name + Standard (with an
    in-body ACC-Standard fallback), an RT/other verdict roll-up, and the
    Item → Description → per-row İtem/Detal fallback chain.
    """
    series = strip_retest(report_no)
    rank = retest_rank(report_no)
    client = squash(meta.get("client", ""))

    fn = docx_reader.parse_filename_metadata(path)
    document_name = fn["document_name"] or report_no
    standard = fn["standard"] or extractor.extract_standard(tables)
    if collapse_standard_spaces_enabled(settings):
        standard = collapse_spaces(standard)

    eff_method = method or detect_method(report_no, settings)
    welds = (extractor.extract_rt_welds(tables) if eff_method == "RT"
             else extractor.extract_welds(tables))

    header_labels = reject_item_header_labels(settings)
    item_detail = extractor.extract_item_global(tables, header_labels)
    if extractor.item_is_bad(item_detail, header_labels):
        item_detail = squash(meta.get("description", ""))
    if extractor.item_is_bad(item_detail, header_labels):
        valid_items = [squash(w.get("item", "")) for w in welds
                       if not extractor.item_is_bad(w.get("item", ""), header_labels)]
        item_detail = Counter(valid_items).most_common(1)[0][0] if valid_items else ""

    # Informational methods (UTM, HrT) never carry a Yararlı/Yarasız verdict —
    # their Nəticə column always reads "Məlumat üçün".
    result = ("Info" if is_informational(eff_method, settings)
              else _aggregate_result(welds, tables))

    return ReportRow(
        date=date,
        date_str=date.strftime(settings.date_format),
        report_no=report_no,
        series_key=series,
        retest_rank=rank,
        client=client,
        document_name=document_name,
        standard=standard,
        item_detail=item_detail,
        result=result,
        equipment=extractor.extract_equipment(tables),
        # Resolved once, here, and carried on the row: the renderer's Üsul column
        # and the sidecar both read it instead of re-running detect_method.
        method=eff_method,
        source_order=(date, report_no),
        match_key=(series,),   # document-level: retest groups under its parent
        source_path=path,
    )


def build_monthly_report(settings, translator, method: str | None = None,
                         client_code: str | None = None,
                         seq: int = 1,
                         cache: dict | None = None,
                         *, stats: dict | None = None) -> MonthlyReport:
    """Aggregate the in-month reports into a **1-document-=-1-row** summary.

    Each source ``.docx`` contributes exactly one :class:`ReportRow`: its metadata
    header supplies İtem / Detal, and its internal weld table is rolled up into a
    single ``Fit`` / ``Unfit`` verdict. When ``client_code`` is given only that
    client's reports are included — and under ADR-004 that, with the month, is the
    whole grouping: one compiled document per client-month, every NDT method in it,
    each row naming its own in the Üsul column. ``method`` is therefore normally
    ``None``. Passing a token (``"MT"``/``"UT"``/``"RT"`` — the ``--method`` flag)
    still narrows the rows to that method, which produces a deliberately PARTIAL
    document: a diagnostic view, never a deliverable. ``cache``
    (``{Path: tables}`` from :func:`docx_reader.read_many`) avoids re-parsing; when
    omitted the files are read from disk so the CLI path still works standalone.
    """
    if cache is not None:
        items = sorted(cache.items(), key=lambda kv: str(kv[0]))
    else:
        # Recursive, in-place scan: reports are read wherever they sit under input/
        # — flat or in manual subfolders. Word lock/temp artifacts and the
        # quarantine folder are skipped.
        input_dir = Path(settings.input_dir)
        files = sorted(p for p in input_dir.rglob("*.docx")
                       if not p.name.startswith("~$")
                       and p.relative_to(input_dir).parts[0].casefold() != QUARANTINE_DIR.casefold())
        items = []
        for p in files:
            try:
                items.append((p, docx_reader.read_tables(p)))
            except Exception as exc:
                items.append((p, exc))

    records: list[ReportRow] = []
    used_reports: list[tuple[_dt.date, str]] = []
    signatures_seen: list[dict[str, str]] = []
    skipped: list[tuple[str, str]] = []
    discrepancies: list[tuple[str, str, str]] = []
    seen_report_keys: set[str] = set()   # dedup twin files (…_en_en) by Report №
    block_copies = report_no_mismatch.block_enabled(settings)
    # filtering.exclude_delete_folder_sources (default off): {} leaves every path in.
    from_delete = (delete_folder_sources(settings, [p for p, _ in items])
                   if exclude_delete_folder_sources(settings) else {})

    # Corpus-wide client volume, over the SAME items (the whole parsed corpus in the
    # main.py path, the whole input/ tree in the standalone path). Mirrors the
    # discover_groups gate so this stage rejects a retired/inactive or throwaway-volume
    # client even when called directly (tests / CLI), independent of pre_processor.
    #
    # ``stats`` lets the orchestrator pass in the snapshot discover_groups already
    # decided on: identical by construction (same post-quarantine corpus), but
    # computed once per RUN instead of once per GROUP — this is a full extract_meta
    # pass over the whole corpus, and a hundred-group run repeated it a hundred times.
    # Sharing it also makes the agreement between the two stages structural rather
    # than coincidental. Omitted, it is derived here as before.
    if stats is None:
        stats = corpus_client_stats(items, settings)

    for path, tables in items:
        if isinstance(tables, Exception):  # corrupted / unreadable: preserve run
            skipped.append((path.name, f"unreadable: {tables}"))
            continue

        meta = extractor.extract_meta(tables)
        # Report number: filename is authoritative; flag any internal drift.
        # Resolved BEFORE the date because the date parser needs it: a cell whose
        # year the inspector truncated ("17.03.202") is repaired from the report
        # number's -<YY>- (KB-1). Only the assignment moved up — every skip below
        # still fires in the same order, so a file's recorded skip reason is
        # unchanged.
        report_no, drift = resolve_report_no(meta, path)
        # ``pdf_twin.names_for`` is the same twin lookup discover_groups used, so a
        # cell repaired from its PDF original (KB-1b) lands in the same month here.
        date = date_detector.parse_inspection_date(
            meta.get("date", ""), settings.dayfirst, report_no,
            pdf_twin.names_for(path, settings))
        if not date_detector.is_in_month(date, settings.target_month):
            skipped.append((path.name, f"date {meta.get('date','?')} not in {settings.target_month}"))
            continue

        # ASR/ARS documents are excluded entirely (defense — normally already
        # quarantined at the discover stage before they reach here).
        if is_excluded(path.name, report_no):
            skipped.append((path.name, "ASR/ARS excluded"))
            continue
        if method is not None and detect_method(report_no, settings) != method:
            skipped.append((path.name, f"method {detect_method(report_no, settings)} != {method}"))
            continue
        # Separate compiled PDF per client: keep only this group's client. Resolved
        # INTERNALLY-FIRST (the document's Client: field), report-number prefix as
        # fallback — so Khazar Fabrication vs Engineering (same KF prefix) split.
        code, _name = resolve_client_by_field(meta, report_no, settings)
        # Retired accounts never compile (defense — normally already quarantined at
        # the discover stage before they reach here). Both blacklist signals honoured.
        if is_excluded_client(code, settings) or not is_active_client(code, settings):
            skipped.append((path.name, f"client {code} inactive/excluded"))
            continue
        # Corpus-wide low-volume filter (defense mirror of discover_groups): an
        # active client below the cumulative floor and present in a single month is a
        # throwaway one-off and does not compile. Not quarantined here either — the
        # file is left in place so future months can accumulate.
        if not client_volume_ok(code, stats, settings):
            skipped.append((path.name, f"client {code} below min_total_client_volume"))
            continue
        if client_code is not None and code != client_code:
            skipped.append((path.name, f"client {code} != {client_code}"))
            continue
        # A source the inspector set aside in a share folder named "delete" feeds no
        # row. Checked before the copy block and the twin dedup, so a working-folder
        # copy of the same number is the one that takes the row.
        if path in from_delete:
            skipped.append((path.name, f"{DELETE_FOLDER_REASON}: {from_delete[path]}"))
            continue
        # filtering.block_mismatched_report_no: a file whose tables are identical to
        # another file named with its BODY's serial (U-RT-26-005 = U-RT-26-004) is
        # the same inspection under a second number, so on ``true`` it is left out.
        # A name/body mismatch that is not such a copy is only warned about
        # (main.py, report_no_mismatch). Nothing is renamed — the source is fixed
        # on the LAN.
        if block_copies and drift is not None:
            reason = _copy_block_reason(path, tables, meta, items)
            if reason is not None:
                skipped.append((path.name, reason))
                continue
        # Deduplicate twin files that carry the SAME Report № (e.g. a document and
        # its "…_en_en.docx" re-export) so one document contributes exactly one
        # row. Sorted iteration keeps the first (plain) file over its twin;
        # retests keep distinct numbers (…R1) so they are never collapsed.
        rkey = report_key(report_no)
        if rkey in seen_report_keys:
            skipped.append((path.name, f"duplicate Report № {report_no}"))
            continue
        seen_report_keys.add(rkey)
        # Record drift only for reports that belong to THIS group (post method +
        # client filter) so the tally is group-scoped, not month-wide.
        if drift is not None:
            discrepancies.append((path.name, drift[0], drift[1]))

        record = _row_from_doc(path, tables, meta, report_no, date, settings, method)
        # Standard ingestion gate. The row's Standart is filename-first, in-body
        # ACC-Standard fallback — and the body cell is where an unapproved code
        # (e.g. an internal client spec "EP-GIS-42-103") slips past the filename-only
        # guardrail in pre_processor.discover_groups. Reject it here: a non-blank
        # standard that is neither on allowed_standards nor an approved standard's
        # edition/section variant has its row omitted from BOTH the compiled PDF and
        # the JSON sidecar (both render report.rows). Blanks pass (owned by
        # _fill_missing_standards downstream).
        #
        # The source file is deliberately LEFT IN PLACE. This gate resolves through
        # the in-body cell, which pre_processor.discover_groups and settings.yaml's
        # allowed_standards block both document as unfit to quarantine on: across the
        # real corpus it holds project doc references, edition suffixes and typos.
        # Moving the file was also what made the pipeline non-idempotent — it removed
        # a source from the corpus AFTER main.py had printed the group count from it,
        # so the count only dropped on the NEXT run (104 -> 102 -> 101). STAGE 3 does
        # not mutate the corpus STAGE 2 decided on; main.py names every omitted file
        # in its run-end summary so the operator can fix the cell or extend the
        # allowlist.
        if not is_allowed_standard_lenient(record.standard, settings):
            skipped.append((path.name, f"{UNAPPROVED_STANDARD_REASON} "
                                       f"{record.standard!r} not listed in "
                                       f"butun_standartlar.md — row omitted"))
            continue
        records.append(record)
        used_reports.append((date, report_no))
        sig = extractor.extract_signatures(tables)
        sig["inspector"] = sig.get("evaluator") or extractor.extract_inspector_name(tables)
        if any(sig.values()):
            signatures_seen.append(sig)

    # Cross-month retest traceability: import each retest's ORIGINAL from an earlier
    # month so a failure (Yarasız, e.g. April) and its repair (Yararlı, e.g. May)
    # render together. Only in the cached, multi-month path (main.py).
    #
    # retest_tracker filters on ONE method token and stamps it onto the rows it
    # builds, so it is called once per method present in this document. Before
    # ADR-004 the group WAS one method and a single call sufficed; passing None
    # would have silently disabled the whole pull and taken B1's traceability with
    # it. The token list comes from the records already read — no extra disk I/O —
    # and results are de-duplicated by Report № because a parent reachable from two
    # methods must still appear once.
    pulled: list[ReportRow] = []
    if cache is not None:
        wanted = ([method] if method is not None
                  else sorted({r.method for r in records if r.method}))
        seen_pulled: set[str] = set()
        # A delete-folder source is no parent candidate either; an older working
        # copy may then be pulled instead. Its exclusion is recorded by its own month.
        pull_cache = ({p: t for p, t in cache.items() if p not in from_delete}
                      if from_delete else cache)
        for _m in wanted:
            for row in retest_tracker.pull_cross_month_parents(
                    records, pull_cache, settings, _m, client_code,
                    row_builder=_row_from_doc, refused=skipped):
                if row.report_no in seen_pulled:
                    continue
                seen_pulled.add(row.report_no)
                pulled.append(row)
    if block_copies:
        # Same copy block as the in-month loop, applied before the parents are
        # counted; no older candidate is tried — the retest stays an orphan.
        kept: list[ReportRow] = []
        for row in pulled:
            reason = _copy_block_reason(row.source_path, cache.get(row.source_path),
                                        None, items)
            if reason is not None:
                skipped.append((Path(row.source_path).name, reason))
                continue
            kept.append(row)
        pulled = kept
    for row in pulled:
        # Same standard gate as the in-month loop — a pulled parent carrying an
        # unapproved standard must not compile either. No quarantine here: the
        # source file belongs to an already-processed earlier month, so it is only
        # omitted from this month's output, not moved.
        if not is_allowed_standard_lenient(row.standard, settings):
            continue
        records.append(row)
        used_reports.append((row.date, row.report_no))

    records, duplicate_notes = duplicate_identity.merge_duplicates(records, items, settings)
    skipped.extend(duplicate_notes)
    retest_pairs = _assign_sequence_numbers(records)
    records.sort(key=lambda r: r.sort_key)

    # Representative signatures: most common non-empty name per role.
    signatures = _pick_signatures(signatures_seen)

    # The serial's {yy}/{mm} come from the TARGET MONTH, never from records[0].date.
    # A cross-month retest parent pulled above is a rank-0 parent dated to its OWN
    # earlier month, so it sorts to records[0] and used to drag the whole document
    # number back with it — a May report filed as MR-UT-UBOC-26-02. The reporting
    # period, the output filename and the group's own row filter are all keyed on
    # settings.target_month, so the serial has to be too or the four disagree on one
    # sheet. Same reason, same fix as the resolve_inspector call below.
    #
    # settings.target_month is per-GROUP during STAGE 3 (main.py sets it before each
    # build_monthly_report call), which is exactly the value wanted here: this
    # report's month.
    month_date = _dt.date.fromisoformat(settings.target_month + "-01")
    # ADR-004: a document carries every method of the client-month, so the
    # report-level method is the SET of its rows' tokens, joined with "/" in a
    # stable order ("DP/MPI/RT/UTM"). It no longer feeds the serial (the official
    # number is MR-<CLIENT>-<YY>-<MM>); it labels the sidecar's ndt_method, backs
    # the renderer's per-row fallback, and tells the uploader whether the whole
    # document is informational. Taking records[0]'s method — the old behaviour —
    # would name a mixed document after whichever row happened to sort first.
    resolved_method = "/".join(sorted({r.method for r in records if r.method})) or (
        method or (detect_method(records[0].report_no, settings) if records else ""))

    # Standart column: borrow a sibling's standard from within this monthly batch.
    # A batch that is blank throughout keeps "" — no forced method default (a report
    # with no source standard, e.g. PMI, must stay blank, not inherit ASTM E1476).
    _fill_missing_standards(records)

    # Client code + display name for this group. Resolved internally-first from a
    # representative record (all records already share this group's client), so the
    # display name is the registry name (e.g. "Khazar Fabrication") — falling back
    # to the prefix name when the internal field was empty.
    if records:
        rep = records[0]
        reg_code, reg_name = resolve_client_by_field(
            {"client": rep.client}, rep.report_no, settings)
    else:
        reg_code = reg_name = client_code or "NA"
    resolved_client = client_code or reg_code
    client_name = reg_name or resolved_client

    # İnspektor: the configured assignment matrix WINS over the name scraped from
    # the source sign-off tables. Who inspects a client is a standing routing
    # decision; letting whichever document parsed first decide it is how the
    # signature block drifts. An unmapped client returns "" and keeps the scrape,
    # so this can never blank a signature that was previously rendering.
    #
    # The date passed is the TARGET MONTH's first day, deliberately not
    # records[0].date: cross-month retest parents imported above are dated to their
    # own earlier month, and a date-routed client must not have its whole signature
    # dragged backwards by one borrowed row. Spelled out rather than reusing
    # ``month_date`` so tests/test_aggregator.py can keep reading this call in
    # isolation: the guard there is that no ROW date reaches the routing.
    assigned = resolve_inspector(
        resolved_client,
        _dt.date.fromisoformat(settings.target_month + "-01"),
        settings)
    if assigned:
        signatures["inspector"] = assigned

    report = MonthlyReport(
        month=settings.target_month,
        document_number=document_number(settings, month_date, seq=seq,
                                        method=resolved_method, client=resolved_client),
        title=settings.report_title,
        method=resolved_method,
        client_code=resolved_client,
        client_name=client_name,
        rows=records,
        signatures=signatures,
        source_reports=[rn for _, rn in sorted(used_reports)],
        untranslated=sorted(translator.untranslated),
        retest_pairs=retest_pairs,
        pulled_parents=len(pulled),
        skipped=skipped,
        discrepancies=discrepancies,
    )
    return report


def _assign_sequence_numbers(records: list[ReportRow]) -> int:
    """Assign ``4`` / ``4a`` / ``4b`` numbers; return the count of matched retests."""
    parents = [r for r in records if r.retest_rank == 0]
    retests = [r for r in records if r.retest_rank > 0]

    # Method first, then the document's own (date, report_no). ADR-004: one document
    # now holds every method of a client-month, and two things depend on same-method
    # rows staying adjacent — collapse_display_rows only merges NEIGHBOURING rows
    # with an equal method (_can_merge), so a pure date order would shatter every
    # range; and the Üsul column reads as blocks instead of a token flickering line
    # to line. For a single-method document (every pre-ADR-004 group, and any
    # --method run) the key is constant in its first element, so the order is
    # exactly what it was.
    parents.sort(key=lambda r: (r.method, r.source_order))
    parent_by_key: dict[tuple, ReportRow] = {}
    counter = 0
    for p in parents:
        counter += 1
        p.seq = str(counter)
        p.sort_key = (counter, 0)
        parent_by_key.setdefault(p.match_key, p)

    # Group retests by the parent they match, ordered by retest rank then date.
    retests.sort(key=lambda r: (r.retest_rank, r.source_order))
    used_suffix: dict[int, int] = {}
    matched = 0
    for r in retests:
        parent = parent_by_key.get(r.match_key)
        if parent is None:
            # Orphan retest: no parent present in this month -> own index, flagged.
            counter += 1
            r.seq = str(counter)
            r.sort_key = (counter, 0)
            r.is_orphan_retest = True
            continue
        base = int(parent.seq)
        n = used_suffix.get(base, 0)
        suffix = chr(ord("a") + n)          # a, b, c, ...
        used_suffix[base] = n + 1
        r.seq = f"{base}{suffix}"
        r.sort_key = (base, n + 1)
        matched += 1
    return matched


def _pick_signatures(seen: list[dict[str, str]]) -> dict[str, str]:
    out = {"evaluator": "", "contractor": "", "client": "", "inspector": ""}
    for role in out:
        names = Counter(s[role] for s in seen if s.get(role))
        if names:
            out[role] = names.most_common(1)[0][0]
    return out


# ---------------------------------------------------------------------------
# Presentation layer: consecutive-range collapsing
# ---------------------------------------------------------------------------
# A month of routine radiography is dozens of identical reports — same standard,
# same method, same verdict, consecutive numbers — and each one used to take a
# full table line (106 lines for RT/SDLN/SEP_2025). Collapsing a run into
# ``RT-SDL-25-(086-102)`` is a PRESENTATION decision: it happens here, on a
# throwaway view model, and it NEVER touches ``report.rows``. The JSON sidecar
# keeps one entry per report, ``total_records`` keeps counting reports, and the
# document serial / filenames / ledger keys are all built upstream of this.
#
# The rules are deliberately strict — this is a government-facing document:
#   * only rank-0 parents merge, and only when adjacent in the rendered order;
#   * standard, method, result, number prefix AND number suffix must match;
#   * the numeric part must be consecutive and equally zero-padded;
#   * a parent that has a retest child NEVER merges — its ``53a`` child is
#     anchored to the parent's Sıra №, and a parent swallowed by a range would
#     leave ``53a`` pointing at a number the document does not contain;
#   * a verdict change breaks the run on purpose, so a problem report cannot
#     hide inside a range.

#: Report numbers end in their sequence: ``RT-SDL-25-086`` -> ``RT-SDL-25-`` + ``086``.
_TRAILING_NUMBER = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)$")

#: Separator inside a collapsed Tarix cell: en dash, spaced.
_DATE_RANGE_SEP = " – "


@dataclass
class DisplayRow:
    """One RENDERED table line — a single report, or a whole collapsed run.

    Built by :func:`collapse_display_rows` and consumed by ``pdf_renderer``.
    It is a view model, not a record: nothing downstream of the PDF reads it.
    """
    seq: str                # Sıra № as printed — renumbered over display lines
    date_str: str           # single date, or "03.11.2025 – 07.11.2025"
    report_label: str       # document_name, or "PREFIX-(N-M)<suffix>"
    standard: str
    method: str             # RAW row.method; the renderer keeps its own fallback
    item_detail: str
    result: str
    is_retest_child: bool = False   # drives the amber shading in the PDF
    span: int = 1                   # how many ReportRows this line stands for
    pulled_from: str = ""           # "YYYY-MM" of a cross-month parent's own
                                    # month (see pulled_from()), else ""; the
                                    # renderer marks it only when asked to


def collapse_ranges_enabled(settings) -> bool:
    """Read ``presentation.collapse_ranges`` — ON when the block is absent.

    Collapsing is the intended presentation, so a config that predates the
    feature (``config/settings.yaml`` is git-ignored and hand-maintained) still
    gets it. Turning it OFF is the explicit act.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    return bool(block.get("collapse_ranges", True))


def rollup_retests_enabled(settings) -> bool:
    """Read ``presentation.rollup_retests`` — OFF when the block is absent.

    The opposite default to :func:`collapse_ranges_enabled`, and deliberately:
    rolling a retest chain up HIDES table lines and REWRITES the parent's
    printed verdict. A document that already went to the state must not change
    because a key was added to a config file the operator never edited.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    return bool(block.get("rollup_retests", False))


def split_ranges_on_item_enabled(settings) -> bool:
    """Read ``presentation.split_ranges_on_item`` — OFF when the block is absent.

    ON makes a different İtem / Detal break a range, the same way a verdict
    change does. OFF keeps the behaviour that predates the key: the reports
    still merge and a collapsed line with mixed items prints the column blank.
    OFF by default for the same reason as :func:`rollup_retests_enabled` — it
    changes how an already delivered document is drawn.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    return bool(block.get("split_ranges_on_item", False))


#: Accepted ``presentation.pulled_parent_style`` values. Anything else falls back
#: to ``plain`` — the drawing that predates the key. ``hidden`` is honoured only
#: under ``range_mode: by_number``; everywhere else it reads as ``marked`` (see
#: :func:`display_options`).
_PULLED_PARENT_STYLES = ("plain", "marked", "hidden")


def pulled_parent_style(settings) -> str:
    """Read ``presentation.pulled_parent_style`` — ``plain`` when absent or unknown.

    A cross-month parent (``retest_tracker.pull_cross_month_parents``) is shown so
    the retest it belongs to can be read, but it was reported in its own month.
    ``marked`` says so on the page: the line gets a ``*`` and a note under the
    table, it never joins a range, a roll-up never folds its retest into it, and
    the sidecar row carries ``pulled_from``. ``hidden`` drops the parent from the
    page altogether under ``range_mode: by_number`` (the sidecar is the same as
    on ``marked``). ``plain`` is the behaviour that predates the key — OFF by
    default for the same reason as :func:`rollup_retests_enabled`.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = str(block.get("pulled_parent_style", "plain") or "plain").strip().lower()
    return value if value in _PULLED_PARENT_STYLES else "plain"


def pulled_from(row: "ReportRow") -> str:
    """``"YYYY-MM"`` of a cross-month parent's own month — ``""`` for any other row.

    The parent keeps its original inspection date (``retest_tracker``), so its
    month is read off that date; nothing is looked up or guessed.
    """
    if not row.is_pulled_parent:
        return ""
    return f"{row.date.year:04d}-{row.date.month:02d}"


#: Accepted ``presentation.unfit_placement`` values. Anything else falls back to
#: ``inline`` — an unreadable value must not silently restructure the document.
_UNFIT_PLACEMENTS = ("inline", "section")

#: The verdict that :func:`unfit_placement` ``"section"`` moves out of the table.
#: ``ReportRow.result`` is the CANONICAL English token produced by
#: :func:`_aggregate_result` — ``Fit`` / ``Unfit`` / ``Info``. The Azerbaijani
#: ``Yarasız`` the reader sees is `az.json`'s translation, applied by the
#: renderer and the exporter, and must never be compared against here.
UNFIT_RESULT = "Unfit"


def unfit_placement(settings) -> str:
    """Read ``presentation.unfit_placement`` — ``inline`` when absent or unknown.

    ``inline`` is the behaviour that predates the option: a ``Yarasız`` line
    sits at its chronological place in the one table. ``section`` moves the
    unrepaired ones into a second, captioned block after it, numbering
    continuing from the main table.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = str(block.get("unfit_placement", "inline") or "inline").strip().lower()
    return value if value in _UNFIT_PLACEMENTS else "inline"


def _split_report_number(row: "ReportRow") -> tuple[str, str, str] | None:
    """``(prefix, digits, suffix)`` — or ``None`` when the row must not merge.

    ``suffix`` is whatever ``document_name`` carries past ``report_no`` (the
    ``" (Dashgil 2)"`` job tail), kept verbatim so a collapsed label loses no
    information. Refused, and therefore never collapsed, when:

    * the row is a retest — ``RT-SDL-25-123R1`` would otherwise parse as prefix
      ``RT-SDL-25-123R`` + number ``1`` and merge with a ``...R2`` sibling;
    * the number does not end in digits;
    * ``document_name`` is not ``report_no`` + tail, so the tail cannot be
      isolated without guessing.
    """
    if row.retest_rank:
        return None
    report_no = row.report_no or ""
    m = _TRAILING_NUMBER.match(report_no)
    if not m:
        return None
    name = row.document_name or report_no
    if not name.startswith(report_no):
        return None
    return m.group("prefix"), m.group("num"), name[len(report_no):]


def _same_numbering_width(a: str, b: str) -> bool:
    """Do two number strings belong to the same written scheme?

    Equal width always does — ``099`` -> ``100`` is one zero-padded 3-digit run.
    Unequal width only when NEITHER is zero-padded, which is ordinary growth:
    ``9`` -> ``10`` reads fine as ``(1-37)``. Mixing the two — ``086`` next to
    ``87`` — is a numbering change, and printing it as a range would misstate
    which documents the line covers.
    """
    if len(a) == len(b):
        return True
    padded = (len(a) > 1 and a[0] == "0") or (len(b) > 1 and b[0] == "0")
    return not padded


def _can_merge(a: "ReportRow", pa, b: "ReportRow", pb, *,
               on_item: bool = False) -> bool:
    """True when ``b`` may join the run ending at ``a``. All conditions, no ORs.

    ``on_item`` (``presentation.split_ranges_on_item``) adds İtem / Detal to the
    values that must match, so every collapsed line names its item.
    """
    if pa is None or pb is None:
        return False
    if pa[0] != pb[0] or pa[2] != pb[2]:          # prefix and suffix, verbatim
        return False
    if not _same_numbering_width(pa[1], pb[1]):
        return False
    if int(pb[1]) != int(pa[1]) + 1:              # a gap starts a new range
        return False
    return (a.standard == b.standard
            and a.method == b.method              # raw equal -> effective equal
            and a.result == b.result              # a verdict change must show
            and (not on_item or a.item_detail == b.item_detail))


def _atoms(rows: list["ReportRow"]) -> list[tuple["ReportRow", list["ReportRow"]]]:
    """Group the sorted rows into ``(parent, [retest children])`` units.

    ``report.rows`` is already sorted by ``sort_key``, so a lettered child always
    follows its parent immediately.
    """
    out: list[tuple[ReportRow, list[ReportRow]]] = []
    for r in rows:
        if r.sort_key[1] > 0 and out:
            out[-1][1].append(r)
        else:
            out.append((r, []))
    return out


def _display_line(members: list["ReportRow"], seq: str, pa, pb) -> DisplayRow:
    """Render one display line for a run of one or more rows."""
    first = members[0]
    if len(members) == 1:
        return DisplayRow(seq=seq, date_str=first.date_str,
                          report_label=first.document_name,
                          standard=first.standard, method=first.method,
                          item_detail=first.item_detail, result=first.result,
                          pulled_from=pulled_from(first))

    label = f"{pa[0]}({pa[1]}-{pb[1]}){pa[2]}"
    if len({m.date_str for m in members}) == 1:
        date_str = first.date_str
    else:
        lo = min(members, key=lambda m: m.date)
        hi = max(members, key=lambda m: m.date)
        date_str = f"{lo.date_str}{_DATE_RANGE_SEP}{hi.date_str}"
    # İtem / Detal: the shared value, else BLANK. A collapsed line must never
    # name an item the reports did not name — no invented group heading.
    items = {m.item_detail for m in members}
    item_detail = first.item_detail if len(items) == 1 else ""
    return DisplayRow(seq=seq, date_str=date_str, report_label=label,
                      standard=first.standard, method=first.method,
                      item_detail=item_detail, result=first.result,
                      span=len(members))


def _units(rows: list["ReportRow"], rollup: bool,
           mark_pulled: bool = False) -> list[tuple]:
    """``(parent, children, parsed-number-or-None)`` per atom.

    Without the roll-up a unit that HAS children is left unparsed on purpose,
    which makes it unmergeable on both sides (its ``53a`` child is anchored to
    its Sıra №). With the roll-up the children are not drawn at all, so that
    anchor no longer exists and the parent becomes an ordinary mergeable row —
    carrying the chain's FINAL verdict, on a copy. ``report.rows`` is untouched.

    ``mark_pulled`` (``pulled_parent_style: marked``) keeps a cross-month parent
    out of both: it is left unparsed, so it never joins a range, and it is never
    rolled up, because the rolled-up line would carry the parent's number and
    date and hide the retest that is this month's own work.
    """
    out: list[tuple] = []
    for parent, kids in _atoms(rows):
        pulled = mark_pulled and parent.is_pulled_parent
        if pulled:
            out.append((parent, kids, None))
        elif rollup and kids:
            # The chain is already in rank order (report.rows is sorted by
            # sort_key), so the last child is the last word on this weld.
            eff = _dc_replace(parent, result=kids[-1].result)
            out.append((eff, [], _split_report_number(eff)))
        else:
            out.append((parent, kids, None if kids else _split_report_number(parent)))
    return out


def _runs(units: list[tuple], on_item: bool = False) -> list[list[tuple]]:
    """Chain the units into runs of neighbours that may draw as one line."""
    runs: list[list[tuple]] = []
    for unit in units:
        if runs and _can_merge(runs[-1][-1][0], runs[-1][-1][2], unit[0], unit[2],
                               on_item=on_item):
            runs[-1].append(unit)
        else:
            runs.append([unit])
    return runs


def _emit(runs: list[list[tuple]], counter: int) -> tuple[list[DisplayRow], int]:
    """Draw the runs, numbering them from ``counter`` + 1. Returns the last number.

    Passing the counter back out is what lets a second block continue the main
    table's numbering instead of restarting at 1.
    """
    out: list[DisplayRow] = []
    for run in runs:
        counter += 1
        out.append(_display_line([u[0] for u in run], str(counter),
                                 run[0][2], run[-1][2]))
        # Only an unmerged single unit can carry children (see _units), and
        # they renumber onto the line just emitted: 53 -> 53a, 53b.
        for n, child in enumerate(run[0][1] if len(run) == 1 else []):
            out.append(DisplayRow(seq=f"{counter}{chr(ord('a') + n)}",
                                  date_str=child.date_str,
                                  report_label=child.document_name,
                                  standard=child.standard, method=child.method,
                                  item_detail=child.item_detail,
                                  result=child.result, is_retest_child=True))
    return out, counter


def _partition_unfit(runs: list[list[tuple]]) -> tuple[list[list[tuple]], list[list[tuple]]]:
    """Split the runs into ``(main, unfit)`` for ``unfit_placement: section``.

    A run leaves the main table only when BOTH hold:

    * its verdict is ``Unfit`` — the run is uniform by construction, since
      ``_can_merge`` refuses to merge across a verdict change;
    * it carries no retest child. A parent with a child is an unfinished story,
      not an unrepaired weld, and moving it would tear ``53a`` away from ``53``.

    With the roll-up on, the second condition costs nothing: a rolled-up chain
    has no children left, and one that ended ``Fit`` fails the first condition
    anyway. With the roll-up off it is what keeps the pair together.
    """
    main: list[list[tuple]] = []
    unfit: list[list[tuple]] = []
    for run in runs:
        (unfit if run[0][0].result == UNFIT_RESULT and not run[0][1] else main).append(run)
    return main, unfit


def split_display_rows(report: "MonthlyReport", *, enabled: bool = True,
                       rollup: bool = False,
                       placement: str = "inline",
                       split_on_item: bool = False,
                       mark_pulled: bool = False,
                       range_mode: str = "strict",
                       hide_pulled: bool = False,
                       row_order: str = "method_date",
                       date_format: str = "%d.%m.%Y",
                       tail_allow: tuple[str, ...] = (),
                       ignore_tag: bool = False,
                       merge_standards: bool = False,
                       item_rule: str = "split",
                       item_blank_methods: tuple[str, ...] = (),
                       absorb_tails: tuple[str, ...] = (),
                       ) -> tuple[list[DisplayRow], list[DisplayRow]]:
    """Project ``report.rows`` onto ``(main table lines, second block lines)``.

    The second list is empty unless ``placement == "section"``; the caller then
    draws it under its own caption, with the numbering already continuing from
    the main table.

    ``enabled=False`` returns one line per row with every value — Sıra №
    included — exactly as the row carries it, i.e. the pre-feature table.
    ``placement`` is IGNORED in that branch and reported as inline: those lines
    print the row's own Sıra №, so pulling some of them out would leave both
    blocks numbered in gaps. ``rollup`` still applies there — hiding a lettered
    child leaves the integer numbering untouched. ``split_on_item`` has nothing
    to split there and is ignored too. ``mark_pulled`` still applies there: a
    cross-month parent's chain is not rolled up.

    ``range_mode="by_number"`` (with ``enabled``) draws every report number —
    retest chain included — as one unit and ranges the units by number; see
    :func:`_number_lines`. ``rollup`` and ``placement`` are ignored there (a
    chain is already one line; there is no second block). ``hide_pulled`` is
    only read there, and so are ``tail_allow`` (``range_tail_allow``),
    ``ignore_tag`` (E1), ``merge_standards`` (E2), ``item_rule`` (E3),
    ``item_blank_methods`` and ``absorb_tails`` (``range_absorb_tails``).
    ``row_order="method_volume"`` puts the method with the
    most reports first; it is ignored with ``enabled=False``, whose lines print
    each row's own Sıra №.

    ``report.rows`` is never mutated on any path: the sidecar reads the same
    objects and must keep seeing one entry per report.
    """
    rows = list(report.rows)
    if enabled and range_mode == "by_number":
        lines = _number_lines(rows, split_on_item=split_on_item,
                              mark_pulled=mark_pulled, hide_pulled=hide_pulled,
                              row_order=row_order, date_format=date_format,
                              tail_allow=tail_allow, ignore_tag=ignore_tag,
                              merge_standards=merge_standards,
                              item_rule=item_rule,
                              item_blank_methods=item_blank_methods,
                              absorb_tails=absorb_tails)
        return [line for line, _ in lines], []
    if enabled and row_order == "method_volume":
        rows = _volume_ordered(rows)
    if not enabled:
        out: list[DisplayRow] = []
        for parent, kids in _atoms(rows):
            fold = rollup and not (mark_pulled and parent.is_pulled_parent)
            eff = _dc_replace(parent, result=kids[-1].result) if fold and kids else parent
            for r in [eff, *([] if fold else kids)]:
                out.append(DisplayRow(seq=r.seq, date_str=r.date_str,
                                      report_label=r.document_name,
                                      standard=r.standard, method=r.method,
                                      item_detail=r.item_detail,
                                      result=r.result,
                                      is_retest_child=r.sort_key[1] > 0,
                                      pulled_from=pulled_from(r)))
        return out, []

    runs = _runs(_units(rows, rollup, mark_pulled), on_item=split_on_item)
    main_runs, unfit_runs = (_partition_unfit(runs) if placement == "section"
                             else (runs, []))
    main, counter = _emit(main_runs, 0)
    unfit, _ = _emit(unfit_runs, counter)
    return main, unfit


def collapse_display_rows(report: "MonthlyReport", *, enabled: bool = True,
                          rollup: bool = False,
                          split_on_item: bool = False,
                          mark_pulled: bool = False) -> list[DisplayRow]:
    """One flat list of display lines — :func:`split_display_rows` inline."""
    main, _ = split_display_rows(report, enabled=enabled, rollup=rollup,
                                 placement="inline",
                                 split_on_item=split_on_item,
                                 mark_pulled=mark_pulled)
    return main


# ---------------------------------------------------------------------------
# Presentation layer: range_mode by_number, row_order, row_style
# ---------------------------------------------------------------------------
# The director's shorter table. A report NUMBER is the unit: U-RT-26-014,
# 014R1, 014RW and 014RW1 are one unit, drawn once. Units then range by number
# the same way strict ranges rows — prefix, label tail, zero padding,
# consecutive number, standard, method (and İtem with split_ranges_on_item)
# must all match — but a verdict change no longer breaks the run. What that
# costs is written to stdout and an audit file (range_verdict_notes), never
# silently absorbed. Everything is opt-in; the defaults below are the drawing
# that predates the keys, and report.rows is never mutated.

#: Accepted ``presentation.range_mode`` values; the first is the default.
_RANGE_MODES = ("strict", "by_number")

#: Accepted ``presentation.row_order`` values; the first is the default.
#: ``method_date`` is today's order — method name, then date
#: (:func:`_assign_sequence_numbers`).
_ROW_ORDERS = ("method_date", "method_volume")

#: Accepted ``presentation.row_style`` values; the first is the default.
_ROW_STYLES = ("retest_highlight", "method_zebra")

#: Separator inside a by_number Tarix cell: en dash, unspaced ("01–15.04.2026").
_NUMBER_DATE_SEP = "–"

#: The date format whose ranges print in the compact "01–15.04.2026" form.
_COMPACT_DATE_FORMAT = "%d.%m.%Y"


def _presentation_choice(settings, key: str, allowed: tuple[str, ...]) -> str:
    """``presentation.<key>`` if it is one of ``allowed``, else ``allowed[0]``."""
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = str(block.get(key, allowed[0]) or allowed[0]).strip().lower()
    return value if value in allowed else allowed[0]


def range_mode(settings) -> str:
    """Read ``presentation.range_mode`` — ``strict`` when absent or unknown."""
    return _presentation_choice(settings, "range_mode", _RANGE_MODES)


def row_order(settings) -> str:
    """Read ``presentation.row_order`` — ``method_date`` when absent or unknown."""
    return _presentation_choice(settings, "row_order", _ROW_ORDERS)


def row_style(settings) -> str:
    """Read ``presentation.row_style`` — ``retest_highlight`` when absent or unknown."""
    return _presentation_choice(settings, "row_style", _ROW_STYLES)


def range_tail_allow(settings) -> tuple[str, ...]:
    """Read ``presentation.range_tail_allow`` — ``()`` when absent or not a list.

    Each entry is a number tail (``"T"`` in ``RT-KF-25-080T``) that may range
    under by_number, matched case-sensitively and whole. Blank entries are
    dropped: a number with no tail already ranges.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = block.get("range_tail_allow") or []
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v) for v in value if str(v)))


#: A ``range_absorb_tails`` entry: ONE upper-case Latin letter. Anything longer
#: (``rej``, ``test``, ``del``) names a different report and is never absorbed.
_ABSORB_TAIL = re.compile(r"[A-Z]")


def range_absorb_tails(settings) -> tuple[str, ...]:
    """Read ``presentation.range_absorb_tails`` — ``()`` when absent or not a list.

    Each entry is a one-letter number tail (``"A"`` in ``BS-RT-26-010A``) whose
    number joins its base number's slot under by_number: ``010A`` ranges as if
    it were ``010``. Matched case-sensitively and whole; an entry that is not a
    single upper-case letter is dropped, so ``003rej`` can never be absorbed.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = block.get("range_absorb_tails") or []
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(str(v) for v in value
                               if _ABSORB_TAIL.fullmatch(str(v))))


#: Accepted ``presentation.range_item`` values; the first is the default.
#: ``split`` defers to ``split_ranges_on_item``; ``dominant`` is E3.
_RANGE_ITEMS = ("split", "dominant")


def range_ignore_tag_enabled(settings) -> bool:
    """Read ``presentation.range_ignore_tag`` (E1) — OFF when absent.

    ON lets numbers whose label tail (the ``" (2236)"`` job tag) differs range
    under by_number; the range line then prints no tag. A single number keeps
    its own document name. Ignored under strict.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    return bool(block.get("range_ignore_tag", False))


def range_merge_standards_enabled(settings) -> bool:
    """Read ``presentation.range_merge_standards`` (E2) — OFF when absent.

    ON lets a different standard join a by_number range; the Standart cell
    lists every distinct standard once, in number order. Ignored under strict.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    return bool(block.get("range_merge_standards", False))


def range_item(settings) -> str:
    """Read ``presentation.range_item`` (E3) — ``split`` when absent or unknown."""
    return _presentation_choice(settings, "range_item", _RANGE_ITEMS)


def range_item_blank_methods(settings) -> tuple[str, ...]:
    """Read ``presentation.range_item_blank_methods`` — ``()`` when absent or not a list.

    Methods (compared trimmed, any case) whose multi-İtem range line prints
    :data:`_BLANK_ITEM` instead of the dominant item. Only read under
    ``range_item: dominant``.
    """
    block = (getattr(settings, "raw", None) or {}).get("presentation") or {}
    value = block.get("range_item_blank_methods") or []
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(_method_key(v) for v in value if _method_key(v)))


def _method_key(method) -> str:
    return str(method or "").strip().casefold()


def display_options(settings) -> dict:
    """Every presentation key, resolved once, as :func:`split_display_rows` kwargs.

    The renderer and :func:`range_verdict_notes` both read this, so the table
    and the stdout audit can never be built from different settings. The key
    interactions are decided here:

    * ``collapse_ranges: false`` wins over ``range_mode: by_number`` — that mode
      prints each row's own Sıra №;
    * ``pulled_parent_style: hidden`` hides only under by_number; everywhere
      else it reads as ``marked``, because a strict table would print the
      parent's ``53a`` child anchored to a line that is not there.
    """
    enabled = collapse_ranges_enabled(settings)
    by_number = enabled and range_mode(settings) == "by_number"
    style = pulled_parent_style(settings)
    return {
        "enabled": enabled,
        "rollup": rollup_retests_enabled(settings),
        "placement": unfit_placement(settings),
        "split_on_item": split_ranges_on_item_enabled(settings),
        "mark_pulled": style == "marked" or (style == "hidden" and not by_number),
        "hide_pulled": style == "hidden" and by_number,
        "range_mode": "by_number" if by_number else "strict",
        "row_order": row_order(settings),
        "date_format": getattr(settings, "date_format", None) or _COMPACT_DATE_FORMAT,
        "tail_allow": range_tail_allow(settings),
        "absorb_tails": range_absorb_tails(settings),
        "ignore_tag": range_ignore_tag_enabled(settings),
        "merge_standards": range_merge_standards_enabled(settings),
        "item_rule": range_item(settings),
        "item_blank_methods": range_item_blank_methods(settings),
    }


def _visible(row: "ReportRow", hide_pulled: bool) -> bool:
    return not (hide_pulled and row.is_pulled_parent)


def _method_rank(rows: list["ReportRow"], hide_pulled: bool = False) -> dict[str, int]:
    """Block position per method: most visible rows first, ties by method name."""
    volume = Counter(r.method for r in rows if _visible(r, hide_pulled))
    return {m: i for i, m in enumerate(sorted(volume, key=lambda m: (-volume[m], m)))}


def _volume_ordered(rows: list["ReportRow"]) -> list["ReportRow"]:
    """``row_order: method_volume`` for strict mode — whole atoms, stably.

    A parent moves with its lettered children, and inside a method block the
    order (date) is untouched.
    """
    rank = _method_rank(rows)
    atoms = sorted(_atoms(rows), key=lambda a: rank.get(a[0].method, 0))
    return [r for parent, kids in atoms for r in (parent, *kids)]


@dataclass
class _NumberUnit:
    """Every visible row of one report number (a parent and its retests)."""
    members: list                   # chain order: rank, then date, then number
    series: str                     # the number, retest marker stripped
    tail: str | None                # head's label tail, None when not isolable
    parsed: tuple | None            # (prefix, digits, tail) — None: never ranges
    pulled: str                     # pulled_from() when marked, else ""
    absorbed: bool = False          # range_absorb_tails: sits in its base number's slot

    @property
    def head(self) -> "ReportRow":
        """The lowest-rank visible member: it supplies the line's values."""
        return self.members[0]

    @property
    def result(self) -> str:
        """The chain's LAST verdict (D3)."""
        return self.members[-1].result

    @property
    def label(self) -> str:
        """The unit's Report № when it draws alone.

        One visible row prints its own document name verbatim. A chain prints
        its number with the head's label tail — built from the original
        number, so ``rej`` and the like are never cleaned away.
        """
        if len(self.members) == 1 or self.tail is None:
            return self.head.document_name or self.head.report_no
        return f"{self.series}{self.tail}"


def _chain_key(row: "ReportRow") -> tuple:
    # The same order _assign_sequence_numbers letters a chain in.
    return (row.retest_rank, row.date, row.report_no)


def _split_number(series: str, tail_allow: tuple[str, ...]):
    """``(prefix, digits, number tail)`` of a retest-stripped number, or ``None``.

    A number ending in digits has tail ``""``. One whose non-digit tail is in
    ``range_tail_allow`` (``RT-KF-25-080T`` with ``["T"]``) splits too; any
    other tail (``003rej``) does not, so that number never ranges.
    """
    m = _TRAILING_NUMBER.match(series)
    if m:
        return m.group("prefix"), m.group("num"), ""
    if tail_allow:
        m = _NUMBER_WITH_TAIL.match(series)
        if m and m.group("tail") in tail_allow:
            return m.group("prefix"), m.group("num"), m.group("tail")
    return None


def _number_units(rows: list["ReportRow"], *, mark_pulled: bool,
                  hide_pulled: bool,
                  tail_allow: tuple[str, ...] = (),
                  ignore_tag: bool = False,
                  merge_standards: bool = False,
                  dominant_item: bool = False,
                  absorb_tails: tuple[str, ...] = ()) -> list[_NumberUnit]:
    groups: dict[tuple, list] = {}
    for r in rows:
        if _visible(r, hide_pulled):
            groups.setdefault((r.method, strip_retest(r.report_no)), []).append(r)
    units: list[_NumberUnit] = []
    for (_method, series), members in groups.items():
        members.sort(key=_chain_key)
        head = members[0]
        name, number = head.document_name or head.report_no, head.report_no or ""
        tail = name[len(number):] if number and name.startswith(number) else None
        pulled = next((pulled_from(m) for m in members if m.is_pulled_parent),
                      "") if mark_pulled else ""
        m = _split_number(series, tail_allow)
        # range_absorb_tails: "010A" takes the slot of "010" — split with no
        # number tail, so it ranges with the plain numbers. range_tail_allow is
        # read first and keeps its meaning for a tail listed in both.
        absorbed = False
        if m is None and absorb_tails:
            a = _NUMBER_WITH_TAIL.match(series)
            if a and a.group("tail") in absorb_tails:
                m, absorbed = (a.group("prefix"), a.group("num"), ""), True
        # A unit ranges only when its number ends in digits or in an allowed
        # tail (a "003rej" never does), its label tail can be isolated, its
        # members agree on standard and İtem, and it is not a marked
        # cross-month parent. The number tail joins the label tail, so only
        # numbers with the same tail range: RT-KF-25-(080-106)T.
        # E2 / E3 drop the standard / İtem agreement: the line then picks its
        # values with _merged_standards / _dominant_item. E1 keeps only the
        # number tail in the key, so a different job tag no longer breaks.
        mergeable = (m is not None and tail is not None and not pulled
                     and (merge_standards
                          or len({x.standard for x in members}) == 1)
                     and (dominant_item
                          or len({x.item_detail for x in members}) == 1))
        units.append(_NumberUnit(
            members=members, series=series, tail=tail,
            parsed=((m[0], m[1], m[2] if ignore_tag else m[2] + tail)
                    if mergeable else None),
            pulled=pulled, absorbed=absorbed))
    return units


#: Sort-only split of a number with a non-digit tail: ``U-UT-25-003rej`` ->
#: ``U-UT-25-`` + ``003`` + ``rej``. Never used to merge (Q3: such a number
#: never ranges).
_NUMBER_WITH_TAIL = re.compile(r"^(?P<prefix>.*?)(?P<num>\d+)(?P<tail>\D*)$")


def _unit_order(unit: _NumberUnit) -> tuple:
    """Number order inside a method block.

    Plain numbers first, by number; then the numbers with a non-digit tail
    (``003rej``, ``001T``), grouped by tail and by number — so they never land
    between two consecutive plain numbers and break that range. A number with
    no digits at all sorts last, by its text. An absorbed number
    (``range_absorb_tails``) sorts as a plain one, right after its base.
    """
    m = _NUMBER_WITH_TAIL.match(unit.series)
    if m:
        tail = "" if unit.absorbed else m.group("tail")
        return (m.group("prefix"), 0, tail, int(m.group("num")), unit.series)
    return (unit.series, 1, "", 0, unit.series)


def _can_merge_units(a: _NumberUnit, b: _NumberUnit, on_item: bool,
                     merge_standards: bool = False) -> bool:
    """True when ``b`` may join the run ending at ``a`` (D1). Verdict not compared.

    ``merge_standards`` (E2) stops a different standard from breaking the run.
    """
    pa, pb = a.parsed, b.parsed
    if pa is None or pb is None:
        return False
    if pa[0] != pb[0] or pa[2] != pb[2]:          # prefix and label, verbatim
        return False
    if not _same_numbering_width(pa[1], pb[1]):
        return False
    step = int(pb[1]) - int(pa[1])
    # A missing number breaks; an absorbed "010A" shares the slot of "010".
    if not (step == 1 or (step == 0 and b.absorbed)):
        return False
    return ((merge_standards or a.head.standard == b.head.standard)
            and a.head.method == b.head.method
            and (not on_item or a.head.item_detail == b.head.item_detail))


def _standard_key(value: str) -> str:
    # Copy of method_registry._standard_key (separator-blind, case-folded), so
    # "ISO 23278" and "ISO-23278" count as one standard.
    return re.sub(r"[\s_-]+", " ", fold_typography(value).strip()).casefold()


def _merged_standards(run: list[_NumberUnit]) -> str:
    """E2: every distinct standard of the line, once, in number order.

    Members are walked in print order (units by number, a chain by rank), so
    the first appearance decides the position and its spelling: two spellings
    of one standard (``ISO 23278`` / ``ISO-23278``, see :func:`_standard_key`)
    print once. A blank standard adds nothing.
    """
    seen: dict[str, str] = {}
    for u in run:
        for m in u.members:
            if m.standard and _standard_key(m.standard):
                seen.setdefault(_standard_key(m.standard), m.standard)
    return ", ".join(seen.values())


def _item_key(item: str) -> str:
    # The key the translator looks an item up by (Translator.lookup), so two
    # spellings counted as one also print as one.
    return (item or "").strip().lower()


def _most_common_item(items: list[str]) -> str:
    """The most frequent non-blank item; a tie goes to the one seen first.

    ``items`` must already be in number order, so "seen first" is the smallest
    number. Returns the first spelling of the winner, ``""`` when all are blank.
    """
    counts: Counter = Counter()
    first: dict[str, tuple[int, str]] = {}
    for i, item in enumerate(items):
        key = _item_key(item)
        if not key:
            continue
        counts[key] += 1
        first.setdefault(key, (i, item))
    if not counts:
        return ""
    best = min(counts, key=lambda k: (-counts[k], first[k][0]))
    return first[best][1]


def _dominant_item(run: list[_NumberUnit]) -> str:
    """E3: the line's one İtem — counted per report NUMBER, not per row.

    A unit first picks its own item the same way over its members (chain
    order), then each unit is one vote.
    """
    return _most_common_item(
        [_most_common_item([m.item_detail for m in u.members]) for u in run])


#: İtem cell of a multi-item range line under ``range_item_blank_methods``.
_BLANK_ITEM = "—"


def _distinct_items(run: list[_NumberUnit]) -> int:
    return len({_item_key(m.item_detail) for u in run for m in u.members
                if _item_key(m.item_detail)})


def _range_result(verdicts: list[str]) -> str:
    """A multi-number line's verdict: ``Fit`` when ANY number ended ``Fit``.

    Otherwise the shared verdict (``Info`` for an informational method, whose
    units are all ``Info``), else ``Unfit``.
    """
    if "Fit" in verdicts:
        return "Fit"
    if len(set(verdicts)) == 1:
        return verdicts[0]
    return UNFIT_RESULT if UNFIT_RESULT in verdicts else verdicts[0]


def _date_span(members: list["ReportRow"], date_format: str) -> str:
    """D2: min–max over every member; a single day prints once.

    The compact form drops what the end date already says: ``01–21.04.2026``
    in one month, ``31.03–15.04.2026`` across months, ``28.12.2025–05.01.2026``
    across years.
    """
    lo = min(members, key=lambda m: m.date)
    hi = max(members, key=lambda m: m.date)
    if lo.date == hi.date:
        return lo.date_str
    if date_format == _COMPACT_DATE_FORMAT:
        if lo.date.year != hi.date.year:
            start_format = _COMPACT_DATE_FORMAT
        elif lo.date.month != hi.date.month:
            start_format = "%d.%m"
        else:
            start_format = "%d"
        return (f"{lo.date.strftime(start_format)}{_NUMBER_DATE_SEP}"
                f"{hi.date.strftime(_COMPACT_DATE_FORMAT)}")
    return f"{lo.date_str}{_NUMBER_DATE_SEP}{hi.date_str}"


def _number_line(run: list[_NumberUnit], seq: str, date_format: str,
                 merge_standards: bool = False,
                 dominant_item: bool = False,
                 item_blank_methods: tuple[str, ...] = ()) -> DisplayRow:
    members = [m for u in run for m in u.members]
    head = run[0].head
    if len(run) == 1:
        label, result = run[0].label, run[0].result
    else:
        pa, pb = run[0].parsed, run[-1].parsed
        label = f"{pa[0]}({pa[1]}-{pb[1]}){pa[2]}"
        result = _range_result([u.result for u in run])
    if (dominant_item and len(run) > 1
            and _method_key(head.method) in item_blank_methods
            and _distinct_items(run) > 1):
        # The items are identifiers (PMI serials): one of them would hide the rest.
        item_detail = _BLANK_ITEM
    elif dominant_item:
        item_detail = _dominant_item(run)
    else:
        # İtem / Detal: the shared value, else BLANK — as in _display_line.
        items = {u.head.item_detail for u in run}
        item_detail = head.item_detail if len(items) == 1 else ""
    return DisplayRow(seq=seq, date_str=_date_span(members, date_format),
                      report_label=label,
                      standard=(_merged_standards(run) if merge_standards
                                else head.standard),
                      method=head.method,
                      item_detail=item_detail,
                      result=result, span=len(members), pulled_from=run[0].pulled)


def _number_lines(rows: list["ReportRow"], *, split_on_item: bool,
                  mark_pulled: bool, hide_pulled: bool, row_order: str,
                  date_format: str, tail_allow: tuple[str, ...] = (),
                  ignore_tag: bool = False, merge_standards: bool = False,
                  item_rule: str = "split",
                  item_blank_methods: tuple[str, ...] = (),
                  absorb_tails: tuple[str, ...] = (),
                  ) -> list[tuple[DisplayRow, list[_NumberUnit]]]:
    """``range_mode: by_number`` — ``(line, its units)`` in print order.

    Method blocks (by name, or by visible volume under ``method_volume``), units
    by number inside a block, Sıra № 1..N with no lettered sub-numbers.
    ``item_rule="dominant"`` (E3) overrides ``split_on_item``; under it a
    range line of a method in ``item_blank_methods`` with 2+ distinct items
    prints :data:`_BLANK_ITEM`.
    """
    dominant_item = item_rule == "dominant"
    on_item = split_on_item and not dominant_item
    units = _number_units(rows, mark_pulled=mark_pulled, hide_pulled=hide_pulled,
                          tail_allow=tail_allow, ignore_tag=ignore_tag,
                          merge_standards=merge_standards,
                          dominant_item=dominant_item,
                          absorb_tails=absorb_tails)
    if row_order == "method_volume":
        rank = _method_rank(rows, hide_pulled)
        block = lambda u: (rank.get(u.head.method, 0), u.head.method)  # noqa: E731
    else:
        block = lambda u: (0, u.head.method)  # noqa: E731
    units.sort(key=lambda u: (block(u), _unit_order(u)))
    runs: list[list[_NumberUnit]] = []
    for unit in units:
        if runs and _can_merge_units(runs[-1][-1], unit, on_item, merge_standards):
            runs[-1].append(unit)
        else:
            runs.append([unit])
    if absorb_tails:
        # "010" + "010A" alone would label "(010-010)": a run that covers one
        # slot only draws each number on its own line.
        runs = [part for run in runs
                for part in ([[u] for u in run]
                             if len(run) > 1
                             and int(run[0].parsed[1]) == int(run[-1].parsed[1])
                             else [run])]
    return [(_number_line(run, str(n), date_format, merge_standards,
                          dominant_item, item_blank_methods), run)
            for n, run in enumerate(runs, 1)]


def range_verdict_notes(report: "MonthlyReport", settings) -> list[tuple[str, str]]:
    """D8: ``(report_no, line label)`` for every number whose chain ended Unfit
    but which prints inside a multi-number ``Fit`` line.

    ``report_no`` is the chain's last report — the one that said Yarasız. Empty
    unless ``range_mode: by_number`` is in force, so nothing is printed or
    written on the default settings.
    """
    opts = display_options(settings)
    if opts["range_mode"] != "by_number":
        return []
    lines = _number_lines(list(report.rows), split_on_item=opts["split_on_item"],
                          mark_pulled=opts["mark_pulled"],
                          hide_pulled=opts["hide_pulled"],
                          row_order=opts["row_order"],
                          date_format=opts["date_format"],
                          tail_allow=opts["tail_allow"],
                          ignore_tag=opts["ignore_tag"],
                          merge_standards=opts["merge_standards"],
                          item_rule=opts["item_rule"],
                          item_blank_methods=opts["item_blank_methods"],
                          absorb_tails=opts["absorb_tails"])
    return [(u.members[-1].report_no, line.report_label)
            for line, run in lines
            if len(run) > 1 and line.result == "Fit"
            for u in run if u.result == UNFIT_RESULT]


def format_range_verdict(tag: str, report_no: str, label: str) -> str:
    """The D8 stdout line. Four-space indent: gui/services/progress._RENDERED and
    the console's accent rule anchor on a line STARTING with '['."""
    return (f"    [range-verdict] {tag}: {report_no} Yarasız → \"Yararlı\" "
            f"diapazonda çap olundu: {label}")
