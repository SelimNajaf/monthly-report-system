"""The pre-upload checklist: VÖENs, director FIN/serial, and NDT standards.

``settings_service.portal_readiness`` aggregates three existing pipeline primitives
into one ``list[Check]`` for the header chip and the Pre-Flight dialog. These pin the
aggregation — which domain fails, and why — by driving the primitives with fabricated
config rather than a real settings file. The director read and the filename→standard
parse are patched so the test states one thing at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from monthly_report import docx_reader, method_registry
from monthly_report.gui.services import settings_service
from monthly_report.gui.services import settings_writer


@dataclass
class _FakeSettings:
    input_dir: Path
    raw: dict = field(default_factory=dict)


def _by_label(checks, label):
    return next(c for c in checks if c.label == label)


@pytest.fixture
def _director_ok(monkeypatch):
    monkeypatch.setattr(settings_writer, "read_director",
                        lambda _p: {"fin": "1234567", "seriya_nomresi": "AA123"})


def _settings(tmp_path, clients, allowed=None):
    raw = {"clients": clients}
    if allowed is not None:
        raw["allowed_standards"] = allowed
    return _FakeSettings(input_dir=tmp_path, raw=raw)


class TestVoen:
    def test_missing_voen_fails_the_check(self, tmp_path, _director_ok):
        settings = _settings(tmp_path, {
            "KHF": {"code": "KHF", "voen": "111"},
            "AZF": {"code": "AZF", "voen": ""},
        })
        check = _by_label(settings_service.portal_readiness(settings), "Client VÖENs")
        assert not check.ok and "AZF" in check.detail

    def test_all_voens_present_passes(self, tmp_path, _director_ok):
        settings = _settings(tmp_path, {"KHF": {"code": "KHF", "voen": "111"}})
        assert _by_label(settings_service.portal_readiness(settings), "Client VÖENs").ok


class TestDirector:
    def test_missing_fin_and_serial_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings_writer, "read_director",
                            lambda _p: {"fin": "", "seriya_nomresi": ""})
        settings = _settings(tmp_path, {})
        check = _by_label(settings_service.portal_readiness(settings),
                          "Director FIN / serial")
        assert not check.ok and "fin" in check.detail and "seriya_nomresi" in check.detail

    def test_configured_director_passes(self, tmp_path, _director_ok):
        settings = _settings(tmp_path, {})
        assert _by_label(settings_service.portal_readiness(settings),
                         "Director FIN / serial").ok


class TestStandards:
    def test_unmapped_standard_fails(self, tmp_path, _director_ok, monkeypatch):
        (tmp_path / "report_A.docx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(docx_reader, "parse_filename_metadata",
                            lambda _p: {"standard": "BADSTD"})
        monkeypatch.setattr(method_registry, "is_allowed_standard",
                            lambda std, _s: std != "BADSTD")
        settings = _settings(tmp_path, {})
        check = _by_label(settings_service.portal_readiness(settings), "NDT standards")
        assert not check.ok and "BADSTD" in check.detail

    def test_all_standards_allowed_passes(self, tmp_path, _director_ok, monkeypatch):
        (tmp_path / "report_A.docx").write_text("x", encoding="utf-8")
        monkeypatch.setattr(docx_reader, "parse_filename_metadata",
                            lambda _p: {"standard": "ISO"})
        monkeypatch.setattr(method_registry, "is_allowed_standard", lambda *_: True)
        settings = _settings(tmp_path, {})
        assert _by_label(settings_service.portal_readiness(settings), "NDT standards").ok

    def test_temp_lock_files_are_ignored(self, tmp_path, _director_ok, monkeypatch):
        (tmp_path / "~$open.docx").write_text("x", encoding="utf-8")
        called = []
        monkeypatch.setattr(docx_reader, "parse_filename_metadata",
                            lambda p: called.append(p) or {"standard": "ISO"})
        monkeypatch.setattr(method_registry, "is_allowed_standard", lambda *_: True)
        settings_service.portal_readiness(_settings(tmp_path, {}))
        assert not called  # the ~$ lock file was skipped before parsing
