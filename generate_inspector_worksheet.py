"""Compile the Inspector Assignment Worksheet to a one-page A4 PDF.

Standalone helper: reads the client registry and the ``inspector_matrix`` from
config/settings.yaml and renders the assignment currently in force — one row per
active client, each carrying the inspector the pipeline actually signs its
compiled reports with. Retired clients (``excluded_clients``) are omitted; they
compile nothing, so they have no inspector.

Deliberately does not import monthly_report.pdf_renderer: this is a temporary
utility, so it borrows the house style (DejaVu fonts, #1B365D header rule,
A4 margins) by copying the constants rather than coupling to renderer internals.

    python generate_inspector_worksheet.py
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from monthly_report.config import load_settings
from monthly_report.inspector_registry import as_date, resolve_inspector
from monthly_report.method_registry import is_excluded_client
from monthly_report.naming import AZ_MONTHS

FONT_REGULAR = "DejaVu"
FONT_BOLD = "DejaVu-Bold"

_HEADER_BG = colors.HexColor("#1B365D")
_HEADER_FG = colors.white
_GRID = colors.HexColor("#9AA5B1")
_RULE = colors.HexColor("#1B365D")
_MUTED = colors.HexColor("#555555")
_LEGEND_BG = colors.HexColor("#F4F6F8")

_LEFT = 15 * mm
_RIGHT = 12 * mm
_TOP = 34 * mm
_BOTTOM = 17 * mm

# Equal left/right reservations, as in pdf_renderer: the logo lives in the left
# one, so the title band between them is centered on the margin box and the two
# can never collide regardless of logo width.
_HEADER_SIDE = 140

_TITLE = "İNSPEKTOR BÖLÜŞDÜRÜLMƏSİ İŞ VƏRƏQİ"

_INTRO = (
    "Aşağıdakı cədvəl hazırda qüvvədə olan inspektor bölüşdürülməsini əks etdirir: "
    "hər müştərinin aylıq hesabatı göstərilən inspektorun adı ilə imzalanır. "
    "Bölüşdürmə config/settings.yaml faylındakı inspector_matrix bölməsindən "
    "oxunur — dəyişiklik yalnız orada edilir."
)

_INSPECTORS = ["Emil Ağalarov", "Emin Nəcəfov", "Azadxan Əhmədov", "Taleh Məmmədov"]

# Sums to the 183 mm content width (A4 minus our margins).
_COL_MM = [15, 78, 90]
_HEADERS = ["Sıra №", "Müştəri / Sifarişçi", "Təyin Olunan İnspektor"]


def _register_fonts(settings) -> None:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(settings.font_regular)))
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(settings.font_bold)))


def _boundary(code: str, settings) -> dt.date | None:
    """The configured ``date_routing`` boundary for a client code, if it has one."""
    routing = (settings.raw.get("inspector_matrix") or {}).get("date_routing") or {}
    for key, spec in routing.items():
        if str(key).strip().casefold() == str(code).strip().casefold():
            return as_date((spec or {}).get("boundary"))
    return None


def _collect_clients(settings) -> list[tuple[str, str]]:
    """``[(display name, assigned inspector)]`` for every active client.

    Order follows settings.yaml. Retired clients are dropped — they compile no
    reports, so printing an inspector for them would be a lie. A client routed by
    date (SDLN) prints BOTH sides of its boundary with the cutover month spelled
    out: a printed sheet outlives the month it was printed in, so naming only
    today's inspector would make it wrong the moment the boundary passes.
    """
    registry = settings.raw.get("clients") or {}
    rows: list[tuple[str, str]] = []
    for key, entry in registry.items():
        if not isinstance(entry, dict) or not entry.get("name"):
            continue
        code = str(entry.get("code", key))
        if is_excluded_client(code, settings):
            continue
        cutover = _boundary(code, settings)
        if cutover is not None:
            # Resolved through resolve_inspector on both sides rather than read
            # straight out of the config, so the sheet reports what the compiler
            # would actually do — including "—" if a side is misconfigured.
            before = resolve_inspector(code, cutover - dt.timedelta(days=1), settings)
            after = resolve_inspector(code, cutover, settings)
            label = f"{AZ_MONTHS[cutover.month]} {cutover.year}"
            assigned = (f"{before or '—'}  <font size=8.5>({label}-dan əvvəl)</font><br/>"
                        f"{after or '—'}  <font size=8.5>({label} və sonra)</font>")
        else:
            assigned = resolve_inspector(code, None, settings) or "—"
        rows.append((str(entry["name"]), assigned))
    if not rows:
        raise SystemExit(
            "settings.yaml: 'clients' registry is empty — nothing to map. "
            "Add client entries before compiling the worksheet."
        )
    return rows


def _styles() -> dict:
    return {
        "head": ParagraphStyle("head", fontName=FONT_BOLD, fontSize=8.5, leading=11,
                               alignment=1, textColor=_HEADER_FG),
        "client": ParagraphStyle("client", fontName=FONT_REGULAR, fontSize=10, leading=13),
        "seq": ParagraphStyle("seq", fontName=FONT_REGULAR, fontSize=10, leading=13,
                              alignment=1),
        "intro": ParagraphStyle("intro", fontName=FONT_REGULAR, fontSize=9.5, leading=14,
                                textColor=_MUTED),
        "legend_cap": ParagraphStyle("lcap", fontName=FONT_BOLD, fontSize=9, leading=12,
                                     textColor=_HEADER_BG),
        "legend_item": ParagraphStyle("litem", fontName=FONT_REGULAR, fontSize=9.5,
                                      leading=13),
    }


def _draw_chrome(c, doc, settings) -> None:
    """Logo + centered title + blue rule on top; muted rule + date at the foot."""
    w, h = A4
    logo_top = h - 11 * mm
    logo_h = 13 * mm
    logo_cy = logo_top - logo_h / 2

    logo_path = Path(settings.header_logo)
    if logo_path.is_file():
        logo = ImageReader(str(logo_path))
        iw, ih = logo.getSize()
        c.drawImage(logo, _LEFT, logo_top - logo_h,
                    width=logo_h * iw / ih, height=logo_h,
                    preserveAspectRatio=True, mask="auto")

    band_left = _LEFT + _HEADER_SIDE
    band_right = (w - _RIGHT) - _HEADER_SIDE
    band_cx = (band_left + band_right) / 2.0
    band_w = band_right - band_left
    fs = 13.0
    while fs > 8.0 and c.stringWidth(_TITLE, FONT_BOLD, fs) > band_w:
        fs -= 0.5
    c.setFont(FONT_BOLD, fs)
    c.setFillColor(_RULE)
    c.drawCentredString(band_cx, logo_cy - fs * 0.34, _TITLE)

    rule_y = h - 25 * mm
    c.setStrokeColor(_RULE)
    c.setLineWidth(1)
    c.line(_LEFT, rule_y, w - _RIGHT, rule_y)

    c.setFont(FONT_REGULAR, 8)
    c.setFillColor(_MUTED)
    c.setStrokeColor(_GRID)
    c.setLineWidth(0.5)
    c.line(_LEFT, _BOTTOM - 3 * mm, w - _RIGHT, _BOTTOM - 3 * mm)
    c.drawString(_LEFT, _BOTTOM - 8 * mm, "MAG-Pi  •  İş vərəqi")
    c.drawRightString(w - _RIGHT, _BOTTOM - 8 * mm,
                      f"Tarix: {dt.date.today().strftime(settings.date_format)}")


def _build_table(clients: list[tuple[str, str]], st: dict) -> Table:
    data = [[Paragraph(hd, st["head"]) for hd in _HEADERS]]
    for i, (name, inspector) in enumerate(clients, start=1):
        data.append([
            Paragraph(str(i), st["seq"]),
            Paragraph(name, st["client"]),
            Paragraph(inspector, st["client"]),
        ])

    # Auto row heights: the SDLN row carries two lines and a fixed height would
    # clip it. The generous cell padding below keeps the rows from crowding.
    table = Table(data, colWidths=[w * mm for w in _COL_MM], repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.6, _GRID),
        # A printed table now, not a form: every column gets the same solid grid.
        ("LINEBELOW", (0, 1), (-1, -1), 0.5, _GRID),
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, _GRID),
        ("LINEBELOW", (0, 0), (-1, 0), 1, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _build_legend(st: dict) -> KeepTogether:
    cells = [[Paragraph(f"•  {name}", st["legend_item"])] for name in _INSPECTORS]
    inner = Table([[Paragraph("İNSPEKTOR SİYAHISI (aktiv heyət)", st["legend_cap"])]]
                  + cells,
                  colWidths=[sum(_COL_MM) * mm])
    inner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), _LEGEND_BG),
        ("BOX", (0, 0), (-1, -1), 0.6, _GRID),
        ("LINEBELOW", (0, 0), (0, 0), 0.5, _GRID),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return KeepTogether([Spacer(1, 8 * mm), inner])


def main() -> None:
    settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")
    _register_fonts(settings)
    clients = _collect_clients(settings)

    out_path = settings.output_dir / "inspector_worksheet.pdf"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    st = _styles()
    story = [
        Paragraph(_INTRO, st["intro"]),
        Spacer(1, 5 * mm),
        _build_table(clients, st),
        _build_legend(st),
    ]

    doc = SimpleDocTemplate(
        str(out_path), pagesize=A4,
        leftMargin=_LEFT, rightMargin=_RIGHT, topMargin=_TOP, bottomMargin=_BOTTOM,
        title=_TITLE, author="MAG-Pi",
    )
    doc.build(story, onFirstPage=lambda c, d: _draw_chrome(c, d, settings),
              onLaterPages=lambda c, d: _draw_chrome(c, d, settings))
    print(f"Worksheet compiled: {out_path}  ({len(clients)} clients)")


if __name__ == "__main__":
    main()
