"""Pin ``presentation.pulled_parent_style`` — a cross-month parent, marked.

``retest_tracker.pull_cross_month_parents`` brings a retest's original forward
from the month it was reported in, so the retest can be read. On ``marked`` the
document says so instead of presenting it as this month's work:

* the line gets a ``*`` on its Sıra № and a note under the table naming the
  month it belongs to;
* it never joins a range, so the mark always names exactly one report;
* a roll-up never folds its retest into it — the rolled-up line would carry the
  parent's number and date and hide the retest this month actually did;
* its sidecar row carries ``pulled_from``; it stays in ``items_table`` and in
  ``total_records`` because it is on the page.

``plain`` — the default — must be exactly the behaviour that predates the key.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, pulled_from, pulled_parent_style,
    split_display_rows)
from monthly_report.json_exporter import build_report_json  # noqa: E402


class _Translator:
    def term(self, text):
        return text


class _Settings:
    def __init__(self, **presentation):
        self.raw = {"clients": {}, "presentation": presentation}


def _row(report_no, *, seq, sort_key=None, date=(2026, 3, 10), result="Fit",
         retest_rank=0, pulled=False, item="Boru", job=" (Zığ)"):
    d = _dt.date(*date)
    series = report_no.split("R")[0] if retest_rank else report_no
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=series, retest_rank=retest_rank, client="UBOC",
        document_name=f"{report_no}{job}", standard="ASME B31.3",
        item_detail=item, result=result, method="RT", seq=seq,
        sort_key=sort_key if sort_key is not None else (int(seq), 0),
        is_pulled_parent=pulled)


def _report(*rows):
    return MonthlyReport(month="2026-03", document_number="MR-UBOC-26-03",
                         title="T", method="RT", client_code="UBOC",
                         client_name="UBOC", rows=list(rows))


def _chains():
    """Two February parents pulled for March retests, then March's own run."""
    return [
        _row("U-RT-26-006", seq="1", date=(2026, 2, 27), result="Unfit", pulled=True),
        _row("U-RT-26-006R1", seq="1a", sort_key=(1, 1), date=(2026, 3, 6),
             retest_rank=1),
        _row("U-RT-26-007", seq="2", date=(2026, 2, 27), result="Unfit", pulled=True),
        _row("U-RT-26-007R1", seq="2a", sort_key=(2, 1), date=(2026, 3, 6),
             retest_rank=1),
        _row("U-RT-26-008", seq="3"),
        _row("U-RT-26-009", seq="4"),
    ]


def _labels(lines):
    return [(d.seq, d.report_label, d.pulled_from) for d in lines]


def test_style_is_plain_when_the_block_the_key_or_the_value_is_unknown():
    class _Bare:
        raw = {}

    assert pulled_parent_style(_Bare()) == "plain"
    assert pulled_parent_style(_Settings()) == "plain"
    assert pulled_parent_style(_Settings(pulled_parent_style="bold")) == "plain"
    assert pulled_parent_style(_Settings(pulled_parent_style=" Marked ")) == "marked"


def test_pulled_from_is_the_parents_own_month_and_blank_for_other_rows():
    rows = _chains()
    assert pulled_from(rows[0]) == "2026-02"
    assert pulled_from(rows[1]) == ""
    assert pulled_from(rows[4]) == ""


def test_plain_rolls_the_pulled_parents_into_one_range_as_before():
    main, _ = split_display_rows(_report(*_chains()), rollup=True)
    assert [(d.seq, d.report_label, d.result) for d in main] == [
        ("1", "U-RT-26-(006-009) (Zığ)", "Fit"),
    ]


def test_marked_never_ranges_a_pulled_parent_and_keeps_its_retest_visible():
    main, _ = split_display_rows(_report(*_chains()), rollup=True,
                                 mark_pulled=True)
    assert _labels(main) == [
        ("1", "U-RT-26-006 (Zığ)", "2026-02"),
        ("1a", "U-RT-26-006R1 (Zığ)", ""),
        ("2", "U-RT-26-007 (Zığ)", "2026-02"),
        ("2a", "U-RT-26-007R1 (Zığ)", ""),
        ("3", "U-RT-26-(008-009) (Zığ)", ""),
    ]
    # The parent prints its OWN verdict, not the chain's final one.
    assert [d.result for d in main[:2]] == ["Unfit", "Fit"]


def test_marked_still_rolls_up_a_chain_whose_parent_is_this_months():
    rows = [
        _row("U-RT-26-010", seq="1", result="Unfit"),
        _row("U-RT-26-010R1", seq="1a", sort_key=(1, 1), date=(2026, 3, 12),
             retest_rank=1),
    ]
    main, _ = split_display_rows(_report(*rows), rollup=True, mark_pulled=True)
    assert [(d.seq, d.report_label, d.result) for d in main] == [
        ("1", "U-RT-26-010 (Zığ)", "Fit"),
    ]


def test_marked_keeps_the_unfit_section_off_a_pulled_chain():
    main, unfit = split_display_rows(_report(*_chains()), rollup=True,
                                     placement="section", mark_pulled=True)
    assert unfit == []
    assert [d.seq for d in main] == ["1", "1a", "2", "2a", "3"]


def test_marked_with_collapse_off_keeps_each_rows_own_number():
    main, _ = split_display_rows(_report(*_chains()), enabled=False,
                                 rollup=True, mark_pulled=True)
    assert _labels(main) == [
        ("1", "U-RT-26-006 (Zığ)", "2026-02"),
        ("1a", "U-RT-26-006R1 (Zığ)", ""),
        ("2", "U-RT-26-007 (Zığ)", "2026-02"),
        ("2a", "U-RT-26-007R1 (Zığ)", ""),
        ("3", "U-RT-26-008 (Zığ)", ""),
        ("4", "U-RT-26-009 (Zığ)", ""),
    ]


def test_plain_with_collapse_off_still_hides_the_children_under_rollup():
    main, _ = split_display_rows(_report(*_chains()), enabled=False, rollup=True)
    assert [d.seq for d in main] == ["1", "2", "3", "4"]


def test_marking_never_mutates_report_rows():
    report = _report(*_chains())
    before = [(r.seq, r.result, r.is_pulled_parent) for r in report.rows]
    split_display_rows(report, rollup=True, placement="section", mark_pulled=True)
    assert [(r.seq, r.result, r.is_pulled_parent) for r in report.rows] == before


def test_sidecar_on_plain_carries_no_new_key():
    data = build_report_json(_report(*_chains()), _Settings(), _Translator())
    assert all("pulled_from" not in r for r in data["items_table"])


def test_sidecar_on_marked_flags_only_the_pulled_rows_and_keeps_the_count():
    report = _report(*_chains())
    plain = build_report_json(report, _Settings(), _Translator())
    marked = build_report_json(report, _Settings(pulled_parent_style="marked"),
                               _Translator())
    assert [r.get("pulled_from") for r in marked["items_table"]] == [
        "2026-02", None, "2026-02", None, None, None]
    assert marked["total_records"] == plain["total_records"] == 6
    assert marked["source_report_count"] == plain["source_report_count"]
    strip = [{k: v for k, v in r.items() if k != "pulled_from"}
             for r in marked["items_table"]]
    assert strip == plain["items_table"]


def _table(display, mark):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from monthly_report import pdf_renderer

    fonts = _ROOT / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("DejaVu", str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(fonts / "DejaVuSans-Bold.ttf")))
    return pdf_renderer._build_table(_report(), _Translator(),
                                     pdf_renderer._styles(), display, mark)


def test_the_mark_is_drawn_on_the_sira_number_only_when_asked():
    main, _ = split_display_rows(_report(*_chains()), rollup=True,
                                 mark_pulled=True)
    marked = [row[0].text for row in _table(main, True)._cellvalues[1:]]
    plain = [row[0].text for row in _table(main, False)._cellvalues[1:]]
    assert marked == ["1*", "1a", "2*", "2a", "3"]
    assert plain == ["1", "1a", "2", "2a", "3"]


class _Az:
    """The real az.json, looked up the way translator.Translator does."""

    def __init__(self):
        raw = json.loads((_ROOT / "translations" / "az.json").read_text(encoding="utf-8"))
        self._d = {k.strip().lower(): v for k, v in raw.items()}

    def term(self, text):
        return self._d.get(text.strip().lower(), text)


def test_one_note_per_month_in_the_approved_wording():
    from monthly_report import pdf_renderer

    rows = _chains() + [
        _row("U-RT-26-020", seq="5", date=(2026, 1, 20), pulled=True),
        _row("U-RT-26-020R1", seq="5a", sort_key=(5, 1), date=(2026, 3, 20),
             retest_rank=1),
    ]
    main, _ = split_display_rows(_report(*rows), rollup=True, mark_pulled=True)
    assert pdf_renderer._pulled_notes(_Az(), main) == [
        "* Yanvar 2026 hesabatına aiddir, burada arayış üçün göstərilir.",
        "* Fevral 2026 hesabatına aiddir, burada arayış üçün göstərilir.",
    ]
    assert pdf_renderer._pulled_notes(_Az(), main[4:5]) == []
