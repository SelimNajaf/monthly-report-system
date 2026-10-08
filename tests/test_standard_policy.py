"""portal.standard_policy: all | any — ADR-010.

"all" (default) is the zero-substitution rule: one standard the portal does not offer
refuses the whole report. "any" files the offered standards, names the rest on stdout,
and still refuses a report with zero offered. The live listbox stays the authority: a
standard the baseline matched but the live listbox lacks refuses the whole report under
either policy (QC2).

Every test pins its own settings (no alias map, explicit policy), so the live
config/settings.yaml does not decide what these tests see.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="uploader imports playwright helpers")

import uploader  # noqa: E402
from uploader import PORTAL_STANDARDS, _standard_key  # noqa: E402

_NEW_LINE = "  standards skipped (policy any): "


@pytest.fixture
def policy(monkeypatch):
    """``policy(value)`` installs settings with that standard_policy and no aliases.

    ``value=None`` removes the key (the default path).
    """
    real = uploader._settings()

    def _install(value):
        raw = json.loads(json.dumps(real.raw, ensure_ascii=False, default=str))
        portal = dict(raw.get("portal") or {})
        portal["standard_aliases"] = {}
        portal.pop("standard_policy", None)
        if value is not None:
            portal["standard_policy"] = value
        raw["portal"] = portal
        fake = dataclasses.replace(real, raw=raw)
        monkeypatch.setattr(uploader, "_settings", lambda: fake)
        return fake

    return _install


def _report(*standards: str) -> dict:
    return {"client_name": "KHF", "client_voen": "1234567890",
            "reporting_period": "Mart 2026", "ndt_method": "MT",
            "report_serial_no": "MR-KHF-26-03", "total_records": len(standards),
            "items_table": [{"item_name": f"Boru {i}", "standard": s, "method": "MT"}
                            for i, s in enumerate(standards)]}


class _DryPage:
    dry_run = True
    url = "https://e-keyfiyyet.gov.az/uqq/new-appeal"


@pytest.fixture
def captured_payload(monkeypatch):
    """Replace the dry-run narration with a recorder of the payload it would file."""
    seen: list[dict] = []

    def _record(payload, pdf_path, json_data, live):
        seen.append(dict(payload, standards=list(payload["standards"])))
        return "REACHED_THE_FILL"

    monkeypatch.setattr(uploader, "_simulate_upload", _record)
    return seen


# --------------------------------------------------------------------------- #
# the setting itself
# --------------------------------------------------------------------------- #
def test_default_is_all(policy):
    policy(None)
    assert uploader._standard_policy() == "all"


@pytest.mark.parametrize("value,want", [("all", "all"), ("any", "any"), (" ANY ", "any")])
def test_known_values(policy, value, want):
    policy(value)
    assert uploader._standard_policy() == want


def test_unknown_value_raises(policy):
    policy("some")
    with pytest.raises(ValueError, match="standard_policy"):
        uploader._standard_policy()


# --------------------------------------------------------------------------- #
# pre-flight
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("portal_2026_08_12")
def test_any_partial_match_files_only_the_matches(policy, captured_payload, capsys):
    policy("any")
    outcome = uploader.upload_report(_DryPage(), "r.pdf",
                                     _report("API 1104 & AWS D1.1", "ISO 11666"), {})
    assert outcome == "REACHED_THE_FILL"
    assert captured_payload[0]["standards"] == ["API 1104"]
    assert uploader._POLICY_SKIPPED == ["AWS D1.1", "ISO 11666"]
    assert uploader._UNMATCHED == []
    out = capsys.readouterr().out
    assert f"{_NEW_LINE}['AWS D1.1', 'ISO 11666']\n" in out
    assert "SKIPPED — the portal does not offer" not in out


@pytest.mark.usefixtures("portal_2026_08_12")
def test_any_new_line_is_exact_and_gui_safe(policy, captured_payload, capsys):
    from monthly_report.gui.services import progress
    policy("any")
    uploader.upload_report(_DryPage(), "r.pdf", _report("EEMUA 158", "ASME B31.3"), {})
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith(_NEW_LINE)]
    assert lines == ["  standards skipped (policy any): ['ASME B31.3']"]
    for pat in (v for v in vars(progress).values() if isinstance(v, re.Pattern)):
        assert not pat.search(lines[0]), pat.pattern


@pytest.mark.usefixtures("portal_2026_08_12")
def test_any_zero_matches_refuses(policy, captured_payload, capsys):
    policy("any")
    outcome = uploader.upload_report(_DryPage(), "r.pdf",
                                     _report("AWS D1.1", "ASME B31.3"), {})
    assert outcome == "SKIPPED_UNMATCHED_STANDARD"
    assert captured_payload == []
    assert uploader._UNMATCHED == ["AWS D1.1", "ASME B31.3"]
    assert uploader._POLICY_SKIPPED == []
    assert _NEW_LINE not in capsys.readouterr().out


@pytest.mark.usefixtures("portal_2026_08_12")
@pytest.mark.parametrize("value", [None, "all"])
def test_all_still_refuses_a_partial_match(policy, captured_payload, capsys, value):
    policy(value)
    outcome = uploader.upload_report(_DryPage(), "r.pdf",
                                     _report("API 1104 & AWS D1.1"), {})
    assert outcome == "SKIPPED_UNMATCHED_STANDARD"
    assert captured_payload == []
    assert uploader._UNMATCHED == ["AWS D1.1"]
    assert uploader._POLICY_SKIPPED == []
    assert _NEW_LINE not in capsys.readouterr().out


@pytest.mark.usefixtures("portal_2026_08_12")
def test_any_full_match_prints_nothing_new(policy, captured_payload, capsys):
    policy("any")
    uploader.upload_report(_DryPage(), "r.pdf", _report("API 1104", "ISO 17636"), {})
    assert captured_payload[0]["standards"] == ["API 1104", "ISO 17636"]
    assert _NEW_LINE not in capsys.readouterr().out


def test_any_empty_standard_still_refused(policy):
    policy("any")
    assert uploader.upload_report(None, "r.pdf", _report("", "  "), {}) == \
        "SKIPPED_EMPTY_STANDARD"


@pytest.mark.usefixtures("portal_2026_08_12")
def test_pre_flight_does_not_read_the_policy_when_nothing_is_missing(policy, captured_payload):
    """Default path untouched: a bad policy value only matters when it is consulted."""
    policy("bogus")
    assert uploader.upload_report(_DryPage(), "r.pdf", _report("API 1104"), {}) == \
        "REACHED_THE_FILL"


# --------------------------------------------------------------------------- #
# dry-run narration agrees with the pre-flight
# --------------------------------------------------------------------------- #
def test_dry_run_narration_tells_the_truth_under_any(policy, tmp_path, capsys):
    policy("any")
    pdf = tmp_path / "r.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    outcome = uploader.upload_report(_DryPage(), pdf, _report("API 1104 & AWS D1.1"), {})
    out = capsys.readouterr().out
    assert outcome != "SKIPPED_UNMATCHED_STANDARD"
    assert "WILL SKIP REPORT" not in out
    assert "not filed — not offered by the portal (policy any)" in out
    assert "API 1104" in out


def test_simulate_standards_default_output_unchanged(policy, capsys):
    policy(None)
    uploader._simulate_standards(["API 1104"], "MT")
    a = capsys.readouterr().out
    uploader._simulate_standards(["API 1104"], "MT", skipped=())
    assert capsys.readouterr().out == a


# --------------------------------------------------------------------------- #
# QC2: live listbox lacks a filable option -> whole report refused
# --------------------------------------------------------------------------- #
@pytest.mark.usefixtures("portal_2026_08_12")
def test_live_listbox_missing_a_filable_option_refuses_whole_report(policy, monkeypatch):
    policy("any")
    for name in ("_open_new_document_form", "_fill_date", "_fill_verified"):
        monkeypatch.setattr(uploader, name, lambda *a, **k: None)
    monkeypatch.setattr(uploader, "_field_after_caption", lambda *a, **k: MagicMock())
    tried: list[str] = []

    def _listbox(page, box, standard, method="", already=None):
        tried.append(standard)
        return "unmatched" if standard == "ISO 17636" else "exact"

    resets: list[object] = []
    monkeypatch.setattr(uploader, "_select_standard", _listbox)
    monkeypatch.setattr(uploader, "_reset_appeal_form", lambda page: resets.append(page))
    saved = MagicMock()
    page = MagicMock()
    page.dry_run = False
    page.get_by_role.return_value = saved

    outcome = uploader.upload_report(page, "r.pdf",
                                     _report("API 1104", "ISO 17636", "AWS D1.1"), {},
                                     live=True)

    assert outcome == "SKIPPED_UNMATCHED_STANDARD"
    assert tried == ["API 1104", "ISO 17636"]          # AWS D1.1 never offered to it
    assert resets == [page]
    assert not page.set_input_files.called
    assert not any("Yadda saxla" in str(c) for c in page.get_by_role.call_args_list)


# --------------------------------------------------------------------------- #
# batch summaries
# --------------------------------------------------------------------------- #
def _targets(tmp_path):
    out = []
    for name, serial in (("report_one", "SER-1"), ("report_two", "SER-2")):
        js = tmp_path / f"{name}.json"
        js.write_text(json.dumps(_report("API 1104")), encoding="utf-8")
        pdf = tmp_path / f"{name}.pdf"
        pdf.write_bytes(f"%PDF {serial}".encode())
        out.append((js, pdf))
    return out


def test_batch_lists_policy_skipped_and_not_as_unmatched(tmp_path, monkeypatch, capsys):
    from monthly_report.upload_ledger import UploadLedger

    def _stub(page, pdf_path, json_data, portal_cfg, live=False, confirm=None):
        uploader._UNMATCHED.clear()
        uploader._POLICY_SKIPPED.clear()
        if Path(pdf_path).stem == "report_one":
            uploader._POLICY_SKIPPED.append("AWS D1.1")
            return "OK"
        uploader._UNMATCHED.append("ASME B31.3")
        return "SKIPPED_UNMATCHED_STANDARD"

    monkeypatch.setattr(uploader, "upload_report", _stub)
    ledger = UploadLedger(tmp_path / "state.json")
    # A fake dry page and a tmp ledger: nothing reaches a browser or the real ledger.
    # --live --no-interactive is the argv the existing batch tests use to walk more
    # than one report (a non-live run stops after one; see _effective_limit).
    args = uploader.build_parser().parse_args(["--live", "--all", "--no-interactive"])
    stats = uploader._run_batch(_DryPage(), _targets(tmp_path), args, ledger, {})

    assert stats.policy_skipped == [("report_one", "AWS D1.1")]
    assert stats.unmatched == [("report_two", "ASME B31.3")]
    assert stats.uploaded == 1 and stats.skipped == 1
    capsys.readouterr()
    uploader._print_summary(stats, ledger)
    out = capsys.readouterr().out
    assert "  standards skipped (policy any): 1 report(s) went through" in out
    assert "report_one  ['AWS D1.1']" in out


def test_print_policy_skipped_list_silent_when_empty(capsys):
    uploader._print_policy_skipped_list(uploader._Stats())
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------- #
# single source of truth
# --------------------------------------------------------------------------- #
def test_in_portal_md_equals_portal_standards():
    """standarts/in_portal.md is documentation; PORTAL_STANDARDS is the code's truth.
    They must name the same 21 documents (provisional list, 2026-10-06), compared
    separator-blind so a spacing difference between the two files cannot hide."""
    text = (_ROOT / "standarts" / "in_portal.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*\d+\s*\|\s*(.+?)\s*\|\s*$", text, flags=re.MULTILINE)
    assert len(rows) == len(PORTAL_STANDARDS) == 21
    assert sorted(_standard_key(r) for r in rows) == \
        sorted(_standard_key(s) for s in PORTAL_STANDARDS)
