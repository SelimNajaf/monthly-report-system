"""Characterization tests for result roll-up and sequence numbering."""

import datetime as dt
import unicodedata

from monthly_report.document_aggregator import (ReportRow, _aggregate_result,
                                                _assign_sequence_numbers,
                                                _fill_missing_standards)

# Built from code points, not typed: an editor round-trip could normalise a
# literal into the very spelling these cases exist to tell apart.
_IMTINA = "İmtina"                                   # composed İmtina
_IMTINA_NFD = unicodedata.normalize("NFD", _IMTINA)       # "I" + U+0307
_YARASIZ = "yarasız"                                 # yarasız (dotless ı)


def _row(report_no, rank, series, date, standard="STD"):
    return ReportRow(
        date=date, date_str=date.strftime("%d.%m.%Y"), report_no=report_no,
        series_key=series, retest_rank=rank, client="C", document_name=report_no,
        standard=standard, item_detail="Pipe", result="Fit",
        source_order=(date, report_no), match_key=(series,),
    )


def test_aggregate_result_fit_by_default():
    assert _aggregate_result([]) == "Fit"
    assert _aggregate_result([{"result": "Accept"}]) == "Fit"


def test_aggregate_result_any_reject_dominates():
    assert _aggregate_result([{"result": "Accept"}, {"result": "REJECTED"}]) == "Unfit"
    assert _aggregate_result([{"result": "imtina"}]) == "Unfit"
    assert _aggregate_result([{"result": _YARASIZ}]) == "Unfit"
    assert _aggregate_result([{"result": "YARASIZ"}]) == "Unfit"
    assert _aggregate_result([{"result": "NOK"}]) == "Unfit"


def test_aggregate_result_dotted_capital_i_rejects():
    """Dotted İmtina must reject in both its spellings (see text_norm.fold).

    Regression: plain casefold() left a combining dot on the İ, so this rolled
    up to "Fit" and a rejected weld reported as Yararlı.
    """
    assert _IMTINA != _IMTINA_NFD                 # guards the fixture
    assert _aggregate_result([{"result": _IMTINA}]) == "Unfit"
    assert _aggregate_result([{"result": _IMTINA_NFD}]) == "Unfit"
    assert _aggregate_result([{"result": f"Nəticə: {_IMTINA}"}]) == "Unfit"
    # Same rule through the whole-document table fallback.
    assert _aggregate_result([], [[["Weld", "Nəticə"],
                                   ["W1", _IMTINA]]]) == "Unfit"


def test_aggregate_result_table_fallback_ignores_header_cell():
    # No welds parsed: scan cells, but the "Accept/Reject" header is not a verdict.
    tables = [[["Weld", "Accept/Reject"], ["W1", "Reject"]]]
    assert _aggregate_result([], tables) == "Unfit"
    tables_ok = [[["Weld", "Accept/Reject"], ["W1", "Accepted"]]]
    assert _aggregate_result([], tables_ok) == "Fit"


def test_assign_sequence_numbers_parent_child():
    d = dt.date(2026, 6, 1)
    parent = _row("U-UT-26-005", 0, "U-UT-26-005", d)
    retest = _row("U-UT-26-005R1", 1, "U-UT-26-005", d + dt.timedelta(days=3))
    other = _row("U-UT-26-006", 0, "U-UT-26-006", d + dt.timedelta(days=1))
    records = [retest, other, parent]
    matched = _assign_sequence_numbers(records)
    assert matched == 1
    assert parent.seq == "1" and retest.seq == "1a" and other.seq == "2"
    assert not retest.is_orphan_retest


def test_assign_sequence_numbers_orphan_retest():
    d = dt.date(2026, 6, 10)
    orphan = _row("U-UT-26-099R1", 1, "U-UT-26-099", d)
    records = [orphan]
    matched = _assign_sequence_numbers(records)
    assert matched == 0
    assert orphan.is_orphan_retest and orphan.seq == "1"


def test_fill_missing_standards_borrows_sibling_never_injects_default():
    d = dt.date(2026, 6, 1)
    a = _row("A-MT-26-001", 0, "A-MT-26-001", d, standard="AWS D1.1")
    b = _row("A-MT-26-002", 0, "A-MT-26-002", d, standard="")
    _fill_missing_standards([a, b])
    assert b.standard == "AWS D1.1"          # borrows the batch's most common
    # Whole batch blank: nothing to borrow -> "" is PRESERVED (no method default
    # injected). A PMI report with no source standard must stay blank.
    c = _row("A-PMI-26-003", 0, "A-PMI-26-003", d, standard="")
    _fill_missing_standards([c])
    assert c.standard == ""


# --------------------------------------------------------------------------- #
# İnspektor assignment — the configured matrix overrides the scraped name.
# Source-inspected: the override is four lines inside build_monthly_report, and
# reaching it for real needs a directory of parsed .docx documents.
# --------------------------------------------------------------------------- #
def _aggregator_source() -> str:
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    text = (root / "src" / "monthly_report" / "document_aggregator.py").read_text(
        encoding="utf-8")
    return text.split("def build_monthly_report(")[1].split("\ndef ")[0]


def test_the_matrix_overrides_the_scraped_inspector():
    """resolve_inspector's answer must be assigned AFTER _pick_signatures reads
    the documents — otherwise the scrape wins and the matrix is decoration."""
    body = _aggregator_source()
    picked = body.index("_pick_signatures(signatures_seen)")
    assigned = body.index("resolve_inspector(")
    written = body.index('signatures["inspector"] = assigned')

    assert picked < assigned < written, (
        "the configured inspector must be applied after the documents are scraped")


def test_the_inspector_date_is_the_target_month_not_a_row_date():
    """A date-routed client (SDLN) must be decided by WHICH MONTH the report is for.

    ``month_date`` is ``records[0].date``, and the records list has cross-month retest
    parents appended to it — rows dated to an EARLIER month. Routing on one of those
    would let a single borrowed row drag a whole report's signature back across the
    boundary to the previous inspector.
    """
    body = _aggregator_source()
    call = body[body.index("resolve_inspector("):]
    call = call[:call.index(")\n") + 1]

    assert "settings.target_month" in call, (
        f"expected the target month to decide the routing, got: {call}")
    assert "month_date" not in call, (
        "month_date is records[0].date — contaminated by cross-month retest parents")
