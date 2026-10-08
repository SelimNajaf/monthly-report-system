"""Pin the PDF's consecutive-range collapsing — the rules AND the refusals.

A month of routine radiography is dozens of identical reports, and the summary
table used to spend one line on each (106 lines for RT/SDLN/SEP_2025). The PDF
now draws a run of consecutive identical ones as ``RT-SDL-25-(086-102)``.

This is a government-facing document, so the interesting half of these tests is
what does NOT merge:

* a parent that has a retest child stands alone — the child's Sıra № is derived
  from the parent's (``53`` -> ``53a``), and a parent swallowed by a range would
  leave ``53a`` anchored to a number the document does not contain;
* a verdict change breaks the run, so a rejected report can never hide inside a
  range of accepted ones;
* ``RT-SDL-25-123R1`` must never be read as prefix ``RT-SDL-25-123R`` + number
  ``1`` — a real report number from the corpus that a naive trailing-digit
  parser merges with its own siblings.

And the data contract: collapsing is a projection. ``report.rows`` is never
mutated, so the JSON sidecar keeps one entry per report and ``total_records``
keeps counting reports — the PDF/sidecar row-count mismatch is deliberate.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, collapse_display_rows, collapse_ranges_enabled,
    split_display_rows, split_ranges_on_item_enabled)
from monthly_report.json_exporter import build_report_json  # noqa: E402


class _Translator:
    """Identity translation — keeps the assertions about VALUES, not wording."""

    def term(self, text):
        return text


class _Settings:
    """Only what build_report_json touches."""

    raw = {"clients": {}}


def _row(report_no="RT-SDL-25-086", *, seq="1", sort_key=None, date=(2025, 9, 10),
         standard="ASME B31.1", method="RT", item="", result="Fit",
         job="", retest_rank=0, orphan=False):
    d = _dt.date(*date)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=report_no, retest_rank=retest_rank, client="SDLN",
        document_name=f"{report_no}{job}", standard=standard, item_detail=item,
        result=result, method=method, seq=seq,
        sort_key=sort_key if sort_key is not None else (int(seq), 0),
        is_orphan_retest=orphan,
    )


def _run(prefix="MPI-25-01-", start=1, count=37, **kw):
    """A run of consecutive parents, numbered and sequenced like the aggregator."""
    return [_row(f"{prefix}{n}", seq=str(i), **kw)
            for i, n in enumerate(range(start, start + count), start=1)]


def _report(*rows):
    return MonthlyReport(month="2025-09", document_number="MR-RT-SDLN-25-09",
                         title="İNSPEKSİYA ÜZRƏ AYLIQ HESABATIN NƏTİCƏSİ",
                         method="RT", client_code="SDLN", client_name="Sədələn",
                         rows=list(rows))


def _labels(display):
    return [(d.seq, d.report_label) for d in display]


# --------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------

def test_thirty_seven_identical_consecutive_reports_become_one_line():
    display = collapse_display_rows(_report(*_run()))
    assert len(display) == 1
    assert display[0].seq == "1"
    assert display[0].report_label == "MPI-25-01-(1-37)"
    assert display[0].span == 37


def test_a_verdict_change_splits_the_run_at_the_exact_boundary():
    rows = _run(count=37)
    rows[12].result = "Unfit"            # the 13th report
    display = collapse_display_rows(_report(*rows))
    assert _labels(display) == [("1", "MPI-25-01-(1-12)"),
                                ("2", "MPI-25-01-13"),
                                ("3", "MPI-25-01-(14-37)")]
    assert [d.result for d in display] == ["Fit", "Unfit", "Fit"]


def test_a_gap_in_the_numbering_starts_a_new_range():
    rows = [_row("MPI-25-01-1", seq="1"), _row("MPI-25-01-2", seq="2"),
            _row("MPI-25-01-4", seq="3")]
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "MPI-25-01-(1-2)"), ("2", "MPI-25-01-4")]


def test_a_lone_report_never_uses_the_range_format():
    display = collapse_display_rows(_report(_row("MPI-25-01-5", seq="1")))
    assert [d.report_label for d in display] == ["MPI-25-01-5"]
    assert display[0].span == 1


# --------------------------------------------------------------------------
# Retests — the reason the rules are strict
# --------------------------------------------------------------------------

def test_a_parent_with_a_retest_child_stays_out_of_the_range():
    """122 and 123 are consecutive and identical, but 123 has a 123R1 child.

    Straight from RT/SDLN/SEP_2025: rows 52/53/53a. Merging 123 into a range
    would leave 53a pointing at a Sıra № the table no longer prints.
    """
    rows = [
        _row("RT-SDL-25-121", seq="1", date=(2025, 9, 16), result="Unfit"),
        _row("RT-SDL-25-122", seq="2", date=(2025, 9, 16), result="Unfit"),
        _row("RT-SDL-25-123", seq="3", date=(2025, 9, 16), result="Unfit"),
        _row("RT-SDL-25-123R1", seq="3a", sort_key=(3, 1), date=(2025, 9, 17),
             result="Unfit", retest_rank=1),
    ]
    display = collapse_display_rows(_report(*rows))
    assert _labels(display) == [("1", "RT-SDL-25-(121-122)"),
                                ("2", "RT-SDL-25-123"),
                                ("2a", "RT-SDL-25-123R1")]
    # The anchor survives the renumbering: the child hangs off the line above it.
    assert display[2].is_retest_child is True
    assert display[1].is_retest_child is False


def test_a_retest_number_is_never_parsed_as_prefix_plus_trailing_digit():
    """``…-123R1`` and ``…-123R2`` are NOT a consecutive pair of parents."""
    rows = [_row("RT-SDL-25-123R1", seq="1", retest_rank=1, orphan=True),
            _row("RT-SDL-25-123R2", seq="2", retest_rank=2, orphan=True)]
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "RT-SDL-25-123R1"), ("2", "RT-SDL-25-123R2")]


def test_an_orphan_retest_gets_its_own_unshaded_line():
    rows = [_row("RT-SDL-25-086", seq="1"),
            _row("RT-SDL-25-090R1", seq="2", retest_rank=1, orphan=True),
            _row("RT-SDL-25-087", seq="3")]
    display = collapse_display_rows(_report(*rows))
    assert _labels(display) == [("1", "RT-SDL-25-086"),
                                ("2", "RT-SDL-25-090R1"),
                                ("3", "RT-SDL-25-087")]
    # Orphans are plain integers and stay unshaded, as before the feature.
    assert [d.is_retest_child for d in display] == [False, False, False]


# --------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------

def test_a_different_standard_or_method_does_not_merge():
    std = [_row("MPI-25-01-1", seq="1"),
           _row("MPI-25-01-2", seq="2", standard="ASME B31.3")]
    assert len(collapse_display_rows(_report(*std))) == 2

    mth = [_row("MPI-25-01-1", seq="1"),
           _row("MPI-25-01-2", seq="2", method="UT")]
    assert len(collapse_display_rows(_report(*mth))) == 2


def test_a_different_suffix_does_not_merge_and_the_suffix_is_kept():
    rows = [_row("RT-U-25-151", seq="1", job=" (Dashgil 2)"),
            _row("RT-U-25-152", seq="2", job=" (Dashgil 2)"),
            _row("RT-U-25-153", seq="3", job=" (Dashgil 3)")]
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "RT-U-25-(151-152) (Dashgil 2)"),
        ("2", "RT-U-25-153 (Dashgil 3)")]


def test_mixed_zero_padding_does_not_merge():
    """``086`` and ``87`` are consecutive numerically but print ambiguously."""
    rows = [_row("RT-SDL-25-086", seq="1"), _row("RT-SDL-25-87", seq="2")]
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "RT-SDL-25-086"), ("2", "RT-SDL-25-87")]


def test_zero_padding_is_preserved_inside_the_range():
    rows = _run(prefix="RT-SDL-25-0", start=86, count=3)
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "RT-SDL-25-(086-088)")]


def test_a_width_rollover_inside_one_scheme_still_merges():
    """``9`` -> ``10`` and ``099`` -> ``100`` are ordinary growth, not a change."""
    plain = _run(prefix="MPI-25-01-", start=8, count=4)          # 8,9,10,11
    assert _labels(collapse_display_rows(_report(*plain))) == [
        ("1", "MPI-25-01-(8-11)")]

    padded = [_row("RT-SDL-25-099", seq="1"), _row("RT-SDL-25-100", seq="2")]
    assert _labels(collapse_display_rows(_report(*padded))) == [
        ("1", "RT-SDL-25-(099-100)")]


# --------------------------------------------------------------------------
# Cell content
# --------------------------------------------------------------------------

def test_differing_dates_render_as_a_range_and_equal_dates_as_one_date():
    spread = [_row("RT-SDL-25-086", seq="1", date=(2025, 11, 3)),
              _row("RT-SDL-25-087", seq="2", date=(2025, 11, 5)),
              _row("RT-SDL-25-088", seq="3", date=(2025, 11, 7))]
    assert collapse_display_rows(_report(*spread))[0].date_str == \
        "03.11.2025 – 07.11.2025"

    same = _run(prefix="RT-SDL-25-", start=86, count=3)
    assert collapse_display_rows(_report(*same))[0].date_str == "10.09.2025"


def test_a_differing_item_detail_goes_blank_rather_than_being_invented():
    """The one mixed group in the real corpus is {'', 'SDLN WORK SHOP'}."""
    mixed = [_row("RT-SDL-25-157", seq="1", item=""),
             _row("RT-SDL-25-158", seq="2", item="SDLN WORK SHOP")]
    assert collapse_display_rows(_report(*mixed))[0].item_detail == ""

    shared = _run(prefix="RT-SDL-25-1", start=24, count=3, item="SDLN WORK SHOP")
    assert collapse_display_rows(_report(*shared))[0].item_detail == "SDLN WORK SHOP"


# --------------------------------------------------------------------------
# The switch, and the data contract
# --------------------------------------------------------------------------

def test_collapse_ranges_false_reproduces_the_old_table_exactly():
    rows = _run(count=37)
    display = collapse_display_rows(_report(*rows), enabled=False)
    assert len(display) == len(rows)
    assert [d.seq for d in display] == [r.seq for r in rows]
    assert [d.report_label for d in display] == [r.document_name for r in rows]


def test_the_flag_defaults_to_on_when_the_block_is_absent():
    class _Bare:
        raw = {"clients": {}}

    class _Off:
        raw = {"presentation": {"collapse_ranges": False}}

    class _On:
        raw = {"presentation": {"collapse_ranges": True}}

    assert collapse_ranges_enabled(_Bare()) is True
    assert collapse_ranges_enabled(_Off()) is False
    assert collapse_ranges_enabled(_On()) is True


def test_collapsing_never_mutates_report_rows_so_the_sidecar_is_untouched():
    report = _report(*_run(count=37))
    before = build_report_json(report, _Settings(), _Translator())
    display = collapse_display_rows(report)

    after = build_report_json(report, _Settings(), _Translator())
    assert after == before
    assert after["total_records"] == 37
    assert len(after["items_table"]) == 37
    assert [r["seq_no"] for r in after["items_table"]] == \
        [str(n) for n in range(1, 38)]
    # ...while the PDF draws exactly one line for the same 37 reports.
    assert len(display) == 1


# --------------------------------------------------------------------------
# The renderer end: what actually reaches the LongTable
# --------------------------------------------------------------------------

def _table_of(report, *, enabled=True):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from monthly_report import pdf_renderer

    fonts = _ROOT / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("DejaVu", str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(fonts / "DejaVuSans-Bold.ttf")))
    display = collapse_display_rows(report, enabled=enabled)
    table = pdf_renderer._build_table(report, _Translator(),
                                      pdf_renderer._styles(), display)
    return table, display


def test_the_rendered_table_carries_the_collapsed_line_count():
    report = _report(*_run(count=37))
    collapsed, _ = _table_of(report)
    verbatim, _ = _table_of(report, enabled=False)
    assert len(collapsed._cellvalues) == 1 + 1       # header + one range line
    assert len(verbatim._cellvalues) == 1 + 37       # header + every report


def test_only_lettered_children_are_shaded_after_collapsing():
    from reportlab.lib import colors

    from monthly_report import pdf_renderer

    rows = [
        _row("RT-SDL-25-121", seq="1", result="Unfit"),
        _row("RT-SDL-25-122", seq="2", result="Unfit"),
        _row("RT-SDL-25-123", seq="3", result="Unfit"),
        _row("RT-SDL-25-123R1", seq="3a", sort_key=(3, 1), date=(2025, 9, 17),
             result="Unfit", retest_rank=1),
        _row("RT-SDL-25-140R1", seq="4", date=(2025, 9, 18), result="Unfit",
             retest_rank=1, orphan=True),
    ]
    table, display = _table_of(_report(*rows))
    shaded = [cmd[1][1] for cmd in table._bkgrndcmds
              if cmd[3] == colors.HexColor("#FDF3D8")]
    # Table line 3 is 123R1 — the only matched child. The orphan on line 4 and
    # the collapsed range on line 1 stay unshaded.
    assert shaded == [3]
    assert [d.seq for d in display] == ["1", "2", "2a", "3"]
    assert pdf_renderer._COL_MM == [12, 24, 40, 33, 14, 35, 25]  # layout untouched


# --------------------------------------------------------------------------
# presentation.split_ranges_on_item — İtem / Detal as one more merge condition
# --------------------------------------------------------------------------

def _items(*items):
    """Consecutive, otherwise identical reports that differ only in İtem."""
    return [_row(f"MPI-25-01-{n}", seq=str(n), item=it)
            for n, it in enumerate(items, start=1)]


def test_split_on_item_is_off_when_the_block_or_the_key_is_absent():
    class _Bare:
        raw = {"clients": {}}

    class _NoKey:
        raw = {"presentation": {"collapse_ranges": True}}

    class _On:
        raw = {"presentation": {"split_ranges_on_item": True}}

    class _Off:
        raw = {"presentation": {"split_ranges_on_item": False}}

    assert split_ranges_on_item_enabled(_Bare()) is False
    assert split_ranges_on_item_enabled(_NoKey()) is False
    assert split_ranges_on_item_enabled(_On()) is True
    assert split_ranges_on_item_enabled(_Off()) is False


def test_switch_off_merges_across_items_and_blanks_the_column_as_before():
    rows = _items("A", "A", "B", "B", "A")
    display = collapse_display_rows(_report(*rows), split_on_item=False)
    assert _labels(display) == [("1", "MPI-25-01-(1-5)")]
    assert display[0].item_detail == ""
    assert _labels(collapse_display_rows(_report(*rows))) == _labels(display)


def test_switch_on_breaks_the_range_wherever_the_item_changes():
    rows = _items("A", "A", "B", "B", "A")
    display = collapse_display_rows(_report(*rows), split_on_item=True)
    assert _labels(display) == [("1", "MPI-25-01-(1-2)"),
                                ("2", "MPI-25-01-(3-4)"),
                                ("3", "MPI-25-01-5")]
    assert [d.item_detail for d in display] == ["A", "B", "A"]
    assert [d.span for d in display] == [2, 2, 1]


def test_switch_on_never_prints_a_blank_item_for_a_collapsed_line():
    rows = _items("A", "", "", "B", "B", "B", "C")
    for d in collapse_display_rows(_report(*rows), split_on_item=True):
        assert d.item_detail == ({"1": "A", "2": "", "3": "B", "4": "C"})[d.seq]


def test_switch_on_leaves_a_uniform_run_as_one_line():
    rows = _run(count=37, item="SDLN WORK SHOP")
    assert _labels(collapse_display_rows(_report(*rows), split_on_item=True)) ==         [("1", "MPI-25-01-(1-37)")]


def test_switch_on_changes_nothing_when_collapsing_is_off():
    rows = _items("A", "B", "A")
    on = collapse_display_rows(_report(*rows), enabled=False, split_on_item=True)
    off = collapse_display_rows(_report(*rows), enabled=False)
    assert on == off


def test_switch_on_keeps_the_section_numbering_gapless():
    rows = [_row("MPI-25-01-1", seq="1", item="A"),
            _row("MPI-25-01-2", seq="2", item="B"),
            _row("MPI-25-01-3", seq="3", item="B", result="Unfit"),
            _row("MPI-25-01-4", seq="4", item="C", result="Unfit")]
    main, unfit = split_display_rows(_report(*rows), placement="section",
                                     split_on_item=True)
    assert [d.seq for d in main] == ["1", "2"]
    assert [d.seq for d in unfit] == ["3", "4"]


def test_switch_on_never_touches_report_rows_so_the_sidecar_is_unchanged():
    report = _report(*_items("A", "A", "B", "B", "A"))
    before = build_report_json(report, _Settings(), _Translator())
    collapse_display_rows(report, split_on_item=True)
    after = build_report_json(report, _Settings(), _Translator())
    assert after == before
    assert after["total_records"] == 5
