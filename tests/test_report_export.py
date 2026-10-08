"""reports/ export copy — services/report_export.py.

Everything runs in tmp_path: a fake output/<Client>/ tree and a fake export dir.
Nothing touches the real output/ or reports/.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from monthly_report.gui.services import progress
from monthly_report.services import report_export as rx


def _sidecar(out: Path, client: str, mon: str, year: int, period: str | None = None,
             pdf: bytes = b"%PDF-1 a", body: dict | None = None) -> Path:
    folder = out / client
    folder.mkdir(parents=True, exist_ok=True)
    js = folder / f"compiled_monthly_report_{client}_{mon}_{year}.json"
    data = dict(body or {})
    if period is not None:
        data["reporting_period"] = period
    js.write_text(json.dumps(data), encoding="utf-8")
    js.with_suffix(".pdf").write_bytes(pdf)
    return js


def _settings(tmp_path: Path, **export) -> SimpleNamespace:
    cfg = {"enabled": True, "dir": "reports", "from_month": "2026-01"}
    cfg.update(export)
    return SimpleNamespace(project_root=tmp_path, output_dir=tmp_path / "output",
                           raw={"export": cfg})


def _run(settings):
    lines: list[str] = []
    result = rx.export_reports(settings, log=lines.append)
    return result, lines


# --------------------------------------------------------------------------- #
# naming and month
# --------------------------------------------------------------------------- #
def test_target_name_and_layout(tmp_path):
    _sidecar(tmp_path / "output", "KHF", "FEB", 2026, "Fevral 2026")
    result, lines = _run(_settings(tmp_path))
    assert (tmp_path / "reports/PDF/KHF/2026/KHF_2026-02.pdf").read_bytes() == b"%PDF-1 a"
    assert (tmp_path / "reports/JSON/KHF/2026/KHF_2026-02.json").is_file()
    assert sorted(result.copied) == ["JSON/KHF/2026/KHF_2026-02.json",
                                     "PDF/KHF/2026/KHF_2026-02.pdf"]
    assert lines[-1] == "  Export: copied 2, unchanged 0, overwritten 0, orphan 0, failed 0"


def test_target_name_zero_pads():
    assert rx.target_name("UBOC", _dt.date(2026, 3, 1), ".pdf") == "UBOC_2026-03.pdf"


def test_reporting_period_wins_over_filename(tmp_path):
    js = _sidecar(tmp_path / "output", "BS", "JAN", 2026, "Mart 2026")
    assert rx.sidecar_period(js) == _dt.date(2026, 3, 1)


def test_filename_fallback_when_no_period(tmp_path):
    js = _sidecar(tmp_path / "output", "BS", "APR", 2026)
    assert rx.sidecar_period(js) == _dt.date(2026, 4, 1)


def test_period_agrees_with_uploader(tmp_path):
    uploader = pytest.importorskip("uploader")
    cases = [_sidecar(tmp_path / "output", "A", "DEC", 2025, "Dekabr 2025"),
             _sidecar(tmp_path / "output", "B", "MAY", 2026),
             _sidecar(tmp_path / "output", "C", "XYZ", 2026)]
    for js in cases:
        assert rx.sidecar_period(js) == uploader._sidecar_period_start(js)


def test_sorted_processing_order(tmp_path):
    out = tmp_path / "output"
    _sidecar(out, "UBOC", "MAR", 2026, "Mart 2026")
    _sidecar(out, "AZF", "JAN", 2026, "Yanvar 2026")
    _sidecar(out, "AZF", "FEB", 2026, "Fevral 2026")
    result, _ = _run(_settings(tmp_path))
    assert result.copied == [
        "JSON/AZF/2026/AZF_2026-01.json", "JSON/AZF/2026/AZF_2026-02.json",
        "JSON/UBOC/2026/UBOC_2026-03.json",
        "PDF/AZF/2026/AZF_2026-01.pdf", "PDF/AZF/2026/AZF_2026-02.pdf",
        "PDF/UBOC/2026/UBOC_2026-03.pdf"]


# --------------------------------------------------------------------------- #
# copy behaviour
# --------------------------------------------------------------------------- #
def test_second_run_unchanged(tmp_path):
    _sidecar(tmp_path / "output", "KHF", "FEB", 2026, "Fevral 2026")
    _run(_settings(tmp_path))
    target = tmp_path / "reports/PDF/KHF/2026/KHF_2026-02.pdf"
    mtime = target.stat().st_mtime_ns
    result, lines = _run(_settings(tmp_path))
    assert result.copied == [] and result.overwritten == []
    assert len(result.unchanged) == 2
    assert target.stat().st_mtime_ns == mtime
    assert lines == ["  Export: copied 0, unchanged 2, overwritten 0, orphan 0, failed 0"]


def test_changed_source_overwrites_and_names_it(tmp_path):
    out = tmp_path / "output"
    _sidecar(out, "KHF", "FEB", 2026, "Fevral 2026")
    _run(_settings(tmp_path))
    (out / "KHF/compiled_monthly_report_KHF_FEB_2026.pdf").write_bytes(b"%PDF-1 b")
    result, lines = _run(_settings(tmp_path))
    assert result.overwritten == ["PDF/KHF/2026/KHF_2026-02.pdf"]
    assert "    Export overwritten: PDF/KHF/2026/KHF_2026-02.pdf" in lines
    assert (tmp_path / "reports/PDF/KHF/2026/KHF_2026-02.pdf").read_bytes() == b"%PDF-1 b"
    assert not list((tmp_path / "reports").rglob("*.export-tmp"))


def test_permission_error_is_reported_and_run_continues(tmp_path, monkeypatch):
    out = tmp_path / "output"
    _sidecar(out, "KHF", "FEB", 2026, "Fevral 2026")
    _sidecar(out, "UBOC", "FEB", 2026, "Fevral 2026")
    _run(_settings(tmp_path))
    for js in out.glob("*/*.pdf"):
        js.write_bytes(b"%PDF-1 changed")
    real_replace = os.replace

    def locked(src, dst):
        if Path(dst).name == "KHF_2026-02.pdf":
            raise PermissionError(13, "in use")
        return real_replace(src, dst)

    monkeypatch.setattr(rx.os, "replace", locked)
    result, lines = _run(_settings(tmp_path))
    assert result.failed == ["PDF/KHF/2026/KHF_2026-02.pdf"]
    assert result.overwritten == ["PDF/UBOC/2026/UBOC_2026-02.pdf"]
    assert any(l.startswith("    Export failed (file in use?): PDF/KHF/") for l in lines)
    assert (tmp_path / "reports/PDF/KHF/2026/KHF_2026-02.pdf").read_bytes() == b"%PDF-1 a"
    assert not list((tmp_path / "reports").rglob("*.export-tmp"))


def test_collision_refuses_both(tmp_path):
    out = tmp_path / "output"
    # Two sidecars, one client folder, same reporting month.
    _sidecar(out, "KHF", "FEB", 2026, "Fevral 2026")
    js2 = out / "KHF" / "compiled_monthly_report_MT_KHF_FEB_2026.json"
    js2.write_text(json.dumps({"reporting_period": "Fevral 2026"}), encoding="utf-8")
    js2.with_suffix(".pdf").write_bytes(b"%PDF other")
    result, lines = _run(_settings(tmp_path))
    assert not (tmp_path / "reports/PDF/KHF/2026/KHF_2026-02.pdf").exists()
    assert not (tmp_path / "reports/JSON/KHF/2026/KHF_2026-02.json").exists()
    assert len(result.failed) == 4 and result.copied == []
    refused = [l for l in lines if l.startswith("    Export refused (2+ sources for ")]
    assert len(refused) == 2
    assert "compiled_monthly_report_KHF_FEB_2026.pdf" in refused[1]
    assert "compiled_monthly_report_MT_KHF_FEB_2026.pdf" in refused[1]


def test_orphans_listed_never_deleted(tmp_path):
    _sidecar(tmp_path / "output", "KHF", "FEB", 2026, "Fevral 2026")
    stray = tmp_path / "reports/PDF/OLD/2026/OLD_2026-01.pdf"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"keep me")
    result, lines = _run(_settings(tmp_path))
    assert result.orphans == ["PDF/OLD/2026/OLD_2026-01.pdf"]
    assert "    Export orphan (no source, left in place): PDF/OLD/2026/OLD_2026-01.pdf" in lines
    assert stray.read_bytes() == b"keep me"
    assert lines[-1].endswith("orphan 1, failed 0")


def test_from_month_filter(tmp_path):
    out = tmp_path / "output"
    _sidecar(out, "AZF", "DEC", 2025, "Dekabr 2025")
    _sidecar(out, "AZF", "JAN", 2026, "Yanvar 2026")
    result, _ = _run(_settings(tmp_path))
    assert result.copied == ["JSON/AZF/2026/AZF_2026-01.json", "PDF/AZF/2026/AZF_2026-01.pdf"]
    result, _ = _run(_settings(tmp_path, from_month="2025-12"))
    assert "PDF/AZF/2025/AZF_2025-12.pdf" in result.copied


def test_from_month_default_is_2026_01(tmp_path):
    out = tmp_path / "output"
    _sidecar(out, "AZF", "DEC", 2025, "Dekabr 2025")
    s = _settings(tmp_path)
    del s.raw["export"]["from_month"]
    del s.raw["export"]["dir"]
    result, _ = _run(s)
    assert result.copied == [] and not (tmp_path / "reports/PDF").exists()


def test_bad_from_month_raises(tmp_path):
    with pytest.raises(ValueError):
        _run(_settings(tmp_path, from_month="Jan 2026"))


def test_failures_folder_and_non_sidecars_ignored(tmp_path):
    out = tmp_path / "output"
    (out / "failures").mkdir(parents=True)
    (out / "failures/compiled_monthly_report_X_JAN_2026.json").write_text("{}", encoding="utf-8")
    (out / "upload_status.json").write_text("[]", encoding="utf-8")
    result, lines = _run(_settings(tmp_path))
    assert result.copied == [] and result.failed == []


def test_missing_pdf_reported(tmp_path):
    js = _sidecar(tmp_path / "output", "KHF", "FEB", 2026, "Fevral 2026")
    js.with_suffix(".pdf").unlink()
    result, lines = _run(_settings(tmp_path))
    assert result.failed == ["KHF/compiled_monthly_report_KHF_FEB_2026.pdf"]
    assert result.copied == ["JSON/KHF/2026/KHF_2026-02.json"]


# --------------------------------------------------------------------------- #
# disabled = no trace
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", [{}, {"export": {}}, {"export": {"enabled": False}},
                                 {"export": None}])
def test_disabled_prints_nothing_and_creates_nothing(tmp_path, raw):
    _sidecar(tmp_path / "output", "KHF", "FEB", 2026, "Fevral 2026")
    lines: list[str] = []
    s = SimpleNamespace(project_root=tmp_path, output_dir=tmp_path / "output", raw=raw)
    assert rx.export_reports(s, log=lines.append) is None
    assert lines == []
    assert not (tmp_path / "reports").exists()


def test_main_calls_export_after_closing_rule():
    src = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    tail = src[src.rindex('safe_print("=" * 70)'):]
    assert "report_export.export_reports(settings, log=safe_print)" in tail
    assert tail.index("export_reports") < tail.index("return 0")


# --------------------------------------------------------------------------- #
# GUI stdout contract
# --------------------------------------------------------------------------- #
#: Every compiled pattern the GUI's stdout parser holds (main and uploader tracks).
_GUI_PATTERNS = [v for v in vars(progress).values() if isinstance(v, re.Pattern)]


def test_export_lines_match_no_gui_pattern(tmp_path, monkeypatch):
    out = tmp_path / "output"
    _sidecar(out, "KHF", "FEB", 2026, "Fevral 2026")
    _sidecar(out, "UBOC", "FEB", 2026, "Fevral 2026")
    js2 = out / "UBOC" / "compiled_monthly_report_MT_UBOC_FEB_2026.json"
    js2.write_text(json.dumps({"reporting_period": "Fevral 2026"}), encoding="utf-8")
    js2.with_suffix(".pdf").write_bytes(b"x")
    bad = out / "BS" / "compiled_monthly_report_BS_XYZ_2026.json"
    bad.parent.mkdir()
    bad.write_text("{}", encoding="utf-8")
    stray = tmp_path / "reports/PDF/OLD/2026/OLD_2026-01.pdf"
    stray.parent.mkdir(parents=True)
    stray.write_bytes(b"")
    _, first = _run(_settings(tmp_path))
    (out / "KHF/compiled_monthly_report_KHF_FEB_2026.pdf").write_bytes(b"new")
    real_replace = os.replace
    monkeypatch.setattr(rx.os, "replace", lambda s, d: (_ for _ in ()).throw(
        PermissionError(13, "in use")) if Path(d).suffix == ".json" else real_replace(s, d))
    (out / "KHF/compiled_monthly_report_KHF_FEB_2026.json").write_text(
        json.dumps({"reporting_period": "Fevral 2026", "x": 1}), encoding="utf-8")
    _, second = _run(_settings(tmp_path))
    lines = first + second + ["  Export: not run (ValueError: boom)"]
    kinds = {l.split(":")[0].strip() for l in lines}
    assert {"Export", "Export overwritten", "Export orphan (no source, left in place)",
            "Export skipped (undatable)", "Export failed (file in use?)"} <= kinds
    assert any(l.startswith("    Export refused") for l in lines)
    assert len(_GUI_PATTERNS) >= 15
    assert progress._RENDERED.match("[MT/KHF FEB 2026] -> compiled_x.pdf")
    for line in lines:
        assert not progress._RENDERED.match(line), line
        assert not progress._UPLOAD_STEP.match(line), line
        for pat in _GUI_PATTERNS:
            assert not pat.search(line), (pat.pattern, line)
