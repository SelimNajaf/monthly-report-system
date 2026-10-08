"""Render the monthly report to a print-ready Azerbaijani PDF (ReportLab).

The ONLY module that knows about PDF layout. It registers the embedded DejaVu
Unicode fonts (full Azerbaijani glyph coverage: ``ə ğ ı ö ş ç ü`` and uppercase),
then builds the document with Platypus:

  - Page chrome (MAG-Pi logo top-left, centered title, dynamic document number
    top-right, ``Səhifə X / Y`` footer) is drawn on every page by a page-counting
    canvas so the "of Y" total is correct.
  - The body is a ``LongTable`` with ``Paragraph`` flowables in every cell so long
    text wraps, row heights grow automatically, the header row repeats on each
    page, and the table splits cleanly across pages.
  - The sign-off block (Evaluator | Contractor | Client) is kept together and
    carries the Möhür stamp image in the Contractor cell.

I/O contract
------------
render_pdf(report, settings, translator, output_path) -> Path
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image, KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

from .document_aggregator import (display_options, row_style,
                                  split_display_rows)
from .naming import AZ_MONTHS, reporting_period

FONT_REGULAR = "DejaVu"
FONT_BOLD = "DejaVu-Bold"

# Palette
_HEADER_BG = colors.HexColor("#1B365D")
_HEADER_FG = colors.white
_GRID = colors.HexColor("#9AA5B1")
_RETEST_BG = colors.HexColor("#FDF3D8")   # soft amber for retest rows
# presentation.row_style: method_zebra — every other method block, light grey
# (the first block stays white). Replaces the amber retest shading.
_ZEBRA_BG = colors.HexColor("#F2F2F2")
_RULE = colors.HexColor("#1B365D")

# Unified 7-column layout for ALL methods (1 document = 1 row; client is per-report
# now, shown in the header meta-text — not a column). Sums to the content width
# (183 mm on A4 w/ our margins) — the SAME total the 6-column layout summed to, so
# the page chrome, the sign-off block and the stamp keep their geometry and only
# the column split changed when Üsul was added.
# Sıra № | Tarix | Report № | Standart | Üsul | İtem / Detal | Nəticə
#
# Üsul gets 14 mm: the longest method token is FERRITE (7 chars), ~11.5 mm at the
# 7.5 pt body size plus the 6 pt of cell padding.
_COL_MM = [12, 24, 40, 33, 14, 35, 25]

# presentation.range_mode: by_number — Tarix takes 3 mm from Nəticə so a
# cross-month span ("31.03–15.04.2026", ~26.2 mm with padding) stays on one
# line. Nəticə keeps room for its longest term, "Məlumat üçün" (~21.0 mm).
# Same 183 mm total; strict keeps _COL_MM.
_COL_MM_BY_NUMBER = [12, 27, 40, 33, 14, 35, 22]

# Canonical header keys (translated at render time) for the unified table.
_HEADER_KEYS = ["Row Number", "Date", "Report No",
                "Standard", "Method", "Item / Detail", "Result"]

# Caption of the optional second block (presentation.unfit_placement: section),
# translated through az.json like every other visible term. Operator-approved
# wording: "Təkrar yoxlanılmamış yararsız qaynaqlar".
_UNFIT_SECTION_KEY = "Unretested Rejected Welds"

# presentation.pulled_parent_style: marked — the mark on a cross-month parent's
# Sıra № and the note under its table, one line per month. The key is the
# English template; az.json carries the operator-approved wording
# "* <ay> hesabatına aiddir, burada arayış üçün göstərilir."
_PULLED_MARK = "*"
_PULLED_NOTE_KEY = "* Belongs to the {month} report, shown here for reference."

# Body cell typography (tuned to keep ~126 rows + sign-off within ~5 pages).
_CELL_FS = 7.5
_CELL_LEAD = 9
_CELL_PAD = 2.5

_LEFT = 15 * mm
_RIGHT = 12 * mm
# Top margin reserves a running-header band big enough for logo + 2-line title,
# which end at the blue rule (drawn at h - 25 mm). It used to be 42 mm because an
# enlarged method subtitle was drawn BELOW that rule; the method is now a table
# column (Üsul), the subtitle is gone, and 5 mm of clearance under the rule is
# enough — the reclaimed ~12 mm goes to table rows on every page.
_TOP = 30 * mm
_BOTTOM = 17 * mm

# EQUAL left/right side reservations so the middle band — and thus the title — is
# mathematically centered on the page: band width = (PageWidth - 2*Margin) -
# 2*_HEADER_SIDE. The bare serial box lives in the right reservation and auto-
# shrinks to stay inside it, never reaching the centered title.
_HEADER_SIDE = 140

# NOTE: the per-method header subtitle — "(RADİOQRAFİK ÜSUL / RT)" and its
# siblings, once drawn as a third header line below the blue rule — was REMOVED.
# The method is now carried per row in the Üsul column (see _COL_MM), so a
# document-level method banner would only repeat it.

# Azerbaijani month names for the "Hesabat dövrü" traceability line — shared
# with the JSON exporter via the naming module so the two can never drift.
_AZ_MONTHS = AZ_MONTHS


def _split_title(title: str) -> tuple[str, str]:
    """Split the report title into two balanced lines.

    Prefers breaking right after the word ``ÜZRƏ`` (giving the requested
    ``İNSPEKSİYA ÜZRƏ`` / ``AYLIQ HESABATIN NƏTİCƏSİ``); otherwise splits at the
    word nearest the middle.
    """
    words = title.split()
    if len(words) <= 1:
        return title, ""
    for i, wd in enumerate(words):
        if wd.upper().rstrip(":.") == "ÜZRƏ":
            return " ".join(words[: i + 1]), " ".join(words[i + 1:])
    mid = (len(words) + 1) // 2
    return " ".join(words[:mid]), " ".join(words[mid:])


def _register_fonts(settings) -> None:
    pdfmetrics.registerFont(TTFont(FONT_REGULAR, str(settings.font_regular)))
    bold = settings.font_bold if Path(settings.font_bold).is_file() else settings.font_regular
    pdfmetrics.registerFont(TTFont(FONT_BOLD, str(bold)))


def _styles():
    cell = ParagraphStyle("cell", fontName=FONT_REGULAR, fontSize=_CELL_FS, leading=_CELL_LEAD)
    return {
        "cell": cell,
        "cell_center": ParagraphStyle("cellc", parent=cell, alignment=1),
        "head": ParagraphStyle("head", fontName=FONT_BOLD, fontSize=8, leading=10,
                               alignment=1, textColor=_HEADER_FG),
        "sig_label": ParagraphStyle("sigl", fontName=FONT_BOLD, fontSize=8, leading=11),
        "sig_val": ParagraphStyle("sigv", fontName=FONT_REGULAR, fontSize=8, leading=11),
        "period": ParagraphStyle("period", fontName=FONT_BOLD, fontSize=8.5, leading=11,
                                 textColor=colors.HexColor("#555555")),
        "meta": ParagraphStyle("meta", fontName=FONT_BOLD, fontSize=11, leading=15,
                               textColor=_RULE),
        # Caption of the second table. keepWithNext so the heading can never be
        # left alone at the foot of a page above an empty one.
        "section": ParagraphStyle("section", fontName=FONT_BOLD, fontSize=9.5,
                                  leading=13, textColor=_RULE, keepWithNext=1),
    }


def _serial_label(translator, doc_number: str) -> str:
    """Top-right badge text: ``Hesabat №: <serial>`` (label from az.json)."""
    return f'{translator.term("Report Number Label")}: {doc_number}'


def _page_chrome_factory(settings, report, translator):
    """Return a Canvas subclass that stamps header+footer on every page."""
    title = report.title
    doc_number = report.document_number
    # Captioned serial in the top-right box, e.g. "Hesabat №: MR-MT-UBOC-26-04".
    # The box auto-shrinks its font (see _draw_serial_box) to stay inside the
    # 140pt right column, so the added label never reaches the centered title.
    serial_text = _serial_label(translator, doc_number)
    logo = ImageReader(str(settings.header_logo)) if Path(settings.header_logo).is_file() else None

    class ChromeCanvas(canvas.Canvas):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._pages = []

        def showPage(self):
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for state in self._pages:
                self.__dict__.update(state)
                self._draw_chrome(total)
                super().showPage()
            super().save()

        def _draw_chrome(self, total):
            w, h = A4
            # --- header ---
            # Header center-line, derived from the logo box; used to vertically
            # center the title block and the top-right serial box on it.
            logo_top = h - 11 * mm
            logo_h = 13 * mm
            logo_cy = logo_top - logo_h / 2
            logo_right = _LEFT
            if logo is not None:
                iw, ih = logo.getSize()
                target_w = logo_h * iw / ih
                self.drawImage(logo, _LEFT, logo_top - logo_h,
                               width=target_w, height=logo_h,
                               preserveAspectRatio=True, mask="auto")
                logo_right = _LEFT + target_w
            # Title centered on the page using EQUAL side reservations: a left
            # column and a right column of _HEADER_SIDE each. The middle band
            # therefore sits symmetrically inside the margins, so band_cx is the
            # margin-box center and the title is perfectly centered — independent
            # of the logo/serial widths (which live inside those side columns).
            band_left = _LEFT + _HEADER_SIDE
            band_right = (w - _RIGHT) - _HEADER_SIDE
            band_cx = (band_left + band_right) / 2.0
            band_w = band_right - band_left
            # HEADER ZONE (above the blue rule): the 2-line title only, vertically
            # centered on the header center-line (logo_cy) so logo, title and the
            # top-right serial box share it:
            #   line 1: İNSPEKSİYA ÜZRƏ
            #   line 2: AYLIQ HESABATIN NƏTİCƏSİ   (both from _split_title)
            # Title lines auto-shrink to the centered band.
            line1, line2 = _split_title(title)
            title_lines = [l for l in (line1, line2) if l]
            t_fs = 12
            while t_fs > 7 and max(self.stringWidth(l, FONT_BOLD, t_fs)
                                   for l in title_lines) > band_w:
                t_fs -= 0.5
            t_step = t_fs + 3
            y = logo_cy + (len(title_lines) * t_step) / 2 - t_fs   # top-line baseline
            self.setFont(FONT_BOLD, t_fs)
            self.setFillColor(_RULE)
            for l in title_lines:
                self.drawCentredString(band_cx, y, l)
                y -= t_step
            # Labelled serial in a slim muted, bordered box, top-right — vertically
            # centered on the header center-line (aligned with logo + title).
            self._draw_serial_box(w, logo_cy, serial_text)
            # Blue rule drawn DIRECTLY BELOW the title block.
            rule_y = h - 25 * mm
            self.setStrokeColor(_RULE)
            self.setLineWidth(1)
            self.line(_LEFT, rule_y, w - _RIGHT, rule_y)
            # Nothing is drawn below the rule any more: the method subtitle that
            # used to occupy that band is now the Üsul table column.
            # --- footer ---
            self.setFont(FONT_REGULAR, 8)
            self.setFillColor(colors.HexColor("#555555"))
            self.setStrokeColor(_GRID)
            self.line(_LEFT, _BOTTOM - 3 * mm, w - _RIGHT, _BOTTOM - 3 * mm)
            self.drawString(_LEFT, _BOTTOM - 8 * mm, f"MAG-Pi  •  {doc_number}")
            self.drawRightString(w - _RIGHT, _BOTTOM - 8 * mm,
                                 f"Səhifə {self._pageNumber} / {total}")

        def _draw_serial_box(self, w, center_y, text):
            # Auto-shrink the serial font (8 -> 6.5) so the labelled box always fits
            # inside its reserved right side-column and never reaches the title.
            pad = 2.4 * mm
            max_box_w = _HEADER_SIDE - 6
            fs = 8.0
            while fs > 6.5 and self.stringWidth(text, FONT_REGULAR, fs) + 2 * pad > max_box_w:
                fs -= 0.5
            self.setFont(FONT_REGULAR, fs)
            box_w = self.stringWidth(text, FONT_REGULAR, fs) + 2 * pad
            box_h = 6 * mm
            x1 = w - _RIGHT - box_w
            y1 = center_y - box_h / 2
            self.setStrokeColor(_GRID)
            self.setFillColor(colors.HexColor("#F4F6F8"))
            self.setLineWidth(0.6)
            self.roundRect(x1, y1, box_w, box_h, 1.4 * mm, stroke=1, fill=1)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawRightString(w - _RIGHT - pad, y1 + box_h / 2 - fs * 0.34, text)

    return ChromeCanvas


def _meta_block(report, translator, st):
    """Object + reporting-period meta-text drawn as clean large lines above the
    table.

        Obyekt: <Client Name>
        Hesabat dövrü: <Ay> <İl>

    The compiled report is filed per client, and on the official form that client
    IS the inspected object — so the client name is the object line's value and
    only the label differs. The label itself comes from az.json like every other
    piece of wording on the sheet.
    """
    object_lbl = translator.term("Facility")
    client_name = getattr(report, "client_name", "") or ""
    try:
        year, mon = str(report.month).split("-")
        period = f"{_AZ_MONTHS[int(mon)]} {year}"
    except Exception:
        period = "—"
    lines = [
        Paragraph(f"{object_lbl}: {client_name}", st["meta"]),
        Paragraph(f"Hesabat dövrü: {period}", st["meta"]),
    ]
    return lines


def _method_of(report) -> str:
    return (getattr(report, "method", "") or "").upper()


def _content_width(report) -> float:
    return sum(_COL_MM) * mm


def _pulled_notes(translator, display_rows) -> list[str]:
    """One note per month that a marked line in ``display_rows`` comes from."""
    months = sorted({r.pulled_from for r in display_rows if r.pulled_from})
    return [translator.term(_PULLED_NOTE_KEY).format(month=reporting_period(m))
            for m in months]


def _build_table(report, translator, st, display_rows, mark_pulled=False,
                 zebra=False, col_mm=None):
    """Build the unified 7-column summary table (identical for UT / MT / RT).

    Each line is one source document — or, when ``presentation.collapse_ranges``
    is on, a whole run of consecutive identical ones drawn as
    ``RT-SDL-25-(086-102)``. The projection is decided upstream in
    ``document_aggregator.collapse_display_rows``; this function only draws what
    it is handed (ADR-001: layout lives here, the logic does not). ``Üsul`` is
    the document's own NDT method token (resolved in
    ``document_aggregator._row_from_doc``, so the PDF and the JSON sidecar can
    never disagree), ``İtem / Detal`` comes from the metadata header and
    ``Nəticə`` is the rolled-up ``Yararlı`` / ``Yarasız`` verdict.

    ``zebra`` (``presentation.row_style: method_zebra``) shades every other
    method block instead of the retest lines; the header is unchanged.
    ``col_mm`` overrides the column split (``_COL_MM`` when ``None``).
    """
    data = [[Paragraph(translator.term(h), st["head"]) for h in _HEADER_KEYS]]

    retest_rows: list[int] = []
    zebra_rows: list[int] = []
    block, prev_method = 0, None
    for i, r in enumerate(display_rows, start=1):
        result = translator.term(r.result)
        # Orphan retests (report-level revisions) render as clean integers — no
        # '*'. Only true matched parent->child pairs get lettered sub-numbers.
        seq = f"{r.seq}{_PULLED_MARK}" if mark_pulled and r.pulled_from else r.seq
        row = [
            Paragraph(seq, st["cell_center"]),
            Paragraph(r.date_str, st["cell_center"]),
            Paragraph(r.report_label, st["cell"]),
            Paragraph(r.standard, st["cell_center"]),
            # Method token, not a translated phrase: RT / MPI / UT / PT / FC /
            # PMI / HrT are the same in both languages. Falls back to the report's
            # group method for a row built before the field existed.
            Paragraph(r.method or _method_of(report), st["cell_center"]),
            Paragraph(translator.term(r.item_detail), st["cell_center"]),
            Paragraph(result, st["cell_center"]),
        ]
        data.append(row)
        if zebra:
            if prev_method is not None and r.method != prev_method:
                block += 1
            prev_method = r.method
            if block % 2:
                zebra_rows.append(i)
            continue
        # Shade only true matched children (a lettered sub-number). Orphan
        # retests are left unshaded so an all-orphan table reads cleanly.
        if r.is_retest_child:
            retest_rows.append(i)

    col_widths = [w * mm for w in (col_mm or _COL_MM)]
    table = LongTable(data, colWidths=col_widths, repeatRows=1)
    style = [
        ("FONTNAME", (0, 0), (-1, -1), FONT_REGULAR),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, _GRID),
        ("LINEBELOW", (0, 0), (-1, 0), 1, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), _CELL_PAD),
        ("BOTTOMPADDING", (0, 0), (-1, -1), _CELL_PAD),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]
    for i in retest_rows:
        style.append(("BACKGROUND", (0, i), (-1, i), _RETEST_BG))
    for i in zebra_rows:
        style.append(("BACKGROUND", (0, i), (-1, i), _ZEBRA_BG))
    table.setStyle(TableStyle(style))
    return table


def _next_month_first(month: str, date_format: str) -> str:
    """First calendar day of the month AFTER ``month`` (YYYY-MM), formatted.

    The compiled report is signed off at the close of its period, so a January
    2026 report signs as ``01.02.2026``.
    """
    try:
        import datetime as _dt
        y, m = (int(x) for x in str(month).split("-"))
        nxt = _dt.date(y + (m // 12), (m % 12) + 1, 1)
        return nxt.strftime(date_format)
    except Exception:
        return ""


def _build_signatures(report, translator, st):
    """One inspector-only sign-off: İnspektor + name + auto date + stamp.

    A single block carries the inspector's name, the auto-computed signing date
    (1st of the next month) and the Möhür stamp rendered below. No "Qiymətləndirən"
    / "Evaluated by" / Level / ISO 9712 text.
    """
    sig = report.signatures or {}
    inspector = sig.get("inspector") or sig.get("evaluator", "")
    role = translator.term("Inspector Title")
    name_lbl = translator.term("Name / Surname")
    date_lbl = translator.term("Date")
    stamp_lbl = translator.term("Signature / Stamp")
    sign_date = _next_month_first(report.month, getattr(report, "date_format", "%d.%m.%Y"))
    stamp_path = getattr(report, "stamp_path", None)

    block = [
        Paragraph(role, st["sig_label"]),
        Spacer(1, 2 * mm),
        Paragraph(f"{name_lbl}: {inspector}", st["sig_val"]),
        Paragraph(f"{date_lbl}: {sign_date}", st["sig_val"]),
        Paragraph(f"{stamp_lbl}:", st["sig_val"]),
    ]
    if stamp_path and Path(stamp_path).is_file():
        img = Image(str(stamp_path))
        img._restrictSize(34 * mm, 24 * mm)
        img.hAlign = "LEFT"
        block.append(Spacer(1, 1.5 * mm))
        block.append(img)
    else:
        block.append(Spacer(1, 24 * mm))   # reserve signing space

    content_w = _content_width(report)
    # A single left cell for the inspector block; a right spacer cell keeps the
    # block a natural half-width and the top rule spanning the full content width.
    sig_table = Table([[block, ""]], colWidths=[content_w * 0.5, content_w * 0.5])
    sig_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 1, _RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return KeepTogether([Spacer(1, 6 * mm), sig_table])


def render_pdf(report, settings, translator, output_path: str | Path) -> Path:
    """Build the PDF and return its path. Fails fast if a font TTF is missing."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _register_fonts(settings)

    # expose the stamp path + date format to the signature builder
    report.stamp_path = str(settings.stamp_logo)
    report.date_format = settings.date_format

    st = _styles()
    # Presentation-only projection: N consecutive identical reports may draw as
    # ONE line. report.rows is untouched, so the JSON sidecar written right
    # after this still carries every report separately.
    # Every presentation key is resolved in one place (display_options), so the
    # table and main.py's range-verdict audit read the same settings.
    opts = display_options(settings)
    mark_pulled = opts["mark_pulled"]
    zebra = row_style(settings) == "method_zebra"
    col_mm = _COL_MM_BY_NUMBER if opts["range_mode"] == "by_number" else _COL_MM
    display_rows, unfit_rows = split_display_rows(report, **opts)
    story = [
        *_meta_block(report, translator, st),
        Spacer(1, 3 * mm),
        _build_table(report, translator, st, display_rows, mark_pulled, zebra,
                     col_mm),
    ]
    # presentation.pulled_parent_style: marked — the note sits under the table
    # whose lines it explains. Nothing is added on plain.
    if mark_pulled:
        for note in _pulled_notes(translator, display_rows):
            story += [Spacer(1, 1.5 * mm), Paragraph(note, st["cell"])]
    # presentation.unfit_placement: section — a second table, same 7 columns and
    # same repeating header, under its own caption. Empty on every other
    # setting, so the story is byte-identical to before unless it is asked for.
    if unfit_rows:
        story += [
            Spacer(1, 6 * mm),
            Paragraph(translator.term(_UNFIT_SECTION_KEY), st["section"]),
            Spacer(1, 2 * mm),
            _build_table(report, translator, st, unfit_rows, mark_pulled, zebra,
                         col_mm),
        ]
        if mark_pulled:
            for note in _pulled_notes(translator, unfit_rows):
                story += [Spacer(1, 1.5 * mm), Paragraph(note, st["cell"])]
    story.append(_build_signatures(report, translator, st))

    doc = SimpleDocTemplate(
        str(output_path), pagesize=A4,
        leftMargin=_LEFT, rightMargin=_RIGHT, topMargin=_TOP, bottomMargin=_BOTTOM,
        title=report.title, author="MAG-Pi",
    )
    doc.build(story, canvasmaker=_page_chrome_factory(settings, report, translator))
    return output_path
