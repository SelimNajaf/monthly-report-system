"""The State Registry's one writer: clearing a stalled ledger entry.

``ledger_service`` is otherwise read-only; :func:`reset_entry` is the exception, and it
must behave exactly like the hand-edit it replaces — delete one key, leave the rest, and
never silently reset a ledger it cannot read. These pin that, going through the real
``UploadLedger`` so the atomic-flush path is exercised, not a stub.
"""

from __future__ import annotations

import json

import pytest

from monthly_report.gui.services import ledger_service
from monthly_report.upload_ledger import (SCHEMA_VERSION, STATUS_IN_PROGRESS,
                                          STATUS_UPLOADED, LedgerError,
                                          UploadLedger)


@pytest.fixture
def ledger_path(tmp_path):
    """A ledger with one stalled and one completed entry, flushed to disk."""
    path = tmp_path / ".upload_state.json"
    ledger = UploadLedger.load(path)
    ledger.mark_in_progress("output/RT/KHF/report_a.json", "hashA", "SER-A")
    ledger.mark_uploaded("output/MT/AZF/report_b.json", "hashB", "SER-B")
    return path


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_reset_removes_the_selected_key(ledger_path):
    cleared = ledger_service.reset_entry(ledger_path, "output/RT/KHF/report_a.json")
    assert cleared is True
    entries = _read(ledger_path)
    assert "output/RT/KHF/report_a.json" not in entries
    assert "output/MT/AZF/report_b.json" in entries      # the other row survives


def test_reset_missing_key_is_false_and_a_noop(ledger_path):
    before = _read(ledger_path)
    cleared = ledger_service.reset_entry(ledger_path, "output/nope.json")
    assert cleared is False
    assert _read(ledger_path) == before


def test_reset_on_missing_file_is_false(tmp_path):
    # A never-created ledger loads as empty; the key is simply absent.
    assert ledger_service.reset_entry(tmp_path / "absent.json", "anything") is False


def test_reset_refuses_a_corrupt_ledger(tmp_path):
    bad = tmp_path / ".upload_state.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    with pytest.raises(LedgerError):
        ledger_service.reset_entry(bad, "any")


def test_reset_targets_are_the_stalled_rows(ledger_path):
    # The GUI arms Reset only for is_stalled rows; confirm which rows those are so the
    # button's gate matches the ledger's own IN_PROGRESS semantics.
    view = ledger_service.read(ledger_path)
    stalled = [r.key for r in view.rows if r.is_stalled]
    assert stalled == ["output/RT/KHF/report_a.json"]
    assert view.stalled == 1
