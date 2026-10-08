"""Pin ``presentation.range_mode: by_number`` and its companion keys.

The director's shorter table: one line per report NUMBER (a retest chain is
one number), consecutive numbers ranged, method blocks by volume, zebra per
block, cross-month parents hidden. Decisions D1–D8 (2026-09-24):

* D1 a range breaks on a missing number, prefix, label tail, zero padding,
  standard, method, or İtem with split_ranges_on_item — never on a verdict;
* D2 Tarix is min–max over every member, "01–15.04.2026";
* D3 a single number prints its chain's LAST verdict; a range prints Yararlı
  when any number in it ended Yararlı, else the shared verdict;
* D4 no second table; D5 a hidden parent is off the page, its sidecar is
  byte-identical to ``marked``; D6 blocks by visible volume, numbers inside;
* D7 zebra per method block, no amber; D8 every Yarasız number inside a
  Yararlı range is named on stdout and in ``output/range_verdict_<date>.md``.

Every key absent (or at its default) must be exactly the drawing that
predates them — the (a) tests below.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from monthly_report import document_aggregator as A  # noqa: E402
from monthly_report.document_aggregator import (  # noqa: E402
    MonthlyReport, ReportRow, display_options, format_range_verdict,
    range_mode, range_verdict_notes, row_order, row_style, split_display_rows)
from monthly_report.json_exporter import build_report_json  # noqa: E402
from monthly_report.report_identity import retest_rank, strip_retest  # noqa: E402


class _Translator:
    def term(self, text):
        return text


class _Settings:
    def __init__(self, date_format="%d.%m.%Y", **presentation):
        self.raw = {"clients": {}, "presentation": presentation}
        self.date_format = date_format


def _row(report_no, *, date=(2026, 4, 10), result="Fit", method="RT",
         label="", standard="ASME B31.3", item="Pipe", pulled=False, seq="",
         sort_key=(0, 0)):
    d = _dt.date(*date)
    return ReportRow(
        date=d, date_str=d.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=strip_retest(report_no), retest_rank=retest_rank(report_no),
        client="UBOC", document_name=f"{report_no}{label}", standard=standard,
        item_detail=item, result=result, method=method, seq=seq,
        sort_key=sort_key, is_pulled_parent=pulled)


def _report(*rows):
    return MonthlyReport(month="2026-04", document_number="MR-UBOC-26-04",
                         title="T", method="RT", client_code="UBOC",
                         client_name="UBOC", rows=list(rows))


def _by_number(report, **kw):
    main, second = split_display_rows(report, range_mode="by_number", **kw)
    assert second == []                     # D4: never a second table
    return main


def _lines(main):
    return [(d.seq, d.date_str, d.report_label, d.result) for d in main]


def _uboc():
    """A cut of UBOC APR 2026: pulled parents, chains, a mixed range, DP-003."""
    return _report(
        _row("U-MT-26-001", date=(2026, 3, 31), method="MT", pulled=True,
             seq="1", sort_key=(1, 0)),
        _row("U-MT-26-001R1", date=(2026, 4, 1), method="MT", seq="1a",
             sort_key=(1, 1)),
        _row("U-MT-26-002", date=(2026, 4, 14), method="MT", seq="2",
             sort_key=(2, 0)),
        _row("U-RT-26-012", date=(2026, 3, 31), result="Unfit", pulled=True,
             seq="3", sort_key=(3, 0)),
        _row("U-RT-26-012R1", date=(2026, 4, 1), seq="3a", sort_key=(3, 1)),
        _row("U-RT-26-013", date=(2026, 4, 14), result="Unfit", seq="4",
             sort_key=(4, 0)),
        _row("U-RT-26-013RW1", date=(2026, 4, 15), seq="4a", sort_key=(4, 1)),
        _row("U-RT-26-014", date=(2026, 4, 14), seq="5", sort_key=(5, 0)),
        _row("U-DP-26-003", date=(2026, 4, 21), result="Unfit", method="DP",
             standard="ASME VIII", seq="6", sort_key=(6, 0)),
        _row("U-DP-26-004", date=(2026, 4, 21), method="DP",
             standard="ASME VIII", seq="7", sort_key=(7, 0)),
    )


# --------------------------------------------------------------------------- #
# (a) defaults: nothing changes while the new keys are absent or at default
# --------------------------------------------------------------------------- #
_OLD_COMBOS = [
    {},
    {"rollup_retests": True},
    {"rollup_retests": True, "unfit_placement": "section"},
    {"rollup_retests": True, "split_ranges_on_item": True,
     "pulled_parent_style": "marked", "unfit_placement": "section"},
    {"collapse_ranges": False, "rollup_retests": True,
     "pulled_parent_style": "marked"},
]
_NEW_DEFAULTS = {"range_mode": "strict", "row_order": "method_date",
                 "row_style": "retest_highlight"}


def test_readers_default_and_fall_back():
    class _Bare:
        raw = {}

    for s in (_Bare(), _Settings(), _Settings(range_mode="bogus",
                                              row_order="x", row_style="y")):
        assert (range_mode(s), row_order(s), row_style(s)) == (
            "strict", "method_date", "retest_highlight")
    s = _Settings(range_mode=" By_Number ", row_order="METHOD_VOLUME",
                  row_style="method_zebra")
    assert (range_mode(s), row_order(s), row_style(s)) == (
        "by_number", "method_volume", "method_zebra")
    assert A.pulled_parent_style(_Settings(pulled_parent_style="hidden")) == "hidden"


@pytest.mark.parametrize("old", _OLD_COMBOS)
def test_defaults_draw_exactly_what_the_old_call_drew(old):
    report = _uboc()
    legacy = split_display_rows(
        report,
        enabled=old.get("collapse_ranges", True),
        rollup=old.get("rollup_retests", False),
        placement=old.get("unfit_placement", "inline"),
        split_on_item=old.get("split_ranges_on_item", False),
        mark_pulled=old.get("pulled_parent_style") == "marked")
    absent = split_display_rows(report, **display_options(_Settings(**old)))
    explicit = split_display_rows(
        report, **display_options(_Settings(**old, **_NEW_DEFAULTS)))
    assert absent == legacy == explicit
    assert range_verdict_notes(report, _Settings(**old)) == []


@pytest.mark.parametrize("old", _OLD_COMBOS)
def test_defaults_keep_the_sidecar_bytes(old):
    report = _uboc()
    before = json.dumps(build_report_json(report, _Settings(**old), _Translator()),
                        ensure_ascii=False, indent=2)
    after = json.dumps(build_report_json(report, _Settings(**old, **_NEW_DEFAULTS),
                                         _Translator()), ensure_ascii=False, indent=2)
    assert before == after


def _table(display, mark=False, zebra=None):
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    from monthly_report import pdf_renderer

    fonts = _ROOT / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("DejaVu", str(fonts / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", str(fonts / "DejaVuSans-Bold.ttf")))
    args = (_report(), _Translator(), pdf_renderer._styles(), display, mark)
    if zebra is None:
        return pdf_renderer._build_table(*args)
    return pdf_renderer._build_table(*args, zebra)


def _style_cmds(table):
    """Every style command the table holds, as comparable text."""
    cells = [[(c.fontname, c.valign, c.leftPadding, c.topPadding, str(c.color))
              for c in row] for row in table._cellStyles]
    return ([tuple(map(str, c)) for c in table._bkgrndcmds],
            [tuple(map(str, c)) for c in table._linecmds], cells)


def test_default_table_style_is_unchanged():
    from monthly_report import pdf_renderer

    main, _ = split_display_rows(_uboc())          # retest children, amber
    old = _table(main)
    new = _table(main, zebra=False)
    assert [[p.text for p in row] for row in old._cellvalues] == \
           [[p.text for p in row] for row in new._cellvalues]
    assert _style_cmds(old) == _style_cmds(new)
    amber = [c for c in old._bkgrndcmds if c[3] == pdf_renderer._RETEST_BG]
    assert [c[1][1] for c in amber] == [
        i for i, d in enumerate(main, 1) if d.is_retest_child]


# --------------------------------------------------------------------------- #
# (b) D1 — what breaks a range, and what does not
# --------------------------------------------------------------------------- #
def test_a_verdict_change_does_not_break_the_range():
    main = _by_number(_report(_row("U-RT-26-001"),
                              _row("U-RT-26-002", result="Unfit"),
                              _row("U-RT-26-003")))
    assert [d.report_label for d in main] == ["U-RT-26-(001-003)"]


@pytest.mark.parametrize("second, why", [
    (_row("U-RT-26-003"), "missing number"),
    (_row("U-RT-26-002", standard="ISO 17636"), "standard"),
    (_row("U-RT-26-002", label=" (Dashgil 2)"), "label"),
    (_row("U-RT-26-02"), "zero padding"),
    (_row("U-RT-25-002"), "prefix"),
    (_row("U-RT-26-002", method="MT"), "method"),
])
def test_each_rule_breaks_the_range(second, why):
    main = _by_number(_report(_row("U-RT-26-001"), second))
    assert len(main) == 2, why


def test_item_breaks_only_with_split_on_item():
    rows = (_row("U-RT-26-001"), _row("U-RT-26-002", item="Plate"))
    merged = _by_number(_report(*rows))
    assert [(d.report_label, d.item_detail) for d in merged] == [
        ("U-RT-26-(001-002)", "")]                 # mixed İtem prints blank
    assert len(_by_number(_report(*rows), split_on_item=True)) == 2


def test_retest_suffixes_join_their_number():
    main = _by_number(_report(
        _row("U-RT-26-014", result="Unfit"),
        _row("U-RT-26-014R1", result="Unfit", date=(2026, 4, 2)),
        _row("U-RT-26-014RW", result="Unfit", date=(2026, 4, 14)),
        _row("U-RT-26-014RW1", date=(2026, 4, 15)),
        _row("U-RT-26-015")))
    assert [(d.report_label, d.span) for d in main] == [("U-RT-26-(014-015)", 5)]


def test_a_non_digit_number_never_ranges_and_is_printed_as_written():
    main = _by_number(_report(_row("U-UT-25-002"), _row("U-UT-25-003rej"),
                              _row("U-UT-25-004rej"), _row("U-UT-25-003"),
                              _row("U-UT-25-004")))
    # Tailed numbers sort after the plain ones, so (002-004) stays one line.
    assert [d.report_label for d in main] == [
        "U-UT-25-(002-004)", "U-UT-25-003rej", "U-UT-25-004rej"]


def test_a_unit_whose_members_disagree_never_ranges():
    main = _by_number(_report(
        _row("U-RT-26-001"),
        _row("U-RT-26-002"), _row("U-RT-26-002R1", item="Plate"),
        _row("U-RT-26-003")))
    assert [d.report_label for d in main] == [
        "U-RT-26-001", "U-RT-26-002", "U-RT-26-003"]


def test_the_label_comes_from_the_lowest_rank_member():
    main = _by_number(_report(
        _row("U-RT-26-010", label=" (Dashgil 2)", result="Unfit"),
        _row("U-RT-26-010R1"),
        _row("U-RT-26-011", label=" (Dashgil 2)")))
    assert [d.report_label for d in main] == ["U-RT-26-(010-011) (Dashgil 2)"]


# --------------------------------------------------------------------------- #
# (c) D2 — dates
# --------------------------------------------------------------------------- #
def test_dates_span_min_to_max_in_the_compact_form():
    main = _by_number(_report(_row("U-RT-26-001", date=(2026, 4, 15)),
                              _row("U-RT-26-001R1", date=(2026, 4, 1)),
                              _row("U-RT-26-002", date=(2026, 4, 9))))
    assert main[0].date_str == "01–15.04.2026"


def test_one_day_prints_one_date():
    main = _by_number(_report(_row("U-RT-26-001"), _row("U-RT-26-002")))
    assert main[0].date_str == "10.04.2026"


def test_a_year_boundary_prints_both_years():
    main = _by_number(_report(_row("U-RT-25-001", date=(2025, 12, 28)),
                              _row("U-RT-25-001R1", date=(2026, 1, 5))))
    assert main[0].date_str == "28.12.2025–05.01.2026"


def test_a_single_number_chain_spans_its_dates():
    main = _by_number(_report(_row("U-MT-26-005R1", date=(2026, 4, 2)),
                              _row("U-MT-26-005RW", date=(2026, 4, 14)),
                              _row("U-MT-26-005RW1", date=(2026, 4, 15))))
    assert _lines(main) == [("1", "02–15.04.2026", "U-MT-26-005", "Fit")]


def test_another_date_format_joins_the_formatted_dates():
    rows = [_row("U-RT-26-001", date=(2026, 4, 1)),
            _row("U-RT-26-002", date=(2026, 4, 3))]
    for r in rows:
        r.date_str = r.date.strftime("%Y-%m-%d")
    main = _by_number(_report(*rows), date_format="%Y-%m-%d")
    assert main[0].date_str == "2026-04-01–2026-04-03"


# --------------------------------------------------------------------------- #
# (d) D3 — verdicts
# --------------------------------------------------------------------------- #
def test_a_single_number_prints_its_chains_last_verdict():
    fixed = _by_number(_report(_row("U-RT-26-014", result="Unfit"),
                               _row("U-RT-26-014R1", date=(2026, 4, 11))))
    open_ = _by_number(_report(_row("U-RT-26-014"),
                               _row("U-RT-26-014R1", result="Unfit",
                                    date=(2026, 4, 11))))
    assert [d.result for d in fixed + open_] == ["Fit", "Unfit"]


def test_a_range_is_fit_when_any_number_ended_fit():
    main = _by_number(_report(_row("U-DP-26-003", result="Unfit", method="DP"),
                              _row("U-DP-26-004", method="DP")))
    assert _lines(main) == [("1", "10.04.2026", "U-DP-26-(003-004)", "Fit")]


def test_a_range_with_no_fit_number_prints_unfit():
    main = _by_number(_report(_row("U-RT-26-001", result="Unfit"),
                              _row("U-RT-26-002", result="Unfit")))
    assert [d.result for d in main] == ["Unfit"]


def test_an_informational_range_stays_info():
    main = _by_number(_report(_row("U-UTM-26-001", result="Info", method="UTM"),
                              _row("U-UTM-26-002", result="Info", method="UTM")))
    assert [d.result for d in main] == ["Info"]


def test_by_number_ignores_rollup_and_the_unfit_section():
    report = _report(_row("U-RT-26-001", result="Unfit"), _row("U-RT-26-002"))
    for rollup in (False, True):
        main, second = split_display_rows(report, range_mode="by_number",
                                          rollup=rollup, placement="section")
        assert second == [] and len(main) == 1


def test_collapse_off_wins_over_by_number():
    s = _Settings(collapse_ranges=False, range_mode="by_number")
    opts = display_options(s)
    assert opts["range_mode"] == "strict"
    main, _ = split_display_rows(_uboc(), **opts)
    assert [d.seq for d in main] == [r.seq for r in _uboc().rows]
    assert range_verdict_notes(_uboc(), s) == []


# --------------------------------------------------------------------------- #
# (e) D5 — hidden parents
# --------------------------------------------------------------------------- #
def test_hidden_drops_the_parent_its_date_and_verdict():
    main = _by_number(_report(
        _row("U-RT-26-012", date=(2026, 3, 31), result="Unfit", pulled=True),
        _row("U-RT-26-012R1", date=(2026, 4, 1))), hide_pulled=True)
    assert [(d.date_str, d.report_label, d.result, d.span, d.pulled_from)
            for d in main] == [("01.04.2026", "U-RT-26-012R1", "Fit", 1, "")]


def test_marked_under_by_number_is_a_lone_starred_line():
    main = _by_number(_report(
        _row("U-RT-26-011"),
        _row("U-RT-26-012", date=(2026, 3, 31), result="Unfit", pulled=True),
        _row("U-RT-26-012R1", date=(2026, 4, 1)),
        _row("U-RT-26-013")), mark_pulled=True)
    assert [(d.report_label, d.date_str, d.pulled_from) for d in main] == [
        ("U-RT-26-011", "10.04.2026", ""),
        ("U-RT-26-012", "31.03–01.04.2026", "2026-03"),
        ("U-RT-26-013", "10.04.2026", "")]


def test_hidden_reads_as_marked_outside_by_number():
    for extra in ({}, {"range_mode": "by_number", "collapse_ranges": False}):
        opts = display_options(_Settings(pulled_parent_style="hidden", **extra))
        assert (opts["mark_pulled"], opts["hide_pulled"]) == (True, False)
    opts = display_options(_Settings(pulled_parent_style="hidden",
                                     range_mode="by_number"))
    assert (opts["mark_pulled"], opts["hide_pulled"]) == (False, True)


def test_hidden_sidecar_is_byte_identical_to_marked():
    report = _uboc()

    def dump(style):
        return json.dumps(build_report_json(
            report, _Settings(pulled_parent_style=style, range_mode="by_number"),
            _Translator()), ensure_ascii=False, indent=2).encode("utf-8")

    assert dump("hidden") == dump("marked")
    assert b'"pulled_from": "2026-03"' in dump("hidden")


def test_by_number_never_mutates_report_rows():
    report = _uboc()
    before = [(r.seq, r.result, r.date_str, r.document_name) for r in report.rows]
    _by_number(report, hide_pulled=True, row_order="method_volume")
    range_verdict_notes(report, _Settings(range_mode="by_number",
                                          pulled_parent_style="hidden"))
    assert [(r.seq, r.result, r.date_str, r.document_name)
            for r in report.rows] == before


# --------------------------------------------------------------------------- #
# (f) D6 — order
# --------------------------------------------------------------------------- #
def test_volume_order_counts_visible_rows_and_sorts_numbers_inside():
    main = _by_number(_uboc(), hide_pulled=True, row_order="method_volume")
    # Visible rows: RT 4 (012 hidden), MT 2 (001 hidden), DP 2 — DP before MT by name.
    assert [(d.seq, d.method, d.report_label) for d in main] == [
        ("1", "RT", "U-RT-26-(012-014)"),
        ("2", "DP", "U-DP-26-(003-004)"),
        ("3", "MT", "U-MT-26-(001-002)"),
    ]


def test_method_date_keeps_method_name_order():
    main = _by_number(_uboc(), hide_pulled=True)
    assert [d.method for d in main] == ["DP", "MT", "RT"]


def test_numbers_sort_by_number_not_date():
    main = _by_number(_report(_row("U-RT-26-017", date=(2026, 4, 1)),
                              _row("U-RT-26-010", label=" (X)", date=(2026, 4, 21))))
    assert [d.report_label for d in main] == ["U-RT-26-010 (X)", "U-RT-26-017"]


def test_sira_is_one_to_n_without_letters():
    main = _by_number(_uboc())
    assert [d.seq for d in main] == [str(i) for i in range(1, len(main) + 1)]
    assert not any(d.is_retest_child for d in main)


def test_strict_volume_order_moves_parent_and_child_together():
    main, _ = split_display_rows(_uboc(), row_order="method_volume")
    assert [d.method for d in main][:1] == ["RT"]
    labels = [d.report_label for d in main]
    assert labels.index("U-RT-26-012R1") == labels.index("U-RT-26-012") + 1


# --------------------------------------------------------------------------- #
# D7 — zebra
# --------------------------------------------------------------------------- #
def test_zebra_shades_every_other_block_and_drops_amber():
    from monthly_report import pdf_renderer

    main, _ = split_display_rows(_uboc())          # MT..., RT..., DP... (by seq)
    table = _table(main, zebra=True)
    body = [c for c in table._bkgrndcmds if c[1][1] > 0]
    blocks, prev = [], None
    for d in main:
        blocks.append((blocks[-1] + (d.method != prev)) if blocks else 0)
        prev = d.method
    assert sorted(c[1][1] for c in body) == [
        i for i, b in enumerate(blocks, 1) if b % 2]
    assert {c[3] for c in body} == {pdf_renderer._ZEBRA_BG}
    header = [c for c in table._bkgrndcmds if c[1][1] == 0]
    assert [c[3] for c in header] == [pdf_renderer._HEADER_BG]


# --------------------------------------------------------------------------- #
# (g) D8 — stdout
# --------------------------------------------------------------------------- #
def test_notes_name_each_unfit_number_inside_a_fit_range():
    s = _Settings(range_mode="by_number", pulled_parent_style="hidden",
                  row_order="method_volume")
    assert range_verdict_notes(_uboc(), s) == [
        ("U-DP-26-003", "U-DP-26-(003-004)")]


def test_notes_name_the_chains_last_report():
    report = _report(_row("U-RT-26-001"),
                     _row("U-RT-26-002"),
                     _row("U-RT-26-002R1", result="Unfit", date=(2026, 4, 12)))
    assert range_verdict_notes(report, _Settings(range_mode="by_number")) == [
        ("U-RT-26-002R1", "U-RT-26-(001-002)")]


def test_no_note_for_a_single_number_or_an_all_unfit_range():
    report = _report(_row("U-RT-26-001", result="Unfit"),
                     _row("U-RT-26-002", result="Unfit"),
                     _row("U-MT-26-009", result="Unfit", method="MT"))
    assert range_verdict_notes(report, _Settings(range_mode="by_number")) == []


VERDICT_LINE = format_range_verdict("UBOC APR 2026", "U-DP-26-003",
                                    "U-DP-26-(003-004)")
SUMMARY_LINE = ("  Range verdict: 1 Yarasız report(s) inside a Yararlı range "
                "audited -> range_verdict_2026-09-24.md")


def test_the_line_reads_as_approved():
    assert VERDICT_LINE == ('    [range-verdict] UBOC APR 2026: U-DP-26-003 Yarasız '
                            '→ "Yararlı" diapazonda çap olundu: U-DP-26-(003-004)')


@pytest.mark.parametrize("line", [VERDICT_LINE, SUMMARY_LINE])
def test_the_gui_parsers_ignore_the_new_lines(line):
    from monthly_report.gui.services import quarantine_reasons_service
    from monthly_report.gui.services.progress import PipelineProgressParser

    assert PipelineProgressParser().feed(line) is None
    assert quarantine_reasons_service.parse_line(line) is None
    # console_view colour rules: no danger / warning / success / group accent.
    assert not re.search(r"^\[FATAL\]|Traceback|Error|error:", line, re.I)
    assert not re.search(r"\[quarantine\]|Quarantine Warning|quarantined|failed",
                         line, re.I)
    assert not re.search(r"-> .*\.pdf$", line)
    assert not re.search(r"^\[.+\]\s", line)


# --------------------------------------------------------------------------- #
# range_verdict_<date>.md
# --------------------------------------------------------------------------- #
class _MainSettings:
    def __init__(self, out):
        self.output_dir = str(out)


def test_the_audit_lists_every_note(tmp_path):
    import main

    notes = [("UBOC APR 2026", "U-DP-26-003", "U-DP-26-(003-004)"),
             ("UBOC APR 2026", "U-RT-26-002R1", "U-RT-26-(001-002)")]
    path = main._write_range_verdict_audit(_MainSettings(tmp_path / "out"), notes)
    assert path.name == f"range_verdict_{_dt.date.today().isoformat()}.md"
    text = path.read_text(encoding="utf-8")
    assert "**2 hesabatın**" in text
    assert "| 1 | UBOC APR 2026 | `U-DP-26-003` | `U-DP-26-(003-004)` |" in text
    assert "| 2 | UBOC APR 2026 | `U-RT-26-002R1` | `U-RT-26-(001-002)` |" in text


def test_no_audit_file_when_nothing_to_list(tmp_path):
    import main

    out = tmp_path / "out"
    assert main._write_range_verdict_audit(_MainSettings(out), []) is None
    assert not out.exists()


def test_the_audit_never_reaches_the_uploaders_sidecar_sweep(tmp_path):
    import main
    import uploader                      # imported for one pure helper; never run

    out = tmp_path / "out"
    (out / "UBOC").mkdir(parents=True)
    sidecar = out / "UBOC" / "compiled_monthly_report_UBOC_APR_2026.json"
    sidecar.write_text("{}", encoding="utf-8")
    audit = main._write_range_verdict_audit(
        _MainSettings(out), [("UBOC APR 2026", "U-DP-26-003", "U-DP-26-(003-004)")])
    assert audit.is_file()
    assert uploader._report_sidecars(out) == [sidecar]


def test_main_prints_and_collects_through_one_helper(capsys):
    import main

    sink: list = []
    main._note_range_verdicts(
        _uboc(), _Settings(range_mode="by_number", pulled_parent_style="hidden"),
        "UBOC APR 2026", sink)
    assert sink == [("UBOC APR 2026", "U-DP-26-003", "U-DP-26-(003-004)")]
    assert capsys.readouterr().out.strip() == VERDICT_LINE.strip()
    main._note_range_verdicts(_uboc(), _Settings(), "UBOC APR 2026", sink)
    assert len(sink) == 1 and capsys.readouterr().out == ""
