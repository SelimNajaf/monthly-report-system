"""Read-only projection of the upload ledger for the State Registry table.

``UploadLedger`` is built for the uploader's needs — decide, checkpoint, flush —
and keeps its entries private because nothing in the pipeline should be walking
them. A table does need to walk them, so this reads the file directly, using the
ledger module's own public names (``SCHEMA_VERSION``, ``Entry.from_dict``,
``LedgerError``) rather than re-describing the schema.

Reading is the whole job save one action. :func:`reset_entry` is the single writer
here, and it exists for exactly the failure the ledger flags but cannot fix on its
own: a stalled ``IN_PROGRESS`` row left by a run that died mid-submit. Clearing it
re-queues that one report for the next run — the manual-recovery path
:class:`UploadLedger` was designed around (upload_ledger.py:232-242), surfaced as a
table button instead of a hand-edit. It goes through the ledger's own atomic
``reset``/``_flush``, so it cannot corrupt the file the uploader depends on.

I/O contract
------------
ledger_path(root, dry_run) -> Path
read(path) -> LedgerView          # never raises for a missing file
reset_entry(path, key) -> bool    # delete one key; raises LedgerError on a bad file
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from monthly_report.upload_ledger import (SCHEMA_VERSION, STATUS_IN_PROGRESS,
                                          STATUS_UPLOADED, Entry, LedgerError,
                                          UploadLedger)

#: Filenames chosen by uploader._ledger_path (uploader.py:403). A dry run keeps
#: its own ledger so simulating a batch can never mask a real pending upload.
LIVE_LEDGER = ".upload_state.json"
DRYRUN_LEDGER = ".upload_state.dryrun.json"


@dataclass(frozen=True)
class Row:
    """One ledger entry, flattened for display."""

    key: str          # project-root-relative POSIX path of the PDF
    status: str
    serial: str
    updated_at: str
    content_hash: str

    @property
    def short_hash(self) -> str:
        return self.content_hash[:8] if self.content_hash else ""

    @property
    def name(self) -> str:
        """Just the filename — the full key is too wide for a column."""
        return self.key.rsplit("/", 1)[-1]

    @property
    def is_stalled(self) -> bool:
        """A leftover IN_PROGRESS means a process died mid-submit.

        The ledger treats this as unresolvable without a human (upload_ledger.py:
        28-29, 201) — the portal may or may not have the report. Worth a badge.
        """
        return self.status == STATUS_IN_PROGRESS


@dataclass(frozen=True)
class LedgerView:
    """What the registry tab shows, including the reasons it might show nothing."""

    path: Path
    rows: tuple[Row, ...] = ()
    exists: bool = False
    error: str = ""

    @property
    def uploaded(self) -> int:
        return sum(1 for r in self.rows if r.status == STATUS_UPLOADED)

    @property
    def stalled(self) -> int:
        return sum(1 for r in self.rows if r.is_stalled)


def ledger_path(root: Path, dry_run: bool = False) -> Path:
    """Where the uploader keeps its state, for the given mode."""
    return Path(root) / (DRYRUN_LEDGER if dry_run else LIVE_LEDGER)


def read(path: Path) -> LedgerView:
    """Load the ledger for display.

    A missing file is a first run, not an error — the registry renders an empty
    state. A file that exists but does not parse *is* an error and is reported as
    one, matching ``UploadLedger.load``'s refusal to treat corruption as
    emptiness (upload_ledger.py:140-164).
    """
    path = Path(path)
    if not path.is_file():
        return LedgerView(path=path, exists=False)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise LedgerError("ledger is not a JSON object")

        version = raw.get("version")
        if version != SCHEMA_VERSION:
            raise LedgerError(
                f"ledger schema version {version!r} is not supported "
                f"(this build expects {SCHEMA_VERSION})")

        entries = raw.get("entries") or {}
        if not isinstance(entries, dict):
            raise LedgerError("ledger 'entries' is not an object")

        rows = tuple(_row(key, Entry.from_dict(value))
                     for key, value in sorted(entries.items())
                     if isinstance(value, dict))
        return LedgerView(path=path, rows=rows, exists=True)

    except (LedgerError, json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return LedgerView(path=path, exists=True, error=str(exc))


def _row(key: str, entry: Entry) -> Row:
    return Row(key=key, status=entry.status, serial=entry.serial,
               updated_at=entry.updated_at, content_hash=entry.content_hash)


def reset_entry(path: Path, key: str) -> bool:
    """Forget one report so the next run re-uploads it. True if the key was present.

    Delegates to :meth:`UploadLedger.reset`, which deletes the key and flushes
    atomically (upload_ledger.py:232-242) — the same write the uploader trusts, so a
    reset can never leave a half-written ledger. A missing file loads as empty and the
    key is simply absent (returns False); an *unreadable* file raises ``LedgerError``
    rather than being silently reset to empty, matching :func:`read`'s refusal to treat
    corruption as emptiness.
    """
    ledger = UploadLedger.load(path)   # raises LedgerError on a corrupt/foreign file
    return ledger.reset(key)
