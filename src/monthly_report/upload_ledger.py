"""Durable upload state for the portal uploader — the idempotency ledger.

Why this exists
---------------
``uploader.py`` submits a compiled monthly report to the E-Keyfiyyet portal. That
submit is a *side effect on someone else's database*: doing it twice corrupts the
target. But runs are interrupted (dropped connections), repeated (an operator
re-runs the script), and invalidated (a report is regenerated after a data
correction and genuinely must go up again). The uploader therefore needs to know,
durably and across processes, what it has already sent and whether that thing has
changed since.

The pattern: a local JSON ledger, keyed by report, storing a content hash plus a
status. Chosen over a SQLite register (opaque to manual recovery, buys concurrency
guarantees a single-operator workflow never uses) and over per-report marker files
(state scattered across the output tree with no single view of what is outstanding).
This file is stdlib-only, human-readable, and hand-editable — resetting one report
is deleting one key.

Integrity, not timestamps
-------------------------
An entry records a SHA-256 over the sidecar's bytes *and* the PDF's bytes. Hashing
content rather than trusting mtime means a touch-without-edit does not trigger a
spurious re-upload, and an edit that happens to preserve mtime cannot slip through.

The two-phase status is the crux
--------------------------------
``IN_PROGRESS`` is written *before* the submit and ``UPLOADED`` *after*. A leftover
``IN_PROGRESS`` therefore means the process died mid-submit — and we cannot know
whether the portal committed the row. Retrying it blindly is precisely the duplicate
this module exists to prevent, so it is flagged and skipped until an operator passes
``--force``.

Be honest about the limit: without a portal-side idempotency key (see the README's
DevTools section on discovering the internal REST API), a client-side ledger gives
*at-most-once for reports that completed* plus an explicit flag on the single
in-flight report. It cannot be exactly-once from the client alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

# Ledger file format version. Bump only on a breaking schema change; `load` refuses
# a version it does not understand rather than silently misreading old state.
SCHEMA_VERSION = 1

# Status values persisted in the ledger.
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_UPLOADED = "UPLOADED"

# Where the uploader keeps its state (see uploader._ledger_path). Named here, in the
# module that owns the format, so a consumer whose only business with the ledger is
# to RESPECT it — main.py's stale-output sweeps must not delete a filed deliverable —
# need not import the uploader to learn the filename.
LIVE_LEDGER_NAME = ".upload_state.json"
DRYRUN_LEDGER_NAME = ".upload_state.dryrun.json"

_HASH_CHUNK = 1 << 20  # 1 MiB — bounded memory on large PDFs


class LedgerError(RuntimeError):
    """The ledger file exists but cannot be trusted.

    Raised instead of silently starting from a blank slate: an unreadable ledger
    that degraded to "no state" would re-upload every report in the tree, which is
    the exact failure this module prevents.
    """


class Action(str, Enum):
    """What the uploader should do with a report, per the ledger."""

    UPLOAD = "UPLOAD"    # never sent, or its content changed since it was sent
    SKIP = "SKIP"        # already sent, unchanged — the idempotent no-op
    BLOCKED = "BLOCKED"  # interrupted mid-submit; ambiguous, needs an operator


@dataclass
class Entry:
    """One report's recorded upload state."""

    status: str
    content_hash: str
    serial: str = ""
    updated_at: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "Entry":
        return cls(
            status=str(raw.get("status", "")),
            content_hash=str(raw.get("content_hash", "")),
            serial=str(raw.get("serial", "")),
            updated_at=str(raw.get("updated_at", "")),
        )


def hash_report(json_path: str | Path, pdf_path: str | Path | None = None) -> str:
    """SHA-256 over the sidecar's bytes followed by the PDF's bytes.

    Both files are hashed because both carry uploaded content: the PDF is the
    attachment, the sidecar drives every form field. A correction to either is a
    real change that must re-upload.

    A missing PDF is tolerated (a dry run may target a report whose twin is not on
    disk) — what exists is hashed, and the digest naturally changes if the PDF later
    appears. A missing sidecar is not tolerated: it is the report.
    """
    digest = hashlib.sha256()
    paths = [Path(json_path)]
    if pdf_path is not None:
        pdf = Path(pdf_path)
        if pdf.is_file():
            paths.append(pdf)
    for path in paths:
        with path.open("rb") as handle:
            while chunk := handle.read(_HASH_CHUNK):
                digest.update(chunk)
    return digest.hexdigest()


def ledger_key(pdf_path: str | Path, root: str | Path) -> str:
    """The ledger's identity for one report: its ``root``-relative POSIX path.

    The single definition of the key format. ``uploader`` WRITES keys in this shape
    and ``main.py`` must READ them in the same shape to know which compiled artifacts
    are already filed — two independent spellings of "relative POSIX path" would
    agree today and drift silently on the first edge case (a symlinked project root,
    an ``output_dir`` configured outside the tree). A path outside ``root`` keeps its
    absolute POSIX form, exactly as the uploader records it.
    """
    resolved = Path(pdf_path).resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def protected_keys(path: str | Path) -> frozenset[str]:
    """Keys whose compiled artifacts no NON-upload process may delete.

    Every key the ledger holds, regardless of status. A key exists only because
    :meth:`UploadLedger.mark_in_progress` announced a submit, so every key names
    bytes the E-Keyfiyyet portal may already hold: ``UPLOADED`` certainly does, and
    ``IN_PROGRESS`` is precisely the case nobody can answer (see the module docstring
    and :meth:`UploadLedger.decide`). Deleting either destroys the only local copy of
    what was sent; deleting the sidecar additionally breaks :func:`hash_report`,
    which does not tolerate a missing sidecar — the uploader could then no longer
    even re-decide the report. An unrecognised status is protected for the same
    reason ``decide`` calls it ``BLOCKED``: corrupt state is not a green light.

    Deliberately the mirror image of :meth:`UploadLedger.load`'s strictness. ``load``
    fails CLOSED because under-reporting uploads would re-submit them; this fails
    OPEN — a missing, unreadable or foreign-schema ledger yields an EMPTY set —
    because an unreadable UPLOAD ledger must never abort a COMPILE. Both directions
    of that asymmetry are chosen: the cost here is over-deleting output for a report
    whose ledger the operator has already broken, which is recoverable by re-running
    the compile. Never writes.
    """
    try:
        return UploadLedger.load(path).recorded_keys()
    except (LedgerError, OSError):
        return frozenset()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class UploadLedger:
    """Durable record of what has been uploaded, and of what content.

    Every mutation flushes to disk immediately and atomically. That flush *is* the
    checkpoint that makes a dropped batch resumable — state held only in memory
    until the end of the run would be lost by the very crash it must survive.
    """

    def __init__(self, path: str | Path, entries: dict[str, Entry] | None = None):
        self.path = Path(path)
        self._entries: dict[str, Entry] = dict(entries or {})

    # ---------------------------------------------------------------- loading --
    @classmethod
    def load(cls, path: str | Path) -> "UploadLedger":
        """Read the ledger, or start an empty one if the file does not exist yet.

        A *missing* file is a first run — normal, empty state. A file that exists
        but does not parse is an error, never an empty state (see LedgerError).
        """
        p = Path(path)
        if not p.is_file():
            return cls(p)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise LedgerError(
                f"Upload ledger is unreadable: {p}\n"
                f"  {exc}\n"
                f"Refusing to run: treating this as 'nothing uploaded' would "
                f"re-upload every report. Inspect or delete the file to reset."
            ) from exc
        if not isinstance(raw, dict):
            raise LedgerError(f"Upload ledger is not a JSON object: {p}")
        version = raw.get("version")
        if version != SCHEMA_VERSION:
            raise LedgerError(
                f"Upload ledger schema version {version!r} is not supported "
                f"(this build expects {SCHEMA_VERSION}): {p}")
        entries_raw = raw.get("entries", {})
        if not isinstance(entries_raw, dict):
            raise LedgerError(f"Upload ledger 'entries' is not an object: {p}")
        entries = {k: Entry.from_dict(v) for k, v in entries_raw.items()
                   if isinstance(v, dict)}
        return cls(p, entries)

    # ---------------------------------------------------------------- queries --
    def get(self, key: str) -> Entry | None:
        return self._entries.get(key)

    def __len__(self) -> int:
        return len(self._entries)

    def recorded_keys(self) -> frozenset[str]:
        """Every key the ledger holds — a read-only view over private state.

        Frozen, not a live view: a caller asking "which reports are filed?" must not
        be handed a handle it could mutate into a false answer.
        """
        return frozenset(self._entries)

    def decide(self, key: str, content_hash: str,
               force: bool = False) -> tuple[Action, str]:
        """Decide what to do with one report. Returns (action, human reason).

        The whole idempotency policy lives here, in one pure function, so it can be
        unit-tested without a browser, a portal, or a real report on disk.
        """
        entry = self._entries.get(key)

        if entry is None:
            return Action.UPLOAD, "not uploaded yet"

        changed = entry.content_hash != content_hash

        if entry.status == STATUS_UPLOADED:
            if changed:
                # Failure mode 3: the report was regenerated after a data
                # correction. Blindly skipping it would leave the portal holding
                # the stale version forever.
                return Action.UPLOAD, "content changed since last upload"
            return Action.SKIP, "already uploaded, unchanged"

        if entry.status == STATUS_IN_PROGRESS:
            if changed:
                # Regenerated since the interruption: whatever the portal may hold
                # is stale either way, so re-uploading is the only useful move.
                return Action.UPLOAD, "content changed since the interrupted upload"
            if force:
                return Action.UPLOAD, "interrupted upload, forced by operator"
            # The ambiguous window: we announced the submit but never recorded its
            # outcome. The portal may or may not hold this row.
            return Action.BLOCKED, (
                f"previous run was interrupted mid-upload "
                f"(started {entry.updated_at or 'unknown'}) — the portal may or may "
                f"not already have it. Verify on the portal, then re-run with "
                f"--force to send it anyway")

        # An unrecognised status is corrupt state, not a green light to upload.
        return Action.BLOCKED, f"unrecognised ledger status {entry.status!r}"

    # -------------------------------------------------------------- mutations --
    def mark_in_progress(self, key: str, content_hash: str, serial: str = "") -> None:
        """Record the intent to upload — called BEFORE the submit.

        Ordering is the point: if the process dies during the submit, this entry is
        what tells the next run that the outcome is unknown.
        """
        self._write_entry(key, STATUS_IN_PROGRESS, content_hash, serial)

    def mark_uploaded(self, key: str, content_hash: str, serial: str = "") -> None:
        """Record a confirmed, completed upload — called AFTER the submit."""
        self._write_entry(key, STATUS_UPLOADED, content_hash, serial)

    def reset(self, key: str) -> bool:
        """Forget one report, so the next run re-uploads it. True if it was present.

        The programmatic twin of deleting a key by hand — the manual-recovery path
        this design was chosen for.
        """
        if key not in self._entries:
            return False
        del self._entries[key]
        self._flush()
        return True

    def restore(self, key: str, entry: Entry | None) -> None:
        """Put one key back exactly as it was. The undo of a checkpoint.

        ``entry`` is what :meth:`get` returned BEFORE the checkpoint that is being
        rolled back: None means the key did not exist and must not exist now either.

        ``updated_at`` is carried over rather than refreshed, because this is not a
        new event in the report's life — it is the erasure of one that turned out
        not to have happened. An interactive operator who declines a save must leave
        a ledger indistinguishable from the one they started with, or the next run
        would read a timestamp for an upload nobody attempted.
        """
        if entry is None:
            self.reset(key)
            return
        self._entries[key] = Entry(status=entry.status,
                                   content_hash=entry.content_hash,
                                   serial=entry.serial,
                                   updated_at=entry.updated_at)
        self._flush()

    def _write_entry(self, key: str, status: str, content_hash: str,
                     serial: str) -> None:
        self._entries[key] = Entry(status=status, content_hash=content_hash,
                                   serial=serial, updated_at=_now())
        self._flush()

    def _flush(self) -> None:
        """Persist atomically: write a temp file, then rename over the target.

        ``os.replace`` is atomic on both POSIX and Windows, so a crash mid-write
        leaves the previous good ledger intact rather than a truncated one. Writing
        in the target's own directory keeps the rename on one filesystem.
        """
        payload = {
            "version": SCHEMA_VERSION,
            "entries": {k: asdict(v) for k, v in sorted(self._entries.items())},
        }
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_name = None
        try:
            # delete=False so the handle can be closed before the rename (required
            # on Windows, where an open file cannot be replaced).
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=str(self.path.parent),
                    prefix=self.path.name + ".", suffix=".tmp",
                    delete=False) as tmp:
                tmp_name = tmp.name
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())   # survive a power loss, not just a crash
            os.replace(tmp_name, self.path)
            tmp_name = None
        finally:
            if tmp_name is not None and os.path.exists(tmp_name):
                os.unlink(tmp_name)   # a failed write leaves no debris behind
