"""The dashboard's window onto the persistent parse cache: count, size, purge.

No Qt — ``cache_service`` is pure filesystem work, deliberately so the chip's number
and the purge button's effect can be pinned without a display. The store is just
``<sha256>.json`` files under ``performance.parse_cache_dir`` (parse_cache.py:93), so
these fabricate that shape directly rather than driving a real parse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from monthly_report.gui.services import cache_service
from monthly_report import parse_cache


@dataclass
class _FakeSettings:
    """The two attributes cache_service reads off a Settings — nothing more."""

    project_root: Path
    raw: dict = field(default_factory=dict)


def _settings(tmp_path, *, enabled=True, dirname=".parse_cache") -> _FakeSettings:
    return _FakeSettings(
        project_root=tmp_path,
        raw={"performance": {"parse_cache": enabled, "parse_cache_dir": dirname}})


def _seed(tmp_path, dirname=".parse_cache", count=3) -> Path:
    store = tmp_path / dirname
    store.mkdir(parents=True, exist_ok=True)
    for i in range(count):
        (store / f"{i:064x}.json").write_text('{"schema": 1}', encoding="utf-8")
    # A non-entry file must not be counted or purged.
    (store / "notes.txt").write_text("ignore me", encoding="utf-8")
    return store


class TestStatus:
    def test_cold_store_is_empty_not_an_error(self, tmp_path):
        status = cache_service.status(_settings(tmp_path))
        assert status.enabled is True
        assert status.entries == 0
        assert status.size_bytes == 0
        assert "empty" in status.summary

    def test_counts_only_json_entries(self, tmp_path):
        _seed(tmp_path, count=3)
        status = cache_service.status(_settings(tmp_path))
        assert status.entries == 3            # the .txt is not counted
        assert status.size_bytes > 0
        assert "3 entries" in status.summary

    def test_disabled_flag_is_reported(self, tmp_path):
        _seed(tmp_path, count=2)
        status = cache_service.status(_settings(tmp_path, enabled=False))
        assert status.enabled is False
        assert status.summary == "Parse cache: off"

    def test_default_dirname_when_unset(self, tmp_path):
        # No performance block at all -> defaults to parse_cache's own dirname + on.
        settings = _FakeSettings(project_root=tmp_path, raw={})
        _seed(tmp_path, dirname=parse_cache.DEFAULT_CACHE_DIRNAME, count=1)
        status = cache_service.status(settings)
        assert status.enabled is True
        assert status.entries == 1


class TestPurge:
    def test_deletes_entries_and_returns_count(self, tmp_path):
        store = _seed(tmp_path, count=4)
        removed = cache_service.purge(_settings(tmp_path))
        assert removed == 4
        assert list(store.glob("*.json")) == []
        # A non-entry file is left untouched.
        assert (store / "notes.txt").is_file()

    def test_cold_store_purges_nothing(self, tmp_path):
        assert cache_service.purge(_settings(tmp_path)) == 0

    def test_status_is_empty_after_purge(self, tmp_path):
        _seed(tmp_path, count=2)
        settings = _settings(tmp_path)
        cache_service.purge(settings)
        assert cache_service.status(settings).entries == 0
