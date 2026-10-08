"""The 7-column table contract: Üsul, and the Obyekt meta line above it.

Three things are pinned here, all of them things a later edit could silently
break:

  * The column geometry. ``_COL_MM`` must still sum to the 183 mm content width —
    that total is what the sign-off table, the page chrome and the stamp are laid
    out against (``_content_width``), so a column added by widening the page would
    push the stamp off the sheet.
  * Where Üsul sits and where its value comes from. The column is between Standart
    and İtem / Detal, its header text is translated (never hardcoded), and the value
    is the row's OWN method token — the same field the JSON sidecar mirrors, so the
    two documents can never name a different method for one report.
  * The Obyekt meta line: exactly two meta lines, the object line carrying the
    client name under an az.json-sourced label, then the reporting period.
"""

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402

from monthly_report import pdf_renderer  # noqa: E402
from monthly_report.document_aggregator import MonthlyReport, ReportRow  # noqa: E402
from monthly_report.json_exporter import build_report_json  # noqa: E402
from monthly_report.pdf_renderer import (_COL_MM, _HEADER_KEYS,  # noqa: E402
                                         _meta_block)

#: The A4 content width the whole layout is built against (183 mm).
_CONTENT_MM = 183

# _meta_block builds Paragraphs in the DejaVu styles, so the fonts must be
# registered first. They are a hard prerequisite of the whole pipeline —
# config.load_settings raises FileNotFoundError without them — so requiring them
# here asserts nothing new about the environment.
_FONTS = _ROOT / "assets" / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONTS / "DejaVuSans-Bold.ttf")))


class _Translator:
    """Identity translation — keeps the assertions about VALUES, not wording."""
    def term(self, text):
        return text


class _Settings:
    """Only what build_report_json touches."""
    raw = {"clients": {}}


def _row(report_no="KF-MT-26-001", method="MPI", item="Pipe", seq="1"):
    return ReportRow(
        date=_dt.date(2026, 5, 21), date_str="21.05.2026", report_no=report_no,
        series_key=report_no, retest_rank=0, client="C",
        document_name=report_no, standard="ASME B31.3", item_detail=item,
        result="Fit", method=method, seq=seq,
    )


def _report(*rows, method="MPI"):
    return MonthlyReport(month="2026-05", document_number="MR-MPI-SDLN-26-05",
                         title="İNSPEKSİYA ÜZRƏ AYLIQ HESABATIN NƏTİCƏSİ", method=method,
                         client_code="SDLN", client_name="Sədələn",
                         rows=list(rows))


# --- column geometry -------------------------------------------------------

def test_the_table_has_seven_columns():
    assert len(_COL_MM) == 7
    assert len(_HEADER_KEYS) == 7


def test_the_columns_still_sum_to_the_content_width():
    """Adding Üsul redistributed the existing width; it did not widen the page.
    This is what lets the header, the sign-off block and the stamp stay put."""
    assert sum(_COL_MM) == _CONTENT_MM


def test_content_width_agrees_with_the_column_sum():
    """_content_width feeds the sign-off table's colWidths — it must track _COL_MM."""
    assert (pdf_renderer._content_width(_report(_row()))
            == _CONTENT_MM * pdf_renderer.mm)


def test_usul_sits_between_standart_and_item_detal():
    i = _HEADER_KEYS.index("Method")
    assert _HEADER_KEYS[i - 1] == "Standard"
    assert _HEADER_KEYS[i + 1] == "Item / Detail"


def test_every_header_key_is_translatable():
    """Header text comes from az.json, never hardcoded — an unlisted key would
    render with the translator's [AZ?] flag on an official document."""
    dictionary = json.loads((_ROOT / "translations" / "az.json").read_text(encoding="utf-8"))
    for key in _HEADER_KEYS:
        assert key in dictionary, f"{key!r} missing from translations/az.json"
    assert dictionary["Method"] == "Üsul"


# --- the Üsul value --------------------------------------------------------

def test_the_row_carries_its_own_method_token():
    """detect_method's answer is resolved once, upstream, and stored on the row."""
    assert _row(method="RT").method == "RT"


def test_the_sidecar_mirrors_the_row_method():
    data = build_report_json(_report(_row(method="RT"), _row(report_no="KF-MT-26-002")),
                             _Settings(), _Translator())
    assert [r["method"] for r in data["items_table"]] == ["RT", "MPI"]


def test_a_row_with_no_method_falls_back_to_the_report_method():
    """A row built before the field existed (or by a caller that omits it) still
    renders a method rather than an empty cell."""
    blank = _row()
    blank.method = ""
    data = build_report_json(_report(blank, method="UT"), _Settings(), _Translator())
    assert data["items_table"][0]["method"] == "UT"


# --- the Obyekt meta line --------------------------------------------------

def test_the_meta_block_is_exactly_two_lines_object_then_period():
    """The official sheet carries two meta lines and no more — an extra line here
    pushes the table down on every page of every report."""
    lines = _meta_block(_report(_row(item="Pipe")), _Translator(), pdf_renderer._styles())
    text = [p.text for p in lines]
    assert len(text) == 2
    assert text[0] == "Facility: Sədələn"
    assert text[1] == "Hesabat dövrü: May 2026"


def test_the_object_line_carries_the_client_name_not_item_details():
    """Only the LABEL changed from Müştəri to Obyekt — the value is still the
    client, never the rows' İtem / Detal values."""
    lines = _meta_block(
        _report(_row(item="Pipe"), _row(report_no="KF-MT-26-002", item="Spool")),
        _Translator(), pdf_renderer._styles())
    text = [p.text for p in lines]
    assert text[0].endswith(": Sədələn")
    assert "Pipe" not in text[0] and "Spool" not in text[0]


def test_the_object_label_comes_from_az_json():
    """Wording on an official document is never hardcoded in the renderer."""
    dictionary = json.loads((_ROOT / "translations" / "az.json").read_text(encoding="utf-8"))
    assert dictionary["Facility"] == "Obyekt"


def test_no_separate_customer_line_remains():
    lines = _meta_block(_report(_row()), _Translator(), pdf_renderer._styles())
    assert not any(p.text.startswith("Customer:") for p in lines)
