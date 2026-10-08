"""The Equipment block reader — extractor.extract_equipment.

Every table literal below is a real Equipment row copied verbatim out of the
corpus under input/ (double spaces, unbalanced paren and all), because the
failure this reader has to avoid is not "no value" — it is a plausible-looking
WRONG value picked up from the cell next door.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from monthly_report.extractor import extract_equipment  # noqa: E402


def _tables(*rows):
    """One table, wrapping the rows in the [table][row][cell] shape docx_reader emits."""
    return [list(rows)]


# --------------------------------------------------------------------------- #
# One label per method, read off the real rows.
# --------------------------------------------------------------------------- #
def test_mpi_reads_the_magnet_past_the_power_and_calibration_cells():
    tables = _tables(
        ["Equipment"],
        ["Equipment used", "El/Magnet  (S/N:B1261)", "Power:   110V             220V",
         "Calibration Block:    4.5kq (S/N: 0007)"],
        ["Consumables/ Batch number", "MPI Paint  -     PFINDER 280, B/No4918",
         "MPI Ink -   PFINDER 251, B/No842"],
    )
    assert extract_equipment(tables) == "El/Magnet (S/N:B1261)"


def test_ut_reads_the_set_type_and_keeps_the_unbalanced_paren_verbatim():
    """The corpus really does carry "(№540331110056" with no closing paren.

    We store what the document says. Repairing it here would invent data that the
    operator cannot trace back to the source report.
    """
    tables = _tables(
        ["EQUIPMENT"],
        ["UT Set type & S/N", "SIUI CTS-9006 (№540331110056", "Couplant",
         "Ultrasound couplant 333, Batch 4440", "Calibration block", "IIW(V1), V2",
         "Reference Block", "IIW(V1)"],
    )
    assert extract_equipment(tables) == "SIUI CTS-9006 (№540331110056"


def test_utm_spells_the_label_differently_and_still_resolves():
    """UT says "UT Set type & S/N", UTM says "UT Set type/S/n:".

    _norm reduces & / : to spaces, so both collapse onto one key and neither
    method needs its own branch.
    """
    tables = _tables(
        ["EQUIPMENT"],
        ["UT Set type/S/n:", "Sonatest D70 / (№ 1014948)", "Couplant:",
         "Ultrasound Couplant  333, Batch 4440", "Calibration block:",
         "Step pipe block"],
    )
    assert extract_equipment(tables) == "Sonatest D70 / (№ 1014948)"


def test_rt_reads_the_isotope_not_the_x_ray_checkbox_beside_it():
    tables = _tables(
        ["Equipment"],
        ["Radiation source", "Se 75", "X-ray", "Film type", "MX125", "D3", "T200",
         "Focal Spot Size", "2.8"],
    )
    assert extract_equipment(tables) == "Se 75"


def test_rt_merged_label_and_value_in_one_cell():
    """The "Radiation source: Ir.192" single-cell form, as extract_item_global handles."""
    tables = _tables(["Equipment"], ["Radiation source: Ir.192", "X-ray"])
    assert extract_equipment(tables) == "Ir.192"


def test_pmi_reads_the_analyzer_model_without_swallowing_the_serial_cell():
    """The S/N is a SEPARATE cell. Merging it in would be a per-method rule with no
    stable shape (HT's serial sits two cells right, behind another label)."""
    tables = _tables(
        ["Equipment"],
        ["Equipment used", "Thermo Scientific  Niton XL 3t", "S/N: 56860",
         "Calibration date:  01.08.2025"],
        ["Calibration Standard Grade", "Stainless steel", "S/N: 3063753 C"],
    )
    assert extract_equipment(tables) == "Thermo Scientific Niton XL 3t"


def test_ferrite_keeps_the_serial_that_the_document_put_in_the_same_cell():
    tables = _tables(
        ["Equipment"],
        ["Equipment used", "Feritscope MP30E-S; S/N: 050006576", "Calibration date",
         "09.01.2025"],
    )
    assert extract_equipment(tables) == "Feritscope MP30E-S; S/N: 050006576"


def test_ht_reads_the_tester_not_the_calibration_block_label_beside_it():
    tables = _tables(
        ["Equipment"],
        ["Equipment used", "Hardness tester MET-UDA 140229", "Calibration Block (HV)",
         "S/N: 11676"],
        ["Vickers version"],
    )
    assert extract_equipment(tables) == "Hardness tester MET-UDA 140229"


def test_dp_has_no_equipment_field_and_yields_empty():
    """DP documents carry only Consumables / Lighting Equipment. "" is the right
    answer — the sidecar key stays present and empty."""
    tables = _tables(
        ["Equipment"],
        ["Consumables", "Penetrant - PFINDER 860 / Batch No.: 11860245",
         "Developer - PFINDER 871 / Batch No.:1187345",
         "Cleaner - PFINDER 890 / Batch No.:11890245"],
        ["Lighting Equipment", "Lux meter S/N:  786472", "Lighting:  Artificial light",
         "Light intensity: >1100 Lux"],
    )
    assert extract_equipment(tables) == ""


# --------------------------------------------------------------------------- #
# The wrong-value guards. These are the reason _value_after is not reused.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("neighbour", [
    "Power:   110V             220V",     # MPI
    "X-ray",                              # RT
    "Calibration Block (HV)",             # HT
    "Calibration date",                   # FERRITE
    "Couplant",                           # UT
])
def test_a_blank_value_cell_never_reaches_across_to_the_next_field(neighbour):
    """_value_after would scan rightward past the blank and return `neighbour`.

    A missing instrument must read "" — an instrument name typed onto a government
    appeal form has to come from the report, not from the cell that happened to be
    next to it.
    """
    tables = _tables(["Equipment used", "", neighbour])
    assert extract_equipment(tables) == ""


def test_a_label_only_row_yields_empty():
    assert extract_equipment(_tables(["Equipment used"])) == ""


def test_no_equipment_block_at_all_yields_empty():
    tables = _tables(["Report No", "KF-MT-26-001"], ["Client", "Khazar Fabrication"])
    assert extract_equipment(tables) == ""


def test_a_metadata_label_is_never_returned_as_an_instrument():
    """Guards the merged-cell/adjacent-cell paths against reading the next label."""
    tables = _tables(["Equipment used", "Client", "Khazar Fabrication"])
    assert extract_equipment(tables) == ""


def test_the_reader_never_raises_on_ragged_or_empty_input():
    """The module's contract: missing fields yield "", evolving layouts never crash."""
    assert extract_equipment([]) == ""
    assert extract_equipment([[]]) == ""
    assert extract_equipment(_tables([], [""], ["Equipment used"])) == ""
