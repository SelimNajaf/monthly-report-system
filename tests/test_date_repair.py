"""KB-1 / KB-1b — a cut date cell is reconstructed from evidence, or not at all.

Four promises are pinned here, and they pull against each other:

  * **KB-1 — repair the year.** ``17.03.202`` / ``02.04.2`` / ``29.03.20`` / ``25.06``
    are the real shapes in the corpus: the day and month survived and only the year
    was cut (or never typed). Before this fix dateutil read them as the years 202,
    2002 and 2020, and ``naming.document_number`` collapsed all three through
    ``year % 100`` into phantom ``MAR_0202`` / ``APR_2002`` groups.
  * **KB-1b — repair the month, from the PDF twin.** ``'11'``, ``'17.'``, ``'11.0'``
    and ``'11        /'`` lost the month too, so the report number cannot rescue
    them. The archived original's filename can
    (``...W-1_11.09.2025.pdf``), and the DAY stays the cell's: the cell was cut from
    the right, so its surviving left-hand day is what the inspector typed for this
    report, while the filename's day belongs to the export it names.
  * **No repair where nothing was cut.** A well-formed cell must parse exactly as it
    always did, including a plausible-but-old year like 2019. Both repairs are
    reachable only through a cell with no 4-digit year in it.
  * **No invention.** Where the evidence is absent (no twin, no date in the name) or
    self-contradictory (two dates in one name, a filename year that is not the report
    number's, an impossible 31.02), the answer is ``None`` and the file takes the
    pre-existing "no detectable inspection date" quarantine path. A guess here is
    worse than a quarantine: it files a report into a month nobody inspected in.

The last one is why this file also asserts the console line the pre-processor prints
for a repair cannot be read as progress by the GUI parser: a new line that happened
to match ``_RENDERED`` or ``_QUARANTINE`` would corrupt the progress bar of a run
that is otherwise working.
"""

import datetime as _dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.date_detector import (cell_day,  # noqa: E402
                                          filename_dates,
                                          parse_inspection_date,
                                          parse_inspection_date_ex)
from monthly_report.gui.services import progress  # noqa: E402
from monthly_report.report_identity import report_key_of, serial_year  # noqa: E402

#: The real archived twin of UT-SDLN-25-009 — a name carrying pipe sizes (``15.9``)
#: that must not be mistaken for a date, and one full date that must be found.
_TWIN_009 = "UT-SDLN-25-009(F1815)24''x 15.9_W-1_11.09.2025.pdf"

#: UT-SDLN-25-024's two real archived originals: the report, and the ASR retest that
#: shares its report key. Written verbatim (``''`` for inches, as the exports do).
_TWIN_024 = "UT-SDLN-25-024(F1752)30''x 38.0_W-103_20.09.2025.pdf"
_TWIN_024_ASR = "UT-SDLN-25-024(F1752)30''x 38.0_W-103ASR_22.09.2025.pdf"


@pytest.fixture(name="archive_root")
def _archive_fixture(tmp_path):
    """A miniature ``input/`` whose PDF_ARCHIVE holds the real UT-SDLN-25-024 pair —
    the original and its ASR retest — plus a report with NOTHING but an ASR."""
    from monthly_report import pdf_twin

    archive = tmp_path / "PDF_ARCHIVE"
    archive.mkdir()
    for name in (_TWIN_024, _TWIN_024_ASR,
                 "UT-SDLN-25-026(F1752)30''x 38.0_W-105ASR_22.09.2025.pdf"):
        (archive / name).write_bytes(b"%PDF-1.4\n")
    pdf_twin.reset_cache()
    yield tmp_path
    pdf_twin.reset_cache()


# --- KB-1: the year off the report number ----------------------------------

@pytest.mark.parametrize("raw,report_no,expected", [
    ("17.03.202", "MT-U-25-028", _dt.date(2025, 3, 17)),   # year cut to 3 digits
    ("02.04.2", "MT-U-25-033", _dt.date(2025, 4, 2)),      # year cut to 1 digit
    ("29.03.20", "MT-KF-25-031", _dt.date(2025, 3, 29)),   # year cut to 2 digits
    ("25.08.2", "U-MT-26-081", _dt.date(2026, 8, 25)),     # a 2026 report number
])
def test_a_truncated_year_is_taken_from_the_report_number(raw, report_no, expected):
    assert parse_inspection_date(raw, True, report_no) == expected


@pytest.mark.parametrize("raw,report_no,expected", [
    ("25.06", "MT-U-25-052", _dt.date(2025, 6, 25)),
    ("24.07", "MT-U-25-064", _dt.date(2025, 7, 24)),
])
def test_a_cell_with_day_and_month_but_no_year_at_all_is_repaired(raw, report_no, expected):
    """The corpus's ``25.06`` / ``24.07`` shape: the year is not truncated, it is
    absent. Nothing about the repair changes — day and month are still the cell's,
    the year is still the report number's — so refusing these was arbitrary."""
    assert parse_inspection_date(raw, True, report_no) == expected
    assert parse_inspection_date_ex(raw, True, report_no)[1].source == "serial"


def test_the_repair_is_reported_to_the_caller():
    """The repair record is what the pre-processor prints and audits on — a silent
    repair would leave an operator with no way to know a date was reconstructed."""
    how = parse_inspection_date_ex("17.03.202", True, "MT-U-25-028")[1]
    assert (how.source, how.day_source) == ("serial", "cell")


def test_a_multi_day_range_with_a_truncated_year_keeps_its_first_day():
    """``21-26.05.202`` — the same first-day rule the well-formed path uses, so a
    range does not change meaning just because its year was cut."""
    assert parse_inspection_date("21-26.05.202", True, "U-UT-25-9") == _dt.date(2025, 5, 21)


def test_a_retest_number_still_yields_its_year():
    assert parse_inspection_date("17.03.202", True, "MT-U-25-028R1") == _dt.date(2025, 3, 17)


# --- KB-1b rule 1: month and year from the name, day from the cell ----------

def test_the_month_and_year_come_from_the_twin_and_the_day_from_the_cell():
    """UT-SDLN-25-009: the cell was cut mid-month (``'11.0'``) and the twin is dated
    11.09.2025. Month and year are imported; the day 11 is the cell's own."""
    date, how = parse_inspection_date_ex("11.0", True, "UT-SDLN-25-009", [_TWIN_009])
    assert date == _dt.date(2025, 9, 11)
    assert (how.source, how.day_source, how.day_delta) == ("filename", "cell", 0)


def test_a_one_digit_cell_day_is_completed_from_the_twin():
    """RT-SDL-25-086: cell ``'1'``, twin dated 10.09.2025. Every day in this corpus is
    typed two digits, so a lone ``1`` is the left half of ``10`` that the cut left
    behind — not the 1st of the month nine days before the export. The twin holds the
    lost digit, and the audit says so with its own ``day_source``."""
    twin = 'RT-SDL-25-086(F1802)3"x15.9_3"-104D0395-04-C_W-5_10.09.2025.pdf'
    date, how = parse_inspection_date_ex("1", True, "RT-SDL-25-086", [twin])
    assert date == _dt.date(2025, 9, 10)
    assert (how.day_source, how.day_delta) == ("twin-truncated", 0)


@pytest.mark.parametrize("raw,twin_day,expected_day,expected_source", [
    ("2", 25, 25, "twin-truncated"),   # all three conditions met
    ("2", 22, 22, "twin-truncated"),
    ("20", 22, 20, "cell"),            # a TWO-digit cell day is a whole day: kept
    ("1", 9, 1, "cell"),               # a one-digit twin day cannot have lost one
    ("1", 21, 1, "cell"),              # first digits differ: two different days
    ("9", 19, 9, "cell"),              # 19 does not start with 9
])
def test_the_cut_day_exception_needs_all_three_conditions(raw, twin_day, expected_day,
                                                          expected_source):
    """The exception is narrow on purpose: a one-digit cell day, a two-digit twin day,
    and the twin's FIRST digit equal to the cell's. Miss any one of them and the
    cell's day stands, which is the ordinary rule."""
    twin = f"MT-U-25-100_W-1_{twin_day:02d}.09.2025.pdf"
    date, how = parse_inspection_date_ex(raw, True, "MT-U-25-100", [twin])
    assert date.day == expected_day
    assert how.day_source == expected_source


def test_the_cell_day_wins_over_a_disagreeing_twin_day():
    """RT-SDL-25-094: cell ``'11'``, twin dated 10.09.2025. The cell keeps the 11th —
    the filename's day describes the export batch, not this weld — and the
    disagreement is reported (``day_delta``) so the audit can flag it."""
    twin = 'RT-SDL-25-094(F1798)6"x18.26_36"-15E441-03-A_W-1_10.09.2025.pdf'
    date, how = parse_inspection_date_ex("11", True, "RT-SDL-25-094", [twin])
    assert date == _dt.date(2025, 9, 11)
    assert (how.day_source, how.day_delta) == ("cell", 1)
    # The month — the only thing that decides the report's group — is the twin's
    # either way, so a day disagreement never moves the report between months.
    assert date.month == 9


# --- KB-1b rule 2: no readable day in the cell -> the day comes from the name -

@pytest.mark.parametrize("raw", ["WPS-002", "", "   ", "0", "45"])
def test_the_day_comes_from_the_name_when_the_cell_shows_no_usable_day(raw):
    """``'WPS-002'`` is not a cut date at all and ``'45'`` is not a day. With no day
    to keep, the whole date is the twin's — still evidence, just weaker."""
    date, how = parse_inspection_date_ex(raw, True, "UT-SDLN-25-009", [_TWIN_009])
    assert date == _dt.date(2025, 9, 11)
    assert how.day_source == "filename"


# --- KB-1b: ASR/ARS twins are not evidence ----------------------------------

def test_an_asr_twin_does_not_make_a_report_ambiguous(archive_root):
    """UT-SDLN-25-024 has two archived originals under one report key: the ``W-103``
    dated 20.09 and its ``W-103ASR`` retest dated 22.09. The ASR document is excluded
    from this pipeline on sight, so counting it as dating evidence for the original
    contradicts the rule that removed it — and it was refusing a clean repair as
    'two disagreeing dates'. ``pdf_twin`` drops it before the parser ever sees it."""
    from monthly_report import pdf_twin

    archive = archive_root / "PDF_ARCHIVE"
    names = pdf_twin.index(archive_root)[report_key_of("UT-SDLN-25-024.docx")]
    assert names == (_TWIN_024,)
    assert archive.is_dir()
    date, how = parse_inspection_date_ex("20", True, "UT-SDLN-25-024", names)
    assert date == _dt.date(2025, 9, 20)
    assert (how.day_source, how.day_delta) == ("cell", 0)


def test_a_report_whose_only_twin_is_an_asr_has_no_twin_at_all(archive_root):
    """Nothing is left to read a month off, so the file stays quarantined rather than
    borrowing the retest's date."""
    from monthly_report import pdf_twin

    assert report_key_of("UT-SDLN-25-026.docx") not in pdf_twin.index(archive_root)


# --- KB-1b rule 3: the filename year must be the report number's ------------

def test_a_filename_year_that_disagrees_with_the_report_number_is_refused():
    """A 2024-dated name under a ``-25-`` report number is describing another job.
    Quarantine, not a repair off whichever source spoke last."""
    twin = "UT-SDLN-25-009(F1815)_W-1_11.09.2024.pdf"
    assert parse_inspection_date("11.0", True, "UT-SDLN-25-009", [twin]) is None


def test_a_report_number_with_no_serial_year_cannot_confirm_the_filename():
    """With no ``-<YY>-`` to check the name against, the year is unverifiable — and
    an unverifiable year is exactly what this module refuses to write down."""
    assert parse_inspection_date("11.0", True, "no-serial-here", [_TWIN_009]) is None


# --- KB-1b rule 4: the assembled date must be real --------------------------

def test_an_impossible_assembled_date_is_refused():
    """Cell day 31 onto a February filename is not the 3rd of March. Refused."""
    twin = "MT-U-25-100_14.02.2025.pdf"
    assert parse_inspection_date("31", True, "MT-U-25-100", [twin]) is None


# --- KB-1b rule 5: two different dates in a name is ambiguity ---------------

def test_two_different_full_dates_in_a_filename_refuse_the_repair():
    """A name holding both 10.09.2025 and 12.09.2025 says nothing about which one
    this report is. The same rule covers two archived twins that disagree."""
    twin = "RT-SDL-25-094_W-1_10.09.2025_rev_12.09.2025.pdf"
    assert parse_inspection_date("11", True, "RT-SDL-25-094", [twin]) is None
    assert parse_inspection_date(
        "11", True, "RT-SDL-25-094",
        ["RT-SDL-25-094_10.09.2025.pdf", "RT-SDL-25-094_12.09.2025.pdf"]) is None
    # The SAME date twice is not ambiguity — one date, repaired.
    assert parse_inspection_date(
        "11", True, "RT-SDL-25-094",
        ["RT-SDL-25-094_10.09.2025.pdf", "RT-SDL-25-094_10.09.2025 (1).pdf"]
    ) == _dt.date(2025, 9, 11)


# --- KB-1b rule 6: no full date in the name -> unchanged quarantine ---------

@pytest.mark.parametrize("twins", [
    (),                                                  # no PDF twin at all
    ("MT-U-25-042 (Dashgil 2).pdf",),                    # a name with no date
    ('RT-SDL-25-094(F1798)6"x18.26_36"-15E441-03-A.pdf',),   # sizes are not dates
    ("MT-U-25-042_11.09.pdf",),                          # no year -> not a full date
    ("MT-U-25-042_31.02.2025.pdf",),                     # not a real date
])
def test_a_name_with_no_unambiguous_full_date_leaves_the_file_undatable(twins):
    assert parse_inspection_date("11", True, "MT-U-25-042", twins) is None


# --- KB-1b rule 7: KB-1 keeps priority --------------------------------------

def test_the_report_number_year_wins_over_the_twin_filename():
    """``17.03.202`` with a twin dated 09.2025: the cell names its own month, so KB-1
    answers first and March is kept. The document outranks the export's name."""
    twin = "MT-U-25-028_W-1_10.09.2025.pdf"
    date, how = parse_inspection_date_ex("17.03.202", True, "MT-U-25-028", [twin])
    assert date == _dt.date(2025, 3, 17)
    assert how.source == "serial"


def test_a_cell_month_contradicting_the_twin_month_is_never_overwritten():
    """The guard behind that priority: if KB-1 could not fire (no usable serial year)
    a cell month that disagrees with the filename must NOT be replaced by it — that
    would be picking a winner between two sources, which is a guess."""
    twin = "MT-U-99-028_W-1_10.09.2099.pdf"
    assert parse_inspection_date("17.03.202", True, "MT-U-99-028", [twin]) is None


# --- what the repairs must NOT touch ----------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("14.01.2026", _dt.date(2026, 1, 14)),
    ("18,26.01.2026", _dt.date(2026, 1, 18)),     # multi-day: first day wins
    ("21-26.05.2026", _dt.date(2026, 5, 21)),     # range: first day wins
    ("05.06.2019", _dt.date(2019, 6, 5)),         # plausible but old — untouched
])
def test_a_well_formed_date_parses_exactly_as_before(raw, expected):
    """With AND without a report number, and with a twin that says something else:
    a cell that never needed help is never touched. The 2019 case is the user's
    explicit requirement — an old year is a fact about the report, not a defect."""
    assert parse_inspection_date(raw, True) == expected
    assert parse_inspection_date(raw, True, "MT-U-25-028") == expected
    assert parse_inspection_date(raw, True, "MT-U-25-028", [_TWIN_009]) == expected
    assert parse_inspection_date_ex(raw, True, "MT-U-25-028")[1] is None


def test_a_well_formed_date_is_never_overridden_by_a_disagreeing_report_number():
    """A 2024-numbered report inspected in 2026 keeps the date the document states."""
    assert parse_inspection_date("14.01.2026", True, "MT-U-24-001") == _dt.date(2026, 1, 14)


# --- what stays undatable ---------------------------------------------------

@pytest.mark.parametrize("raw", [
    "11",            # day only — dateutil filled month AND year from today
    "1",
    "07.",
    "11        /",
    "WPS-002",       # not a date at all
    "",
])
def test_a_cut_cell_with_no_twin_is_undatable(raw):
    """Without a filename to read the month off, the year alone cannot rescue these:
    the month would still come from the system clock, so the answer would change
    every calendar month."""
    assert parse_inspection_date(raw, True, "RT-SDL-25-094") is None
    assert parse_inspection_date_ex(raw, True, "RT-SDL-25-094")[1] is None


def test_a_truncated_year_with_no_report_number_is_undatable():
    """No year token to repair from -> quarantine, never dateutil's invented century."""
    assert parse_inspection_date("17.03.202", True) is None
    assert parse_inspection_date("17.03.202", True, "no-serial-here") is None


def test_a_report_number_year_outside_the_window_is_refused():
    """``-99-`` expands to 2099 — a future year no inspection can carry. Refused
    rather than written into a report."""
    assert parse_inspection_date("17.03.202", True, "MT-U-99-028") is None


def test_an_impossible_day_or_month_is_refused():
    assert parse_inspection_date("17.13.202", True, "MT-U-25-028") is None
    assert parse_inspection_date("32.03.202", True, "MT-U-25-028") is None
    assert parse_inspection_date("31.04.202", True, "MT-U-25-028") is None


# --- the two helpers the rules are built on ---------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("11", 11), ("11.0", 11), ("17.", 17), ("11        /", 11), ("1", 1),
    ("25.06", 25),
    ("WPS-002", None),      # letters: a different field, not a cut date
    ("002", None),          # three digits is not a day
    ("0", None), ("45", None), ("", None),
])
def test_cell_day_reads_only_a_day(raw, expected):
    assert cell_day(raw) == expected


@pytest.mark.parametrize("name,expected", [
    ('UT-SDLN-25-009(F1815)24"x 15.9_W-1_11.09.2025.pdf', [_dt.date(2025, 9, 11)]),
    ('RT-SDL-25-094(F1798)6"x18.26_36"-15E441-03-A.pdf', []),
    ("MT-U-25-024_W-103_22.09.2025.pdf", [_dt.date(2025, 9, 22)]),
    ("a_10.09.2025_b_10.09.2025.pdf", [_dt.date(2025, 9, 10)]),    # deduplicated
    ("a_31.02.2025.pdf", []),                                      # not a real date
    ("a_2025.09.10.pdf", []),                                      # not DD.MM.YYYY
])
def test_filename_dates_finds_only_unambiguous_full_dates(name, expected):
    assert filename_dates([name]) == expected


# --- serial_year ------------------------------------------------------------

@pytest.mark.parametrize("report_no,expected", [
    ("MT-U-25-028", 2025),
    ("U-UT-26-081R1", 2026),          # retest marker stripped first
    ("AZF-RT-W1-25-148", 2025),       # W1 in the middle is not the year
    ("KF-MT--25-051", 2025),          # the corpus's double-hyphen outlier
    ("RT-SDL-25-086", 2025),
    ("", None),
    ("no-serial-here", None),
    ("MT-U-2025-028", None),          # a 4-digit group is not the -<YY>- tail
])
def test_serial_year_reads_the_trailing_two_digit_year(report_no, expected):
    assert serial_year(report_no) == expected


# --- the console lines ------------------------------------------------------

_REPAIR_LINES = (
    ("  [date repair] MT-U-25-028.docx: '17.03.202' -> "
     "2025-03-17 (year from MT-U-25-028)"),
    ("  [date repair] UT-SDLN-25-009.docx: '11.0' -> "
     "2025-09-11 (month/year from PDF twin 2025-09-11, day from cell)"),
)


@pytest.mark.parametrize("line", _REPAIR_LINES)
def test_the_repair_line_is_invisible_to_the_gui_progress_parser(line):
    """§30: the GUI's progress bar is anchored on exact console strings. A new line
    that any of those regexes claimed would move a bar or invent a quarantine card.
    The KB-1b line names the twin by its DATE, never its ``.pdf`` filename, for
    exactly this reason."""
    assert progress.PipelineProgressParser().feed(line) is None
    assert progress.UploadProgressParser().feed(line) is None


@pytest.mark.parametrize("line", _REPAIR_LINES)
def test_the_repair_line_is_not_read_as_a_quarantine_reason(line):
    """quarantine_reasons_service tags files off ``[quarantine]`` lines — a repair
    is the opposite of a quarantine and must not produce a chip."""
    from monthly_report.gui.services import quarantine_reasons_service as qrs
    assert qrs.parse_line(line) is None
