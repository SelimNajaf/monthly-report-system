"""Capturing why a file was quarantined, from the pipeline's console line.

No Qt: ``quarantine_reasons_service`` is a regex over stdout plus a small atomic JSON
read/write, so parse and record→load pin without a display. The state directory is
redirected to ``tmp_path`` so a test never touches the real one.
"""

from __future__ import annotations

import pytest

from monthly_report.gui.services import app_paths, quarantine_reasons_service as svc


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "state_dir", lambda: tmp_path / ".state")


class TestParse:
    def test_parses_the_moved_line(self):
        line = "  [quarantine] scan.docx: no readable text (scanned image) -> input/SKIPPED_REPORTS/"
        assert svc.parse_line(line) == ("scan.docx", "OCR Needed")

    def test_parses_the_name_conflict_variant(self):
        line = "  [quarantine] old.docx: no detectable inspection date (name conflict — left in place)"
        assert svc.parse_line(line) == ("old.docx", "Undatable")

    def test_unreadable_maps_to_its_tag(self):
        line = "  [quarantine] broken.docx: unreadable -> input/SKIPPED_REPORTS/"
        assert svc.parse_line(line) == ("broken.docx", "Unreadable")

    def test_a_non_quarantine_line_is_none(self):
        assert svc.parse_line("Parsing report A") is None

    def test_unknown_reason_falls_back_to_neutral(self):
        line = "  [quarantine] x.docx: something the map never heard of -> input/SKIPPED_REPORTS/"
        assert svc.parse_line(line) == ("x.docx", svc.DEFAULT_TAG)


class TestRoundTrip:
    def test_record_then_load_returns_the_tag(self):
        svc.record("a.docx", "OCR Needed")
        assert svc.load() == {"a.docx": "OCR Needed"}

    def test_record_merges_rather_than_replaces(self):
        svc.record("a.docx", "OCR Needed")
        svc.record("b.docx", "Undatable")
        assert svc.load() == {"a.docx": "OCR Needed", "b.docx": "Undatable"}

    def test_record_creates_the_state_dir(self, tmp_path):
        assert not (tmp_path / ".state").exists()
        svc.record("a.docx", "Unreadable")
        assert (tmp_path / ".state").is_dir()


class TestFallbacks:
    def test_load_is_empty_when_never_recorded(self):
        assert svc.load() == {}

    def test_load_is_empty_on_corrupt_file(self, tmp_path):
        state = tmp_path / ".state"
        state.mkdir(parents=True)
        (state / "quarantine_reasons.json").write_text("{not json", encoding="utf-8")
        assert svc.load() == {}
