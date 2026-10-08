"""The dashboard's memory of the last run's counts — the trend badges' baseline.

No Qt: ``metrics_history_service`` is a small atomic JSON read/write plus delta maths,
so snapshot→load and the "never crash a dashboard" fallbacks pin without a display. The
state directory is redirected to ``tmp_path`` so a test never touches the real one.
"""

from __future__ import annotations

import pytest

from monthly_report.gui.services import app_paths, metrics_history_service
from monthly_report.gui.services.metrics import Metrics


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "state_dir", lambda: tmp_path / ".state")


def _metrics(documents=0, pdfs=0, sidecars=0, quarantined=0):
    return Metrics(documents=documents, pdfs=pdfs, sidecars=sidecars,
                   quarantined=quarantined)


class TestRoundTrip:
    def test_snapshot_then_load_returns_the_same_counts(self):
        metrics_history_service.snapshot(_metrics(50, 40, 40, 6))
        loaded = metrics_history_service.load()
        assert (loaded.documents, loaded.pdfs, loaded.sidecars, loaded.quarantined) \
            == (50, 40, 40, 6)

    def test_snapshot_returns_the_value_it_persisted(self):
        value = metrics_history_service.snapshot(_metrics(9, 3, 3, 1))
        assert value.documents == 9 and value.pdfs == 3
        assert value.recorded_at  # stamped

    def test_snapshot_creates_the_state_dir(self, tmp_path):
        assert not (tmp_path / ".state").exists()
        metrics_history_service.snapshot(_metrics(1))
        assert (tmp_path / ".state").is_dir()


class TestDeltas:
    def test_delta_is_a_signed_change_and_percentage(self):
        baseline = metrics_history_service.snapshot(_metrics(pdfs=100))
        result = metrics_history_service.deltas(_metrics(pdfs=112), baseline)
        gen = result["generated"]
        assert gen.changed == 12
        assert gen.pct == pytest.approx(12.0)
        assert gen.direction == "up"
        assert gen.label == "12%"

    def test_a_drop_reads_as_a_down_direction(self):
        baseline = metrics_history_service.snapshot(_metrics(quarantined=25))
        q = metrics_history_service.deltas(_metrics(quarantined=24), baseline)["quarantined"]
        assert q.direction == "down" and q.label == "4%"

    def test_no_baseline_hides_the_badge(self):
        result = metrics_history_service.deltas(_metrics(documents=5), None)
        d = result["documents"]
        assert d.previous is None and d.pct is None and d.label == ""

    def test_growth_from_zero_has_no_honest_percentage(self):
        baseline = metrics_history_service.snapshot(_metrics(pdfs=0))
        gen = metrics_history_service.deltas(_metrics(pdfs=7), baseline)["generated"]
        assert gen.direction == "up" and gen.pct is None and gen.label == ""

    def test_unchanged_is_flat(self):
        baseline = metrics_history_service.snapshot(_metrics(documents=10))
        d = metrics_history_service.deltas(_metrics(documents=10), baseline)["documents"]
        assert d.direction == "flat"


class TestFallbacks:
    def test_load_is_none_when_never_recorded(self):
        assert metrics_history_service.load() is None

    def test_load_is_none_on_corrupt_file(self, tmp_path):
        state = tmp_path / ".state"
        state.mkdir(parents=True)
        (state / "metrics_history.json").write_text("{not json", encoding="utf-8")
        assert metrics_history_service.load() is None
