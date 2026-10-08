"""Pin STAGE -1 after ADR-003: archive PDFs, never convert them.

Replaces ``test_pre_processor_parallel.py``, which pinned the ``pdf2docx`` pool,
the ``.part`` write protocol and the destination-name reservation — all of which
existed only to make conversion safe, and all of which are gone with it.

What survived the change and is pinned here: no-clobber moves, method scoping,
counter monotonicity, the stdout markers the GUI reads, and — the new half —
:func:`pre_processor.pdf_sources`, which decides what STAGE 1 reads back out of
the archive. That decision carries the rule that used to justify not converting a
PDF: **a curated .docx always wins over its own source PDF.**
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from monthly_report import pre_processor as pp

_RAW = {"ndt_methods": {
    "UT": {"folder": "UT", "patterns": ["-UT-"]},
    "MPI": {"folder": "MPI", "patterns": ["-MT-"]},
    "RT": {"folder": "RT", "patterns": ["-RT-"]},
}}


def _settings(tmp_path: Path, raw=None):
    return SimpleNamespace(input_dir=tmp_path, raw=raw if raw is not None else _RAW,
                           dayfirst=True)


def _pdf(path: Path, name: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    target.write_bytes(b"%PDF-1.4 stub")
    return target


def _docx(path: Path, name: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    target = path / name
    target.write_text("stub", encoding="utf-8")
    return target


class TestArchiving:
    def test_a_dropped_pdf_moves_to_the_archive(self, tmp_path: Path) -> None:
        _pdf(tmp_path, "KF-MT-26-005.pdf")
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert result["archived"] == ["KF-MT-26-005.pdf"]
        assert (tmp_path / pp.PDF_ARCHIVE_DIR / "KF-MT-26-005.pdf").exists()
        assert not (tmp_path / "KF-MT-26-005.pdf").exists()

    def test_it_finds_pdfs_at_any_depth(self, tmp_path: Path) -> None:
        _pdf(tmp_path / "UnSorted" / "KHAZAR", "U-UT-26-010.pdf")
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert result["archived"] == ["U-UT-26-010.pdf"]

    def test_no_pdfs_is_a_no_op(self, tmp_path: Path) -> None:
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert result == {"archived": [], "skipped": [], "failed": []}
        assert not (tmp_path / pp.PDF_ARCHIVE_DIR).exists()

    def test_settled_folders_are_never_touched(self, tmp_path: Path) -> None:
        """An archived, quarantined or pruned PDF is settled — moving it again
        would either be a no-op or would resurrect a file a stage retired."""
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "already.pdf")
        _pdf(tmp_path / pp.QUARANTINE_DIR, "skipped.pdf")
        _pdf(tmp_path / pp.PRUNED_DIR, "pruned.pdf")
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert result["archived"] == []
        assert (tmp_path / pp.QUARANTINE_DIR / "skipped.pdf").exists()
        assert (tmp_path / pp.PRUNED_DIR / "pruned.pdf").exists()

    def test_a_name_clash_leaves_the_original_alone(self, tmp_path: Path) -> None:
        """The archived copy is the one already settled; never overwrite it."""
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "KF-MT-26-005.pdf")
        dropped = _pdf(tmp_path, "KF-MT-26-005.pdf")
        dropped.write_bytes(b"%PDF different bytes")
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert result["archived"] == []
        assert result["skipped"] == [("KF-MT-26-005.pdf", "already archived")]
        assert dropped.read_bytes() == b"%PDF different bytes"
        assert (tmp_path / pp.PDF_ARCHIVE_DIR / "KF-MT-26-005.pdf").read_bytes() \
            == b"%PDF-1.4 stub"

    def test_a_locked_pdf_is_reported_and_left_in_place(self, tmp_path: Path,
                                                        monkeypatch) -> None:
        _pdf(tmp_path, "KF-MT-26-005.pdf")

        def _boom(*_a, **_k):
            raise PermissionError("[WinError 32] locked")

        monkeypatch.setattr(pp, "move_to", _boom)
        result = pp.archive_input_pdfs(_settings(tmp_path))
        assert [n for n, _ in result["failed"]] == ["KF-MT-26-005.pdf"]
        assert (tmp_path / "KF-MT-26-005.pdf").exists()

    def test_it_is_idempotent(self, tmp_path: Path) -> None:
        _pdf(tmp_path, "KF-MT-26-005.pdf")
        pp.archive_input_pdfs(_settings(tmp_path))
        assert pp.archive_input_pdfs(_settings(tmp_path))["archived"] == []


class TestStdoutMarkers:
    """The GUI reads these; ``gui/services/progress.py`` pins the same shapes."""

    def test_header_and_counter_lines(self, tmp_path: Path, capsys) -> None:
        for name in ("a-RT-26-001.pdf", "b-RT-26-002.pdf"):
            _pdf(tmp_path, name)
        pp.archive_input_pdfs(_settings(tmp_path))
        out = capsys.readouterr().out
        assert f"[{pp.STAGE_CONVERT}] [pdf] archiving 2 file(s) across 1 core(s)" in out
        assert f"[{pp.STAGE_CONVERT}] [pdf] (1/2) archived " in out
        assert f"[{pp.STAGE_CONVERT}] [pdf] (2/2) archived " in out

    def test_the_counter_is_monotonic(self, tmp_path: Path, capsys) -> None:
        for i in range(5):
            _pdf(tmp_path, f"r-RT-26-00{i}.pdf")
        pp.archive_input_pdfs(_settings(tmp_path))
        seen = [int(m) for m, _ in re.findall(r"\[pdf\] \((\d+)/(\d+)\)",
                                              capsys.readouterr().out)]
        assert seen == [1, 2, 3, 4, 5]


class TestPdfSources:
    """What STAGE 1 reads back out of the archive."""

    def test_an_archived_pdf_with_no_docx_is_a_source(self, tmp_path: Path) -> None:
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-176.pdf")
        assert [p.name for p in pp.pdf_sources(_settings(tmp_path))] == \
            ["RT-U-25-176.pdf"]

    def test_a_curated_docx_wins_over_its_own_pdf(self, tmp_path: Path) -> None:
        """The aggregator dedupes twins by Report № and keeps the first path in
        sort order. Reading both would let machine-read output displace a
        hand-checked document."""
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-176.pdf")
        _docx(tmp_path / "RT", "RT-U-25-176 (Ilk Inshaat)_en.docx")
        assert pp.pdf_sources(_settings(tmp_path)) == []

    def test_a_quarantined_docx_also_wins(self, tmp_path: Path) -> None:
        """Reading the PDF of a quarantined report would silently un-quarantine it.

        Every one of the 171 archived PDFs with no live .docx has a quarantined
        one, so this rule is what keeps switching readers from changing the corpus:
        those files come back only when an operator removes them deliberately.
        """
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-176.pdf")
        _docx(tmp_path / pp.QUARANTINE_DIR, "RT-U-25-176.docx")
        assert pp.pdf_sources(_settings(tmp_path)) == []

    def test_a_pruned_docx_does_not_count(self, tmp_path: Path) -> None:
        """_PRUNED is the trash: a file there was retired, not held."""
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-176.pdf")
        _docx(tmp_path / pp.PRUNED_DIR, "RT-U-25-176.docx")
        assert [p.name for p in pp.pdf_sources(_settings(tmp_path))] ==             ["RT-U-25-176.pdf"]

    def test_asr_pdfs_are_never_read(self, tmp_path: Path) -> None:
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "ASR-RT-26-001.pdf")
        assert pp.pdf_sources(_settings(tmp_path)) == []

    def test_no_archive_folder_is_an_empty_list(self, tmp_path: Path) -> None:
        assert pp.pdf_sources(_settings(tmp_path)) == []

    def test_only_pdfs_come_out_of_the_archive(self, tmp_path: Path) -> None:
        """PDF_ARCHIVE stays in SETTLED_DIRS: a .docx parked there is settled and
        must not be re-read as a report."""
        _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-176.pdf")
        _docx(tmp_path / pp.PDF_ARCHIVE_DIR, "RT-U-25-177.docx")
        assert [p.name for p in pp.pdf_sources(_settings(tmp_path))] == \
            ["RT-U-25-176.pdf"]

    def test_the_order_is_stable(self, tmp_path: Path) -> None:
        for name in ("c-RT-26-003.pdf", "a-RT-26-001.pdf", "b-RT-26-002.pdf"):
            _pdf(tmp_path / pp.PDF_ARCHIVE_DIR, name)
        assert [p.name for p in pp.pdf_sources(_settings(tmp_path))] == \
            ["a-RT-26-001.pdf", "b-RT-26-002.pdf", "c-RT-26-003.pdf"]


class TestConversionIsGone:
    """ADR-003 removed the stage, not just its call site."""

    @pytest.mark.parametrize("name", ["convert_input_pdfs", "converted_docx_path",
                                      "sweep_part_files", "PART_SUFFIX",
                                      "_convert_one", "_convert_workers",
                                      "DEFAULT_CONVERT_WORKERS"])
    def test_the_symbol_is_gone(self, name: str) -> None:
        assert not hasattr(pp, name)

    def test_pdf2docx_is_not_imported_anywhere_in_the_package(self) -> None:
        src = Path(pp.__file__).resolve().parent
        offenders = [p.name for p in src.rglob("*.py")
                     if "import pdf2docx" in p.read_text(encoding="utf-8")
                     or "from pdf2docx" in p.read_text(encoding="utf-8")]
        assert offenders == []
