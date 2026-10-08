"""One report, two spellings — merge transposed Report № identities.

``scripts/audit_duplicate_identity.py`` measured 231 pairs of compiled rows whose
report numbers are the SAME segments in a different order (``RT-U-25-090`` /
``U-RT-25-090``). The cause is documented there: the corpus was systematically
renamed to ``<CLIENT>-<METHOD>`` while the signed body still reads
``<METHOD>-<CLIENT>``, ``resolve_report_no`` treats the filename as authoritative,
and :func:`report_identity.report_key` — correctly — keeps segment ORDER, so the
aggregator's twin dedup never sees the two spellings meet. A second row appears
only where an un-renamed copy is still read: the archived PDF original that
ADR-003 turned back into a source.

This module is the opt-in merge. It never infers from the number: a pair is
collapsed only when the two documents' **weld identifiers** prove they are one
physical report. Numbers alone are not evidence — the corpus contains pairs that
transpose to the same key and are genuinely two separate inspections.

Order of evidence (A is checked FIRST, deliberately):

* **A** — two live working documents whose weld sets are both populated and
  **disjoint** -> ``DISTINCT``, nothing is merged. Merging here would delete an
  inspection from a document that goes to the state; that error is not symmetric
  with leaving one row too many.
* **B** — two live documents, weld sets equal -> ``SAME``.
* **C** — two live documents, weld evidence incomplete -> ``UNDECIDED``.
* **D** — one live document plus a settled copy (archived PDF / pruned
  conversion) sharing the filename tail and the client, the settled copy's welds
  a subset of the live one's -> ``SAME``. The settled copy is the signed original
  the live document was made from.
* **E/F** — anything else (no source file, one spelling only on disk)
  -> ``UNDECIDED``, recorded for the operator, both rows kept.

Retests follow their parent (chain merge). Once a rank-0 pair is ``SAME``, its
retests carrying the same suffix under both spellings (``RT-U-25-056R1`` /
``U-RT-25-056R1``) are the same retest seen twice and inherit the parent's verdict
— they are NOT classified on their own welds. The winner is again
:func:`_winner_key`. A retest whose suffix exists under one spelling only is kept
and named under :data:`DUPLICATE_IDENTITY_CHILD_UNMATCHED`. Children of a
``DISTINCT`` or ``UNDECIDED`` pair are never touched.

Off by default (``filtering.merge_duplicate_identities: false``). The switch
changes ``report.rows`` and therefore every ``Sıra №`` in the compiled document,
so the operator throws it after reading the collision report — not a default that
quietly renumbers a month.

I/O contract
------------
merge_duplicates(records, items, settings) -> (records, notes)
"""

from __future__ import annotations

import collections
import re
from pathlib import Path

from . import docx_reader, extractor
from .naming import PDF_ARCHIVE_DIR, PRUNED_DIR, QUARANTINE_DIR
from .report_identity import (RETEST_SUFFIX, leading_token, report_key, report_key_of,
                              squash, strip_retest)

#: Stable prefix of the ``report.skipped`` reason recorded for a pair this module
#: could not decide. Both rows stay in the document; the note is the operator's
#: hand-off. Reword the tail freely, never this prefix — the collision report and
#: any run-end summary filter on it.
DUPLICATE_IDENTITY_UNDECIDED = "DUPLICATE_IDENTITY_UNDECIDED"

#: Stable prefix of the ``report.skipped`` reason recorded for a retest of a
#: ``SAME`` parent pair whose suffix appears under one spelling only. The row is
#: kept; same wording rules as :data:`DUPLICATE_IDENTITY_UNDECIDED`.
DUPLICATE_IDENTITY_CHILD_UNMATCHED = "DUPLICATE_IDENTITY_CHILD_UNMATCHED"

#: Stable prefix of the ``report.skipped`` reason recorded for every row a
#: ``SAME`` merge drops (parent pair or inherited retest). The row is gone from
#: the document by design (ADR-005); the note names both spellings so the
#: coverage audit can account for the dropped file. Same wording rules as above.
DUPLICATE_IDENTITY_MERGED = "DUPLICATE_IDENTITY_MERGED"

#: Verdict tokens. Same wording as the audit script, so its report and this
#: module's notes read as one measurement.
SAME = "eyni sənəd"
DISTINCT = "iki ayrı yoxlama"
UNDECIDED = "qərarsız"

#: Trees under ``input/`` that hold settled copies rather than working documents.
#: ``PDF_ARCHIVE`` is included even though ADR-003 reads it again: a file there is
#: evidence ABOUT a report, never the report the operator is maintaining.
_SETTLED_DIRS = frozenset({PDF_ARCHIVE_DIR.casefold(),
                           PRUNED_DIR.casefold(),
                           QUARANTINE_DIR.casefold()})

#: Winner preference between file kinds (R1 step 2): a live ``.docx`` beats the
#: PDF read of the same report every time.
_SUFFIX_RANK = {".docx": 0, ".doc": 1, ".pdf": 2}

_WS = re.compile(r"\s+")


def is_enabled(settings) -> bool:
    """True when ``filtering.merge_duplicate_identities`` is on (default OFF)."""
    block = settings.raw.get("filtering") or {}
    return bool(block.get("merge_duplicate_identities", False))


def canon_key(report_no: str) -> tuple:
    """Order-blind identity of a report number: its segments, sorted.

    ``RT-U-25-090`` and ``U-RT-25-090`` share one key; ``KF-MT-25-081`` and
    ``KF-MT-25-082`` do not. This is the ONLY place segment order is discarded —
    :func:`report_identity.report_key` keeps it, and must keep it.
    """
    return tuple(sorted((report_no or "").upper().split("-")))


def filename_tail(name) -> str:
    """Everything after the leading report-number token, normalised.

    The job number and standard the inspector typed into the filename
    (``(2106)  (EEMUA 158)``) — the one part of the name the transposition does
    not touch, so two files sharing it are the same job.
    """
    stem = Path(name).stem
    token = leading_token(name)
    tail = stem[len(token):] if stem.startswith(token) else stem
    return _WS.sub(" ", tail).strip().casefold()


def _welds_of(tables, method: str) -> set[str]:
    """The weld identifiers a parsed document lists — the inspection's fingerprint."""
    if not tables:
        return set()
    rows = (extractor.extract_rt_welds(tables) if method == "RT"
            else extractor.extract_welds(tables))
    return {squash(w.get("weld_no", "") or w.get("item", "")) for w in rows} - {""}


class _Candidate:
    """One record of a transposed group, joined to its source file and welds."""

    __slots__ = ("record", "path", "tables", "live", "_welds")

    def __init__(self, record, path, tables, live: bool) -> None:
        self.record = record
        self.path = path
        self.tables = tables
        self.live = live
        self._welds: set[str] | None = None

    @property
    def welds(self) -> set[str]:
        """Weld ids, parsed once per candidate — and only for the handful of
        records that landed in a transposed group."""
        if self._welds is None:
            self._welds = _welds_of(self.tables, self.record.method)
        return self._welds

    @property
    def name(self) -> str:
        return self.path.name if self.path is not None else self.record.document_name


def _source_index(items) -> tuple[dict, dict]:
    """``({report key: [paths]}, {path: tables})`` over the parsed corpus.

    A record carries no path, so it is re-joined to its source by Report № key.
    Both keys a file can answer to are registered — its leading filename token and
    the full filename number ``parse_filename_metadata`` reads — because
    ``resolve_report_no`` may have used either. Paths keep ``items`` order, which
    the aggregator already sorted by ``str(path)``, so the FIRST path under a key
    is the same one the twin dedup kept for the record.
    """
    by_key: dict = collections.defaultdict(list)
    tables: dict = {}
    for path, tbl in items:
        if isinstance(tbl, Exception):
            continue
        tables[path] = tbl
        keys = {report_key_of(path.name)}
        fn_no = squash(docx_reader.parse_filename_metadata(path).get("report_no")
                       or "").replace(" ", "")
        if fn_no:
            keys.add(report_key(fn_no))
        for key in keys:
            if path not in by_key[key]:
                by_key[key].append(path)
    return by_key, tables


def _is_live(path, input_dir: Path) -> bool:
    """True for a document the compile reads as a working file, not a settled copy."""
    try:
        top = path.relative_to(input_dir).parts[0]
    except (ValueError, IndexError):
        return True      # outside input/ (tests, CLI) — treat as a working document
    return top.casefold() not in _SETTLED_DIRS


def _candidate(record, by_key, tables, input_dir) -> _Candidate:
    paths = by_key.get(report_key(record.report_no)) or []
    path = paths[0] if paths else None
    live = _is_live(path, input_dir) if path is not None else False
    return _Candidate(record, path, tables.get(path), live)


def classify(candidates) -> tuple[str, str]:
    """Decide whether the group is one report seen twice, or two reports."""
    live = [c for c in candidates if c.path is not None and c.live]
    settled = [c for c in candidates if c.path is not None and not c.live]

    # A / B / C — two working documents. Checked first: the disjoint case is real
    # in this corpus and a merge there would delete an inspection.
    if len(live) >= 2:
        wa, wb = live[0].welds, live[1].welds
        if wa and wb and not (wa & wb):
            return DISTINCT, (f"iki canlı sənəd, tikiş dəstləri kəsişmir: "
                              f"{sorted(wa)} / {sorted(wb)}")
        if wa and wa == wb:
            return SAME, "iki canlı sənəd, tikiş dəstləri eyni"
        return UNDECIDED, (f"iki canlı sənəd, tikiş sübutu natamam "
                           f"({len(wa)} / {len(wb)} tikiş)")

    # D — one working document plus a settled copy of the same job.
    if len(live) == 1 and settled:
        pdfs = [c for c in settled if c.path.suffix.casefold() == ".pdf"]
        other = pdfs[0] if pdfs else settled[0]
        same_job = filename_tail(live[0].path.name) == filename_tail(other.path.name)
        same_client = squash(live[0].record.client) == squash(other.record.client)
        wl, ws = live[0].welds, other.welds
        if same_job and same_client and ws <= wl:
            return SAME, (f"canlı sənəd + settled nüsxə, eyni iş nömrəsi, "
                          f"arxiv tikişləri altçoxluq ({len(ws)} / {len(wl)})")
        return UNDECIDED, ("canlı sənəd + settled nüsxə, lakin "
                           + ("iş nömrəsi fərqli" if not same_job else
                              "müştəri fərqli" if not same_client else
                              f"arxiv tikişləri altçoxluq deyil ({sorted(ws - wl)[:4]})"))

    # E / F — nothing to weigh.
    return UNDECIDED, (f"mənbə faylı tapılmadı "
                       f"(canlı {len(live)}, settled {len(settled)})")


def _winner_key(cand) -> tuple:
    """R1 winner order: live before settled, ``.docx`` before ``.pdf``, more welds,
    then ``str(path)`` so the choice is deterministic across runs and machines."""
    return (0 if cand.live else 1,
            _SUFFIX_RANK.get(cand.path.suffix.casefold(), 9) if cand.path else 9,
            -len(cand.welds),
            str(cand.path) if cand.path is not None else "")


def _retest_suffix(report_no: str) -> str:
    """The retest marker a number ends with, upper-cased (``...-056R1`` -> ``R1``)."""
    m = RETEST_SUFFIX.search(report_no or "")
    return m.group(1).upper() if m else ""


def _merged_note(dropped, keep, reason: str) -> tuple[str, str]:
    """``report.skipped`` pair for a row a ``SAME`` merge removed: both spellings."""
    return (dropped.name,
            f"{DUPLICATE_IDENTITY_MERGED} {dropped.record.report_no} -> "
            f"{keep.record.report_no} ({keep.name}): {reason}")


def merge_duplicates(records: list, items, settings) -> tuple[list, list]:
    """Collapse transposed-number duplicates in ``records``; return the notes.

    Returns ``(records, notes)``. ``records`` is a NEW list with each ``SAME``
    group's losers removed and every other row untouched, in the original order —
    the caller assigns sequence numbers after this, so a merged group frees the
    ``Sıra №`` its duplicate held. ``notes`` are ``(file, reason)`` pairs for the
    undecided groups and for every row a ``SAME`` merge drops
    (``DUPLICATE_IDENTITY_MERGED``, both spellings named), shaped for ``report.skipped``; nothing is written, moved or
    renamed, and ``DISTINCT`` groups are left entirely alone.

    Only rank-0 records are classified: a retest shares its parent's segments by
    design, and an earlier version of the audit flagged ``KF-RT-26-053`` /
    ``KF-RT-26-053R1`` as a duplicate because of it. Retests are grouped by their
    parent's order-blind key AND their suffix, never with the parent, and only a
    ``SAME`` parent pair's retests are merged (see the module docstring).

    ``merge_duplicates.last_stats`` carries the verdict Counter of the last call,
    for the audit and the collision report (same idiom as
    ``parse_cache.read_many_cached.last_stats``). ``merge_duplicates.last_child_stats``
    counts the retest groups: ``inherited`` (merged with the parent's verdict) and
    ``unmatched`` (one spelling only, kept and noted).
    """
    merge_duplicates.last_stats = collections.Counter()
    merge_duplicates.last_child_stats = collections.Counter()
    if not is_enabled(settings):
        return records, []

    input_dir = Path(settings.input_dir)
    by_key, tables = _source_index(items)

    groups: dict = collections.defaultdict(list)
    children: dict = collections.defaultdict(list)
    for record in records:
        if record.retest_rank:
            children[(canon_key(strip_retest(record.report_no)),
                      _retest_suffix(record.report_no))].append(record)
            continue
        groups[canon_key(record.report_no)].append(record)

    stats: collections.Counter = collections.Counter()
    notes: list = []
    dropped: set = set()
    same_keys: set = set()

    for key in sorted(groups):
        group = groups[key]
        if len({report_key(r.report_no) for r in group}) < 2:
            continue      # one spelling — nothing transposed
        cands = [_candidate(r, by_key, tables, input_dir) for r in group]
        verdict, reason = classify(cands)
        stats[verdict] += 1
        numbers = " / ".join(c.record.report_no for c in cands)
        if verdict == SAME:
            same_keys.add(key)
            keep = min(cands, key=_winner_key)
            for cand in cands:
                if cand.record is not keep.record:
                    dropped.add(id(cand.record))
                    notes.append(_merged_note(cand, keep, reason))
        elif verdict == UNDECIDED:
            notes.append((cands[0].name,
                          f"{DUPLICATE_IDENTITY_UNDECIDED} {numbers}: {reason}"))

    # Chain merge: a SAME parent pair's retests inherit the verdict, suffix by suffix.
    child_stats: collections.Counter = collections.Counter()
    for key, suffix in sorted(children):
        if key not in same_keys:
            continue      # parent DISTINCT / UNDECIDED / not transposed — hands off
        group = children[(key, suffix)]
        cands = [_candidate(r, by_key, tables, input_dir) for r in group]
        if len({report_key(r.report_no) for r in group}) < 2:
            child_stats["unmatched"] += 1
            notes.append((cands[0].name,
                          f"{DUPLICATE_IDENTITY_CHILD_UNMATCHED} "
                          f"{' / '.join(r.report_no for r in group)}: "
                          f"valideyn cütü {SAME}, {suffix} yalnız bir yazılışda var"))
            continue
        child_stats["inherited"] += 1
        keep = min(cands, key=_winner_key)
        for cand in cands:
            if cand.record is not keep.record:
                dropped.add(id(cand.record))
                notes.append(_merged_note(cand, keep, f"valideyn cütü {SAME}"))

    merge_duplicates.last_stats = stats
    merge_duplicates.last_child_stats = child_stats
    if not dropped:
        return records, notes
    return [r for r in records if id(r) not in dropped], notes


merge_duplicates.last_stats = collections.Counter()
merge_duplicates.last_child_stats = collections.Counter()
