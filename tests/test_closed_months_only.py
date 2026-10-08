"""portal.upload_closed_months_only — never file a month that has not ended (D6).

Under ``true`` a document whose reporting month is the current month (Asia/Baku) or
later is refused before the limit, the ledger and any browser, under every mode. The
default (absent or ``false``) changes nothing. Every test pins its own settings and its
own "today", so neither the live config nor the calendar decides what these tests see;
no test opens a browser or touches the real ledger.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="uploader imports playwright helpers")

import uploader  # noqa: E402

_NOT_YET_LINE = "  NOT YET (month not closed): "


@pytest.fixture
def portal(monkeypatch):
    """``portal(**keys)`` installs settings whose portal block has exactly these keys
    on top of the live one, with hold_documents and upload_closed_months_only removed
    unless given; a value of ``None`` leaves the key absent."""
    real = uploader._settings()

    def _install(**keys):
        raw = json.loads(json.dumps(real.raw, ensure_ascii=False, default=str))
        block = dict(raw.get("portal") or {})
        block.pop("hold_documents", None)
        block.pop("upload_closed_months_only", None)
        block.update({k: v for k, v in keys.items() if v is not None})
        raw["portal"] = block
        fake = dataclasses.replace(real, raw=raw)
        monkeypatch.setattr(uploader, "_settings", lambda: fake)
        return fake

    return _install


def _targets(tmp_path: Path, *ids: str, period: dict | None = None
             ) -> list[tuple[Path, Path]]:
    out = []
    for doc in ids:
        js = tmp_path / f"compiled_monthly_report_{doc}.json"
        data = {"client_name": "X", "items_table": []}
        if period and doc in period:
            data["reporting_period"] = period[doc]
        js.write_text(json.dumps(data), encoding="utf-8")
        pdf = js.with_suffix(".pdf")
        pdf.write_bytes(b"%PDF")
        out.append((js, pdf))
    return out


# --- config parsing ---------------------------------------------------------------

def test_absent_and_false_mean_off(portal):
    portal()
    assert uploader._closed_months_only() is False
    portal(upload_closed_months_only=False)
    assert uploader._closed_months_only() is False
    portal(upload_closed_months_only=True)
    assert uploader._closed_months_only() is True


@pytest.mark.parametrize("bad", ["true", "false", "yes", 1, 0, ["x"]])
def test_non_boolean_raises_clear_error(portal, bad):
    portal(upload_closed_months_only=bad)
    with pytest.raises(ValueError, match=r"portal\.upload_closed_months_only must be "
                                         r"true or false"):
        uploader._closed_months_only()


def test_today_baku_is_a_date():
    assert isinstance(uploader._today_baku(), dt.date)


# --- _apply_closed_months ----------------------------------------------------------

@pytest.mark.parametrize("value", [None, False])
def test_default_is_byte_identical(portal, tmp_path, capsys, value):
    portal(upload_closed_months_only=value)
    targets = _targets(tmp_path, "UBOC_OCT_2026", "UBOC_SEP_2026")
    kept, not_yet = uploader._apply_closed_months(targets, today=dt.date(2026, 10, 5))
    assert kept is targets and not_yet == []
    assert capsys.readouterr().out == ""


def test_current_month_refused_previous_allowed(portal, tmp_path, capsys):
    portal(upload_closed_months_only=True)
    targets = _targets(tmp_path, "UBOC_SEP_2026", "UBOC_OCT_2026", "UBOC_NOV_2026")
    kept, not_yet = uploader._apply_closed_months(targets, today=dt.date(2026, 10, 5))
    assert kept == [targets[0]]
    assert not_yet == ["UBOC_OCT_2026", "UBOC_NOV_2026"]
    assert capsys.readouterr().out == (_NOT_YET_LINE + "UBOC_OCT_2026\n"
                                       + _NOT_YET_LINE + "UBOC_NOV_2026\n")


@pytest.mark.parametrize("today, sep_closed", [
    (dt.date(2026, 9, 30), False),   # last day of September: September still open
    (dt.date(2026, 10, 1), True),    # 1st of October: September has closed
])
def test_month_boundary(portal, tmp_path, capsys, today, sep_closed):
    portal(upload_closed_months_only=True)
    targets = _targets(tmp_path, "UBOC_AUG_2026", "UBOC_SEP_2026")
    kept, not_yet = uploader._apply_closed_months(targets, today=today)
    assert targets[0] in kept
    assert (targets[1] in kept) is sep_closed
    assert not_yet == ([] if sep_closed else ["UBOC_SEP_2026"])


def test_year_boundary(portal, tmp_path):
    portal(upload_closed_months_only=True)
    targets = _targets(tmp_path, "UBOC_DEC_2026", "UBOC_JAN_2027")
    _, open_dec = uploader._apply_closed_months(targets, today=dt.date(2026, 12, 31))
    assert open_dec == ["UBOC_DEC_2026", "UBOC_JAN_2027"]
    _, open_jan = uploader._apply_closed_months(targets, today=dt.date(2027, 1, 1))
    assert open_jan == ["UBOC_JAN_2027"]


def test_sidecar_period_wins_over_filename(portal, tmp_path):
    """The period comes from _sidecar_period_start, so the sidecar's own
    reporting_period decides, not the filename token."""
    portal(upload_closed_months_only=True)
    targets = _targets(tmp_path, "UBOC_SEP_2026", period={"UBOC_SEP_2026": "Oktyabr 2026"})
    assert uploader._sidecar_period_start(targets[0][0]) == dt.date(2026, 10, 1)
    _, not_yet = uploader._apply_closed_months(targets, today=dt.date(2026, 10, 5))
    assert not_yet == ["UBOC_SEP_2026"]


def test_undatable_is_refused(portal, tmp_path, capsys):
    portal(upload_closed_months_only=True)
    js = tmp_path / "compiled_monthly_report_odd.json"
    js.write_text("{}", encoding="utf-8")
    assert uploader._sidecar_period_start(js) is None
    kept, not_yet = uploader._apply_closed_months([(js, js.with_suffix(".pdf"))],
                                                  today=dt.date(2026, 10, 5))
    assert kept == [] and len(not_yet) == 1
    assert capsys.readouterr().out.startswith(_NOT_YET_LINE)


def test_new_line_matches_no_gui_summary_regex():
    from monthly_report.gui.services import progress
    assert not progress._UPLOAD_SUMMARY.search(_NOT_YET_LINE + "UBOC_OCT_2026")


# --- summary --------------------------------------------------------------------------

def test_summary_lists_not_yet_not_failed(tmp_path, capsys):
    from monthly_report.upload_ledger import UploadLedger
    ledger = UploadLedger(tmp_path / "state.json")
    uploader._print_summary(uploader._Stats(not_yet=["UBOC_OCT_2026"]), ledger)
    out = capsys.readouterr().out
    assert "0 failed" in out and "0 skipped" in out
    assert ("1 document(s) for a month not yet closed "
            "(portal.upload_closed_months_only), not filed: UBOC_OCT_2026") in out


def test_summary_unchanged_without_not_yet(tmp_path, capsys):
    from monthly_report.upload_ledger import UploadLedger
    ledger = UploadLedger(tmp_path / "state.json")
    uploader._print_summary(uploader._Stats(), ledger)
    assert "not yet" not in capsys.readouterr().out


# --- main(): dry-run and live paths ---------------------------------------------------

@pytest.fixture
def harness(monkeypatch, tmp_path):
    """Stub main()'s surroundings: tmp ledger, fixed targets, a fixed "today"
    (2026-10-05), a recording _run_batch, and a Playwright entry point that counts
    every browser start."""
    calls: dict = {"batches": [], "browser": 0}
    ledger_path = tmp_path / "ledger.json"
    monkeypatch.setattr(uploader, "_ledger_path", lambda args: ledger_path)
    monkeypatch.setattr(uploader, "load_portal_config", lambda: {"url": "https://x"})
    monkeypatch.setattr(uploader, "assert_director_configured", lambda cfg: None)
    monkeypatch.setattr(uploader, "_today_baku", lambda: dt.date(2026, 10, 5))

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
    calls["ledger_path"] = ledger_path
    return calls


@pytest.mark.parametrize("argv", [
    ["--dry-run", "--all"],
    ["--live", "--all", "--no-interactive"],
])
def test_open_month_refused_in_dry_run_and_live(portal, harness, capsys, argv):
    portal(upload_closed_months_only=True)
    harness["targets"]("UBOC_OCT_2026", "UBOC_SEP_2026")
    assert uploader.main(argv) == 0
    assert harness["batches"] == [["UBOC_SEP_2026"]]
    out = capsys.readouterr().out
    assert _NOT_YET_LINE + "UBOC_OCT_2026" in out
    assert "1 document(s) for a month not yet closed" in out


@pytest.mark.parametrize("argv", [
    ["--dry-run", "--all"],
    ["--live", "--all", "--no-interactive"],
    ["--live", "--report", "x.json"],
])
def test_only_open_months_opens_no_browser(portal, harness, capsys, argv):
    portal(upload_closed_months_only=True)
    harness["targets"]("UBOC_OCT_2026")
    assert uploader.main(argv) == 0
    assert harness["batches"] == [] and harness["browser"] == 0
    assert _NOT_YET_LINE + "UBOC_OCT_2026" in capsys.readouterr().out
    assert not harness["ledger_path"].exists()


def test_hold_and_not_yet_counted_apart(portal, harness, capsys):
    portal(upload_closed_months_only=True, hold_documents=["UBOC_FEB_2026"])
    harness["targets"]("UBOC_FEB_2026", "UBOC_OCT_2026", "UBOC_SEP_2026")
    assert uploader.main(["--dry-run", "--all"]) == 0
    assert harness["batches"] == [["UBOC_SEP_2026"]]
    out = capsys.readouterr().out
    assert "1 document(s) held by operator" in out
    assert "1 document(s) for a month not yet closed" in out


def test_bad_config_stops_main_before_any_run(portal, harness):
    portal(upload_closed_months_only="yes")
    harness["targets"]("UBOC_SEP_2026")
    with pytest.raises(SystemExit,
                       match=r"config/settings\.yaml: portal\.upload_closed_months_only"):
        uploader.main(["--dry-run", "--all"])
    assert harness["batches"] == [] and harness["browser"] == 0


def test_main_output_identical_absent_vs_false(portal, harness, capsys):
    harness["targets"]("UBOC_OCT_2026", "UBOC_SEP_2026")
    portal()
    uploader.main(["--dry-run", "--all"])
    absent = capsys.readouterr().out
    portal(upload_closed_months_only=False)
    uploader.main(["--dry-run", "--all"])
    assert capsys.readouterr().out == absent
    assert "not yet" not in absent.casefold()
    assert harness["batches"][-1] == ["UBOC_OCT_2026", "UBOC_SEP_2026"]
