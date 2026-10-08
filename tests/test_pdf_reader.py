"""Pin the direct-PDF reader (ADR-003).

Two properties matter here and nothing else:

1. **Contract parity.** ``pdf_reader`` must hand back exactly the shape
   ``docx_reader`` does — ``(list[list[list[str]]], bool)`` — because
   ``_read_one`` dispatches on the file suffix and every consumer downstream
   (parse cache payload, extractor, aggregator) is shared between the two paths.
2. **The header-band merge.** This is the fix that took the cross-check reader
   from 62 wrong verdicts to 10 (ADR-003 D2). A stacked ``Accept/`` + ``Reject``
   column header must land in ONE cell; a row carrying digits must never be
   merged into its neighbour, or the reader could fuse two weld rows and invent
   data.

Fixtures are generated with PyMuPDF rather than committed: the real corpus PDFs
carry client names, and a synthetic page pins the geometry just as well because
the geometry is the whole subject.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from monthly_report import docx_reader, pdf_reader


def _write_pdf(path: Path, lines: list[tuple[float, float, str]]) -> Path:
    """Draw ``(x, y, text)`` runs on one page at 9 pt and save."""
    doc = fitz.open()
    page = doc.new_page()
    for x, y, text in lines:
        page.insert_text((x, y), text, fontsize=9)
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def stacked_header_pdf(tmp_path: Path) -> Path:
    """A UT-shaped page: the verdict column header is stacked over two lines.

    Line 1 ends with ``Accept/``, line 2 ends with ``Reject`` — the exact shape
    that made the word-grid reader emit a lone ``Reject`` cell, which
    ``_aggregate_result`` then read as a rejected report.
    """
    return _write_pdf(tmp_path / "stacked.pdf", [
        (50, 100, "Dia /        Defect        Length       Depth        Accept/"),
        (50, 112, "Thickness    type          mm           mm           Reject"),
        (50, 130, "83           None          12           2            Accept"),
    ])


@pytest.fixture
def scanned_pdf(tmp_path: Path) -> Path:
    """A page with no text layer at all — a scan, as far as any reader can tell."""
    doc = fitz.open()
    doc.new_page()
    doc.save(str(tmp_path / "scan.pdf"))
    doc.close()
    return tmp_path / "scan.pdf"


def _flat(tables) -> list[str]:
    return [cell for table in tables for row in table for cell in row]


class TestContractParity:
    """``pdf_reader`` must be substitutable for ``docx_reader`` at the seam."""

    def test_read_document_returns_tables_and_flag(self, stacked_header_pdf: Path) -> None:
        tables, has_text = pdf_reader.read_document(stacked_header_pdf)
        assert isinstance(has_text, bool)
        assert isinstance(tables, list)
        for table in tables:
            assert isinstance(table, list)
            for row in table:
                assert isinstance(row, list)
                assert all(isinstance(cell, str) for cell in row)

    def test_read_tables_is_the_first_half_of_read_document(self, stacked_header_pdf: Path) -> None:
        assert pdf_reader.read_tables(stacked_header_pdf) == \
            pdf_reader.read_document(stacked_header_pdf)[0]

    def test_same_public_names_as_docx_reader(self) -> None:
        for name in ("read_document", "read_tables"):
            assert callable(getattr(pdf_reader, name))
            assert callable(getattr(docx_reader, name))

    def test_read_both_returns_two_grids_and_the_flag(self, stacked_header_pdf: Path) -> None:
        primary, cross, has_text = pdf_reader.read_both(stacked_header_pdf)
        assert has_text is True
        # Same triple-nested shape on both readers; they need not be equal — that
        # they can differ is the entire reason the cross-check exists.
        for tables in (primary, cross):
            assert all(isinstance(cell, str)
                       for table in tables for row in table for cell in row)

    def test_scanned_pdf_reports_no_text(self, scanned_pdf: Path) -> None:
        tables, has_text = pdf_reader.read_document(scanned_pdf)
        assert has_text is False
        assert _flat(tables) == []


class TestHeaderBandMerge:
    """The cross-check reader's one non-obvious behaviour."""

    def test_stacked_accept_reject_becomes_one_cell(self, stacked_header_pdf: Path) -> None:
        doc = fitz.open(str(stacked_header_pdf))
        try:
            cells = _flat(pdf_reader._tables_crosscheck(doc))
        finally:
            doc.close()
        # "Reject" must never stand alone — that lone cell is what the whole-
        # document verdict fallback misreads as a rejection.
        assert "Reject" not in cells
        assert any("Accept/" in c and "Reject" in c for c in cells)

    def test_row_carrying_digits_is_never_merged(self, stacked_header_pdf: Path) -> None:
        doc = fitz.open(str(stacked_header_pdf))
        try:
            grid = pdf_reader._tables_crosscheck(doc)[0]
        finally:
            doc.close()
        data_rows = [row for row in grid if any("83" in cell for cell in row)]
        assert len(data_rows) == 1
        # The data row kept its own identity: no header text was glued into it.
        assert not any("Depth" in cell or "Accept/" in cell for cell in data_rows[0])

    def test_two_data_rows_stay_separate(self, tmp_path: Path) -> None:
        pdf = _write_pdf(tmp_path / "welds.pdf", [
            (50, 100, "Weld No      Diam         Result"),
            (50, 116, "W1           6            Accept"),
            (50, 130, "W2           8            Accept"),
        ])
        doc = fitz.open(str(pdf))
        try:
            grid = pdf_reader._tables_crosscheck(doc)[0]
        finally:
            doc.close()
        assert sum(1 for row in grid if any("W1" in c for c in row)) == 1
        assert sum(1 for row in grid if any("W2" in c for c in row)) == 1
        assert not any(any("W1" in c for c in row) and any("W2" in c for c in row)
                       for row in grid)


class TestLabelCellSplit:
    """A label welded to its value is invisible to the extractor's next-cell lookup."""

    def test_known_label_splits(self) -> None:
        assert pdf_reader._split_label_cell("Report No: RT-U-25-176") == \
            ["Report No:", "RT-U-25-176"]

    def test_unknown_label_is_left_alone(self) -> None:
        assert pdf_reader._split_label_cell("Ratio: 1:2") == ["Ratio: 1:2"]

    def test_cell_without_colon_is_left_alone(self) -> None:
        assert pdf_reader._split_label_cell("SDLN WORK SHOP") == ["SDLN WORK SHOP"]
