"""The ledger reset empties the ledger — it does not delete or reshape it.

Three properties are worth a test, and they are the three an operator's data
depends on:

* **the file survives, valid and empty.** ``UploadLedger.load`` reads a MISSING file
  as a clean first run but raises on an unparseable one, so "reset" must land on a
  present, schema-correct, entry-free file — not on a deleted one, and never on a
  half-written one.
* **it refuses by default.** Emptying the ledger before the portal drafts are gone
  files a duplicate government appeal. ``--yes`` is the gate; ``--dry-run`` is the
  look-first path, and neither may write when it says it will not.
* **it fails closed on a corrupt ledger,** for the same reason ``UploadLedger.load``
  does: overwriting state nobody can read destroys the only record of what was sent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import reset_upload_ledger                                        # noqa: E402
from monthly_report.upload_ledger import (SCHEMA_VERSION,         # noqa: E402
                                          UploadLedger)


@pytest.fixture
def ledger_path(tmp_path):
    """A ledger holding one UPLOADED and one IN_PROGRESS report."""
    path = tmp_path / ".upload_state.json"
    ledger = UploadLedger.load(path)
    ledger.mark_uploaded("output/UT/UBOC/a.pdf", "hash-a", "MR-UT-UBOC-26-01")
    ledger.mark_in_progress("output/DP/KHF/b.pdf", "hash-b", "MR-DP-KHF-25-12")
    assert len(UploadLedger.load(path)) == 2
    return path


def _run(path, *flags) -> int:
    return reset_upload_ledger.main(["--ledger", str(path), *flags])


# --------------------------------------------------------------------------- #
# The reset itself
# --------------------------------------------------------------------------- #
def test_the_ledger_is_emptied_but_not_deleted(ledger_path):
    assert _run(ledger_path, "--yes") == 0
    assert ledger_path.is_file(), "the ledger file must survive a reset"
    assert len(UploadLedger.load(ledger_path)) == 0


def test_the_emptied_file_keeps_the_schema(ledger_path):
    """A bare `{}` or a deleted file would both read as 'empty' to a human and
    differently to the loader. The written shape is the loader's own."""
    _run(ledger_path, "--yes")
    raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert raw == {"version": SCHEMA_VERSION, "entries": {}}


def test_every_status_is_forgotten_including_in_progress(ledger_path):
    """IN_PROGRESS is the ambiguous one; a reset means the operator has resolved it
    on the portal, so it goes too — leaving it would keep that report BLOCKED."""
    _run(ledger_path, "--yes")
    assert UploadLedger.load(ledger_path).recorded_keys() == frozenset()


def test_the_count_is_reported(ledger_path, capsys):
    _run(ledger_path, "--yes")
    assert "2 entry(ies) forgotten" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The brakes
# --------------------------------------------------------------------------- #
def test_it_refuses_to_write_without_yes(ledger_path):
    with pytest.raises(SystemExit):
        _run(ledger_path)
    assert len(UploadLedger.load(ledger_path)) == 2, "a refusal must not write"


def test_dry_run_writes_nothing(ledger_path, capsys):
    before = ledger_path.read_bytes()
    assert _run(ledger_path, "--dry-run") == 0
    assert ledger_path.read_bytes() == before
    out = capsys.readouterr().out
    assert "DRY RUN" in out
    assert "output/UT/UBOC/a.pdf" in out and "output/DP/KHF/b.pdf" in out


def test_dry_run_ignores_yes(ledger_path):
    """--dry-run wins: 'show me' and 'do it' together must not do it."""
    _run(ledger_path, "--dry-run", "--yes")
    assert len(UploadLedger.load(ledger_path)) == 2


# --------------------------------------------------------------------------- #
# Edge cases
# --------------------------------------------------------------------------- #
def test_a_missing_ledger_is_a_clean_no_op(tmp_path):
    missing = tmp_path / "nope.json"
    assert _run(missing, "--yes") == 0
    assert not missing.exists(), "a first run has no state; do not fabricate a file"


def test_an_already_empty_ledger_is_a_no_op(ledger_path, capsys):
    _run(ledger_path, "--yes")
    capsys.readouterr()
    assert _run(ledger_path, "--yes") == 0
    assert "already empty" in capsys.readouterr().out


def test_a_corrupt_ledger_is_refused_not_overwritten(tmp_path):
    corrupt = tmp_path / ".upload_state.json"
    corrupt.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(corrupt, "--yes")
    assert corrupt.read_text(encoding="utf-8") == "{not json"


def test_a_foreign_schema_version_is_refused(tmp_path):
    future = tmp_path / ".upload_state.json"
    future.write_text(json.dumps({"version": SCHEMA_VERSION + 1, "entries": {}}),
                      encoding="utf-8")
    with pytest.raises(SystemExit):
        _run(future, "--yes")


# --------------------------------------------------------------------------- #
# What it must NOT touch
# --------------------------------------------------------------------------- #
def test_the_script_never_imports_the_uploader():
    """ADR-002: the uploader is frozen against refactoring, and this script has no
    business inside it — the ledger API is the whole contract."""
    source = (_ROOT / "reset_upload_ledger.py").read_text(encoding="utf-8")
    assert "import uploader" not in source
    assert "from uploader" not in source
