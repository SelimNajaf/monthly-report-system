"""Pin the by_number widening keys (ADR-009 follow-up, E1–E3).

* E1 ``range_ignore_tag`` — a different job tag (" (2236)") no longer breaks a
  range; the range line prints no tag, a single number keeps its own name.
* E2 ``range_merge_standards`` — a different standard no longer breaks a range;
  the Standart cell lists every distinct standard once, in number order.
* E3 ``range_item: dominant`` — a different İtem no longer breaks a range; the
  cell names the item seen on the most report NUMBERS, a tie goes to the
  smallest number, a blank item never counts.

Still breaking: a missing number, prefix, method, zero padding, number tail.
Every key at its default must be the drawing that predates it, and the JSON
sidecar never changes.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, display_options, range_verdict_notes,
    split_display_rows)
from monthly_report.json_exporter import build_report_json  # noqa: E402
from monthly_report.report_identity import retest_rank, strip_retest  # noqa: E402

_E_ALL = {"range_ignore_tag": True, "range_merge_standards": True,
          "range_item": "dominant"}


class _Translator:
    def term(self, text):
        return text


class _Settings:
    def __init__(self, date_format="%d.%m.%Y", **presentation):
        self.raw = {"clients": {}, "presentation": presentation}
        self.date_format = date_format


def _row(report_no, *, date=(2026, 6, 10), result="Fit", method="MT",
         tag="", standard="AWS D1.1", item="Konstruktiv tikiş", seq="",
         sort_key=(0, 0)):
    d = _dt.date(*date)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=strip_retest(report_no), retest_rank=retest_rank(report_no),
        client="KHF", document_name=f"{report_no}{tag}", standard=standard,
        item_detail=item, result=result, method=method, seq=seq,
        sort_key=sort_key, is_pulled_parent=False)


def _report(*rows):
    return MonthlyReport(month="2026-06", document_number="MR-KHF-26-06",
                         title="T", method="MT", client_code="KHF",
                         client_name="KHF", rows=list(rows))


def _draw(report, **presentation):
    opts = display_options(_Settings(range_mode="by_number", **presentation))
    main, second = split_display_rows(report, **opts)
    assert second == []
    return main


def _cells(main):
    return [(d.report_label, d.date_str, d.standard, d.item_detail, d.result)
            for d in main]


# --- defaults -------------------------------------------------------------

def _mixed():
    return _report(
        _row("KF-MT-26-001", tag=" (2236)", standard="AWS D1.1"),
        _row("KF-MT-26-002", tag=" (2274)", standard="EEMUA 158", item="Boru kəməri"),
        _row("KF-MT-26-003", tag=" (2274)", standard="EEMUA 158", item="Boru kəməri"),
        _row("KF-MT-26-004", tag=" (2274)", standard="EEMUA 158", item="Boru kəməri"),
    )


def test_defaults_resolve_to_old_behaviour():
    opts = display_options(_Settings())
    assert (opts["ignore_tag"], opts["merge_standards"], opts["item_rule"]) \
        == (False, False, "split")


def test_defaults_are_byte_identical_to_absent_keys():
    for extra in ({}, {"split_ranges_on_item": True}):
        absent = _draw(_mixed(), **extra)
        given = _draw(_mixed(), range_ignore_tag=False,
                      range_merge_standards=False, range_item="split", **extra)
        assert absent == given
    # An unknown range_item reads as split.
    assert _draw(_mixed(), range_item="bogus") == _draw(_mixed())


def test_keys_ignored_under_strict():
    s_off = display_options(_Settings())
    s_on = display_options(_Settings(**_E_ALL))
    assert split_display_rows(_mixed(), **s_off) == split_display_rows(_mixed(), **s_on)


def test_sidecar_is_identical_with_every_key_on():
    off = build_report_json(_mixed(), _Settings(range_mode="by_number"), _Translator())
    on = build_report_json(_mixed(), _Settings(range_mode="by_number", **_E_ALL),
                           _Translator())
    assert json.dumps(off, ensure_ascii=False) == json.dumps(on, ensure_ascii=False)
    # The tag stays in the report number the sidecar carries — it never had it.
    assert [r["report_no"] for r in on["items_table"]] == [
        "KF-MT-26-001", "KF-MT-26-002", "KF-MT-26-003", "KF-MT-26-004"]


# --- E1 -------------------------------------------------------------------

def test_e1_different_tags_range_without_a_tag():
    report = _report(
        _row("KF-MT-26-039", tag=" (2236)"),
        _row("KF-MT-26-040", tag=" (2274)"),
        _row("KF-MT-26-041"),                          # no tag at all
        _row("KF-MT-26-054", tag=" (2334)"),
    )
    assert [d.report_label for d in _draw(report)] == [
        "KF-MT-26-039 (2236)", "KF-MT-26-040 (2274)", "KF-MT-26-041",
        "KF-MT-26-054 (2334)"]
    assert [d.report_label for d in _draw(report, range_ignore_tag=True)] == [
        "KF-MT-26-(039-041)", "KF-MT-26-054 (2334)"]


def test_e1_same_tag_still_prints_no_tag_on_a_range():
    report = _report(_row("KF-MT-26-001", tag=" (2236)"),
                     _row("KF-MT-26-002", tag=" (2236)"))
    assert [d.report_label for d in _draw(report)] == ["KF-MT-26-(001-002) (2236)"]
    assert [d.report_label for d in _draw(report, range_ignore_tag=True)] == [
        "KF-MT-26-(001-002)"]


def test_e1_number_tail_still_breaks_and_prints():
    report = _report(_row("RT-KF-25-080T", tag=" (1)", method="RT"),
                     _row("RT-KF-25-081T", tag=" (2)", method="RT"),
                     _row("RT-KF-25-082", tag=" (3)", method="RT"))
    labels = [d.report_label for d in _draw(report, range_ignore_tag=True,
                                            range_tail_allow=["T"])]
    assert labels == ["RT-KF-25-082 (3)", "RT-KF-25-(080-081)T"]


# --- E2 -------------------------------------------------------------------

def test_e2_standards_listed_once_in_number_order():
    report = _report(
        _row("KF-MT-26-003", date=(2026, 6, 1), standard="ASME B31.3"),
        _row("KF-MT-26-001", date=(2026, 6, 9), standard="AWS D1.1"),
        _row("KF-MT-26-002", date=(2026, 6, 2), standard="EEMUA 158"),
        _row("KF-MT-26-004", date=(2026, 6, 3), standard="AWS D1.1"),
        _row("KF-MT-26-005", date=(2026, 6, 4), standard=""),
    )
    assert len(_draw(report)) == 5
    (line,) = _draw(report, range_merge_standards=True)
    assert line.report_label == "KF-MT-26-(001-005)"
    assert line.standard == "AWS D1.1, EEMUA 158, ASME B31.3"


def test_e2_uniform_standard_prints_as_before():
    report = _report(_row("KF-MT-26-001"), _row("KF-MT-26-002"))
    assert _draw(report, range_merge_standards=True) == _draw(report)


# --- E3 -------------------------------------------------------------------

def test_e3_most_common_item_wins():
    report = _report(
        _row("KF-MT-26-001", item="Boru kəməri"),
        _row("KF-MT-26-002", item="Konstruktiv tikiş"),
        _row("KF-MT-26-003", item="Konstruktiv tikiş"),
    )
    (line,) = _draw(report, range_item="dominant")
    assert line.item_detail == "Konstruktiv tikiş"


def test_e3_tie_goes_to_the_smallest_number():
    report = _report(
        _row("KF-MT-26-002", date=(2026, 6, 1), item="A"),
        _row("KF-MT-26-001", date=(2026, 6, 9), item="B"),
        _row("KF-MT-26-003", item="A"),
        _row("KF-MT-26-004", item="B"),
    )
    (line,) = _draw(report, range_item="dominant")
    assert line.item_detail == "B"


def test_e3_blank_never_counts_and_all_blank_prints_blank():
    report = _report(_row("KF-MT-26-001", item=""), _row("KF-MT-26-002", item=""),
                     _row("KF-MT-26-003", item="Tikiş"))
    (line,) = _draw(report, range_item="dominant")
    assert line.item_detail == "Tikiş"
    blank = _report(_row("KF-MT-26-001", item=""), _row("KF-MT-26-002", item=" "))
    (line,) = _draw(blank, range_item="dominant")
    assert line.item_detail == ""


def test_e3_counts_numbers_not_rows():
    # 001 is one number with three rows of "A"; 002 and 003 are "B".
    report = _report(
        _row("KF-MT-26-001", item="A", sort_key=(1, 0)),
        _row("KF-MT-26-001R1", item="A", sort_key=(1, 1)),
        _row("KF-MT-26-001R2", item="A", sort_key=(1, 2)),
        _row("KF-MT-26-002", item="B", sort_key=(2, 0)),
        _row("KF-MT-26-003", item="B", sort_key=(3, 0)),
    )
    (line,) = _draw(report, range_item="dominant")
    assert line.item_detail == "B"


def test_e3_overrides_split_ranges_on_item():
    report = _report(_row("KF-MT-26-001", item="A"), _row("KF-MT-26-002", item="B"))
    assert len(_draw(report, split_ranges_on_item=True)) == 2
    assert len(_draw(report, split_ranges_on_item=True, range_item="dominant")) == 1


# --- what still breaks ------------------------------------------------------

def test_gap_prefix_method_width_still_break():
    report = _report(
        _row("KF-MT-26-001", tag=" (1)", standard="A", item="x"),
        _row("KF-MT-26-002", tag=" (2)", standard="B", item="y"),
        _row("KF-MT-26-004", tag=" (3)"),                       # gap
        _row("KF-MX-26-005", tag=" (4)"),                       # prefix
        _row("KF-UT-26-003", tag=" (5)", method="UT"),          # method
        _row("KF-MT-26-05", tag=" (6)"),                        # width vs 004
    )
    labels = [d.report_label for d in _draw(report, **_E_ALL)]
    assert labels == ["KF-MT-26-(001-002)", "KF-MT-26-004 (3)",
                      "KF-MT-26-05 (6)", "KF-MX-26-005 (4)", "KF-UT-26-003 (5)"]


# --- inside one number ------------------------------------------------------

def test_unit_with_mixed_values_is_not_split_and_picks_by_the_same_rule():
    report = _report(
        _row("KF-MT-26-001", date=(2026, 6, 1), standard="AWS D1.1", item="",
             result="Unfit", sort_key=(1, 0)),
        _row("KF-MT-26-001R1", date=(2026, 6, 5), standard="ASME B31.3",
             item="Tikiş", sort_key=(1, 1)),
        _row("KF-MT-26-002", date=(2026, 6, 6), sort_key=(2, 0)),
    )
    # Off: a unit whose members disagree never ranges.
    assert len(_draw(report)) == 2
    (line,) = _draw(report, **_E_ALL)
    assert line.report_label == "KF-MT-26-(001-002)"
    assert line.standard == "AWS D1.1, ASME B31.3"
    # 001 votes "Tikiş" (its blank row does not count), 002 votes
    # "Konstruktiv tikiş": a tie, so the smallest number wins.
    assert line.item_detail == "Tikiş"
    # Alone, the unit uses the same rules.
    single = _draw(_report(*report.rows[:2]), **_E_ALL)
    assert [(d.report_label, d.standard, d.item_detail) for d in single] == [
        ("KF-MT-26-001", "AWS D1.1, ASME B31.3", "Tikiş")]


def test_range_verdict_notes_follow_the_widened_line():
    report = _report(_row("KF-MT-26-001", tag=" (1)"),
                     _row("KF-MT-26-002", tag=" (2)", result="Unfit"))
    assert range_verdict_notes(report, _Settings(range_mode="by_number")) == []
    assert range_verdict_notes(
        report, _Settings(range_mode="by_number", range_ignore_tag=True)) == [
        ("KF-MT-26-002", "KF-MT-26-(001-002)")]


# --- KHF JUN 2026 -----------------------------------------------------------

# items_table of output/KHF/compiled_monthly_report_KHF_JUN_2026.json, verbatim
# (item names as printed). Tags: (2334) and (2152) are from the brief; the rest
# are placeholders, one distinct tag per report — their real values do not
# change the outcome under E1.
_KHF_JUN = [
    ("01.06.2026", "KF-HrT-26-005", "ASME B31.3", "HRT", "Boru kəməri", "Info", " (2152)"),
    ("09.06.2026", "KF-MT-26-041", "AWS D1.1", "MT", "Konstruktiv tikiş", "Fit", None),
    ("09.06.2026", "KF-MT-26-042", "ASME B31.3", "MT", "Boru kəməri", "Fit", None),
    ("10.06.2026", "KF-MT-26-039", "AWS D1.1", "MT", "Welding of the basket arms", "Fit", None),
    ("12.06.2026", "KF-MT-26-040", "EEMUA 158", "MT", "Konstruktiv tikiş", "Fit", None),
    ("17.06.2026", "KF-MT-26-043", "ASME B31.3", "MT", "Boru kəməri", "Fit", None),
    ("17.06.2026", "KF-MT-26-044", "AWS D1.1", "MT", "Konstruktiv tikiş", "Fit", None),
    ("19.06.2026", "KF-MT-26-045", "AWS D1.1", "MT", "Konstruktiv tikiş", "Fit", None),
    ("22.06.2026", "KF-MT-26-046", "AWS D1.1", "MT", "Konstruktiv tikiş", "Fit", None),
    ("22.06.2026", "KF-MT-26-047", "EEMUA 158", "MT", "Konstruktiv tikiş", "Fit", None),
    ("22.06.2026", "KF-MT-26-054", "ASME B31.3", "MT", "Boru kəməri", "Fit", " (2334)"),
    ("23.06.2026", "KF-MT-26-048", "ASME B31.3", "MT", "Boru kəməri", "Fit", None),
    ("23.06.2026", "KF-MT-26-049", "AWS D1.1", "MT", "Konstruktiv tikiş", "Fit", None),
    ("25.06.2026", "KF-MT-26-051", "ASME B31.3", "MT", "Boru kəməri", "Fit", None),
    ("29.06.2026", "KF-MT-26-050", "EEMUA 158", "MT", "Konstruktiv tikiş", "Fit", None),
    ("12.06.2026", "KF-UT-26-010", "EEMUA 158", "UT", "Konstruktiv tikişlər", "Fit", None),
    ("17.06.2026", "KF-UT-26-011", "ASME B31.3", "UT", "Boru kəməri", "Fit", None),
    ("17.06.2026", "KF-UT-26-012", "AWS D1.1", "UT", "Lövhə / Plitə", "Fit", None),
    ("19.06.2026", "KF-UT-26-013", "AWS D1.1", "UT", "Konstruktiv tikiş", "Fit", None),
    ("22.06.2026", "KF-UT-26-014", "AWS D1.1", "UT", "Konstruktiv tikiş", "Fit", None),
    ("22.06.2026", "KF-UT-26-015", "EEMUA 158", "UT", "Konstruktiv tikişlər", "Fit", None),
    ("23.06.2026", "KF-UT-26-016", "ASME B31.3", "UT", "Tikiş", "Fit", None),
    ("29.06.2026", "KF-UT-26-017", "EEMUA 158", "UT", "Konstruktiv tikişlər", "Fit", None),
]


def _khf_jun():
    rows = []
    for i, (d, no, std, method, item, result, tag) in enumerate(_KHF_JUN, 1):
        day, month, year = (int(x) for x in d.split("."))
        rows.append(_row(no, date=(year, month, day), standard=std, method=method,
                         item=item, result=result, seq=str(i),
                         tag=tag if tag is not None else f" ({2200 + i})",
                         sort_key=(i, 0)))
    return _report(*rows)


#: The live presentation block (config/settings.yaml, 2026-09-24) minus E1–E3.
_LIVE = {"split_ranges_on_item": True, "pulled_parent_style": "hidden",
         "row_order": "method_volume", "range_tail_allow": ["T"]}


def test_khf_jun_2026_today_nothing_merges():
    assert len(_draw(_khf_jun(), **_LIVE)) == 23


def test_khf_jun_2026_expected_table():
    main = _draw(_khf_jun(), **_LIVE, **_E_ALL)
    assert _cells(main) == [
        ("KF-MT-26-(039-051)", "09–29.06.2026",
         "AWS D1.1, EEMUA 158, ASME B31.3", "Konstruktiv tikiş", "Fit"),
        ("KF-MT-26-054 (2334)", "22.06.2026", "ASME B31.3", "Boru kəməri", "Fit"),
        ("KF-UT-26-(010-017)", "12–29.06.2026",
         "EEMUA 158, ASME B31.3, AWS D1.1", "Konstruktiv tikişlər", "Fit"),
        ("KF-HrT-26-005 (2152)", "01.06.2026", "ASME B31.3", "Boru kəməri", "Info"),
    ]
    assert [d.seq for d in main] == ["1", "2", "3", "4"]
    assert range_verdict_notes(_khf_jun(), _Settings(
        range_mode="by_number", **_LIVE, **_E_ALL)) == []


# --- range_item_blank_methods ------------------------------------------------

_PMI = {"range_item": "dominant", "range_item_blank_methods": ["PMI"]}


def _pmi(*items, method="PMI"):
    return _report(*(_row(f"NOV-PMI-25-{i:03d}", method=method, item=item)
                     for i, item in enumerate(items, 1)))


def test_blank_methods_default_is_off():
    assert display_options(_Settings())["item_blank_methods"] == ()
    report = _pmi("S-1", "S-2", "S-2")
    assert _draw(report, range_item="dominant") == _draw(
        report, range_item="dominant", range_item_blank_methods=[])


def test_blank_methods_multi_item_range_prints_dash():
    (line,) = _draw(_pmi("S-1", "S-2", "s-2 "), **_PMI)
    assert (line.report_label, line.item_detail) == ("NOV-PMI-25-(001-003)", "—")


def test_blank_methods_one_item_range_keeps_its_item():
    # Spellings the translator reads as one, and a blank, are one item.
    (line,) = _draw(_pmi("S-1", " s-1", ""), **_PMI)
    assert line.item_detail == "S-1"


def test_blank_methods_single_number_keeps_its_item():
    report = _report(_row("NOV-PMI-25-001", method="PMI", item="S-1"),
                     _row("NOV-PMI-25-003", method="PMI", item="S-3"))
    assert [d.item_detail for d in _draw(report, **_PMI)] == ["S-1", "S-3"]


def test_blank_methods_other_method_keeps_dominant():
    (line,) = _draw(_pmi("A", "B", "B", method="MT"), **_PMI)
    assert line.item_detail == "B"


def test_blank_methods_match_any_case_and_need_dominant():
    assert _draw(_pmi("S-1", "S-2"), range_item="dominant",
                 range_item_blank_methods=[" pmi "])[0].item_detail == "—"
    # Under split the key is not read: the items break the range as before.
    split = _draw(_pmi("S-1", "S-2"), range_item_blank_methods=["PMI"],
                  split_ranges_on_item=True)
    assert [d.item_detail for d in split] == ["S-1", "S-2"]


def test_blank_methods_sidecar_unchanged():
    report = _pmi("S-1", "S-2")
    off = build_report_json(report, _Settings(range_mode="by_number"), _Translator())
    on = build_report_json(report, _Settings(range_mode="by_number", **_PMI),
                           _Translator())
    assert json.dumps(off, ensure_ascii=False) == json.dumps(on, ensure_ascii=False)


# --- E2 spelling variants ----------------------------------------------------

def test_e2_spelling_variants_print_once_first_seen():
    report = _report(
        _row("KF-MT-25-075", standard="AWS D1.1"),
        _row("KF-MT-25-076", standard="ISO-23278"),
        _row("KF-MT-25-077", standard="ISO 23278"),
        _row("KF-MT-25-078", standard="iso_23278"),
        _row("KF-MT-25-079", standard="aws  d1.1"),
    )
    (line,) = _draw(report, range_merge_standards=True)
    assert line.standard == "AWS D1.1, ISO-23278"


def test_e2_order_is_number_order_not_date():
    report = _report(
        _row("KF-MT-25-002", date=(2026, 6, 1), standard="ISO 23278"),
        _row("KF-MT-25-001", date=(2026, 6, 9), standard="ISO-23278"),
        _row("KF-MT-25-003", date=(2026, 6, 2), standard="EEMUA 158"),
    )
    (line,) = _draw(report, range_merge_standards=True)
    assert line.standard == "ISO-23278, EEMUA 158"
