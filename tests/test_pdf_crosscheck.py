"""Pin the two-reader agreement rule (ADR-003 D2).

The rule is short and the tests match it: agreement is accepted, a ``result``
disagreement quarantines, a metadata disagreement is recorded but shipped, and
whatever reaches the audit file carries both answers and the file to open — an
operator must never be asked to adjudicate blind.

Grids are written inline rather than read from PDFs: what is under test here is
the comparison, not the reconstruction (``test_pdf_reader`` covers that).
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path

from monthly_report import pdf_crosscheck


def _grid(*, report_no: str = "RT-U-25-176", client: str = "UBOC",
          verdict_cell: str = "Accept") -> list[list[list[str]]]:
    """A minimal two-table document: header block + one weld row."""
    return [
        [["Report No:", report_no], ["Date:", "10.09.2025"], ["Client:", client],
         ["Material:", "CS X60"]],
        [["Weld No", "Diam./Thick.", "Result"], ["W1", "6", verdict_cell]],
    ]


class TestAgreement:
    def test_identical_grids_produce_no_disagreement(self) -> None:
        assert pdf_crosscheck.compare(_grid(), _grid(), path="a.pdf") == []

    def test_whitespace_and_case_are_not_a_disagreement(self) -> None:
        left = _grid(client="UBOC")
        right = _grid(client="  uboc  ")
        assert [d.field for d in pdf_crosscheck.compare(left, right, path="a.pdf")] == []

    def test_blank_against_a_value_is_a_disagreement(self) -> None:
        found = pdf_crosscheck.compare(_grid(client="UBOC"), _grid(client=""),
                                       path="a.pdf")
        assert [d.field for d in found] == ["client"]


class TestBlocking:
    def test_result_disagreement_blocks(self) -> None:
        found = pdf_crosscheck.compare(_grid(verdict_cell="Accept"),
                                       _grid(verdict_cell="Reject"), path="a.pdf")
        assert [(d.field, d.blocking) for d in found] == [("result", True)]
        assert pdf_crosscheck.blocks(found) is True

    def test_metadata_disagreement_does_not_block(self) -> None:
        found = pdf_crosscheck.compare(_grid(client="UBOC"), _grid(client="SDLN"),
                                       path="a.pdf")
        assert [(d.field, d.blocking) for d in found] == [("client", False)]
        assert pdf_crosscheck.blocks(found) is False

    def test_both_readers_carry_their_own_answer(self) -> None:
        found = pdf_crosscheck.compare(_grid(verdict_cell="Accept"),
                                       _grid(verdict_cell="Reject"),
                                       path="input/PDF_ARCHIVE/RT-U-25-176.pdf")
        (d,) = found
        assert (d.primary, d.crosscheck) == ("Fit", "Unfit")
        assert d.path == "input/PDF_ARCHIVE/RT-U-25-176.pdf"
        assert d.report_no == "RT-U-25-176"


class TestAudit:
    def _write(self, tmp_path: Path, disagreements):
        return pdf_crosscheck.write_audit(tmp_path / "output", disagreements,
                                          today=_dt.date(2026, 9, 7))

    def test_no_disagreements_writes_nothing(self, tmp_path: Path) -> None:
        assert self._write(tmp_path, []) is None
        assert not (tmp_path / "output").exists()

    def test_row_carries_report_field_both_answers_and_the_path(self, tmp_path: Path) -> None:
        found = pdf_crosscheck.compare(_grid(verdict_cell="Accept"),
                                       _grid(verdict_cell="Reject"),
                                       path="input/PDF_ARCHIVE/RT-U-25-176.pdf")
        path = self._write(tmp_path, found)
        assert path is not None and path.name == "pdf_crosscheck_2026-09-07.md"
        text = path.read_text(encoding="utf-8")
        assert ("| `RT-U-25-176` | result | `Fit` | `Unfit` | "
                "`input/PDF_ARCHIVE/RT-U-25-176.pdf` | QUARANTINE |") in text

    def test_warning_rows_land_in_the_second_section(self, tmp_path: Path) -> None:
        found = pdf_crosscheck.compare(_grid(client="UBOC"), _grid(client="SDLN"),
                                       path="a.pdf")
        text = self._write(tmp_path, found).read_text(encoding="utf-8")
        head, _, tail = text.partition("## 2. XƏBƏRDARLIQ")
        assert "XƏBƏRDARLIQ |" in tail and "XƏBƏRDARLIQ |" not in head
        assert "| `UBOC` | `SDLN` |" in tail

    def test_audit_tells_the_operator_what_to_do(self, tmp_path: Path) -> None:
        found = pdf_crosscheck.compare(_grid(verdict_cell="Accept"),
                                       _grid(verdict_cell="Reject"), path="a.pdf")
        text = self._write(tmp_path, found).read_text(encoding="utf-8")
        assert "Operator nə etməlidir" in text
        assert pdf_crosscheck.PRIMARY_NAME in text
        assert pdf_crosscheck.CROSSCHECK_NAME in text


class TestQuarantineReasonContract:
    """The reason string is a contract with the GUI's Quarantine page."""

    def test_reason_maps_to_a_tag(self) -> None:
        from monthly_report.gui.services import quarantine_reasons_service
        reason = f"{pdf_crosscheck.DISAGREEMENT_REASON} (result: Fit vs Unfit)"
        tag = quarantine_reasons_service.tag_for(reason)
        assert tag != quarantine_reasons_service.DEFAULT_TAG

    def test_the_two_reason_maps_stay_in_step(self) -> None:
        # _TAGS drives the chip on the Quarantine card; REASON_HINTS is its
        # documented mirror. A marker in one and not the other is the drift the
        # reasons service's own docstring warns about.
        from monthly_report.gui.services import (quarantine_reasons_service,
                                                 quarantine_service)
        marker = pdf_crosscheck.DISAGREEMENT_REASON
        assert marker in dict(quarantine_reasons_service._TAGS)
        assert marker in quarantine_service.REASON_HINTS

    def test_console_line_parses_into_name_and_tag(self) -> None:
        from monthly_report.gui.services import quarantine_reasons_service
        line = (f"  [quarantine] RT-U-25-176.pdf: "
                f"{pdf_crosscheck.DISAGREEMENT_REASON} (result: Fit vs Unfit) "
                f"-> input/SKIPPED_REPORTS/")
        parsed = quarantine_reasons_service.parse_line(line)
        assert parsed is not None
        name, tag = parsed
        assert name == "RT-U-25-176.pdf"
        assert tag != quarantine_reasons_service.DEFAULT_TAG
