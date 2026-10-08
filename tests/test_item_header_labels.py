"""Pin ``filtering.reject_item_header_labels`` (R3-D).

A results table whose header row reads ``Item | Qty | ...`` made
:func:`extractor.extract_item_global` take "Item" for the Item: label and the
next column header for its value. Measured in the compiled corpus: ``Qty``,
``S/N``, ``DetailNo``, ``Detail No``, ``Number of holes`` and the ``N/A``
placeholder as İtem. Default off = the old values; on = rejected, and the row
falls back to Description, then the weld items.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from monthly_report import extractor
from monthly_report.document_aggregator import reject_item_header_labels

LABELS = ["Qty", "S/N", "DetailNo", "Detail No", "Number of holes", "N/A"]


def _header_row_tables(label):
    """The leak shape: an "Item" column header followed by another header."""
    return [[["Item", label, "Weld No", "Result"],
             ["1", "2", "W1", "Accept"]]]


@pytest.mark.parametrize("label", LABELS)
def test_default_keeps_the_old_value(label):
    assert extractor.item_is_bad(label) is False
    assert extractor.extract_item_global(_header_row_tables(label)) == label


@pytest.mark.parametrize("label", LABELS)
def test_each_label_is_rejected_when_on(label):
    assert extractor.item_is_bad(label, header_labels=True) is True
    assert extractor.extract_item_global(_header_row_tables(label), True) == ""


@pytest.mark.parametrize("label", ["qty", "s/n", "DETAIL NO", "n/a", "Number of Holes"])
def test_matching_is_on_the_normalised_form(label):
    assert extractor.item_is_bad(label, header_labels=True) is True


@pytest.mark.parametrize("value", ["Structural weld", "Pipe to pipe", "Qty 4 spools",
                                   "S/N 1234 flange", "BOP", "Detail A"])
def test_real_items_are_kept(value):
    assert extractor.item_is_bad(value, header_labels=True) is False


def test_a_rejected_header_lets_the_scan_find_the_real_item_label():
    tables = [[["Item", "Qty", "Weld No", "Result"]],
              [["Item Insp.:", "Structural Welds"]]]
    assert extractor.extract_item_global(tables) == "Qty"
    assert extractor.extract_item_global(tables, True) == "Structural Welds"


def test_merged_cell_form_is_covered_too():
    tables = [[["Item: N/A"]], [["Item:", "Tension Ring"]]]
    assert extractor.extract_item_global(tables) == "N/A"
    assert extractor.extract_item_global(tables, True) == "Tension Ring"


def test_the_reader_defaults_off_and_only_true_turns_it_on():
    s = lambda **f: SimpleNamespace(raw={"filtering": f})
    assert reject_item_header_labels(SimpleNamespace(raw={})) is False
    assert reject_item_header_labels(s()) is False
    assert reject_item_header_labels(s(reject_item_header_labels=True)) is True
    for v in (False, "true", 1):
        assert reject_item_header_labels(s(reject_item_header_labels=v)) is False


def test_the_crosscheck_reading_is_unchanged():
    """pdf_crosscheck compares the two readers' raw Item: it keeps the default."""
    import inspect
    from monthly_report import pdf_crosscheck
    assert "extract_item_global(tables)" in inspect.getsource(pdf_crosscheck)
