"""Shared naming constants and formatting — single home for month tables,
folder names, the document-number pattern and default output paths.

Every module that previously carried its own copy of ``_MONTH_ABBR`` /
``_AZ_MONTHS`` / ``"SKIPPED_REPORTS"`` imports from here instead, so the PDF
header, the JSON sidecar and the console output can never drift apart.

I/O contract
------------
default_output(settings, month, method=None, subdir=None, client=None) -> Path
document_number(settings, month_date, seq=1, method="", client="") -> str
reporting_period(month) -> str
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

# Quarantine folder (under input/) for reports that can never be processed —
# unreadable/corrupt, ASR/ARS, or with no detectable inspection date. Kept out
# of the working method dirs and excluded from every scan.
QUARANTINE_DIR = "SKIPPED_REPORTS"

# Archive folder (under input/) for source .pdf files that have been
# pre-converted to .docx (or that needed no conversion). Excluded from the PDF
# scan, so an archived original is never converted a second time.
PDF_ARCHIVE_DIR = "PDF_ARCHIVE"

# Recoverable trash (under input/) for redundant files the housekeeping pass
# prunes — byte-identical duplicates, quarantine copies replaced by a searchable
# report, and UnSorted leftovers already settled elsewhere. Nothing is deleted;
# it is moved here so a wrong call can be reviewed and restored. Excluded from
# every input scan (see pre_processor.SETTLED_DIRS).
PRUNED_DIR = "_PRUNED"

# The transient staging folder (under input/) where fresh drops land before the
# sorter files them into method folders. Named here so the housekeeping pass can
# find leftovers; it is otherwise an ordinary nested folder, not a settled one.
UNSORTED_DIR = "UnSorted"

MONTH_ABBR = {1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
              7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC"}

# Azerbaijani month names for the "Hesabat dövrü" traceability line — shared by
# the PDF renderer and the JSON exporter so both always agree.
AZ_MONTHS = {
    1: "Yanvar", 2: "Fevral", 3: "Mart", 4: "Aprel", 5: "May", 6: "İyun",
    7: "İyul", 8: "Avqust", 9: "Sentyabr", 10: "Oktyabr", 11: "Noyabr", 12: "Dekabr",
}


def default_output(settings, month: str, method: str | None = None,
                   subdir: str | None = None, client: str | None = None) -> Path:
    """Default PDF path. ``subdir`` (e.g. ``UBOC`` — the client code) segregates
    output into ``output/<subdir>/``; the filename carries whichever of the method
    and client tokens are given, so ``output/UBOC/compiled_monthly_report_UBOC_JAN_2026.pdf``.

    ``method`` is left in the signature and still honoured, but the pipeline stopped
    passing it under ADR-004: a compiled document is one month of one client across
    EVERY method, so there is no single method token to name it by."""
    year, mon = month.split("-")
    abbr = MONTH_ABBR[int(mon)]
    tokens = "".join(f"{t.upper()}_" for t in (method, client) if t)
    base = Path(settings.output_dir)
    if subdir:
        base = base / subdir
    return base / f"compiled_monthly_report_{tokens}{abbr}_{year}.pdf"


def document_number(settings, month_date: _dt.date, seq: int = 1,
                    method: str = "", client: str = "") -> str:
    mon = MONTH_ABBR[month_date.month]
    mm = f"{month_date.month:02d}"
    yy = month_date.year % 100
    method = (method or "").upper()
    # Guard an empty client so the official ``MR-<CLIENT>-<YY>-<MM>`` serial never
    # collapses into a double dash (``MR--26-02``).
    client = (client or "").upper() or "NA"
    try:
        # ``method``/``mon``/``seq`` stay available for back-compat with any custom
        # pattern; the official pattern (ADR-004) uses ``client``, ``yy`` and ``mm``
        # only — one client-month is one document, so it is already unique.
        return settings.doc_number_pattern.format(
            method=method, client=client, mon=mon, mm=mm, yy=f"{yy:02d}", seq=seq)
    except Exception:
        return f"MR-{client}-{yy:02d}-{mm}"


def reporting_period(month: str) -> str:
    """Format a ``YYYY-MM`` month as the PDF's ``<Ay> <İl>`` (e.g. ``Fevral 2026``).

    Mirrors the renderer's meta block exactly; falls back to ``"—"`` on a
    malformed month, just like the renderer, so the field is never blank.
    """
    try:
        year, mon = str(month).split("-")
        return f"{AZ_MONTHS[int(mon)]} {year}"
    except Exception:
        return "—"
