"""The parse cache's *efficiency*, remembered between runs.

``cache_service`` answers "how big is the store"; this answers "how well did the
last run use it". The pipeline prints ``Parse cache: N hit(s), M parsed fresh``
(main.py:213) and nothing keeps it — once the run's console scrolls away, the
number is gone, and the child process that computed it has already exited.

So the dashboard captures that line as it streams (``services.progress``) and
hands the counts here to persist. On the next launch the Cache Efficiency card
reads them back, rather than showing a placeholder until the operator runs the
pipeline again.

Best-effort throughout: a metric that cannot be written or read is not worth
crashing a dashboard over — the card simply falls back to "—".

I/O contract
------------
record(hits, misses) -> CacheEfficiency    # persists and returns the value
load() -> CacheEfficiency | None           # None when never recorded / unreadable
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from . import app_paths

_STATS_FILE = "cache_stats.json"


@dataclass(frozen=True)
class CacheEfficiency:
    """The last run's parse-cache hit/miss outcome."""

    hits: int
    misses: int
    recorded_at: str = ""

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def rate(self) -> float:
        """Hit rate as a percentage. A run that parsed nothing is 0%, not a crash."""
        return (self.hits / self.total * 100.0) if self.total else 0.0

    @property
    def rate_label(self) -> str:
        return f"{self.rate:.1f}%"

    @property
    def caption(self) -> str:
        """One line under the headline: what the rate is made of."""
        return f"{self.hits} reused · {self.misses} fresh"


def _path():
    return app_paths.state_dir() / _STATS_FILE


def record(hits: int, misses: int) -> CacheEfficiency:
    """Persist the last run's counts atomically, and return the value.

    Written temp-then-``os.replace`` for the same reason the parse cache and the
    settings writer do (parse_cache.py:117, settings_writer.py:269): a torn write
    left behind by a crash mid-save must never be read back as a real stat.
    """
    value = CacheEfficiency(hits=int(hits), misses=int(misses),
                            recorded_at=datetime.now(timezone.utc).isoformat())
    try:
        directory = app_paths.state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = _path()
        temp = path.with_suffix(path.suffix + ".tmp")
        payload = {"hits": value.hits, "misses": value.misses,
                   "recorded_at": value.recorded_at}
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass  # a dashboard metric is not worth failing a run's completion over
    return value


def load() -> CacheEfficiency | None:
    """Read the last recorded efficiency, or None if never written / unreadable."""
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CacheEfficiency(hits=int(data["hits"]), misses=int(data["misses"]),
                               recorded_at=str(data.get("recorded_at", "")))
    except (OSError, ValueError, KeyError, TypeError):
        return None
