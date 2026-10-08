"""The acceptance-standard reader — extractor.extract_standard.

The reader must recover the standard from two table layouts: a **merged single
cell** (``"ACC Standard: EEMUA 158"`` — the common PDF-conversion artifact) and a
**separate label cell** whose value sits one or more columns to the right (a
merged docx layout leaves the immediate next cell blank). It recognizes several
label wordings, rejects ``N/A``, and never crashes on empty input.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from monthly_report import extractor  # noqa: E402
from monthly_report.extractor import (  # noqa: E402
    extract_item_global,
    extract_standard,
)


def _tables(*rows):
    """One table, wrapping the rows in the [table][row][cell] shape docx_reader emits."""
    return [list(rows)]


# --------------------------------------------------------------------------- #
# The core PDF fix: label and value merged into one cell.
# --------------------------------------------------------------------------- #
def test_inline_merged_cell_acc_standard():
    tables = _tables(["ACC Standard: EEMUA 158"])
    assert extract_standard(tables) == "EEMUA 158"


def test_inline_merged_cell_with_neighbour_does_not_bleed():
    tables = _tables(["ACC Standard: EEMUA 158", "Date: 2026-07"])
    assert extract_standard(tables) == "EEMUA 158"


# --------------------------------------------------------------------------- #
# Separate label cell (regression — this already worked before the change).
# --------------------------------------------------------------------------- #
def test_adjacent_cell():
    tables = _tables(["ACC Standard:", "EEMUA 158"])
    assert extract_standard(tables) == "EEMUA 158"


def test_merged_blank_cell_then_value():
    tables = _tables(["ACC Standard:", "", "ISO 23278"])
    assert extract_standard(tables) == "ISO 23278"


# --------------------------------------------------------------------------- #
# Punctuation / case variants all collapse via _norm.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("label", ["ACC. Standard:", "Acc Standard:", "ACC STANDARD:"])
def test_acc_punctuation_variants_inline(label):
    tables = _tables([f"{label} ISO 23278"])
    assert extract_standard(tables) == "ISO 23278"


@pytest.mark.parametrize("label", ["ACC. Standard:", "Acc Standard:"])
def test_acc_punctuation_variants_adjacent(label):
    tables = _tables([label, "ISO 23278"])
    assert extract_standard(tables) == "ISO 23278"


# --------------------------------------------------------------------------- #
# The newly added label wordings, inline and adjacent.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "label",
    ["Acceptance Standard:", "Acceptance Criteria:", "Normative Document:", "Code/Standard:"],
)
def test_new_labels_inline(label):
    tables = _tables([f"{label} ISO 5817"])
    assert extract_standard(tables) == "ISO 5817"


@pytest.mark.parametrize(
    "label",
    ["Acceptance Standard:", "Acceptance Criteria:", "Normative Document:", "Code/Standard:"],
)
def test_new_labels_adjacent(label):
    tables = _tables([label, "ISO 5817"])
    assert extract_standard(tables) == "ISO 5817"


# --------------------------------------------------------------------------- #
# Specification is the last-resort label, and still works.
# --------------------------------------------------------------------------- #
def test_specification_inline():
    tables = _tables(["Specification: ASME V"])
    assert extract_standard(tables) == "ASME V"


def test_acc_standard_preferred_over_specification():
    tables = _tables(
        ["Specification: ASME V", "ACC Standard: EEMUA 158"],
    )
    assert extract_standard(tables) == "EEMUA 158"


# --------------------------------------------------------------------------- #
# Rejections and edge cases.
# --------------------------------------------------------------------------- #
def test_na_value_rejected_inline():
    tables = _tables(["ACC Standard: N/A"])
    assert extract_standard(tables) == ""


def test_na_value_rejected_adjacent():
    tables = _tables(["ACC Standard:", "N/A"])
    assert extract_standard(tables) == ""


def test_empty_tables():
    assert extract_standard([]) == ""


def test_bare_label_only_no_value():
    tables = _tables(["ACC Standard:"])
    assert extract_standard(tables) == ""


def test_false_positive_guard_job_specification():
    # Exact-match label guard: "Job Specification" must not match "specification".
    tables = _tables(["Job Specification: SOMETHING"])
    assert extract_standard(tables) == ""


# --- extract_item_global / item_is_bad (task 11-B1) --------------------------
# The trailing-colon rule: a value ending in ":" is the NEXT field's caption, not
# this item's name. It sits in item_is_bad, the single gate both branches of
# extract_item_global and the aggregator's three-step fallback chain consult.

def _rows(*rows):
    return [[list(r) for r in rows]]


def test_item_global_merged_cell():
    assert extract_item_global(_rows(["Item Insp.: Structural Welds"])) == "Structural Welds"


def test_item_global_adjacent_cell():
    assert extract_item_global(_rows(["Item", "Pipe line"])) == "Pipe line"


def test_item_global_rejects_trailing_colon_caption():
    # "Production stage:" is the caption of the field AFTER the item, left in the
    # value cell because the template's own value cell was blank.
    assert extract_item_global(_rows(["Item", "Production stage:"])) == ""


def test_item_global_rejects_trailing_colon_in_merged_cell():
    assert extract_item_global(_rows(["Item Insp.: Production stage:"])) == ""


def test_item_global_rejects_leaked_header():
    assert extract_item_global(_rows(["Item", "Spool No."])) == ""


def test_item_is_bad_colon_rule_is_raw_text():
    # _norm() drops the colon, so the deny-list alone can never see this shape.
    assert extractor.item_is_bad("Description:") is True
    assert extractor.item_is_bad("Production stage:  ") is True
    assert extractor.item_is_bad("Description") is False


def test_item_is_bad_keeps_real_values_with_internal_colon():
    # Only a TRAILING colon is a caption; a colon inside a real name is not.
    assert extractor.item_is_bad("Crane: North side") is False
