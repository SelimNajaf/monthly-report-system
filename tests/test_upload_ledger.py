"""Tests for the upload idempotency ledger.

The whole point of this module is to prevent a duplicate portal submission, so the
decision matrix is pinned exhaustively here — it can be exercised with no browser,
no portal, and no compiled report.
"""

import json

import pytest

from monthly_report.upload_ledger import (STATUS_IN_PROGRESS, STATUS_UPLOADED,
                                          Action, LedgerError, UploadLedger,
                                          hash_report)

_KEY = "output/MPI/KHF/compiled_monthly_report_MT_KHF_FEB_2026.pdf"
_HASH = "a" * 64
_OTHER_HASH = "b" * 64


@pytest.fixture
def ledger(tmp_path):
    return UploadLedger(tmp_path / ".upload_state.json")


@pytest.fixture
def report(tmp_path):
    """A (sidecar, pdf) pair on disk, as main.py would have produced."""
    sidecar = tmp_path / "report.json"
    sidecar.write_text('{"client_name": "Khazar Fabrication"}', encoding="utf-8")
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 original")
    return sidecar, pdf


# ------------------------------------------------------------- decision matrix --
def test_unknown_report_uploads(ledger):
    action, reason = ledger.decide(_KEY, _HASH)
    assert action is Action.UPLOAD
    assert "not uploaded yet" in reason


def test_uploaded_and_unchanged_skips(ledger):
    """Failure mode 2: running the uploader twice must be a no-op."""
    ledger.mark_uploaded(_KEY, _HASH)
    action, reason = ledger.decide(_KEY, _HASH)
    assert action is Action.SKIP
    assert "already uploaded" in reason


def test_uploaded_but_content_changed_re_uploads(ledger):
    """Failure mode 3: a regenerated report must not be skipped forever."""
    ledger.mark_uploaded(_KEY, _HASH)
    action, reason = ledger.decide(_KEY, _OTHER_HASH)
    assert action is Action.UPLOAD
    assert "content changed" in reason


def test_interrupted_upload_is_blocked_not_retried(ledger):
    """The ambiguous window: the portal may or may not already hold this row."""
    ledger.mark_in_progress(_KEY, _HASH)
    action, reason = ledger.decide(_KEY, _HASH)
    assert action is Action.BLOCKED
    assert "--force" in reason


def test_force_overrides_a_blocked_report(ledger):
    ledger.mark_in_progress(_KEY, _HASH)
    action, reason = ledger.decide(_KEY, _HASH, force=True)
    assert action is Action.UPLOAD
    assert "forced by operator" in reason


def test_force_does_not_resurrect_an_already_uploaded_report(ledger):
    """--force unblocks the INTERRUPTED window and nothing else.

    The safeguard the resume command rests on: `--live --all --force` re-offers the
    reports that died mid-submit, and still skips every report already on the portal.
    A --force that reached this branch would duplicate every past upload at once.
    """
    ledger.mark_uploaded(_KEY, _HASH)
    action, reason = ledger.decide(_KEY, _HASH, force=True)
    assert action is Action.SKIP
    assert "already uploaded, unchanged" in reason


def test_interrupted_but_regenerated_uploads_without_force(ledger):
    # Whatever the portal may hold is stale either way, so re-uploading is the only
    # useful move — no operator confirmation needed.
    ledger.mark_in_progress(_KEY, _HASH)
    action, _reason = ledger.decide(_KEY, _OTHER_HASH)
    assert action is Action.UPLOAD


def test_unrecognised_status_blocks_rather_than_uploads(ledger, tmp_path):
    path = tmp_path / "weird.json"
    path.write_text(json.dumps({
        "version": 1,
        "entries": {_KEY: {"status": "WAT", "content_hash": _HASH}},
    }), encoding="utf-8")
    action, reason = UploadLedger.load(path).decide(_KEY, _HASH)
    assert action is Action.BLOCKED
    assert "unrecognised" in reason


# ------------------------------------------------------- resume / checkpointing --
def test_state_survives_a_new_process(ledger):
    """The checkpoint is only real if it is on disk before the run ends."""
    ledger.mark_uploaded(_KEY, _HASH, serial="MR-MT-KHF-26-02")
    reloaded = UploadLedger.load(ledger.path)
    entry = reloaded.get(_KEY)
    assert entry.status == STATUS_UPLOADED
    assert entry.serial == "MR-MT-KHF-26-02"
    assert entry.updated_at            # stamped, for the operator's benefit
    assert reloaded.decide(_KEY, _HASH)[0] is Action.SKIP


def test_batch_interrupted_after_the_fourth_resumes_at_the_fifth(ledger):
    """Failure mode 1, end to end, as the ledger sees it."""
    keys = [f"output/r{i}.pdf" for i in range(1, 11)]
    for key in keys[:4]:                       # 1-4 completed
        ledger.mark_uploaded(key, _HASH)
    ledger.mark_in_progress(keys[4], _HASH)    # 5 died mid-submit

    resumed = UploadLedger.load(ledger.path)
    actions = [resumed.decide(k, _HASH)[0] for k in keys]

    assert actions[:4] == [Action.SKIP] * 4          # never re-sent
    assert actions[4] is Action.BLOCKED              # ambiguous — operator decides
    assert actions[5:] == [Action.UPLOAD] * 5        # untouched, resume freely


def test_mark_in_progress_then_uploaded_transitions(ledger):
    ledger.mark_in_progress(_KEY, _HASH)
    assert ledger.get(_KEY).status == STATUS_IN_PROGRESS
    ledger.mark_uploaded(_KEY, _HASH)
    assert ledger.get(_KEY).status == STATUS_UPLOADED


def test_reset_forgets_one_report(ledger):
    ledger.mark_uploaded(_KEY, _HASH)
    assert ledger.reset(_KEY) is True
    assert ledger.get(_KEY) is None
    assert ledger.decide(_KEY, _HASH)[0] is Action.UPLOAD
    assert ledger.reset(_KEY) is False            # already gone — not an error


def test_reset_is_persisted(ledger):
    ledger.mark_uploaded(_KEY, _HASH)
    ledger.reset(_KEY)
    assert UploadLedger.load(ledger.path).get(_KEY) is None


# ------------------------------------------------------------------- restore --
# The undo of a checkpoint. An interactive operator who declines a save must be
# left a ledger indistinguishable from the one the run started with.
def test_restore_puts_a_checkpointed_entry_back_untouched(ledger):
    ledger.mark_uploaded(_KEY, _HASH, serial="MR-MT-KHF-26-02")
    before = ledger.get(_KEY)

    ledger.mark_in_progress(_KEY, _OTHER_HASH, "MR-MT-KHF-26-02")
    ledger.restore(_KEY, before)
    after = ledger.get(_KEY)

    assert (after.status, after.content_hash, after.serial) == (
        STATUS_UPLOADED, _HASH, "MR-MT-KHF-26-02")
    assert after.updated_at == before.updated_at, (
        "this is the erasure of an event, not a new one — the timestamp must not "
        "move, or the next run reads a time for an upload nobody attempted")


def test_restoring_a_key_that_did_not_exist_removes_it(ledger):
    """The common case: a first-time report the operator declined at the prompt."""
    before = ledger.get(_KEY)                      # None — never seen
    ledger.mark_in_progress(_KEY, _HASH)

    ledger.restore(_KEY, before)

    assert ledger.get(_KEY) is None
    assert ledger.decide(_KEY, _HASH)[0] is Action.UPLOAD, (
        "a declined report must stay offerable, not become BLOCKED")


def test_restore_is_persisted(ledger):
    ledger.mark_uploaded(_KEY, _HASH)
    before = ledger.get(_KEY)
    ledger.mark_in_progress(_KEY, _OTHER_HASH)

    ledger.restore(_KEY, before)

    reloaded = UploadLedger.load(ledger.path).get(_KEY)
    assert (reloaded.status, reloaded.content_hash) == (STATUS_UPLOADED, _HASH)


def test_a_checkpoint_and_its_restore_leave_the_file_byte_identical(ledger):
    """The guarantee stated as the operator experiences it: nothing happened."""
    ledger.mark_uploaded(_KEY, _HASH, serial="MR-MT-KHF-26-02")
    original = ledger.path.read_bytes()

    ledger.restore(_KEY, ledger.get(_KEY))

    assert ledger.path.read_bytes() == original


def test_flush_leaves_no_temp_debris(ledger):
    ledger.mark_uploaded(_KEY, _HASH)
    siblings = list(ledger.path.parent.iterdir())
    assert siblings == [ledger.path]


def test_ledger_file_is_readable_and_hand_editable(ledger):
    """Manual recovery is a design requirement, not an accident."""
    ledger.mark_uploaded(_KEY, _HASH, serial="MR-MT-KHF-26-02")
    raw = json.loads(ledger.path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["entries"][_KEY]["status"] == "UPLOADED"
    # Delete the key by hand -> the report uploads again.
    del raw["entries"][_KEY]
    ledger.path.write_text(json.dumps(raw), encoding="utf-8")
    assert UploadLedger.load(ledger.path).decide(_KEY, _HASH)[0] is Action.UPLOAD


# ----------------------------------------------------------------- corruption --
def test_missing_ledger_is_an_empty_first_run(tmp_path):
    fresh = UploadLedger.load(tmp_path / "nope.json")
    assert len(fresh) == 0
    assert fresh.decide(_KEY, _HASH)[0] is Action.UPLOAD


def test_corrupt_ledger_raises_rather_than_silently_re_uploading(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(LedgerError, match="unreadable"):
        UploadLedger.load(path)


def test_unknown_schema_version_raises(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(json.dumps({"version": 99, "entries": {}}), encoding="utf-8")
    with pytest.raises(LedgerError, match="schema version"):
        UploadLedger.load(path)


# ---------------------------------------------------------------- hashing --
def test_hash_is_stable_when_nothing_changes(report):
    sidecar, pdf = report
    assert hash_report(sidecar, pdf) == hash_report(sidecar, pdf)


def test_hash_changes_when_the_pdf_is_regenerated(report):
    sidecar, pdf = report
    before = hash_report(sidecar, pdf)
    pdf.write_bytes(b"%PDF-1.4 corrected")
    assert hash_report(sidecar, pdf) != before


def test_hash_changes_when_the_sidecar_is_corrected(report):
    sidecar, pdf = report
    before = hash_report(sidecar, pdf)
    sidecar.write_text('{"client_name": "Khazar Engineering"}', encoding="utf-8")
    assert hash_report(sidecar, pdf) != before


def test_hash_ignores_mtime(report):
    """Content addressing, not timestamps: a touch must not force a re-upload."""
    sidecar, pdf = report
    before = hash_report(sidecar, pdf)
    import os
    os.utime(pdf, (0, 0))
    assert hash_report(sidecar, pdf) == before


def test_hash_tolerates_a_missing_pdf(report):
    sidecar, pdf = report
    pdf.unlink()
    assert len(hash_report(sidecar, pdf)) == 64      # sidecar-only digest


def test_hash_requires_the_sidecar(tmp_path):
    with pytest.raises(FileNotFoundError):
        hash_report(tmp_path / "gone.json", None)


def test_modified_report_round_trip(ledger, report):
    """Failure mode 3 through the real hash: upload, correct, re-upload, settle."""
    sidecar, pdf = report
    first = hash_report(sidecar, pdf)
    ledger.mark_uploaded(_KEY, first)
    assert ledger.decide(_KEY, first)[0] is Action.SKIP

    pdf.write_bytes(b"%PDF-1.4 corrected after a data fix")
    second = hash_report(sidecar, pdf)
    action, reason = ledger.decide(_KEY, second)
    assert action is Action.UPLOAD and "content changed" in reason

    ledger.mark_uploaded(_KEY, second)
    assert ledger.decide(_KEY, second)[0] is Action.SKIP


def test_successful_submission_is_recorded_with_all_its_fields(tmp_path, report):
    """A committed upload persists serial, the SHA-256 over sidecar+PDF, an UPLOADED
    status and a timestamp — and a fresh process reading that file skips the report.

    The end-to-end shape requirement 2 asks for: the ledger key is the report's
    identity (its path), the content_hash is the SHA-256 of the sidecar's bytes
    followed by the PDF's, and a repeat run is an automatic no-op."""
    sidecar, pdf = report
    path = tmp_path / ".upload_state.json"
    content = hash_report(sidecar, pdf)
    assert content == hash_report(sidecar, pdf)            # deterministic SHA-256
    assert len(content) == 64                              # hex SHA-256 digest

    UploadLedger(path).mark_uploaded(_KEY, content, serial="MR-MT-KHF-26-02")

    reloaded = UploadLedger.load(path)                     # a brand-new process
    entry = reloaded.get(_KEY)
    assert entry.status == STATUS_UPLOADED
    assert entry.content_hash == content
    assert entry.serial == "MR-MT-KHF-26-02"
    assert entry.updated_at                                # stamped
    # The idempotency payoff: the second run skips without touching the portal.
    assert reloaded.decide(_KEY, content)[0] is Action.SKIP
