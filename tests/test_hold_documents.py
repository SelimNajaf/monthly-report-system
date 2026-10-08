"""portal.hold_documents — the operator's hold list (ADR-010 addendum).

A held document (``<CLIENT>_<MON>_<YYYY>``) is refused before any browser action and
before the ledger is consulted, under every mode. The default (absent or ``[]``) changes
nothing. Every test pins its own settings, so the live config does not decide what
these tests see; no test opens a browser or touches the real ledger.
"""

from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="uploader imports playwright helpers")

import uploader  # noqa: E402

_HELD_LINE = "  HELD by operator (portal.hold_documents): "


@pytest.fixture
def hold(monkeypatch):
    """``hold(value)`` installs settings with that hold_documents; ``None`` removes it."""
    real = uploader._settings()

    def _install(value):
        raw = json.loads(json.dumps(real.raw, ensure_ascii=False, default=str))
        portal = dict(raw.get("portal") or {})
        portal.pop("hold_documents", None)
        if value is not None:
            portal["hold_documents"] = value
        raw["portal"] = portal
        fake = dataclasses.replace(real, raw=raw)
        monkeypatch.setattr(uploader, "_settings", lambda: fake)
        return fake

    return _install


def _targets(tmp_path: Path, *ids: str) -> list[tuple[Path, Path]]:
    out = []
    for doc in ids:
        js = tmp_path / f"compiled_monthly_report_{doc}.json"
        js.write_text(json.dumps({"client_name": "X", "items_table": []}), encoding="utf-8")
        pdf = js.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        out.append((js, pdf))
    return out


# --- config parsing ---------------------------------------------------------------

def test_absent_and_empty_hold_nothing(hold):
    hold(None)
    assert uploader._hold_documents() == frozenset()
    hold([])
    assert uploader._hold_documents() == frozenset()


def test_valid_ids(hold):
    hold(["UBOC_FEB_2026", "UBOC_SEP_2026"])
    assert uploader._hold_documents() == {"UBOC_FEB_2026", "UBOC_SEP_2026"}


@pytest.mark.parametrize("bad", [
    ["uboc_feb_2026"],            # lower case
    ["UBOC_FEBRUARY_2026"],       # not a month token
    ["UBOC_FEB_26"],              # two-digit year
    ["UBOC FEB 2026"],            # spaces
    ["compiled_monthly_report_UBOC_FEB_2026"],
    [2026],
])
def test_bad_id_raises_clear_error(hold, bad):
    hold(bad)
    with pytest.raises(ValueError, match=r"portal\.hold_documents.*<CLIENT>_<MON>_<YYYY>"):
        uploader._hold_documents()


def test_non_list_raises(hold):
    hold("UBOC_FEB_2026")
    with pytest.raises(ValueError, match=r"portal\.hold_documents must be a list"):
        uploader._hold_documents()


def test_document_id_from_filename():
    assert uploader._document_id(
        Path("output/UBOC/compiled_monthly_report_UBOC_FEB_2026.json")) == "UBOC_FEB_2026"
    assert uploader._document_id(
        Path("compiled_monthly_report_MT_UBOC_FEB_2026.pdf")) == "UBOC_FEB_2026"


# --- _apply_hold ---------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, []])
def test_default_is_byte_identical(hold, tmp_path, capsys, value):
    hold(value)
    targets = _targets(tmp_path, "UBOC_FEB_2026", "KHF_MAR_2026")
    kept, held = uploader._apply_hold(targets)
    assert kept is targets and held == []
    assert capsys.readouterr().out == ""


def test_held_document_removed_with_exact_line(hold, tmp_path, capsys):
    hold(["UBOC_FEB_2026"])
    targets = _targets(tmp_path, "UBOC_FEB_2026", "KHF_MAR_2026")
    kept, held = uploader._apply_hold(targets)
    assert kept == [targets[1]] and held == ["UBOC_FEB_2026"]
    assert capsys.readouterr().out == _HELD_LINE + "UBOC_FEB_2026\n"


def test_new_line_matches_no_gui_summary_regex():
    from monthly_report.gui.services import progress
    assert not progress._UPLOAD_SUMMARY.search(_HELD_LINE + "UBOC_FEB_2026")


# --- summary --------------------------------------------------------------------------

def test_summary_lists_held_not_failed(tmp_path, capsys):
    from monthly_report.upload_ledger import UploadLedger
    ledger = UploadLedger(tmp_path / "state.json")
    stats = uploader._Stats(held=["UBOC_FEB_2026", "UBOC_SEP_2026"])
    uploader._print_summary(stats, ledger)
    out = capsys.readouterr().out
    assert "0 failed" in out and "0 skipped" in out
    assert ("2 document(s) held by operator (portal.hold_documents), not filed: "
            "UBOC_FEB_2026, UBOC_SEP_2026") in out


def test_summary_unchanged_without_held(tmp_path, capsys):
    from monthly_report.upload_ledger import UploadLedger
    ledger = UploadLedger(tmp_path / "state.json")
    uploader._print_summary(uploader._Stats(), ledger)
    assert "held" not in capsys.readouterr().out


# --- main(): dry-run and live paths ---------------------------------------------------

@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Stub main()'s surroundings: tmp ledger, fixed targets, a recording _run_batch,
    and a Playwright entry point that fails the test if a browser is ever started."""
    calls: dict = {"batches": [], "browser": 0}
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(uploader, "_ledger_path", lambda args: ledger_path)
    monkeypatch.setattr(uploader, "load_portal_config", lambda: {"url": "https://x"})
    monkeypatch.setattr(uploader, "assert_director_configured", lambda cfg: None)

    def _batch(page, targets, args, ledger, portal_cfg):
        calls["batches"].append([uploader._document_id(js) for js, _ in targets])
        return uploader._Stats(uploaded=len(targets))

    monkeypatch.setattr(uploader, "_run_batch", _batch)

    class _Ctx:
        def close(self):
            pass

    class _PW:
        def __enter__(self):
            calls["browser"] += 1
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(uploader, "_sync_playwright", lambda: _PW())
    monkeypatch.setattr(uploader, "_launch_context", lambda pw, cfg: _Ctx())
    monkeypatch.setattr(uploader, "_reach_appeal_form", lambda ctx, cfg, url: object())

    def _set_targets(*ids):
        targets = _targets(tmp_path, *ids)
        monkeypatch.setattr(uploader, "_resolve_targets", lambda args: list(targets))

    calls["targets"] = _set_targets
    return calls


@pytest.mark.parametrize("argv", [
    ["--dry-run", "--all"],
    ["--live", "--all", "--no-interactive"],
])
def test_held_refused_in_dry_run_and_live(hold, harness, capsys, argv):
    hold(["UBOC_FEB_2026"])
    harness["targets"]("UBOC_FEB_2026", "KHF_MAR_2026")
    assert uploader.main(argv) == 0
    assert harness["batches"] == [["KHF_MAR_2026"]]
    out = capsys.readouterr().out
    assert _HELD_LINE + "UBOC_FEB_2026" in out
    assert "1 document(s) held by operator" in out


@pytest.mark.parametrize("argv", [
    ["--dry-run", "--all"],
    ["--live", "--all", "--no-interactive"],
    ["--live", "--report", "x.json"],
])
def test_all_held_opens_no_browser(hold, harness, capsys, argv):
    hold(["UBOC_FEB_2026"])
    harness["targets"]("UBOC_FEB_2026")
    assert uploader.main(argv) == 0
    assert harness["batches"] == [] and harness["browser"] == 0
    assert _HELD_LINE + "UBOC_FEB_2026" in capsys.readouterr().out
    assert not (Path(uploader._ledger_path(None))).exists()


def test_bad_config_stops_main_before_any_run(hold, harness):
    hold(["uboc_feb_2026"])
    harness["targets"]("UBOC_FEB_2026")
    with pytest.raises(SystemExit, match=r"config/settings\.yaml: portal\.hold_documents"):
        uploader.main(["--dry-run", "--all"])
    assert harness["batches"] == [] and harness["browser"] == 0


def test_main_output_identical_absent_vs_empty(hold, harness, capsys):
    harness["targets"]("UBOC_FEB_2026", "KHF_MAR_2026")
    hold(None)
    uploader.main(["--dry-run", "--all"])
    absent = capsys.readouterr().out
    hold([])
    uploader.main(["--dry-run", "--all"])
    assert capsys.readouterr().out == absent
    assert "held" not in absent.casefold()
