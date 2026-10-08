"""Pin ``presentation.range_absorb_tails`` (ADR-009 addendum, R2-B).

Under ``range_mode: by_number`` a number whose tail is listed (``"A"``) takes
its base number's slot: ``BS-RT-26-010A`` ranges as if it were ``010``, so
``001 … 010, 010A, 011 … 016`` prints as ONE line ``BS-RT-26-(001-016)``.
Default ``[]`` draws exactly what the key's absence draws. Only single
upper-case letters are honoured: ``rej``, ``test``, ``del`` and a lowercase
``a`` never join a range. The sidecar never sees the key — every report keeps
its own number (red line 2).
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, display_options, range_absorb_tails,
    range_verdict_notes, split_display_rows)
from monthly_report.json_exporter import build_report_json  # noqa: E402
from monthly_report.report_identity import retest_rank, strip_retest  # noqa: E402


class _Settings:
    def __init__(self, **presentation):
        self.raw = {"clients": {"BS": {"code": "BS", "voen": "1000000004"}},
                    "presentation": presentation}
        self.date_format = "%d.%m.%Y"


class _Translator:
    def term(self, text):
        return text


def _row(report_no, *, day=19, result="Fit", method="RT", item="Boru",
         standard="ASME B31.3"):
    d = _dt.date(2026, 5, day)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=strip_retest(report_no), retest_rank=retest_rank(report_no),
        client="BOS SHELF", document_name=report_no, standard=standard,
        item_detail=item, result=result, method=method)


def _report(*rows):
    return MonthlyReport(month="2026-05", document_number="MR-BS-26-05",
                         title="T", method="RT", client_code="BS",
                         client_name="BOS SHELF", rows=list(rows))


def _lines(report, **presentation):
    opts = display_options(_Settings(range_mode="by_number", **presentation))
    main, _ = split_display_rows(report, **opts)
    return main


def _labels(report, **presentation):
    return [d.report_label for d in _lines(report, **presentation)]


def _bs_may(**overrides):
    """The operator's BS_MAY_2026 shape: 001 … 010, 010A, 011 … 016."""
    nums = [f"BS-RT-26-{n:03d}" for n in range(1, 11)]
    nums += ["BS-RT-26-010A"] + [f"BS-RT-26-{n:03d}" for n in range(11, 17)]
    return _report(*[_row(n, day=2 + i, **overrides.get(n, {}))
                     for i, n in enumerate(nums)])


# --------------------------------------------------------------------------- #
# The reader


def test_reader_keeps_only_single_upper_case_letters():
    s = _Settings(range_absorb_tails=["A", "rej", "a", "AB", "", "B", "A", "1"])
    assert range_absorb_tails(s) == ("A", "B")


def test_reader_defaults_to_empty():
    assert range_absorb_tails(_Settings()) == ()
    assert range_absorb_tails(_Settings(range_absorb_tails="A")) == ()
    assert display_options(_Settings())["absorb_tails"] == ()


# --------------------------------------------------------------------------- #
# Default: byte-identical


def test_default_empty_list_draws_what_absence_draws():
    report = _bs_may()
    absent = _lines(report)
    empty = _lines(report, range_absorb_tails=[])
    assert absent == empty
    # ...and that is the old table: 010A stands on its own line.
    assert [d.report_label for d in absent] == [
        "BS-RT-26-(001-016)", "BS-RT-26-010A"]


# --------------------------------------------------------------------------- #
# Absorption


def test_010A_is_absorbed_into_the_range():
    report = _bs_may()
    lines = _lines(report, range_absorb_tails=["A"])
    assert [d.report_label for d in lines] == ["BS-RT-26-(001-016)"]
    assert lines[0].span == 17                       # every report is on the line
    assert lines[0].date_str == "02–18.05.2026"      # 010A's date is in the span


def test_010B_is_not_absorbed_when_only_A_is_listed():
    report = _report(_row("BS-RT-26-009"), _row("BS-RT-26-010"),
                     _row("BS-RT-26-010B"), _row("BS-RT-26-011"))
    assert _labels(report, range_absorb_tails=["A"]) == [
        "BS-RT-26-(009-011)", "BS-RT-26-010B"]


def test_lowercase_a_is_not_absorbed():
    report = _report(_row("BS-RT-26-009"), _row("BS-RT-26-010"),
                     _row("BS-RT-26-010a"), _row("BS-RT-26-011"))
    assert _labels(report, range_absorb_tails=["A"]) == [
        "BS-RT-26-(009-011)", "BS-RT-26-010a"]


def test_003rej_is_never_absorbed():
    report = _report(_row("U-UT-25-002"), _row("U-UT-25-003rej"),
                     _row("U-UT-25-004"))
    # "rej" is dropped by the reader, so listing it changes nothing.
    for absorb in (["A"], ["A", "rej"], ["rej"]):
        assert _labels(report, range_absorb_tails=absorb) == [
            "U-UT-25-002", "U-UT-25-004", "U-UT-25-003rej"]


def test_tail_allow_is_unchanged_and_wins_for_a_tail_listed_in_both():
    report = _report(_row("RT-KF-25-080T"), _row("RT-KF-25-081T"),
                     _row("RT-KF-25-081"))
    assert _labels(report, range_tail_allow=["T"]) == _labels(
        report, range_tail_allow=["T"], range_absorb_tails=["T"])


def test_base_number_missing_absorbed_number_fills_its_slot():
    # 010 is not in the document: 010A takes its slot, so 009 … 011 is ONE run
    # and the label still reads by number.
    report = _report(_row("BS-RT-26-009"), _row("BS-RT-26-010A"),
                     _row("BS-RT-26-011"))
    assert _labels(report) == ["BS-RT-26-009", "BS-RT-26-011", "BS-RT-26-010A"]
    assert _labels(report, range_absorb_tails=["A"]) == ["BS-RT-26-(009-011)"]


def test_absorbed_number_alone_keeps_its_own_name():
    report = _report(_row("BS-RT-26-010A"), _row("BS-RT-26-020"))
    assert _labels(report, range_absorb_tails=["A"]) == [
        "BS-RT-26-010A", "BS-RT-26-020"]


def test_absorbed_retest_chain_stays_one_unit():
    report = _report(_row("BS-RT-26-010"), _row("BS-RT-26-010A", result="Unfit"),
                     _row("BS-RT-26-010AR1", day=25), _row("BS-RT-26-011"))
    lines = _lines(report, range_absorb_tails=["A"])
    assert [d.report_label for d in lines] == ["BS-RT-26-(010-011)"]
    assert lines[0].span == 4


# --------------------------------------------------------------------------- #
# Verdict rule


def test_verdict_rule_counts_the_absorbed_number_like_any_other():
    unfit = {"BS-RT-26-010A": {"result": "Unfit"}}
    report = _bs_may(**unfit)
    s = _Settings(range_mode="by_number", range_absorb_tails=["A"])
    lines = _lines(report, range_absorb_tails=["A"])
    assert lines[0].result == "Fit"                  # any Fit number -> Fit
    assert range_verdict_notes(report, s) == [
        ("BS-RT-26-010A", "BS-RT-26-(001-016)")]
    # Off: 010A prints alone with its own verdict, no audit line.
    off = _Settings(range_mode="by_number")
    assert range_verdict_notes(report, off) == []


def test_all_unfit_range_stays_unfit():
    report = _report(_row("BS-RT-26-009", result="Unfit"),
                     _row("BS-RT-26-010", result="Unfit"),
                     _row("BS-RT-26-010A", result="Unfit"))
    lines = _lines(report, range_absorb_tails=["A"])
    assert [(d.report_label, d.result) for d in lines] == [
        ("BS-RT-26-(009-010)", "Unfit")]


def test_one_slot_run_draws_each_number_alone():
    # 010 + 010A and nothing next to them: no "(010-010)" label.
    report = _report(_row("BS-RT-26-010"), _row("BS-RT-26-010A"),
                     _row("BS-RT-26-020"))
    assert _labels(report, range_absorb_tails=["A"]) == [
        "BS-RT-26-010", "BS-RT-26-010A", "BS-RT-26-020"]


def test_strict_mode_ignores_the_key():
    report = _bs_may()
    strict_off = split_display_rows(report, **display_options(_Settings()))
    strict_on = split_display_rows(
        report, **display_options(_Settings(range_absorb_tails=["A"])))
    assert strict_off == strict_on


# --------------------------------------------------------------------------- #
# Sidecar


def test_sidecar_is_unchanged_and_keeps_every_number():
    report = _bs_may()
    off = build_report_json(report, _Settings(range_mode="by_number"), _Translator())
    on = build_report_json(report, _Settings(range_mode="by_number",
                                             range_absorb_tails=["A"]), _Translator())
    assert on == off
    assert "BS-RT-26-010A" in [r["report_no"] for r in on["items_table"]]
    assert len(on["items_table"]) == 17
    # The rows themselves are untouched by drawing the table.
    _lines(report, range_absorb_tails=["A"])
    assert [r.report_no for r in report.rows].count("BS-RT-26-010A") == 1
