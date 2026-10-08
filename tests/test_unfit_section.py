"""Pin ``presentation.rollup_retests`` and ``presentation.unfit_placement``.

Two PDF-only switches, both defaulting to the behaviour that predates them.

The roll-up draws a retest chain as ONE line: the ``53a`` rows are not printed
and ``53`` carries the chain's FINAL verdict, so a weld rejected in April and
passed on the May retest appears once, as accepted. Because the chain is gone,
the parent stops being an anchor and becomes an ordinary mergeable row.

The placement answers what is left: a weld that was rejected and NEVER retested
is not part of any chain and stays rejected. ``section`` moves those out of the
chronological table into a second, captioned block — numbering CONTINUING, so
the document still reads as one gapless Sıra № sequence.

What must NOT happen is the point of most of these tests: ``report.rows`` is
never mutated (the sidecar keeps one entry per report), a parent that still
carries a retest row never leaves the main table, and neither switch does
anything at all until it is explicitly turned on.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, collapse_display_rows, rollup_retests_enabled,
    split_display_rows, unfit_placement)
from monthly_report.json_exporter import build_report_json  # noqa: E402


class _Translator:
    def term(self, text):
        return text


class _Settings:
    raw = {"clients": {}}


def _cfg(**presentation):
    class _C:
        raw = {"presentation": dict(presentation)}
    return _C()


def _row(report_no, *, seq="1", sort_key=None, date=(2025, 9, 10),
         standard="ASME B31.1", method="RT", item="", result="Fit",
         retest_rank=0):
    d = _dt.date(*date)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=report_no, retest_rank=retest_rank, client="SDLN",
        document_name=report_no, standard=standard, item_detail=item,
        result=result, method=method, seq=seq,
        sort_key=sort_key if sort_key is not None else (int(seq), 0),
    )


def _report(*rows):
    return MonthlyReport(month="2025-09", document_number="MR-RT-SDLN-25-09",
                         title="İNSPEKSİYA ÜZRƏ AYLIQ HESABATIN NƏTİCƏSİ",
                         method="RT", client_code="SDLN", client_name="Sədələn",
                         rows=list(rows))


def _labels(display):
    return [(d.seq, d.report_label, d.result) for d in display]


def _chain():
    """Rows 1/2/3/3a: three rejected reports, the last one retested and passed."""
    return [
        _row("RT-SDL-25-121", seq="1", result="Unfit"),
        _row("RT-SDL-25-122", seq="2", result="Unfit"),
        _row("RT-SDL-25-123", seq="3", result="Unfit"),
        _row("RT-SDL-25-123R1", seq="3a", sort_key=(3, 1), date=(2025, 9, 17),
             result="Fit", retest_rank=1),
    ]


# --------------------------------------------------------------------------
# The switches: absent means the old document
# --------------------------------------------------------------------------

def test_rollup_is_off_unless_it_is_asked_for():
    """The opposite default to collapse_ranges, and deliberately so.

    The roll-up hides lines and rewrites a printed verdict. A document already
    delivered to the state must not change because a key appeared in a config
    file the operator never edited.
    """
    class _Bare:
        raw = {"clients": {}}

    assert rollup_retests_enabled(_Bare()) is False
    assert rollup_retests_enabled(_cfg()) is False
    assert rollup_retests_enabled(_cfg(rollup_retests=False)) is False
    assert rollup_retests_enabled(_cfg(rollup_retests=True)) is True


def test_placement_defaults_to_inline_and_an_unknown_value_reads_as_inline():
    class _Bare:
        raw = {"clients": {}}

    assert unfit_placement(_Bare()) == "inline"
    assert unfit_placement(_cfg()) == "inline"
    assert unfit_placement(_cfg(unfit_placement="section")) == "section"
    assert unfit_placement(_cfg(unfit_placement="SECTION ")) == "section"
    # A typo must not restructure a government document in silence.
    assert unfit_placement(_cfg(unfit_placement="anneks")) == "inline"
    assert unfit_placement(_cfg(unfit_placement=None)) == "inline"


def test_both_switches_off_reproduce_the_current_table_exactly():
    rows = _chain()
    assert _labels(collapse_display_rows(_report(*rows))) == \
        _labels(split_display_rows(_report(*rows))[0])
    assert split_display_rows(_report(*rows))[1] == []


# --------------------------------------------------------------------------
# rollup_retests
# --------------------------------------------------------------------------

def test_the_rollup_hides_the_child_and_gives_the_parent_the_final_verdict():
    main, unfit = split_display_rows(_report(*_chain()), rollup=True)
    assert unfit == []
    assert _labels(main) == [("1", "RT-SDL-25-(121-122)", "Unfit"),
                             ("2", "RT-SDL-25-123", "Fit")]
    assert [d.is_retest_child for d in main] == [False, False]


def test_a_rolled_up_parent_may_join_a_range_again():
    """With no 53a left to anchor, the parent is an ordinary row.

    121 is rejected and repaired; 122 and 123 passed first time. After the
    roll-up all three read Fit and collapse into one line — which is exactly
    what cannot happen while the child is printed.
    """
    rows = [
        _row("RT-SDL-25-121", seq="1", result="Unfit"),
        _row("RT-SDL-25-121R1", seq="1a", sort_key=(1, 1), result="Fit",
             retest_rank=1),
        _row("RT-SDL-25-122", seq="2"),
        _row("RT-SDL-25-123", seq="3"),
    ]
    assert _labels(collapse_display_rows(_report(*rows), rollup=True)) == [
        ("1", "RT-SDL-25-(121-123)", "Fit")]
    # Off, the same rows draw the parent, its child and a two-report range.
    assert _labels(collapse_display_rows(_report(*rows))) == [
        ("1", "RT-SDL-25-121", "Unfit"),
        ("1a", "RT-SDL-25-121R1", "Fit"),
        ("2", "RT-SDL-25-(122-123)", "Fit")]


def test_a_chain_that_never_passed_keeps_the_rejected_verdict():
    """The roll-up reports the chain's last word, whatever it is."""
    rows = [
        _row("RT-SDL-25-130", seq="1", result="Unfit"),
        _row("RT-SDL-25-130R1", seq="1a", sort_key=(1, 1), result="Unfit",
             retest_rank=1),
        _row("RT-SDL-25-130R2", seq="1b", sort_key=(1, 2), result="Unfit",
             retest_rank=2),
    ]
    assert _labels(collapse_display_rows(_report(*rows), rollup=True)) == [
        ("1", "RT-SDL-25-130", "Unfit")]


def test_the_rollup_never_mutates_report_rows():
    report = _report(*_chain())
    before = build_report_json(report, _Settings(), _Translator())
    split_display_rows(report, rollup=True, placement="section")
    after = build_report_json(report, _Settings(), _Translator())
    assert after == before
    assert after["total_records"] == 4
    assert [r["seq_no"] for r in after["items_table"]] == ["1", "2", "3", "3a"]
    # The parent's own verdict on disk is still the one its document carries.
    assert report.rows[2].result == "Unfit"


# --------------------------------------------------------------------------
# unfit_placement: section
# --------------------------------------------------------------------------

def test_the_section_takes_the_rejected_lines_and_keeps_the_numbering_going():
    rows = [
        _row("RT-SDL-25-121", seq="1"),
        _row("RT-SDL-25-122", seq="2", result="Unfit"),
        _row("RT-SDL-25-123", seq="3", result="Unfit"),
        _row("RT-SDL-25-124", seq="4"),
    ]
    main, unfit = split_display_rows(_report(*rows), placement="section")
    assert _labels(main) == [("1", "RT-SDL-25-121", "Fit"),
                             ("2", "RT-SDL-25-124", "Fit")]
    # 3, not 1: the block continues the table it follows.
    assert _labels(unfit) == [("3", "RT-SDL-25-(122-123)", "Unfit")]


def test_the_informational_verdict_stays_in_the_main_table():
    rows = [_row("UTM-25-01-1", seq="1", method="UTM", result="Info"),
            _row("UTM-25-01-2", seq="2", method="UTM", result="Unfit")]
    main, unfit = split_display_rows(_report(*rows), placement="section")
    assert _labels(main) == [("1", "UTM-25-01-1", "Info")]
    assert _labels(unfit) == [("2", "UTM-25-01-2", "Unfit")]


def test_a_parent_that_still_carries_a_retest_row_never_leaves_the_table():
    """Moving 3 would tear 3a away from it — the block would print 3a alone."""
    main, unfit = split_display_rows(_report(*_chain()), placement="section")
    assert _labels(main) == [("1", "RT-SDL-25-123", "Unfit"),
                             ("1a", "RT-SDL-25-123R1", "Fit")]
    assert _labels(unfit) == [("2", "RT-SDL-25-(121-122)", "Unfit")]


def test_rollup_and_section_together_leave_only_the_unrepaired_welds_behind():
    """The E3 document: repaired welds read Fit in the table, the rest below."""
    main, unfit = split_display_rows(_report(*_chain()), rollup=True,
                                     placement="section")
    assert _labels(main) == [("1", "RT-SDL-25-123", "Fit")]
    assert _labels(unfit) == [("2", "RT-SDL-25-(121-122)", "Unfit")]
    assert sum(d.span for d in main + unfit) == 3   # 4 rows, one retest hidden


def test_a_document_with_nothing_rejected_gets_no_second_block():
    rows = [_row("RT-SDL-25-121", seq="1"), _row("RT-SDL-25-122", seq="2")]
    main, unfit = split_display_rows(_report(*rows), placement="section")
    assert len(main) == 1 and unfit == []


def test_placement_is_ignored_while_collapse_ranges_is_off():
    """That mode prints each row's own Sıra №, so a split would gap BOTH blocks."""
    rows = _chain()
    main, unfit = split_display_rows(_report(*rows), enabled=False,
                                     placement="section")
    assert unfit == []
    assert [d.seq for d in main] == ["1", "2", "3", "3a"]


def test_the_rollup_still_applies_with_collapse_ranges_off():
    main, unfit = split_display_rows(_report(*_chain()), enabled=False,
                                     rollup=True, placement="section")
    assert unfit == []
    # The lettered child is gone, so the integer numbering stays gapless.
    assert _labels(main) == [("1", "RT-SDL-25-121", "Unfit"),
                             ("2", "RT-SDL-25-122", "Unfit"),
                             ("3", "RT-SDL-25-123", "Fit")]


# --------------------------------------------------------------------------
# The renderer end
# --------------------------------------------------------------------------

def test_the_section_caption_is_translated_through_az_json():
    """The operator approved the wording; the renderer must not hard-code it."""
    from monthly_report import pdf_renderer

    az = json.loads((_ROOT / "translations" / "az.json").read_text(encoding="utf-8"))
    assert az[pdf_renderer._UNFIT_SECTION_KEY] == \
        "Təkrar yoxlanılmamış yararsız qaynaqlar"


def test_the_second_block_renders_as_its_own_table_with_the_same_columns():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from monthly_report import pdf_renderer

    fonts = _ROOT / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("DejaVu", str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(fonts / "DejaVuSans-Bold.ttf")))

    report = _report(*_chain())
    main, unfit = split_display_rows(report, rollup=True, placement="section")
    st = pdf_renderer._styles()
    table = pdf_renderer._build_table(report, _Translator(), st, unfit)
    # Header row + the one collapsed line, and the header repeats on a page break
    # exactly as the main table's does.
    assert len(table._cellvalues) == 2
    assert len(table._cellvalues[0]) == len(pdf_renderer._HEADER_KEYS)
    assert table.repeatRows == 1
    assert len(main) == 1
