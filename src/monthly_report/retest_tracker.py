"""Cross-month retest traceability — pull a retest's original parent forward.

When a target-month document is a retest (``R1``/``R2``/``RS1``) whose original
is missing from the month, this stage scans the whole parsed-document cache
(all months under ``input/``) for the same ``(method, base series)`` rank-0
document and imports the latest original dated strictly before the retest, so
a failure (Yarasız) and its cross-month repair (Yararlı) render together.

The row factory is injected (``row_builder``) so this module needs no knowledge
of how a :class:`~monthly_report.document_aggregator.ReportRow` is built —
dependencies point inward, no cycle with the aggregator.

``retest.pull_weld_check: strict`` makes the pull prove the parent is the
retest's own original before it is imported — see :func:`parent_evidence`.

I/O contract
------------
pull_cross_month_parents(records, cache, settings, method, client_code,
                         row_builder, refused=None) -> list[ReportRow]
pull_weld_check(settings) -> "off" | "strict"
parse_refusal(reason) -> (parent_no, retests, why) | None
"""

from __future__ import annotations

import datetime as _dt
import re
from collections import defaultdict
from typing import Callable

from . import date_detector, docx_reader, extractor, pdf_twin
from .method_registry import detect_method
from .report_identity import (is_excluded, report_key, resolve_report_no,
                              retest_rank, squash, strip_retest)

_PULL_WELD_CHECKS = ("off", "strict")

# The ``refused`` reason a strict pull records; ``main.py`` reads it back with
# :func:`parse_refusal` to print ``[pull rejected]``, so the shape is a contract.
_REFUSAL = re.compile(r"^çarpaz-ay valideyn (?P<parent>\S+) gətirilmədi "
                      r"\((?P<retests>[^)]*)\): (?P<why>.+)$")

# A weld's repair tail: ``QB-5RW`` / ``W40R1`` / ``QB-5RW1`` name weld QB-5 / W40.
_WELD_REPAIR = re.compile(r"(RW\d*|R\d+)$")


def pull_weld_check(settings) -> str:
    """Read ``retest.pull_weld_check`` — ``off`` when absent or unknown.

    A report number can be reused for two different jobs, and a file can carry
    another report's content, so the latest earlier original of a retest's series
    is not always that retest's original. ``strict`` checks the evidence before
    the pull (:func:`parent_evidence`) and refuses a parent that does not match.
    ``off`` is the behaviour that predates the key.
    """
    block = (getattr(settings, "raw", None) or {}).get("retest") or {}
    value = str(block.get("pull_weld_check", "off") or "off").strip().lower()
    return value if value in _PULL_WELD_CHECKS else "off"


def parse_refusal(reason: str) -> tuple[str, str, str] | None:
    """``(parent_no, retests, why)`` of a pull-refusal reason, else ``None``."""
    m = _REFUSAL.match(reason or "")
    return (m.group("parent"), m.group("retests"), m.group("why")) if m else None


def weld_bases(tables, method: str) -> set[str]:
    """The welds a document inspected, repair tails removed.

    Upper-cased, spaces removed, cut at ``/`` (``QB-1/RW-1`` -> ``QB-1``,
    ``W6/1`` -> ``W6``), then every trailing ``R<n>`` / ``RW<n>`` stripped
    (``QB-5RW`` -> ``QB-5``). Cells holding a ``:`` are header text the extractor
    picked up, not weld ids, and are dropped. Empty when nothing is readable.
    """
    if not isinstance(tables, list):
        return set()
    welds = (extractor.extract_rt_welds(tables) if method == "RT"
             else extractor.extract_welds(tables))
    out: set[str] = set()
    for w in welds:
        v = re.sub(r"\s+", "", w.get("weld_no") or "").upper()
        if not v or ":" in v:
            continue
        v = v.split("/", 1)[0]
        prev = None
        while v != prev:
            prev, v = v, _WELD_REPAIR.sub("", v)
        v = v.rstrip("-")
        if v:
            out.add(v)
    return out


def _job_tail(document_name: str) -> str:
    """The filename's job group — ``(Zığ)`` of ``U-RT-26-005 (Zığ)`` — or ``""``."""
    m = re.search(r"\(([^)]*)\)", document_name or "")
    return _fold(m.group(1)) if m else ""


def _fold(text: str) -> str:
    return squash(text).casefold()


def parent_evidence(parent, parent_tables, retests, cache: dict,
                    method: str) -> str | None:
    """Why ``parent`` is NOT the original of ``retests`` — ``None`` when it is.

    Primary evidence is the welds. When both sides name welds, every weld the
    retests inspected must be one the parent inspected; anything else refuses the
    parent (``tikiş QB-4 ≠ QB-5``).

    When either side names none, the secondary evidence decides: the filename's
    job group, the standard and the İtem / Detal must each be the same for the
    parent and every retest. Any difference refuses the parent. There is no
    fallback to an older candidate — a refused parent is simply not pulled.
    """
    parent_welds = weld_bases(parent_tables, method)
    retest_welds: set[str] = set()
    for r in retests:
        retest_welds |= weld_bases(cache.get(getattr(r, "source_path", None)), method)
    if parent_welds and retest_welds:
        if retest_welds <= parent_welds:
            return None
        return (f"tikiş {', '.join(sorted(parent_welds))} ≠ "
                f"{', '.join(sorted(retest_welds))}")
    for r in retests:
        for label, a, b in (("iş", _job_tail(parent.document_name), _job_tail(r.document_name)),
                            ("standart", _fold(parent.standard), _fold(r.standard)),
                            ("item", _fold(parent.item_detail), _fold(r.item_detail))):
            if a != b:
                return f"tikiş oxunmadı; {label} {a or '—'} ≠ {b or '—'}"
    return None


def pull_cross_month_parents(records: list, cache: dict, settings,
                             method: str, client_code: str | None,
                             row_builder: Callable,
                             refused: list | None = None) -> list:
    """Import each in-month retest's ORIGINAL from an earlier month, if any.

    For every retest row whose parent original is NOT already in this month's
    records, scan the whole ``cache`` (all months) for the same ``(method, base
    series)`` rank-0 document and pull in the **latest original dated strictly
    before the retest** — correctly handling base-№ reuse cycles (e.g. a base
    number re-inspected in a later cycle). Pulled rows are tagged
    ``is_pulled_parent`` and carry their own original date / verdict / standard, so
    a failure (Yarasız) and its cross-month repair (Yararlı) render together.

    ``row_builder`` is the aggregator's row factory
    (``(path, tables, meta, report_no, date, settings, method) -> ReportRow``).

    On ``retest.pull_weld_check: strict`` the chosen parent must pass
    :func:`parent_evidence`; a parent that fails is not pulled, the retest stays
    an orphan, and ``(parent file, reason)`` is appended to ``refused``.
    """
    strict = pull_weld_check(settings) == "strict"
    have_parent = {r.series_key for r in records if r.retest_rank == 0}
    need: dict[str, _dt.date] = {}   # base series -> earliest retest date this month
    for r in records:
        if r.retest_rank > 0 and r.series_key not in have_parent:
            cur = need.get(r.series_key)
            need[r.series_key] = min(cur, r.date) if cur else r.date
    if not need:
        return []

    # Cheap filename-only index of rank-0 candidates by normalized base series.
    candidates: dict[str, list] = defaultdict(list)
    for p in cache:
        fn_no = docx_reader.parse_filename_metadata(p).get("report_no") or ""
        if is_excluded(p.name, fn_no) or detect_method(fn_no, settings) != method or retest_rank(fn_no) != 0:
            continue
        candidates[report_key(strip_retest(fn_no))].append(p)

    pulled: list = []
    for series, retest_date in need.items():
        best = None   # (date, path, tables, meta, report_no)
        for p in candidates.get(report_key(series), []):
            tables = cache.get(p)
            if not isinstance(tables, list):
                continue
            meta = extractor.extract_meta(tables)
            rno, _drift = resolve_report_no(meta, p)
            if retest_rank(rno) != 0 or report_key(strip_retest(rno)) != report_key(series):
                continue
            d = date_detector.parse_inspection_date(
                meta.get("date", ""), settings.dayfirst, rno,
                pdf_twin.names_for(p, settings))
            if d is None or d >= retest_date:
                continue   # must be a PRIOR original
            if best is None or d > best[0]:
                best = (d, p, tables, meta, rno)
        if best is None:
            continue   # no earlier original -> stays an orphan retest
        d, p, tables, meta, rno = best
        row = row_builder(p, tables, meta, rno, d, settings, method)
        if strict:
            retests = [r for r in records
                       if r.retest_rank > 0 and r.series_key == series]
            why = parent_evidence(row, tables, retests, cache, method)
            if why is not None:
                if refused is not None:
                    names = ", ".join(r.report_no for r in retests)
                    refused.append((p.name, f"çarpaz-ay valideyn {rno} gətirilmədi "
                                            f"({names}): {why}"))
                continue
        row.is_pulled_parent = True
        pulled.append(row)
    return pulled
