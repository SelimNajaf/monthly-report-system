"""The persistent parse cache, seen from the dashboard: is it on, how big, purge it.

The pipeline's parse cache (:mod:`monthly_report.parse_cache`) is a content-addressed
store of ``.docx`` parses that makes a recurring monthly run re-parse only new/changed
files. It is invisible from the GUI, which is a problem the day an operator wonders why
a run was instant, or needs to force a full re-parse after a bad batch.

This is the read-only window onto it, plus the one destructive action — purge — that a
Settings button exposes behind a confirmation. Nothing here parses or writes cache
entries; the pipeline owns that. We only count and delete, resolving the store's
location exactly as ``main.py`` does (``_ROOT / performance.parse_cache_dir``) so the
number shown is the number the next run will use.

I/O contract
------------
status(settings) -> CacheStatus       # never raises on a cold/missing store
purge(settings) -> int                # entries deleted; best-effort, never fatal
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from monthly_report import parse_cache


@dataclass(frozen=True)
class CacheStatus:
    """What the dashboard chip shows about the parse cache."""

    enabled: bool          # performance.parse_cache — false means every run re-parses
    entries: int           # *.json entries currently stored
    size_bytes: int        # total on-disk size of those entries

    @property
    def size_label(self) -> str:
        kb = self.size_bytes / 1024
        if kb < 1:
            return f"{self.size_bytes} B"
        return f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"

    @property
    def summary(self) -> str:
        """One line for the chip: state first, then size when there is any."""
        if not self.enabled:
            return "Parse cache: off"
        if not self.entries:
            return "Parse cache: on · empty"
        return f"Parse cache: on · {self.entries} entries · {self.size_label}"


def _cache_dir(settings) -> Path:
    """Resolve the store's location the way ``main.py`` does (main.py:198-199).

    ``parse_cache_dir`` is relative to the project root, so the count and purge here
    target the very directory a pipeline run reads and writes — not some sibling path.
    """
    performance = (settings.raw.get("performance") or {}) if settings.raw else {}
    name = str(performance.get("parse_cache_dir", parse_cache.DEFAULT_CACHE_DIRNAME))
    return Path(settings.project_root) / name


def _enabled(settings) -> bool:
    performance = (settings.raw.get("performance") or {}) if settings.raw else {}
    return bool(performance.get("parse_cache", True))


def status(settings) -> CacheStatus:
    """Count the store's entries and size. A cold/missing store is empty, not an error.

    Each entry is one ``<sha256>.json`` (parse_cache.py:93); a file that vanishes
    mid-scan is skipped rather than raising, matching the listing discipline of
    :mod:`quarantine_service`.
    """
    directory = _cache_dir(settings)
    entries = 0
    size = 0
    if directory.is_dir():
        for entry in directory.glob("*.json"):
            try:
                size += entry.stat().st_size
            except OSError:
                continue   # vanished mid-scan; a status read must not raise
            entries += 1
    return CacheStatus(enabled=_enabled(settings), entries=entries, size_bytes=size)


def purge(settings) -> int:
    """Delete every stored parse. Returns the count removed. Best-effort, never fatal.

    Mirrors :meth:`parse_cache.ParseCache.gc`'s deletion posture — a locked entry is
    left behind rather than aborting the whole purge. The next run simply re-parses
    everything from disk (no report is lost; only the memoized *work* is), which is the
    documented effect of turning the cache off.
    """
    directory = _cache_dir(settings)
    if not directory.is_dir():
        return 0
    removed = 0
    for entry in directory.glob("*.json"):
        try:
            entry.unlink()
            removed += 1
        except OSError:
            pass
    return removed
