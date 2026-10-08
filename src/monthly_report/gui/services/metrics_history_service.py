"""The dashboard's memory of the last run's counts — so the cards can show a trend.

``metrics`` answers "what is on disk right now"; this answers "how much did that
change since the last run began". The Stitch design puts a small delta badge beside
each headline number (``↑ 12%`` / ``↓ 4%``); an honest badge needs a baseline to
compare against, and the running process keeps none — once a run ends, the previous
figure is gone.

So the window snapshots the current counts when a run *starts* (the "before"
picture) and, on the next scan, this computes the delta between what is on disk now
and that snapshot. The badge therefore reads "what has changed since you last kicked
off a run" — a genuine figure, not a mock one. Before the first snapshot exists every
delta has no baseline and the badge stays hidden.

Best-effort throughout, exactly like :mod:`cache_stats_service`: a trend that cannot
be written or read is not worth crashing a dashboard over — the badge simply does not
show.

I/O contract
------------
snapshot(metrics) -> MetricSnapshot        # persists the current counts, returns them
load() -> MetricSnapshot | None            # the last snapshot, or None if never written
deltas(current, baseline) -> dict[str, MetricDelta]   # keyed documents/generated/quarantined
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from . import app_paths
from .metrics import Metrics

_HISTORY_FILE = "metrics_history.json"


@dataclass(frozen=True)
class MetricSnapshot:
    """The counts recorded at the start of the last run — the trend's baseline."""

    documents: int = 0
    pdfs: int = 0
    sidecars: int = 0
    quarantined: int = 0
    recorded_at: str = ""


@dataclass(frozen=True)
class MetricDelta:
    """One card's change from its baseline.

    ``previous`` is ``None`` when there is no baseline yet (the first run) — the badge
    reads that as "nothing to compare" and hides, rather than inventing a 0%.
    """

    current: int
    previous: int | None = None

    @property
    def changed(self) -> int:
        return self.current - self.previous if self.previous is not None else 0

    @property
    def pct(self) -> float | None:
        """Percentage change from the baseline.

        ``None`` when there is no baseline, or when the baseline was zero — a jump from
        nothing to something has no honest percentage, so the badge stays hidden rather
        than showing an infinite or fabricated figure.
        """
        if self.previous is None or self.previous == 0:
            return None
        return self.changed / self.previous * 100.0

    @property
    def direction(self) -> str:
        if self.changed > 0:
            return "up"
        if self.changed < 0:
            return "down"
        return "flat"

    @property
    def label(self) -> str:
        """``"12%"`` — or ``""`` when there is no baseline to compare against."""
        pct = self.pct
        return f"{abs(pct):.0f}%" if pct is not None else ""


def _path():
    return app_paths.state_dir() / _HISTORY_FILE


def snapshot(metrics: Metrics) -> MetricSnapshot:
    """Persist the current counts as the next trend baseline, and return them.

    Written temp-then-``os.replace`` for the same reason cache_stats_service.record does
    (cache_stats_service.py:74): a torn write left by a crash mid-save must never be read
    back as a real baseline.
    """
    value = MetricSnapshot(
        documents=int(metrics.documents), pdfs=int(metrics.pdfs),
        sidecars=int(metrics.sidecars), quarantined=int(metrics.quarantined),
        recorded_at=datetime.now(timezone.utc).isoformat())
    try:
        directory = app_paths.state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = _path()
        temp = path.with_suffix(path.suffix + ".tmp")
        payload = {"documents": value.documents, "pdfs": value.pdfs,
                   "sidecars": value.sidecars, "quarantined": value.quarantined,
                   "recorded_at": value.recorded_at}
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass  # a trend badge is not worth failing a run's start over
    return value


def load() -> MetricSnapshot | None:
    """Read the last recorded snapshot, or None if never written / unreadable."""
    path = _path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return MetricSnapshot(
            documents=int(data["documents"]), pdfs=int(data["pdfs"]),
            sidecars=int(data["sidecars"]), quarantined=int(data["quarantined"]),
            recorded_at=str(data.get("recorded_at", "")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def deltas(current: Metrics, baseline: MetricSnapshot | None) -> dict[str, MetricDelta]:
    """The per-card change from ``baseline`` to ``current``.

    Keyed to the three counted cards. ``generated`` tracks the produced PDFs
    (``metrics.pdfs``), the same figure the Generated card shows.
    """
    return {
        "documents": MetricDelta(current.documents,
                                 baseline.documents if baseline else None),
        "generated": MetricDelta(current.pdfs,
                                 baseline.pdfs if baseline else None),
        "quarantined": MetricDelta(current.quarantined,
                                   baseline.quarantined if baseline else None),
    }
