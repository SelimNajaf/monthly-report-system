"""Pin the Stage 4 fixes to ``range_mode: by_number``.

A. Tarix drops what the end date already says — ``01–21.04.2026`` in one
   month, ``31.03–15.04.2026`` across months, ``28.12.2025–05.01.2026``
   across years — and the by_number table gives Tarix 3 mm from Nəticə so
   the longest of those that the corpus prints stays on one line. Strict
   keeps its text and its column split.
B. ``presentation.range_tail_allow`` lets a tailed number range, only with
   numbers of the same tail: ``RT-KF-25-(080-106)T``. Default ``[]`` draws
   exactly what the key's absence draws.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from reportlab.lib.units import mm  # noqa: E402
from reportlab.pdfbase import pdfmetrics  # noqa: E402
from reportlab.pdfbase.ttfonts import TTFont  # noqa: E402
from reportlab.platypus import Paragraph  # noqa: E402

from monthly_report import pdf_renderer  # noqa: E402
from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, display_options, range_tail_allow,
    range_verdict_notes, split_display_rows)
from monthly_report.report_identity import retest_rank, strip_retest  # noqa: E402

_FONTS = _ROOT / "assets" / "fonts"
pdfmetrics.registerFont(TTFont("DejaVu", str(_FONTS / "DejaVuSans.ttf")))
pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(_FONTS / "DejaVuSans-Bold.ttf")))


class _Settings:
    def __init__(self, **presentation):
        self.raw = {"clients": {}, "presentation": presentation}
        self.date_format = "%d.%m.%Y"


class _Translator:
    def term(self, text):
        return text


def _row(report_no, *, date=(2025, 8, 5), result="Fit", method="RT",
         label="", standard="ASME B31.3", item="Pipe"):
    d = _dt.date(*date)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=strip_retest(report_no), retest_rank=retest_rank(report_no),
        client="KHF", document_name=f"{report_no}{label}", standard=standard,
        item_detail=item, result=result, method=method)


def _report(*rows):
    return MonthlyReport(month="2025-08", document_number="MR-KHF-25-08",
                         title="T", method="RT", client_code="KHF",
                         client_name="KHF", rows=list(rows))


def _labels(report, **presentation):
    opts = display_options(_Settings(range_mode="by_number", **presentation))
    main, _ = split_display_rows(report, **opts)
    return [d.report_label for d in main]


def _span(first, last):
    report = _report(_row("U-RT-26-001", date=first), _row("U-RT-26-002", date=last))
    main, _ = split_display_rows(report, range_mode="by_number")
    return main[0].date_str


# --------------------------------------------------------------------------- #
# A. Tarix text
# --------------------------------------------------------------------------- #
def test_one_month_prints_the_month_and_year_once():
    assert _span((2026, 4, 1), (2026, 4, 21)) == "01–21.04.2026"


def test_two_months_print_day_and_month_then_the_full_end():
    assert _span((2026, 3, 31), (2026, 4, 15)) == "31.03–15.04.2026"


def test_two_years_print_both_dates_in_full():
    assert _span((2025, 12, 28), (2026, 1, 5)) == "28.12.2025–05.01.2026"


def test_one_day_is_unchanged():
    assert _span((2026, 4, 16), (2026, 4, 16)) == "16.04.2026"


def test_strict_tarix_text_is_unchanged():
    report = _report(_row("U-RT-26-001", date=(2026, 4, 1)),
                     _row("U-RT-26-002", date=(2026, 4, 21)))
    main, _ = split_display_rows(report)
    assert [d.date_str for d in main] == ["01.04.2026 – 21.04.2026"]


# --------------------------------------------------------------------------- #
# A. Column widths
# --------------------------------------------------------------------------- #
def _lines_at(text, width_mm):
    """How many lines ``text`` takes in a body cell ``width_mm`` wide."""
    p = Paragraph(text, pdf_renderer._styles()["cell_center"])
    p.wrap(width_mm * mm - 6, 1000)          # LEFT/RIGHTPADDING 3 pt each
    return len(p.blPara.lines)


def test_by_number_columns_keep_the_content_width():
    assert sum(pdf_renderer._COL_MM_BY_NUMBER) == sum(pdf_renderer._COL_MM) == 183


def test_strict_columns_are_unchanged():
    assert pdf_renderer._COL_MM == [12, 24, 40, 33, 14, 35, 25]


@pytest.mark.parametrize("text", ["01–21.04.2026", "31.03–15.04.2026", "16.04.2026"])
def test_the_longest_by_number_dates_fit_one_line(text):
    assert _lines_at(text, pdf_renderer._COL_MM_BY_NUMBER[1]) == 1


def test_the_old_width_would_wrap_a_cross_month_span():
    """Why Tarix is wider: 24 mm breaks "31.03–15.04.2026" in two."""
    assert _lines_at("31.03–15.04.2026", pdf_renderer._COL_MM[1]) == 2


@pytest.mark.parametrize("text", ["Məlumat üçün", "Yararlı", "Yarasız"])
def test_the_narrower_neticə_still_fits_every_verdict(text):
    assert _lines_at(text, pdf_renderer._COL_MM_BY_NUMBER[6]) == 1


def test_build_table_uses_the_split_it_is_given():
    main, _ = split_display_rows(_report(_row("U-RT-26-001")))
    args = (_report(), _Translator(), pdf_renderer._styles(), main)
    default = pdf_renderer._build_table(*args)
    wide = pdf_renderer._build_table(*args, False, False,
                                     pdf_renderer._COL_MM_BY_NUMBER)
    assert default._colWidths == [w * mm for w in pdf_renderer._COL_MM]
    assert wide._colWidths == [w * mm for w in pdf_renderer._COL_MM_BY_NUMBER]


# --------------------------------------------------------------------------- #
# B. range_tail_allow
# --------------------------------------------------------------------------- #
_T_RUN = [_row(f"RT-KF-25-{n:03d}T") for n in range(80, 107)]


def test_reader_defaults_and_drops_junk():
    assert range_tail_allow(_Settings()) == ()
    assert range_tail_allow(_Settings(range_tail_allow="T")) == ()
    assert range_tail_allow(_Settings(range_tail_allow=["T", "", "T"])) == ("T",)


def test_an_allowed_tail_ranges():
    assert _labels(_report(*_T_RUN), range_tail_allow=["T"]) == ["RT-KF-25-(080-106)T"]


def test_the_tail_match_is_case_sensitive():
    assert len(_labels(_report(*_T_RUN), range_tail_allow=["t"])) == len(_T_RUN)


def test_a_tail_not_in_the_list_never_ranges():
    rows = [_row("U-UT-25-003rej"), _row("U-UT-25-004rej")]
    assert _labels(_report(*rows), range_tail_allow=["T"]) == [
        "U-UT-25-003rej", "U-UT-25-004rej"]


def test_a_tailed_number_never_joins_a_plain_one():
    rows = [_row("RT-KF-25-001"), _row("RT-KF-25-002"),
            _row("RT-KF-25-002T"), _row("RT-KF-25-003T")]
    assert _labels(_report(*rows), range_tail_allow=["T"]) == [
        "RT-KF-25-(001-002)", "RT-KF-25-(002-003)T"]
    rows = [_row("RT-KF-25-001"), _row("RT-KF-25-002T")]
    assert _labels(_report(*rows), range_tail_allow=["T"]) == [
        "RT-KF-25-001", "RT-KF-25-002T"]


def test_a_retest_of_a_tailed_number_joins_its_number():
    rows = [_row("RT-KF-25-080T", result="Unfit"),
            _row("RT-KF-25-080TR1", date=(2025, 8, 13)),
            _row("RT-KF-25-081T")]
    assert _labels(_report(*rows), range_tail_allow=["T"]) == ["RT-KF-25-(080-081)T"]


def test_the_label_tail_follows_the_number_tail():
    rows = [_row("RT-KF-25-080T", label=" (Dashgil 2)"),
            _row("RT-KF-25-081T", label=" (Dashgil 2)")]
    assert _labels(_report(*rows), range_tail_allow=["T"]) == [
        "RT-KF-25-(080-081)T (Dashgil 2)"]


@pytest.mark.parametrize("extra", [{}, {"range_tail_allow": []}])
def test_default_changes_nothing(extra):
    rows = [*_T_RUN, _row("U-UT-25-003rej"), _row("RT-KF-25-001"),
            _row("RT-KF-25-002")]
    report = _report(*rows)
    absent = split_display_rows(report, **display_options(
        _Settings(range_mode="by_number")))
    given = split_display_rows(report, **display_options(
        _Settings(range_mode="by_number", **extra)))
    legacy = split_display_rows(report, range_mode="by_number")
    assert absent == given == legacy
    assert len(absent[0]) == len(_T_RUN) + 2


def test_strict_ignores_the_key():
    report = _report(*_T_RUN)
    assert (split_display_rows(report, **display_options(_Settings()))
            == split_display_rows(report, **display_options(
                _Settings(range_tail_allow=["T"]))))


def test_an_unfit_t_number_inside_a_fit_range_is_audited():
    rows = [_row("RT-KF-25-080T"), _row("RT-KF-25-081T", result="Unfit")]
    s = _Settings(range_mode="by_number", range_tail_allow=["T"])
    assert range_verdict_notes(_report(*rows), s) == [
        ("RT-KF-25-081T", "RT-KF-25-(080-081)T")]
