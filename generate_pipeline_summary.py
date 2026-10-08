#!/usr/bin/env python3
"""Compile the Executive Pipeline Analytics & Audit report to a print-ready PDF.

Standalone helper: scans the LIVE system state — the compiled ``output/`` sidecars,
the ``input/`` document footprint, the ``.parse_cache/`` store, the ``.state/``
dashboard bookkeeping, and the portal upload ledger (``.upload_state.json`` +
``output/upload_status.json``) — and renders a multi-page Azerbaijani executive
audit report to ``output/pipeline_executive_summary_report.pdf``.

It is an aggregator + ReportLab composer over the existing pipeline modules, not
new pipeline logic. Every stat comes from a service the pipeline already exposes:

* headline counts        -> monthly_report.gui.services.metrics.collect
* generated artefacts    -> monthly_report.gui.services.catalog.scan
* cache hit-rate         -> monthly_report.gui.services.cache_stats_service.load
* quarantine reasons     -> monthly_report.gui.services.quarantine_reasons_service
* per-report records     -> the json_exporter sidecars under output/<Client>/*.json

Deliberately does not import monthly_report.pdf_renderer: like the inspector
worksheet, this borrows the house style (DejaVu fonts, #1B365D header rule, A4
margins) by copying the constants rather than coupling to renderer internals.

Charts are drawn with reportlab.graphics (vector, embedded as Drawing flowables)
so no extra dependency is needed.

    python generate_pipeline_summary.py
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

# Windows consoles default to a legacy codepage (cp1251) that cannot encode the
# Azerbaijani characters in our status output; force UTF-8 so prints never crash.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

from monthly_report import __version__ as SYSTEM_VERSION
from monthly_report.config import load_settings
from monthly_report.method_registry import (is_active_client,
                                            is_excluded_client,
                                            resolve_client_by_field)
from monthly_report.naming import AZ_MONTHS, MONTH_ABBR, reporting_period
from monthly_report.gui.services import (
    cache_stats_service,
    catalog as catalog_mod,
    metrics as metrics_mod,
    quarantine_reasons_service,
)

# --- House style (copied from pdf_renderer / generate_inspector_worksheet) --------------

FONT_REGULAR = "DejaVu"
FONT_BOLD = "DejaVu-Bold"

FONT_REGULAR_PATH = PROJECT_ROOT / "assets" / "fonts" / "DejaVuSans.ttf"
FONT_BOLD_PATH = PROJECT_ROOT / "assets" / "fonts" / "DejaVuSans-Bold.ttf"

# Company logo stamped top-left in the page header. Optional: a missing file is
# never fatal (see _draw_chrome) so a fresh checkout still builds.
LOGO_PATH = PROJECT_ROOT / "images" / "Mag-Pi Logo.png"

_HEADER_BG = colors.HexColor("#1B365D")
_HEADER_FG = colors.white
_GRID = colors.HexColor("#5A6570")   # darker than the on-screen grid so rules stay crisp in B&W print
_RULE = colors.HexColor("#1B365D")
_MUTED = colors.HexColor("#555555")
# KPI cards are print-first: solid charcoal ink on a faint grey fill with crisp
# dark borders, so a black-and-white print stays legible with no colour cue lost.
_INK = colors.HexColor("#111827")          # near-black charcoal for all card text
_CARD_BG = colors.HexColor("#F8FAFC")      # light grey fill
_CARD_BORDER = colors.HexColor("#334155")  # crisp dark card border

# Categorical palette for the charts — ordered as a luminance ladder so the
# slices/bars stay distinct even when the report is printed in black-and-white
# (each step is a clearly different grey). White strokes separate adjacent fills.
_PALETTE = [
    colors.HexColor("#14243B"), colors.HexColor("#7A8794"),
    colors.HexColor("#3E6B4A"), colors.HexColor("#B08A1E"),
    colors.HexColor("#8C3A2E"), colors.HexColor("#4A3A5E"),
    colors.HexColor("#2E6E8E"), colors.HexColor("#C4CBD2"),
]

_LEFT = 15 * mm
_RIGHT = 12 * mm
_TOP = 34 * mm
_BOTTOM = 17 * mm
_HEADER_SIDE = 115
_CONTENT_MM = 183  # A4 minus our margins

_TITLE = ("NDT İNSPEKSİYA VƏ AYLIQ HESABAT AVTOMATLAŞDIRMA SİSTEMİ — "
          "İCRAÇI AUDİT VƏ STATİSTİKA HESABATI")
# Header band shows the system name only — the report name lives in the large
# page-1 body title (_TITLE_PAGE), so the two never repeat the same phrase.
_HEADER_TITLE = "NDT İNSPEKSİYA VƏ AYLIQ HESABAT AVTOMATLAŞDIRMA SİSTEMİ"
_TITLE_SHORT = "İcraçı Audit və Statistika Hesabatı"
# Page-1 body title — enlarged, uppercase. Hardcoded (not .upper()) so the
# Azerbaijani dotted/dotless i pair is cased correctly (İ, not I).
_TITLE_PAGE = "İCRAÇI AUDİT VƏ STATİSTİKA HESABATI"

# Quality verdict labels (from translations/az.json — echoed here for tallying).
_Q_YARARLI = "Yararlı"
_Q_YARARSIZ = "Yararsız"
_Q_INFO = "Məlumat üçün"

# NDT method token -> display label, in the order the spec asks them shown.
# Tokens are the sidecar `ndt_method` values (MT=MPI folder, FC=FERRITE, HRT=HT).
_METHOD_ORDER: list[tuple[str, str]] = [
    ("UT", "UT"), ("MT", "MT"), ("RT", "RT"), ("DP", "DP"),
    ("UTM", "UTM"), ("FC", "FERRITE"), ("PMI", "PMI"), ("HRT", "HT"),
]
_METHOD_LABELS = dict(_METHOD_ORDER)
# Accept a few alternate tokens defensively (older sidecars / hand edits).
_METHOD_ALIASES = {"FERRITE": "FC", "HT": "HRT", "MPI": "MT", "PT": "DP"}


# --- Month resolution (incomplete-month exclusion + CLI scoping) ------------------------
#
# Official audit reports are only ever cut for a *fully completed* calendar month.
# The current month is incomplete, so the default target is always the latest
# closed month (July 24, 2026 -> "2026-06"). --month / --date may scope to any
# other closed month; requesting the ongoing month is refused, not silently
# rolled back, so an operator never mistakes a partial extract for an official one.

_ABBR_TO_NUM = {abbr: num for num, abbr in MONTH_ABBR.items()}
_AZ_MONTH_TO_NUM = {name.casefold(): num for num, name in AZ_MONTHS.items()}


def latest_completed_month(today: dt.date | None = None) -> str:
    """The most recent fully finished calendar month as ``YYYY-MM``.

    Last day of the previous month = ``(first of this month) - 1 day``; the
    ongoing month is never returned because it is not finished yet.
    """
    today = today or dt.date.today()
    last_prev = today.replace(day=1) - dt.timedelta(days=1)
    return f"{last_prev.year:04d}-{last_prev.month:02d}"


def is_month_complete(month: str, today: dt.date | None = None) -> bool:
    """True when ``month`` (``YYYY-MM``) is strictly before the ongoing month.

    ``YYYY-MM`` sorts lexicographically the same as chronologically, so a plain
    string compare is enough and avoids a second date parse.
    """
    today = today or dt.date.today()
    return month < f"{today.year:04d}-{today.month:02d}"


def parse_month_arg(arg: str) -> str:
    """Normalise a CLI month token to canonical ``YYYY-MM``.

    Accepts ``YYYY-MM`` (2026-06), ``YY-MM`` (26-06 / 26-02), ``MMM_YYYY``
    (JUN_2026), and the same forms with ``-``/``_``/``/``/``.`` separators.
    """
    tokens = [t for t in re.split(r"[-_/. ]+", str(arg).strip().upper()) if t]
    if len(tokens) != 2:
        raise ValueError(f"Unparseable month token: {arg!r}")
    a, b = tokens
    if a.isalpha():          # MMM_YYYY
        mon, year = _ABBR_TO_NUM.get(a), _int(b)
    elif b.isalpha():        # YYYY_MMM
        mon, year = _ABBR_TO_NUM.get(b), _int(a)
    elif len(a) == 4:        # YYYY-MM
        year, mon = _int(a), _int(b)
    elif len(b) == 4:        # MM-YYYY
        mon, year = _int(a), _int(b)
    else:                    # YY-MM
        year, mon = 2000 + _int(a), _int(b)
    if mon is None or year is None or not 1 <= mon <= 12:
        raise ValueError(f"Unparseable month token: {arg!r}")
    return f"{year:04d}-{mon:02d}"


def _int(text: str) -> int | None:
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def resolve_target_month(arg: str | None = None, today: dt.date | None = None) -> str:
    """Canonical ``YYYY-MM`` target for the report, enforcing the closed-month rule.

    ``None`` -> latest completed month. An explicit incomplete/ongoing (or future)
    month is refused with a ``SystemExit`` rather than downgraded silently.
    """
    today = today or dt.date.today()
    if arg is None:
        return latest_completed_month(today)
    month = parse_month_arg(arg)
    if not is_month_complete(month, today):
        raise SystemExit(
            f"İmtina: {month} tamamlanmamış/cari aydır — rəsmi hesabat yalnız "
            f"bağlanmış ay üçün tərtib olunur. Ən son bağlanmış ay: "
            f"{latest_completed_month(today)}."
        )
    return month


def catalog_month(month: str) -> str:
    """``2026-06`` -> ``JUN_2026`` (the catalog/metrics/sidecar month token)."""
    year, mon = month.split("-")
    return f"{MONTH_ABBR[int(mon)]}_{year}"


def scoped_output_name(month: str) -> str:
    """Month-stamped PDF filename, e.g. ``pipeline_executive_summary_report_2026_06.pdf``."""
    year, mon = month.split("-")
    return f"pipeline_executive_summary_report_{year}_{mon}.pdf"


def audit_serial(month: str) -> str:
    """Traceable audit serial for a ``YYYY-MM`` month, e.g. ``AUD-MR-2026-06``.

    Stamped top-right in every page header so a printed summary is uniquely
    identifiable and tied to exactly one closed reporting month.
    """
    year, mon = str(month).split("-")
    return f"AUD-MR-{int(year):04d}-{int(mon):02d}"


# --- Aggregation (pure, unit-testable) --------------------------------------------------


@dataclass
class MethodRow:
    token: str
    label: str
    reports: int = 0        # distinct compiled reports (sidecars) for this method
    records: int = 0        # summed item rows across those reports
    yararli: int = 0        # item rows with a "Yararlı" verdict
    items: int = 0          # verdict-bearing item rows (denominator for Yararlı %)

    @property
    def yararli_pct(self) -> float:
        """Share of this method's verdict rows that came back ``Yararlı``."""
        return (self.yararli / self.items * 100.0) if self.items else 0.0


@dataclass
class ClientRow:
    name: str
    voen: str
    records: int = 0
    serials: list[str] = field(default_factory=list)


@dataclass
class Aggregation:
    method_rows: list[MethodRow] = field(default_factory=list)
    client_rows: list[ClientRow] = field(default_factory=list)
    quality: dict[str, int] = field(default_factory=dict)  # label -> row count
    total_reports: int = 0        # compiled report sidecars in scope
    total_records: int = 0        # item rows across those reports
    total_source_reports: int = 0  # distinct source inspection reports behind them


def _canonical_method(token: str) -> str:
    token = (token or "").strip().upper()
    return _METHOD_ALIASES.get(token, token)


def tally_sidecars(sidecars: list[dict]) -> Aggregation:
    """Roll a list of json_exporter sidecar dicts into the report's aggregates.

    Kept pure (list-in, dataclass-out) so it can be unit-tested with inline
    fixtures without touching the filesystem or rendering a PDF.
    """
    by_method: dict[str, MethodRow] = {}
    by_client: dict[tuple[str, str], ClientRow] = {}
    quality: dict[str, int] = defaultdict(int)
    total_source = 0

    for sc in sidecars:
        # Distinct source inspection reports behind this compiled batch — the
        # honest "documents processed" figure, scoped to whatever month subset
        # this call was handed (retests merge, so it can exceed the record count).
        total_source += _as_int(sc.get("source_report_count"), default=1)
        records = _as_int(sc.get("total_records"), default=len(sc.get("items_table") or []))

        # Method breakdown, attributed PER ROW. Before ADR-004 one sidecar was one
        # method and "+1 report, +total_records records" was exact; a document now
        # spans every method of its client-month, so crediting all of it to whichever
        # token the root ndt_method happens to name would file a client's DP and UTM
        # rows under MT. Rows are attributed by items_table[].method; `reports` still
        # counts DOCUMENTS — now "documents containing this method", which is the
        # same number as before for a single-method sidecar. A sidecar with no
        # per-row method (pre-ADR-004) falls back to the root token, and one with no
        # items_table at all falls back to its declared total_records, so the old
        # figures are reproduced exactly.
        rows = [r for r in (sc.get("items_table") or []) if isinstance(r, dict)]
        root_token = _canonical_method(sc.get("ndt_method", ""))
        per_method: dict[str, int] = {}
        for item in rows:
            tok = _canonical_method(str(item.get("method", "") or "")) or root_token
            per_method[tok] = per_method.get(tok, 0) + 1
        if not per_method:
            per_method = {root_token: records}
        elif len(per_method) == 1:
            # One method in the document: its DECLARED total_records is authoritative,
            # exactly as before ADR-004. Only a mixed document has to be split by row,
            # because there the declared total says nothing about who owns what.
            per_method = {next(iter(per_method)): records}
        for token, n_rows in per_method.items():
            label = _METHOD_LABELS.get(token, token or "NDT")
            row = by_method.get(token)
            if row is None:
                row = by_method[token] = MethodRow(token=token, label=label)
            row.reports += 1
            row.records += n_rows

        name = str(sc.get("client_name") or "—")
        voen = str(sc.get("client_voen") or "—")
        crow = by_client.get((name, voen))
        if crow is None:
            crow = by_client[(name, voen)] = ClientRow(name=name, voen=voen)
        crow.records += records
        serial = sc.get("report_serial_no")
        if serial:
            crow.serials.append(str(serial))

        for item in sc.get("items_table") or []:
            result = str((item or {}).get("result") or "").strip()
            if result:
                quality[result] += 1
                row.items += 1
                if result == _Q_YARARLI:
                    row.yararli += 1

    # Method rows in the spec's canonical order first, then any extras present.
    ordered: list[MethodRow] = []
    for token, label in _METHOD_ORDER:
        if token in by_method:
            ordered.append(by_method.pop(token))
        else:
            ordered.append(MethodRow(token=token, label=label))
    ordered.extend(sorted(by_method.values(), key=lambda r: r.label))

    clients = sorted(by_client.values(), key=lambda c: c.records, reverse=True)

    return Aggregation(
        method_rows=ordered,
        client_rows=clients,
        quality=dict(quality),
        total_reports=sum(r.reports for r in ordered),
        total_records=sum(r.records for r in ordered),
        total_source_reports=total_source,
    )


def _as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def yararli_ratio(quality: dict[str, int]) -> float:
    """Conformance ratio: ``Yararlı`` as a percent of all graded verdict rows.

    Denominator is the three official verdicts (``Yararlı`` / ``Məlumat üçün`` /
    ``Yararsız``); returns ``0.0`` when nothing has been graded so a KPI card
    never divides by zero.
    """
    graded = sum(quality.get(k, 0) for k in (_Q_YARARLI, _Q_INFO, _Q_YARARSIZ))
    return (quality.get(_Q_YARARLI, 0) / graded * 100.0) if graded else 0.0


def load_sidecars(output_dir: Path) -> list[dict]:
    """Every compiled report's JSON sidecar, best-effort.

    A malformed sidecar someone hand-edited must not stop the audit report from
    building, so unreadable files are skipped rather than raising.
    """
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return []
    out: list[dict] = []
    for path in sorted(output_dir.rglob("compiled_monthly_report_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            # Stamp the catalog-format month from the filename (the most reliable
            # source: `..._JUN_2026.json` -> `JUN_2026`) so month scoping never
            # depends on re-parsing the Azerbaijani reporting_period string.
            parts = path.stem.split("_")
            if len(parts) >= 2:
                data.setdefault("_month", f"{parts[-2]}_{parts[-1]}")
            out.append(data)
    return out


def sidecar_month(sc: dict) -> str:
    """Catalog-format month (``JUN_2026``) for a sidecar, best-effort.

    Prefers the filename stamp injected by :func:`load_sidecars`; falls back to
    the Azerbaijani ``reporting_period`` (``İyun 2026``) and finally the serial
    suffix (``MR-DP-KHE-26-06`` -> ``JUN_2026``) so a hand-built or older sidecar
    with no ``_month`` key still scopes correctly.
    """
    stamped = str(sc.get("_month") or "")
    if stamped:
        return stamped
    toks = str(sc.get("reporting_period") or "").split()
    if len(toks) == 2 and toks[1].isdigit():
        num = _AZ_MONTH_TO_NUM.get(toks[0].casefold())
        if num:
            return f"{MONTH_ABBR[num]}_{toks[1]}"
    m = re.search(r"-(\d{2})-(\d{2})$", str(sc.get("report_serial_no") or ""))
    if m:
        yy, mm = int(m.group(1)), int(m.group(2))
        if 1 <= mm <= 12:
            return f"{MONTH_ABBR[mm]}_20{yy:02d}"
    return ""


def filter_sidecars_by_month(sidecars: list[dict], cat_month: str) -> list[dict]:
    """Keep only sidecars belonging to ``cat_month`` (catalog format ``JUN_2026``)."""
    if not cat_month:
        return list(sidecars)
    return [sc for sc in sidecars if sidecar_month(sc) == cat_month]


def filter_active_clients(sidecars: list[dict], settings) -> list[dict]:
    """Drop sidecars for retired/inactive clients from the audit aggregation.

    A blacklisted client (``active: false`` or ``excluded_clients``) must not appear
    in the executive tables, charts or the "Aktiv Müştəri Portfeli" KPI, even if a
    report compiled before it was retired still sits in output/. The sidecar carries
    the display ``client_name``; it is resolved back to the registry code the same
    way the uploader does. Low-volume clients need no filter here — they never
    compiled a sidecar (skipped in place), and main.py purges any stale one.
    """
    kept: list[dict] = []
    for sc in sidecars:
        code, _name = resolve_client_by_field(
            {"client": str(sc.get("client_name", "") or "")}, "", settings)
        if code and (is_excluded_client(code, settings)
                     or not is_active_client(code, settings)):
            continue
        kept.append(sc)
    return kept


def load_portal_ledger(root: Path) -> dict:
    """Portal upload state, summarised defensively from the two on-disk sources.

    ``.upload_state.json`` is the idempotency ledger (status per compiled PDF);
    ``output/upload_status.json`` is the human-readable audit array. Either may be
    absent or empty on a fresh checkout — we never raise, we return zeroes.
    """
    root = Path(root)
    status_counts: dict[str, int] = defaultdict(int)
    entries = 0
    try:
        data = json.loads((root / ".upload_state.json").read_text(encoding="utf-8"))
        for entry in (data.get("entries") or {}).values():
            entries += 1
            status_counts[str((entry or {}).get("status") or "?")] += 1
    except (OSError, ValueError, AttributeError):
        pass

    audit_counts: dict[str, int] = defaultdict(int)
    audit_total = 0
    try:
        arr = json.loads((root / "output" / "upload_status.json").read_text(encoding="utf-8"))
        if isinstance(arr, list):
            for rec in arr:
                audit_total += 1
                audit_counts[str((rec or {}).get("status") or "?")] += 1
    except (OSError, ValueError):
        pass

    return {
        "ledger_entries": entries,
        "ledger_status": dict(status_counts),
        "audit_total": audit_total,
        "audit_status": dict(audit_counts),
    }


def parse_cache_size(root: Path) -> int:
    """Number of memoised parses in the ``.parse_cache/`` store (0 if absent)."""
    cache_dir = Path(root) / ".parse_cache"
    if not cache_dir.is_dir():
        return 0
    return sum(1 for p in cache_dir.glob("*.json") if p.is_file())


# --- PDF styles -------------------------------------------------------------------------


def _register_fonts() -> None:
    if not FONT_REGULAR_PATH.is_file() or not FONT_BOLD_PATH.is_file():
        raise SystemExit(
            f"Required font missing under {FONT_REGULAR_PATH.parent}: "
            "DejaVuSans.ttf / DejaVuSans-Bold.ttf (see assets/fonts/README.md)."
        )
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(FONT_REGULAR_PATH)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(FONT_BOLD_PATH)))
    pdfmetrics.registerFontFamily(
        FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD,
        italic=FONT_REGULAR, boldItalic=FONT_BOLD,
    )


def _styles() -> dict:
    return {
        "title_pg": ParagraphStyle("title_pg", fontName=FONT_BOLD, fontSize=15,
                                   leading=18, textColor=_HEADER_BG, alignment=1,
                                   spaceBefore=0, spaceAfter=4),
        "h1": ParagraphStyle("h1", fontName=FONT_BOLD, fontSize=13, leading=17,
                             textColor=_HEADER_BG, spaceBefore=6, spaceAfter=6,
                             keepWithNext=True),
        "h2": ParagraphStyle("h2", fontName=FONT_BOLD, fontSize=11, leading=15,
                             textColor=_HEADER_BG, spaceBefore=10, spaceAfter=4,
                             keepWithNext=True),
        "body": ParagraphStyle("body", fontName=FONT_REGULAR, fontSize=9.5, leading=14),
        "muted": ParagraphStyle("muted", fontName=FONT_REGULAR, fontSize=9, leading=13,
                                textColor=_MUTED),
        "th": ParagraphStyle("th", fontName=FONT_BOLD, fontSize=8.5, leading=11,
                             alignment=1, textColor=_HEADER_FG),
        "td": ParagraphStyle("td", fontName=FONT_REGULAR, fontSize=8.5, leading=12),
        "td_c": ParagraphStyle("td_c", fontName=FONT_REGULAR, fontSize=8.5, leading=12,
                               alignment=1),
        "td_r": ParagraphStyle("td_r", fontName=FONT_REGULAR, fontSize=8.5, leading=12,
                               alignment=2),
        "kpi_num": ParagraphStyle("kpi_num", fontName=FONT_BOLD, fontSize=20, leading=22,
                                  textColor=_INK, alignment=1),
        "kpi_lbl": ParagraphStyle("kpi_lbl", fontName=FONT_BOLD, fontSize=8, leading=11,
                                  textColor=_INK, alignment=1),
        "kpi_sub": ParagraphStyle("kpi_sub", fontName=FONT_REGULAR, fontSize=7.5, leading=10,
                                  textColor=_INK, alignment=1),
        "sig": ParagraphStyle("sig", fontName=FONT_REGULAR, fontSize=9, leading=16),
        "sig_b": ParagraphStyle("sig_b", fontName=FONT_BOLD, fontSize=9, leading=16,
                                textColor=_HEADER_BG),
    }


def _draw_chrome(c, doc, settings, target_month: str | None = None,
                 all_time: bool = False) -> None:
    """Centered title band + blue rule on top; muted rule + page number at foot.

    ``target_month`` (canonical ``YYYY-MM``) drives the top-right audit identity
    block (serial, period, build version) so every printed page is traceable to
    exactly one closed reporting month. ``all_time`` overrides that with the global
    ``BÜTÜN DÖVR`` identity for the un-scoped ``--all`` audit.
    """
    w, h = A4
    band_left = _LEFT + _HEADER_SIDE
    band_right = (w - _RIGHT) - _HEADER_SIDE
    band_cx = (band_left + band_right) / 2.0
    band_w = band_right - band_left

    # Two-line wrap of the system name, auto-fit to the band width.
    line1, line2 = _split_title(_HEADER_TITLE)
    fs = 10.5
    while fs > 6.0 and (
        c.stringWidth(line1, FONT_BOLD, fs) > band_w
        or c.stringWidth(line2, FONT_BOLD, fs) > band_w
    ):
        fs -= 0.5
    c.setFont(FONT_BOLD, fs)
    c.setFillColor(_RULE)
    top_y = h - 12 * mm
    c.drawCentredString(band_cx, top_y, line1)
    c.drawCentredString(band_cx, top_y - (fs + 2), line2)

    # Top-right audit identity stack — unique serial + traceability metadata.
    if all_time:
        ident = [
            ("Audit Hesabat №: AUD-MR-BÜTÜN-DÖVR", FONT_BOLD, _RULE),
            ("Hesabat dövrü: Bütün dövr", FONT_REGULAR, _MUTED),
            (f"Tərtib: {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}", FONT_REGULAR, _MUTED),
            (f"Sistem versiyası: {SYSTEM_VERSION}", FONT_REGULAR, _MUTED),
        ]
    elif target_month:
        ident = [
            (f"Audit Hesabat №: {audit_serial(target_month)}", FONT_BOLD, _RULE),
            (f"Hesabat dövrü: {reporting_period(target_month)}", FONT_REGULAR, _MUTED),
            (f"Tərtib: {dt.datetime.now().strftime('%d.%m.%Y %H:%M')}", FONT_REGULAR, _MUTED),
            (f"Sistem versiyası: {SYSTEM_VERSION}", FONT_REGULAR, _MUTED),
        ]
    else:
        ident = []
    if ident:
        iy = h - 11 * mm
        for text, font, color in ident:
            c.setFont(font, 7)
            c.setFillColor(color)
            c.drawRightString(w - _RIGHT, iy, text)
            iy -= 9

    # Company logo in the left header reservation. Optional and best-effort — a
    # missing or unreadable asset must never break the audit build.
    try:
        if LOGO_PATH.is_file():
            logo = ImageReader(str(LOGO_PATH))
            iw, ih = logo.getSize()
            logo_h = 16 * mm
            logo_w = logo_h * (iw / ih) if ih else logo_h
            logo_w = min(logo_w, _HEADER_SIDE - 6)   # never spill into the title band
            c.drawImage(logo, _LEFT, h - 22 * mm, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, anchor="sw", mask="auto")
    except Exception:
        pass

    rule_y = h - 25 * mm
    c.setStrokeColor(_RULE)
    c.setLineWidth(1)
    c.line(_LEFT, rule_y, w - _RIGHT, rule_y)

    c.setFont(FONT_REGULAR, 8)
    c.setFillColor(_MUTED)
    c.setStrokeColor(_GRID)
    c.setLineWidth(0.5)
    c.line(_LEFT, _BOTTOM - 3 * mm, w - _RIGHT, _BOTTOM - 3 * mm)
    c.drawString(_LEFT, _BOTTOM - 8 * mm, "MAG-Pi  •  İcraçı Audit Hesabatı")
    c.drawCentredString((w) / 2.0, _BOTTOM - 8 * mm, f"Səhifə {doc.page}")
    c.drawRightString(w - _RIGHT, _BOTTOM - 8 * mm,
                      f"Tarix: {dt.date.today().strftime(settings.date_format)}")


def _split_title(title: str) -> tuple[str, str]:
    """Break the title into two balanced header lines.

    Prefers the em-dash; otherwise splits at the word boundary nearest the
    character midpoint so neither line runs long and clips against the logo.
    """
    if "—" in title:
        left, right = title.split("—", 1)
        return left.strip(), "— " + right.strip()
    words = title.split()
    if len(words) < 2:
        return title, ""
    mid = len(title) / 2.0
    best_i, best_gap = 1, None
    run = 0
    for i, word in enumerate(words[:-1], start=1):
        run += len(word) + 1  # word + trailing space
        gap = abs(run - mid)
        if best_gap is None or gap < best_gap:
            best_gap, best_i = gap, i
    return " ".join(words[:best_i]), " ".join(words[best_i:])


# --- PDF sections -----------------------------------------------------------------------


def _kpi_card(value: str, label: str, sub: str, st: dict) -> Table:
    inner = Table(
        [[Paragraph(value, st["kpi_num"])],
         [Paragraph(label, st["kpi_lbl"])],
         [Paragraph(sub, st["kpi_sub"])]],
        colWidths=[(_CONTENT_MM / 3 - 4) * mm],
    )
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _CARD_BG),
        ("BOX", (0, 0), (-1, -1), 1, _CARD_BORDER),
        ("LINEABOVE", (0, 0), (-1, 0), 2.5, _CARD_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, 1), 1),
    ]))
    return inner


def _kpi_section(metrics, agg, cache_eff, cache_size, ledger, st,
                 scoped: bool = True) -> list:
    """The six executive KPI cards, exactly as the audit spec prescribes.

    Print-first: no trend deltas, no colour cues — every card carries a clean,
    direct Azerbaijani caption in solid charcoal so the grid prints cleanly in
    black-and-white with nothing lost.

    ``scoped`` (default) draws the month-scoped numbers straight from ``agg`` (the
    month-filtered sidecars). ``scoped=False`` is the ``--all`` global audit view:
    cards 1/3 fall back to the cumulative ``metrics.collect`` counts. Card 3
    (quarantine) has no month attribution on disk, so it always shows the all-time
    backlog — its subtext just says so plainly when scoped.
    """
    cache_rate = cache_eff.rate_label if cache_eff else "—"
    cache_cap = cache_eff.caption if cache_eff else f"{cache_size} keşlənmiş fayl"

    if scoped:
        card1 = _kpi_card(str(agg.total_source_reports), "Ümumi İnspeksiya Sayı",
                          "Skan edilmiş ilkin sənədlər", st)
        card3 = _kpi_card(str(metrics.quarantined), "Karantin / Anomaliya Sayı",
                          "Cəmi backlog — aya görə bölünmür", st)
    else:
        card1 = _kpi_card(str(metrics.documents), "Ümumi İnspeksiya Sayı",
                          "Skan edilmiş ilkin sənədlər (bütün dövr)", st)
        card3 = _kpi_card(str(metrics.quarantined), "Karantin / Anomaliya Sayı",
                          "Karantinə alınmış fayllar", st)

    cards = [
        card1,
        _kpi_card(str(metrics.pdfs), "Hazırlanmış Rəsmi PDF/JSON",
                  "Tərtib edilmiş rəsmi hesabatlar", st),
        card3,
        _kpi_card(str(agg.total_records), "Qiymətləndirilmiş Qeyd Sayı",
                  "Cəmi müayinə qeydləri", st),
        _kpi_card(cache_rate, "Keş Səmərəliliyi", cache_cap, st),
        _kpi_card(str(len(agg.client_rows)), "Aktiv Müştəri Portfeli",
                  "unikal sifarişçi", st),
    ]
    grid = Table(
        [cards[0:3], cards[3:6]],
        colWidths=[(_CONTENT_MM / 3) * mm] * 3,
    )
    grid.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return [Paragraph("İcraçı Əsas Göstəricilər (KPI)", st["h2"]), grid]


def _table(data: list[list], col_mm: list[float], st: dict, aligns=None) -> Table:
    table = Table(data, colWidths=[w * mm for w in col_mm], repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.75, _GRID),
        ("LINEBELOW", (0, 1), (-1, -1), 0.75, _GRID),
        ("LINEAFTER", (0, 0), (-2, -1), 0.75, _GRID),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, _RULE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    table.setStyle(TableStyle(style))
    return table


def _method_table(agg: Aggregation, st: dict) -> Table:
    head = [Paragraph(h, st["th"]) for h in
            ("NDT Metodu", "Metod Kodu", "Hesabat Sayı", "Cəmi Qeyd",
             "Nəticə Payı<br/>(Yararlı %)")]
    data = [head]
    for r in agg.method_rows:
        data.append([
            Paragraph(r.label, st["td"]),
            Paragraph(r.token, st["td_c"]),
            Paragraph(str(r.reports), st["td_c"]),
            Paragraph(str(r.records), st["td_c"]),
            Paragraph(f"{r.yararli_pct:.1f}%", st["td_r"]),
        ])
    data.append([
        Paragraph("CƏMİ", st["td"]),
        Paragraph("", st["td_c"]),
        Paragraph(str(agg.total_reports), st["td_c"]),
        Paragraph(str(agg.total_records), st["td_c"]),
        Paragraph(f"{yararli_ratio(agg.quality):.1f}%", st["td_r"]),
    ])
    table = _table(data, [50, 28, 32, 32, 41], st)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, -1), (-1, -1), FONT_BOLD),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAEFF4")),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, _RULE),
    ]))
    return table


def _client_table(agg: Aggregation, st: dict) -> Table:
    head = [Paragraph(h, st["th"]) for h in
            ("Müştəri (Sifarişçi)", "VÖEN", "Qeyd sayı", "Hesabat Serialı", "Status")]
    data = [head]
    if not agg.client_rows:
        data.append([Paragraph("Məlumat yoxdur", st["td"]), Paragraph("—", st["td_c"]),
                     Paragraph("0", st["td_c"]), Paragraph("—", st["td"]),
                     Paragraph("—", st["td_c"])])
    for c in agg.client_rows:
        serials = ", ".join(sorted(set(c.serials))) if c.serials else "—"
        status = "Portala hazır" if c.records > 0 else "Boş"
        data.append([
            Paragraph(c.name, st["td"]),
            Paragraph(c.voen, st["td_c"]),
            Paragraph(str(c.records), st["td_c"]),
            Paragraph(serials, st["td"]),
            Paragraph(status, st["td_c"]),
        ])
    return _table(data, [48, 27, 20, 60, 28], st)


def _bar_chart(agg: Aggregation) -> Drawing:
    labels = [r.label for r in agg.method_rows]
    values = [r.reports for r in agg.method_rows]
    d = Drawing(_CONTENT_MM * mm, 175)
    bc = VerticalBarChart()
    bc.x = 24
    bc.y = 28
    bc.width = _CONTENT_MM * mm - 48
    bc.height = 128
    bc.data = [values]
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontName = FONT_REGULAR
    bc.categoryAxis.labels.fontSize = 8
    bc.valueAxis.labels.fontName = FONT_REGULAR
    bc.valueAxis.labels.fontSize = 8
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(values + [1]) + 1
    bc.barWidth = 10
    bc.groupSpacing = 6
    bc.bars[0].fillColor = _PALETTE[0]      # darkest fill — highest B&W contrast
    bc.bars[0].strokeColor = colors.white
    bc.bars[0].strokeWidth = 0.75
    # Numeric value labels sitting just above each bar.
    bc.barLabelFormat = "%d"
    bc.barLabels.fontName = FONT_REGULAR
    bc.barLabels.fontSize = 7.5
    bc.barLabels.fillColor = _HEADER_BG
    bc.barLabels.dy = 4
    d.add(bc)
    return d


def _client_chart(agg: Aggregation, top: int = 8) -> Drawing | None:
    """Chart C — inspection volume (records) per client, busiest first.

    Reuses ``agg.client_rows`` (already sorted by records desc); shows the top
    ``top`` clients so the axis stays legible. Returns ``None`` when no client
    has been processed, so the caller can render a graceful placeholder.
    """
    rows = [c for c in agg.client_rows if c.records > 0][:top]
    if not rows:
        return None

    labels = [_short_client(c.name) for c in rows]
    values = [c.records for c in rows]
    d = Drawing(_CONTENT_MM * mm, 185)
    bc = VerticalBarChart()
    bc.x = 24
    bc.y = 40
    bc.width = _CONTENT_MM * mm - 48
    bc.height = 128
    bc.data = [values]
    bc.categoryAxis.categoryNames = labels
    bc.categoryAxis.labels.fontName = FONT_REGULAR
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.angle = 25       # slant so longer names don't collide
    bc.categoryAxis.labels.boxAnchor = "ne"
    bc.categoryAxis.labels.dy = -2
    bc.valueAxis.labels.fontName = FONT_REGULAR
    bc.valueAxis.labels.fontSize = 8
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = max(values + [1]) + 1
    bc.barWidth = 12
    bc.groupSpacing = 8
    bc.bars[0].fillColor = _PALETTE[2]
    bc.bars[0].strokeColor = colors.white
    bc.bars[0].strokeWidth = 0.75
    bc.barLabelFormat = "%d"
    bc.barLabels.fontName = FONT_REGULAR
    bc.barLabels.fontSize = 7.5
    bc.barLabels.fillColor = _HEADER_BG
    bc.barLabels.dy = 4
    d.add(bc)
    return d


def _short_client(name: str, width: int = 14) -> str:
    """Trim a client name for a chart axis label without dropping meaning."""
    name = str(name or "—").strip()
    return name if len(name) <= width else name[: width - 1] + "…"


def _donut_chart(quality: dict[str, int]) -> Drawing | None:
    order = [_Q_YARARLI, _Q_INFO, _Q_YARARSIZ]
    pairs = [(lbl, quality.get(lbl, 0)) for lbl in order]
    pairs += [(k, v) for k, v in quality.items() if k not in order and v]
    pairs = [(lbl, val) for lbl, val in pairs if val > 0]
    if not pairs:
        return None

    d = Drawing(_CONTENT_MM * mm, 175)
    pie = Pie()
    pie.x = 30
    pie.y = 22
    pie.width = 130
    pie.height = 130
    pie.data = [v for _, v in pairs]
    pie.labels = None
    pie.simpleLabels = 1
    pie.slices.strokeColor = colors.white
    pie.slices.strokeWidth = 1
    try:
        pie.innerRadiusFraction = 0.55  # donut hole
    except Exception:
        pass
    total = sum(v for _, v in pairs)
    for i, (_, _v) in enumerate(pairs):
        pie.slices[i].fillColor = _PALETTE[i % len(_PALETTE)]
    d.add(pie)

    legend = Legend()
    legend.x = 200
    legend.y = 120
    legend.fontName = FONT_REGULAR
    legend.fontSize = 9
    legend.dxTextSpace = 6
    legend.deltay = 15
    legend.colorNamePairs = [
        (_PALETTE[i % len(_PALETTE)], f"{lbl}: {val}  ({val / total * 100:.0f}%)")
        for i, (lbl, val) in enumerate(pairs)
    ]
    d.add(legend)
    d.add(String(30, 160, "Keyfiyyət Nəticələrinin Bölgüsü",
                 fontName=FONT_BOLD, fontSize=9.5, fillColor=_HEADER_BG))
    return d


def _ledger_table(ledger: dict, st: dict) -> Table:
    head = [Paragraph(h, st["th"]) for h in ("Portal vəziyyəti", "Mənbə", "Sayı")]
    data = [head]
    rows: list[tuple[str, str, int]] = []
    for status, n in sorted(ledger["audit_status"].items()):
        rows.append((status, "upload_status.json", n))
    for status, n in sorted(ledger["ledger_status"].items()):
        rows.append((status, ".upload_state.json", n))
    if not rows:
        rows.append(("Yükləmə qeydi yoxdur", "—", 0))
    for status, src, n in rows:
        data.append([Paragraph(status, st["td"]), Paragraph(src, st["td"]),
                     Paragraph(str(n), st["td_c"])])
    return _table(data, [70, 78, 35], st)


def _quarantine_table(reasons: dict[str, str], st: dict) -> Table:
    counts: dict[str, int] = defaultdict(int)
    for tag in reasons.values():
        counts[tag] += 1
    head = [Paragraph(h, st["th"]) for h in ("Karantin səbəbi", "Fayl sayı")]
    data = [head]
    if not counts:
        data.append([Paragraph("Karantin səbəbi qeydə alınmayıb", st["td"]),
                     Paragraph("0", st["td_c"])])
    for tag, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        data.append([Paragraph(tag, st["td"]), Paragraph(str(n), st["td_c"])])
    return _table(data, [113, 70], st)


def _signature_block(settings, st: dict) -> KeepTogether:
    director = (settings.raw.get("portal", {}) or {}).get("director", {}) or {}
    full_name = " ".join(
        p for p in (director.get("soyadi"), director.get("ad"), director.get("atasinin_adi"))
        if p
    ) or "____________________"

    cell = lambda role, name: [  # noqa: E731
        Paragraph(role, st["sig_b"]),
        Paragraph(name, st["sig"]),
        Paragraph("İmza: ____________________", st["muted"]),
        Paragraph(f"Tarix: {dt.date.today().strftime(settings.date_format)}", st["muted"]),
    ]
    data = [[cell("Hazırladı (Avtomatlaşdırma Sistemi):", "MAG-Pi Monthly Report Studio"),
             cell("Təsdiq etdi (Qurumun rəhbəri):", full_name)]]
    table = Table(data, colWidths=[(_CONTENT_MM / 2) * mm] * 2)
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 1, _GRID),
        ("LINEAFTER", (0, 0), (0, -1), 0.9, _GRID),
        ("LINEABOVE", (0, 0), (-1, 0), 2.2, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
    ]))
    return KeepTogether([Spacer(1, 6 * mm),
                         Paragraph("İMZA VƏ TƏSDİQ BLOKU", st["h2"]), table])


# --- Assembly ---------------------------------------------------------------------------


def build_report(settings=None, output_path: str | Path | None = None,
                 target_month: str | None = None, all_time: bool = False) -> Path:
    """Scan the live state and render the executive audit PDF. Returns its path.

    ``settings`` defaults to the real ``config/settings.yaml``. ``target_month``
    (canonical ``YYYY-MM``) scopes every PDF metric, KPI card, table and chart to
    one closed month; ``None`` resolves to the latest completed month and refuses
    the ongoing one. ``all_time=True`` is the un-scoped global audit: no month
    filter, cumulative KPI cards, and the ``BÜTÜN DÖVR`` title/identity.
    ``output_path`` overrides the destination verbatim (used by tests); otherwise
    the PDF is written month-stamped and copied to the canonical
    ``pipeline_executive_summary_report.pdf``. Every data source is read
    best-effort, so a fresh checkout with empty output/ still builds cleanly.
    """
    if settings is None:
        settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")
    if all_time:
        target_month = None
        cat_month = catalog_mod.ALL
        period_label = "Bütün dövr"
    else:
        if target_month is None:
            target_month = resolve_target_month()
        cat_month = catalog_month(target_month)
        period_label = reporting_period(target_month)
    _register_fonts()

    root = Path(settings.project_root)
    output_dir = Path(settings.output_dir)

    # --- gather live state (scoped to the target month, or cumulative when --all) ---
    client_names = catalog_mod.client_names_from(settings)
    cat = catalog_mod.scan(output_dir, client_names)
    metrics = metrics_mod.collect(settings, cat, month=cat_month)
    cache_eff = cache_stats_service.load()
    cache_size = parse_cache_size(root)
    reasons = quarantine_reasons_service.load()
    ledger = load_portal_ledger(root)

    sidecars = filter_sidecars_by_month(load_sidecars(output_dir), cat_month)
    sidecars = filter_active_clients(sidecars, settings)
    agg = tally_sidecars(sidecars)

    st = _styles()
    page_title = "ÜMUMİ İCRAÇI AUDİT HESABATI (BÜTÜN DÖVR ÜZRƏ)" if all_time else _TITLE_PAGE
    generated_at = dt.datetime.now().strftime("%d.%m.%Y %H:%M")
    intro = (
        f"Bu hesabat sistemin canlı vəziyyətini əks etdirir və avtomatik olaraq "
        f"tərtib edilmişdir. Hesabat dövrü: <b>{period_label}</b>. "
        f"Tərtib tarixi: <b>{generated_at}</b>. Bütün göstəricilər diskdəki faktiki "
        f"fayllardan (input/, output/, .parse_cache/, .state/, upload ledger) oxunur."
    )

    story: list = [
        Paragraph(page_title, st["title_pg"]),
        Paragraph(intro, st["muted"]),
        Spacer(1, 2 * mm),
    ]
    story += _kpi_section(metrics, agg, cache_eff, cache_size, ledger, st,
                          scoped=not all_time)
    story += [
        Spacer(1, 1.5 * mm),
        Paragraph(
            f"Parse keş anbarı: <b>{cache_size}</b> memoizasiya faylı · "
            f"Cəmi tərtib olunmuş hesabat: <b>{agg.total_reports}</b> · "
            f"Müayinə qeydləri: <b>{agg.total_records}</b>.", st["body"]),
    ]

    # Table 1 shares Page 1 with the title + KPI grid (no PageBreak): the spacers
    # above are trimmed so the method table fits under the KPIs without a blank
    # tail. The client table (Table 2) then flows onto the next page naturally.
    client_title = f"Cədvəl 2 — Müştəri üzrə İcraçı Matris ({period_label})"
    story += [
        Spacer(1, 2 * mm),
        KeepTogether([
            Paragraph("Cədvəl 1 — NDT Metodları üzrə İcra Analitikası", st["h2"]),
            _method_table(agg, st),
        ]),
        Spacer(1, 4 * mm),
        KeepTogether([
            Paragraph(client_title, st["h2"]),
            _client_table(agg, st),
        ]),
    ]

    story += [PageBreak(),
              KeepTogether([
                  Paragraph("Qrafik 1 — NDT Metodu üzrə İş Həcmi (Hesabat sayı)", st["h2"]),
                  _bar_chart(agg),
              ]),
              Spacer(1, 4 * mm)]
    donut = _donut_chart(agg.quality)
    quality_head = Paragraph("Qrafik 2 — Müayinə Nəticəsi Bölgüsü (Yararlı / Məlumat üçün / Yararsız)", st["h2"])
    if donut is not None:
        story.append(KeepTogether([quality_head, donut]))
    else:
        story.append(KeepTogether([
            quality_head,
            Paragraph("Keyfiyyət nəticəsi məlumatı mövcud deyil.", st["muted"]),
        ]))

    story.append(Spacer(1, 4 * mm))
    client_chart = _client_chart(agg)
    client_chart_head = Paragraph("Qrafik 3 — Müştəri üzrə İş Həcmi Bölgüsü", st["h2"])
    if client_chart is not None:
        story.append(KeepTogether([client_chart_head, client_chart]))
    else:
        story.append(KeepTogether([
            client_chart_head,
            Paragraph("Müştəri iş həcmi məlumatı mövcud deyil.", st["muted"]),
        ]))

    story += [PageBreak(),
              KeepTogether([
                  Paragraph("Portal Yükləmə Vəziyyəti", st["h2"]),
                  _ledger_table(ledger, st),
              ]),
              Spacer(1, 6 * mm),
              KeepTogether([
                  Paragraph("Cədvəl 3 — Karantin və Anomaliya Diagnostikası", st["h2"]),
                  _quarantine_table(reasons, st),
              ]),
              _signature_block(settings, st)]

    # Explicit path wins verbatim (tests). Otherwise write the month-stamped file
    # and copy it to the canonical name so the newest build is always both
    # addressable by month and resolvable by the stable filename.
    if output_path is not None:
        out_path = Path(output_path)
    elif all_time:
        out_path = output_dir / "pipeline_executive_summary_report_all.pdf"
    else:
        out_path = output_dir / scoped_output_name(target_month)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=_LEFT, rightMargin=_RIGHT, topMargin=_TOP, bottomMargin=_BOTTOM,
        title=_TITLE_SHORT, author="MAG-Pi",
    )
    doc.build(story,
              onFirstPage=lambda c, d: _draw_chrome(c, d, settings, target_month, all_time),
              onLaterPages=lambda c, d: _draw_chrome(c, d, settings, target_month, all_time))

    # Only the month-scoped build owns the canonical filename; the --all report
    # keeps its own name so it never clobbers the latest monthly canonical copy.
    if output_path is None and not all_time:
        canonical = output_dir / "pipeline_executive_summary_report.pdf"
        if canonical.resolve() != out_path.resolve():
            shutil.copyfile(out_path, canonical)
    return out_path


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=(
            "İcraçı audit PDF hesabatını tərtib edir. Rəsmi hesabat yalnız "
            "tamamlanmış (bağlanmış) ay üçün çıxarılır; arqument verilməzsə ən "
            "son bağlanmış ay seçilir."
        )
    )
    ap.add_argument(
        "--month", "--date", dest="month", metavar="AY",
        help="Hədəf ay: YYYY-MM (2026-06), YY-MM (26-06 / 26-02) və ya MMM_YYYY (JUN_2026).",
    )
    ap.add_argument(
        "--all", dest="all_time", action="store_true",
        help="Bütün dövr üzrə kumulyativ audit (ay üzrə bölünmür). --month ilə birlikdə istifadə olunmur.",
    )
    return ap


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    ns = parser.parse_args(argv)
    if ns.all_time and ns.month:
        parser.error("--all və --month birlikdə istifadə oluna bilməz.")
    settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")

    if ns.all_time:
        out_path = build_report(settings, all_time=True)
        rel = _relativise(out_path)
        print("=" * 70)
        print("Ümumi İcraçı Audit Hesabatı (bütün dövr) tərtib edildi.")
        print("  Hesabat dövrü: Bütün dövr")
        print(f"  Fayl: {rel}")
        print("  Yenidən yaratmaq üçün əmr:")
        print("      python generate_pipeline_summary.py --all")
        print("=" * 70)
        return 0

    target_month = resolve_target_month(ns.month)
    out_path = build_report(settings, target_month=target_month)
    rel = _relativise(out_path)
    print("=" * 70)
    print("İcraçı Audit Hesabatı tərtib edildi.")
    print(f"  Hesabat dövrü: {reporting_period(target_month)} ({target_month})")
    print(f"  Fayl: {rel}")
    print(f"  Kanonik nüsxə: output/pipeline_executive_summary_report.pdf")
    print("  Yenidən yaratmaq üçün əmr:")
    print(f"      python generate_pipeline_summary.py --month {target_month}")
    print("=" * 70)
    return 0


def _relativise(path: Path) -> Path:
    """Best-effort project-relative display path (absolute if it lies outside)."""
    try:
        return path.relative_to(PROJECT_ROOT)
    except ValueError:
        return path


if __name__ == "__main__":
    raise SystemExit(main())
