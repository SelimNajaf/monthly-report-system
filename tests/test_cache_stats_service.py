"""The dashboard's memory of the last run's parse-cache efficiency.

No Qt: ``cache_stats_service`` is a small atomic JSON read/write, so record→load and
the "never crash a dashboard" fallbacks pin without a display. The state directory is
redirected to ``tmp_path`` so a test never touches the real one beside the app.
"""

from __future__ import annotations

import pytest

from monthly_report.gui.services import app_paths, cache_stats_service


@pytest.fixture(autouse=True)
def _state_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(app_paths, "state_dir", lambda: tmp_path / ".state")


class TestRoundTrip:
    def test_record_then_load_returns_the_same_counts(self):
        cache_stats_service.record(116, 4)
        loaded = cache_stats_service.load()
        assert (loaded.hits, loaded.misses) == (116, 4)

    def test_record_returns_the_value_it_persisted(self):
        value = cache_stats_service.record(9, 1)
        assert value.hits == 9 and value.misses == 1
        assert value.recorded_at  # stamped

    def test_record_creates_the_state_dir(self, tmp_path):
        assert not (tmp_path / ".state").exists()
        cache_stats_service.record(1, 0)
        assert (tmp_path / ".state").is_dir()


class TestRate:
    def test_rate_is_a_hit_percentage(self):
        assert cache_stats_service.CacheEfficiency(3, 1).rate == pytest.approx(75.0)

    def test_a_run_that_parsed_nothing_is_zero_not_a_crash(self):
        eff = cache_stats_service.CacheEfficiency(0, 0)
        assert eff.rate == 0.0 and eff.rate_label == "0.0%"

    def test_caption_states_the_split(self):
        assert cache_stats_service.CacheEfficiency(116, 2).caption == "116 reused · 2 fresh"


class TestFallbacks:
    def test_load_is_none_when_never_recorded(self):
        assert cache_stats_service.load() is None

    def test_load_is_none_on_corrupt_file(self, tmp_path):
        state = tmp_path / ".state"
        state.mkdir(parents=True)
        (state / "cache_stats.json").write_text("{not json", encoding="utf-8")
        assert cache_stats_service.load() is None
