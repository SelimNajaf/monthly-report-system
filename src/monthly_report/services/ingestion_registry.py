"""Persistent ingestion registry — the O(1) metadata index behind STAGE 0-LAN.

Both share-sync engines in :mod:`network_ingestion` write one manifest,
``.state/network_sync_manifest.json``. This module owns it so there is a single
reader/writer instead of duplicate JSON handling on either side.

TWO MAPS, ONE FILE:

* ``entries`` — ``{sha256: {name, date, staged_at}}``. The cutoff engine's content
  index (``sync_since``), unchanged since schema 1.
* ``files`` — ``{normcase(unc_path): {unc_path, size, mtime, sha256, staged_at}}``.
  NEW in schema 2: a fingerprint per share file, so a repeat run answers "have I
  already ingested this exact file?" from local JSON in O(1) with **zero** SMB
  transfer. ``size`` and ``mtime`` come straight off the ``os.scandir`` DirEntry
  that enumerated the folder — on Windows those are carried in the directory
  listing itself, so reading them costs no extra round-trip.

Why the metadata triple and not just the hash: hashing needs the file's BYTES, which
over SMB is the very transfer this is meant to avoid. ``(unc_path, size, mtime)``
is free at enumeration time, and a mismatch on either number is exactly the signal
that a report was edited on the share — the case the old filename-stem index missed
entirely, leaving the local copy silently stale. ``sha256`` is still recorded when
a copy actually happened (it is computed locally, off the staged file), so content
dedup keeps working; ``None`` simply means "not known without a transfer".

DEGRADES, NEVER RAISES. A missing, corrupt or future-version manifest loads as
empty — the sync then re-derives dedup from the live local index and rebuilds the
registry for free from the next walk's metadata, exactly as :mod:`parse_cache`
treats an unreadable entry as a miss. (Deliberately NOT ``upload_ledger``'s
raise-on-corrupt discipline: a damaged ledger could double-upload, while a damaged
ingestion registry can only cost one slow run.)
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Bumped from 1 when the ``files`` map was added. A schema-1 manifest still loads:
#: its ``entries``/``cutoff`` are preserved and ``files`` simply starts empty.
SCHEMA_VERSION = 2

#: Manifest location relative to the project root — the path
#: ``reset_and_sync_input.py`` already uses.
DEFAULT_REGISTRY_REL = Path(".state") / "network_sync_manifest.json"

#: Timestamps survive a network copy only to the coarser filesystem's resolution
#: (FAT/SMB round to 2s), so an exact float compare would call every file modified.
MTIME_TOLERANCE_S = 2.0


@dataclass(frozen=True)
class FileRecord:
    """One share file's fingerprint as of the run that last ingested it."""

    unc_path: str
    size: int
    mtime: float
    sha256: str | None
    staged_at: str

    def to_json(self) -> dict:
        return {
            "unc_path": self.unc_path,
            "size": self.size,
            "mtime": self.mtime,
            "sha256": self.sha256,
            "staged_at": self.staged_at,
        }

    @classmethod
    def from_json(cls, data) -> "FileRecord | None":
        """Rebuild a record, or ``None`` when the stored shape is unusable.

        A single malformed record is dropped rather than failing the load — it just
        re-fingerprints on the next walk.
        """
        if not isinstance(data, dict):
            return None
        try:
            size = int(data["size"])
            mtime = float(data["mtime"])
        except (KeyError, TypeError, ValueError):
            return None
        digest = data.get("sha256")
        return cls(
            unc_path=str(data.get("unc_path", "")),
            size=size,
            mtime=mtime,
            sha256=str(digest) if digest else None,
            staged_at=str(data.get("staged_at", "")),
        )


def _key(unc_path) -> str:
    """Index key for a share path — case-folded the way Windows compares paths."""
    return os.path.normcase(str(unc_path))


def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def read_manifest(path) -> dict:
    """Return the raw manifest dict; ``{}`` when absent, corrupt or a newer schema."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    version = data.get("version")
    if not isinstance(version, int) or version > SCHEMA_VERSION:
        return {}     # written by a newer build — do not guess at its shape
    return data


def write_manifest(path, payload: dict) -> None:
    """Persist ``payload`` atomically (temp file + fsync + ``os.replace``).

    Same durable-write shape as :meth:`upload_ledger.UploadLedger._flush` and
    :meth:`parse_cache.ParseCache.put` — a crash mid-write leaves the previous good
    manifest intact, never a truncated one.
    """
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=str(path.parent),
                prefix=path.name + ".", suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
        tmp_name = None
    finally:
        if tmp_name is not None and os.path.exists(tmp_name):
            os.unlink(tmp_name)


class IngestionRegistry:
    """The manifest, in memory: the ``files`` fingerprint index + the ``entries`` map.

    Mutations are in memory; :meth:`save` writes once, at the end of a sync, so a
    thousand-file walk costs one atomic write rather than a thousand.
    """

    def __init__(self, path, files=None, entries=None, cutoff=None) -> None:
        self.path = Path(path)
        self._files: dict[str, FileRecord] = dict(files or {})
        #: Round-tripped untouched for the cutoff engine, which owns them.
        self.entries: dict = dict(entries or {})
        self.cutoff = cutoff
        self._dirty = False

    # -- construction ---------------------------------------------------------

    @classmethod
    def load(cls, path) -> "IngestionRegistry":
        """Load the manifest at ``path``; an unusable one yields an empty registry."""
        data = read_manifest(path)
        raw_files = data.get("files")
        files: dict[str, FileRecord] = {}
        if isinstance(raw_files, dict):
            for key, value in raw_files.items():
                record = FileRecord.from_json(value)
                if record is not None:
                    files[_key(key)] = record
        raw_entries = data.get("entries")
        entries = raw_entries if isinstance(raw_entries, dict) else {}
        return cls(path, files=files, entries=entries, cutoff=data.get("cutoff"))

    # -- the O(1) query -------------------------------------------------------

    def get(self, unc_path) -> FileRecord | None:
        """The fingerprint recorded for ``unc_path``, or ``None`` if never ingested."""
        return self._files.get(_key(unc_path))

    def is_unchanged(self, unc_path, size: int, mtime: float) -> bool:
        """True when ``(size, mtime)`` still match the recorded fingerprint.

        The whole point of the registry: a True here skips the file with no stem
        scan, no hash and no byte off the network.
        """
        record = self._files.get(_key(unc_path))
        if record is None:
            return False
        return (record.size == size
                and abs(record.mtime - mtime) <= MTIME_TOLERANCE_S)

    # -- mutation -------------------------------------------------------------

    def record(self, unc_path, size: int, mtime: float,
               sha256: str | None = None) -> FileRecord:
        """Fingerprint ``unc_path`` as ingested now, returning the stored record.

        ``sha256`` is optional: a file skipped on the local-filename index was never
        transferred, so its content hash is unknown and stays ``None``. The metadata
        triple alone is enough for the O(1) skip on the next run. A previously known
        hash is NOT dropped by a later ``None`` — re-fingerprinting an untransferred
        file must not lose content evidence the store already had.
        """
        key = _key(unc_path)
        if sha256 is None:
            previous = self._files.get(key)
            if previous is not None and previous.size == size:
                sha256 = previous.sha256
        record = FileRecord(unc_path=str(unc_path), size=int(size),
                            mtime=float(mtime), sha256=sha256, staged_at=_now())
        self._files[key] = record
        self._dirty = True
        return record

    def forget(self, unc_path) -> bool:
        """Drop a fingerprint (the file left the share). True when one was removed."""
        if self._files.pop(_key(unc_path), None) is None:
            return False
        self._dirty = True
        return True

    def set_entries(self, entries: dict, cutoff=None) -> None:
        """Replace the cutoff engine's content map (and optionally its cutoff)."""
        self.entries = dict(entries)
        if cutoff is not None:
            self.cutoff = cutoff
        self._dirty = True

    # -- persistence ----------------------------------------------------------

    def save(self, cutoff=None) -> None:
        """Write the manifest, preserving both maps. ``cutoff`` overrides the stored one."""
        if cutoff is not None:
            self.cutoff = cutoff
        stored_cutoff = self.cutoff
        if hasattr(stored_cutoff, "isoformat"):
            stored_cutoff = stored_cutoff.isoformat()
        payload = {
            "version": SCHEMA_VERSION,
            "cutoff": stored_cutoff,
            "entries": self.entries,
            "files": {key: rec.to_json() for key, rec in sorted(self._files.items())},
        }
        write_manifest(self.path, payload)
        self._dirty = False

    # -- introspection --------------------------------------------------------

    @property
    def files(self) -> dict[str, FileRecord]:
        return dict(self._files)

    def __len__(self) -> int:
        return len(self._files)

    def __contains__(self, unc_path) -> bool:
        return _key(unc_path) in self._files
