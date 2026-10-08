"""Pin the drag-and-drop ingestion rules.

A drop is the one place a user hands this system files directly, so it is the one
place a mistake is theirs and the consequence is ours. These tests cover what a
real drop does that a tidy one does not: nested folders, Word lock files, names
that already exist, and a drag that started inside ``input/`` itself.

No Qt and no display — the drop *zone* is a widget, but everything it decides
lives here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from monthly_report.gui.services import ingest_service as ing


@pytest.fixture
def tree(tmp_path):
    """A dropped folder shaped like a real one: nested, mixed, with noise."""
    drop = tmp_path / "drop"
    (drop / "MPI" / "May").mkdir(parents=True)
    (drop / "scans").mkdir()

    (drop / "KF-MT-26-001.docx").write_text("report", encoding="utf-8")
    (drop / "MPI" / "KF-MT-26-002.docx").write_text("report", encoding="utf-8")
    (drop / "MPI" / "May" / "KF-MT-26-003.docx").write_text("report", encoding="utf-8")
    (drop / "scans" / "KF-MT-26-004.pdf").write_bytes(b"%PDF-1.4")
    (drop / "notes.txt").write_text("not a report", encoding="utf-8")
    (drop / "~$KF-MT-26-001.docx").write_text("word lock", encoding="utf-8")
    (drop / "Thumbs.db").write_bytes(b"junk")
    return drop


class TestDiscover:
    def test_finds_reports_at_every_depth(self, tree, tmp_path):
        found = ing.discover([tree], tmp_path / "input")
        assert [p.name for p in found] == [
            "KF-MT-26-001.docx", "KF-MT-26-002.docx",
            "KF-MT-26-003.docx", "KF-MT-26-004.pdf",
        ]

    def test_ignores_everything_that_is_not_a_report(self, tree, tmp_path):
        names = {p.name for p in ing.discover([tree], tmp_path / "input")}
        assert "notes.txt" not in names
        assert "Thumbs.db" not in names

    def test_ignores_word_lock_files(self, tree, tmp_path):
        """~$ stubs are skipped by every scan in the pipeline; don't import them."""
        names = {p.name for p in ing.discover([tree], tmp_path / "input")}
        assert "~$KF-MT-26-001.docx" not in names

    def test_accepts_a_mix_of_loose_files_and_folders(self, tree, tmp_path):
        loose = tmp_path / "loose.docx"
        loose.write_text("report", encoding="utf-8")
        found = ing.discover([tree / "MPI", loose], tmp_path / "input")
        assert [p.name for p in found] == [
            "KF-MT-26-002.docx", "KF-MT-26-003.docx", "loose.docx"]

    def test_a_file_dragged_out_of_input_is_not_copied_onto_itself(self, tmp_path):
        input_dir = tmp_path / "input"
        (input_dir / "MPI").mkdir(parents=True)
        inside = input_dir / "MPI" / "KF-MT-26-001.docx"
        inside.write_text("report", encoding="utf-8")

        assert ing.discover([inside], input_dir) == []
        assert ing.discover([input_dir], input_dir) == []

    def test_deduplicates_overlapping_selections(self, tree, tmp_path):
        """Dropping a folder AND a file inside it must not copy that file twice."""
        found = ing.discover([tree, tree / "KF-MT-26-001.docx"], tmp_path / "input")
        assert len(found) == len({p for p in found})
        assert sum(p.name == "KF-MT-26-001.docx" for p in found) == 1

    def test_a_path_that_does_not_exist_is_ignored_not_raised(self, tmp_path):
        assert ing.discover([tmp_path / "gone.docx"], tmp_path / "input") == []

    def test_nothing_dropped_is_not_an_error(self, tmp_path):
        assert ing.discover([], tmp_path / "input") == []


class TestIngest:
    def test_files_land_flat_in_the_input_root(self, tree, tmp_path):
        """sort_input_files reads the method registry and does the filing (stage 0)."""
        input_dir = tmp_path / "input"
        result = ing.ingest(ing.discover([tree], input_dir), input_dir)

        assert len(result.copied) == 4
        assert sorted(p.name for p in input_dir.iterdir()) == [
            "KF-MT-26-001.docx", "KF-MT-26-002.docx",
            "KF-MT-26-003.docx", "KF-MT-26-004.pdf",
        ]

    def test_content_survives_the_copy(self, tmp_path):
        source = tmp_path / "KF-MT-26-001.docx"
        source.write_text("the actual report", encoding="utf-8")
        input_dir = tmp_path / "input"
        ing.ingest([source], input_dir)
        assert (input_dir / "KF-MT-26-001.docx").read_text(encoding="utf-8") == \
            "the actual report"

    def test_the_source_is_copied_not_moved(self, tmp_path):
        """A drop must never empty the folder the user dragged from."""
        source = tmp_path / "KF-MT-26-001.docx"
        source.write_text("report", encoding="utf-8")
        ing.ingest([source], tmp_path / "input")
        assert source.exists()

    def test_an_existing_name_is_skipped_never_overwritten(self, tmp_path):
        """No-clobber, matching pre_processor.move_to (pre_processor.py:69)."""
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "KF-MT-26-001.docx").write_text("the curated one", encoding="utf-8")
        source = tmp_path / "KF-MT-26-001.docx"
        source.write_text("a different file, same name", encoding="utf-8")

        result = ing.ingest([source], input_dir)

        assert result.copied == []
        assert result.skipped == [("KF-MT-26-001.docx", "already in input/")]
        assert (input_dir / "KF-MT-26-001.docx").read_text(encoding="utf-8") == \
            "the curated one"

    def test_redropping_the_same_folder_is_idempotent(self, tree, tmp_path):
        input_dir = tmp_path / "input"
        files = ing.discover([tree], input_dir)

        first = ing.ingest(files, input_dir)
        second = ing.ingest(files, input_dir)

        assert len(first.copied) == 4 and first.skipped == []
        assert second.copied == [] and len(second.skipped) == 4
        assert len(list(input_dir.iterdir())) == 4

    def test_progress_is_reported_for_every_file(self, tree, tmp_path):
        seen = []
        files = ing.discover([tree], tmp_path / "input")
        ing.ingest(files, tmp_path / "input",
                   progress=lambda i, n, name: seen.append((i, n)))
        assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]

    def test_cancel_stops_between_files_and_says_so(self, tree, tmp_path):
        input_dir = tmp_path / "input"
        files = ing.discover([tree], input_dir)
        calls = {"n": 0}

        def _cancelled() -> bool:
            calls["n"] += 1
            return calls["n"] > 2       # let two through, then stop

        result = ing.ingest(files, input_dir, cancelled=_cancelled)

        assert result.cancelled is True
        assert len(result.copied) == 2
        assert len(list(input_dir.iterdir())) == 2

    def test_a_cancelled_ingest_leaves_no_partial_file(self, tree, tmp_path):
        input_dir = tmp_path / "input"
        files = ing.discover([tree], input_dir)
        ing.ingest(files, input_dir, cancelled=lambda: True)
        assert list(input_dir.rglob(f"*{ing.PART_SUFFIX}")) == []

    def test_a_failed_copy_leaves_no_partial_file(self, tmp_path, monkeypatch):
        """A truncated .docx in input/ would be parsed as a real, broken report."""
        def _die(src, dst, **kwargs):
            Path(dst).write_text("half a fi", encoding="utf-8")
            raise OSError("disk full")

        source = tmp_path / "KF-MT-26-001.docx"
        source.write_text("report", encoding="utf-8")
        monkeypatch.setattr(ing.shutil, "copy2", _die)

        input_dir = tmp_path / "input"
        result = ing.ingest([source], input_dir)

        assert len(result.failed) == 1
        assert "disk full" in result.failed[0][1]
        assert list(input_dir.iterdir()) == []

    def test_one_bad_file_does_not_abort_the_batch(self, tmp_path, monkeypatch):
        good_a = tmp_path / "a.docx"
        bad = tmp_path / "b.docx"
        good_b = tmp_path / "c.docx"
        for f in (good_a, bad, good_b):
            f.write_text("report", encoding="utf-8")

        real_copy = ing.shutil.copy2

        def _sometimes(src, dst, **kwargs):
            if Path(src).name == "b.docx":
                raise OSError("locked by another process")
            return real_copy(src, dst, **kwargs)

        monkeypatch.setattr(ing.shutil, "copy2", _sometimes)
        result = ing.ingest([good_a, bad, good_b], tmp_path / "input")

        assert result.copied == ["a.docx", "c.docx"]
        assert len(result.failed) == 1

    def test_input_dir_is_created_if_absent(self, tmp_path):
        source = tmp_path / "a.docx"
        source.write_text("report", encoding="utf-8")
        input_dir = tmp_path / "brand" / "new" / "input"
        assert ing.ingest([source], input_dir).copied == ["a.docx"]
        assert (input_dir / "a.docx").exists()

    def test_nothing_to_ingest_is_not_an_error(self, tmp_path):
        result = ing.ingest([], tmp_path / "input")
        assert result.total == 0 and result.copied == []


class TestSummary:
    def test_the_headline_the_dashboard_shows(self):
        result = ing.IngestResult(copied=[f"r{i}.docx" for i in range(350)])
        assert result.summary() == "350 file(s) accepted. Ready to process."

    def test_skipped_files_are_surfaced_not_swallowed(self):
        """No-clobber only stays honest if the user can see it happened."""
        result = ing.IngestResult(copied=["a.docx"],
                                  skipped=[("b.docx", "already in input/")])
        assert "1 already present" in result.summary()

    def test_an_empty_drop_says_why(self):
        assert "no .docx or .pdf" in ing.IngestResult().summary()

    def test_a_cancelled_drop_does_not_claim_readiness(self):
        result = ing.IngestResult(copied=["a.docx"], cancelled=True)
        assert "cancelled" in result.summary().casefold()
        assert "Ready to process" not in result.summary()
