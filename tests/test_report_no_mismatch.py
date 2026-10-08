"""Pin the filename-serial != in-body-serial class (``report_no_mismatch``).

``U-RT-26-005 (Zığ).docx`` holds ``U-RT-26-004``: one inspection, two numbers.
Measured 2026-09-21: 22 such files, 9 of them table-identical copies. The rules:

* nothing is renamed or re-numbered — the filename still wins;
* every mismatch is warned about (``[report-no mismatch]`` + an audit file);
* ``filtering.block_mismatched_report_no: true`` drops only a COPY — from the
  month's rows and from a cross-month pull — with the reason in
  ``report.skipped``; a non-copy mismatch stays. ``false`` is the default and
  must be exactly the behaviour that predates the key.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import report_no_mismatch as M                    # noqa: E402
from monthly_report import retest_tracker as rt                       # noqa: E402
from monthly_report.config import load_settings                       # noqa: E402
from monthly_report.document_aggregator import build_monthly_report   # noqa: E402
from monthly_report.gui.services import quarantine_reasons_service    # noqa: E402
from monthly_report.gui.services.progress import PipelineProgressParser  # noqa: E402


class _Translator:
    untranslated: set = set()

    def term(self, text):
        return text


def _tables(report_no, date_str, item="Pipe"):
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", "UBOC"],
        ["ACC Standard:", "ISO 11666"],
        ["Item:", item],
    ]]


@pytest.fixture
def settings():
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.target_month = "2026-05"
    cfg.raw = {**cfg.raw, "retest": {"pull_weld_check": "off"}}
    return cfg


def _block(cfg, on):
    cfg.raw = {**cfg.raw, "filtering": {**(cfg.raw.get("filtering") or {}),
                                        "block_mismatched_report_no": on}}
    return cfg


def _add(tmp_path, cache, name, report_no, date_str, **kw):
    p = tmp_path / name
    p.write_bytes(b"")
    cache[p] = _tables(report_no, date_str, **kw)
    return p


@pytest.mark.parametrize("no, want", [
    ("U-RT-26-005", ("26", 5)),
    ("RT-U-26-005R1", ("26", 5)),
    ("AZF-RT-W1-26-328", ("26", 328)),
    ("Project:Date:", None),
    ("", None),
])
def test_serial_is_the_last_year_seq_pair(no, want):
    assert M.serial(no) == want


@pytest.mark.parametrize("name, body, want", [
    ("U-RT-26-005 (Zığ).docx", "U-RT-26-004", ("U-RT-26-005", "U-RT-26-004")),
    ("U-RT-26-004 (Zığ).docx", "RT-U-26-004", None),     # spelling only
    ("U-MT-26-041R1.docx", "U-MT-26-041", None),         # retest marker only
    ("U-RT-26-004 (Zığ).docx", "Project:Date:", None),   # body unreadable
])
def test_only_a_different_serial_is_a_mismatch(name, body, want):
    assert M.mismatch_of(Path(name), _tables(body, "01.05.2026")) == want


def test_a_copy_needs_identical_tables_and_the_body_serial_in_the_siblings_name(tmp_path):
    cache: dict = {}
    copy = _add(tmp_path, cache, "U-RT-26-005 (Zığ).docx", "U-RT-26-004", "27.02.2026")
    real = _add(tmp_path, cache, "U-RT-26-004 (Zığ).docx", "U-RT-26-004", "27.02.2026")
    stale = _add(tmp_path, cache, "U-RT-26-070.docx", "U-RT-26-067", "11.09.2026")
    _add(tmp_path, cache, "U-RT-26-067.docx", "U-RT-26-067", "11.09.2026", item="Flange")
    found = {m.path.name: m for m in M.find_mismatches(cache)}
    assert sorted(found) == [copy.name, stale.name]
    assert found[copy.name].copy_of == (real,)
    assert found[copy.name].date == "27.02.2026"
    assert not found[stale.name].is_copy


def test_block_is_off_when_the_block_or_the_key_is_absent(settings):
    class _Bare:
        raw = {}

    class _NoKey:
        raw = {"filtering": {}}

    assert M.block_enabled(_Bare()) is False
    # Absent key = OFF. Not read from the live config: that value is the operator's
    # (D4, 2026-10-05: ON) and must not decide what this default test sees.
    assert M.block_enabled(_NoKey()) is False
    assert M.block_enabled(_block(settings, True)) is True


def _month(tmp_path):
    cache: dict = {}
    for n in range(1, 5):   # keep the group above min_total_client_volume
        _add(tmp_path, cache, f"U-UT-26-{n:03d} (Platform).docx",
             f"U-UT-26-{n:03d}", "15.05.2026")
    copy = _add(tmp_path, cache, "U-UT-26-005 (Platform).docx", "U-UT-26-004", "15.05.2026")
    stale = _add(tmp_path, cache, "U-UT-26-007 (Platform).docx", "U-UT-26-006",
                 "16.05.2026", item="Flange")
    return cache, copy, stale


def _build(cfg, cache, tmp_path):
    cfg.input_dir = str(tmp_path)
    return build_monthly_report(cfg, _Translator(), method="UT",
                                client_code="UBOC", cache=cache)


def test_off_keeps_every_row_under_its_filename_number(tmp_path, settings):
    cache, _copy, _stale = _month(tmp_path)
    report = _build(_block(settings, False), cache, tmp_path)
    assert [r.report_no for r in report.rows] == [
        "U-UT-26-001", "U-UT-26-002", "U-UT-26-003", "U-UT-26-004",
        "U-UT-26-005", "U-UT-26-007"]
    assert not [s for s in report.skipped if s[1].startswith(M.BLOCK_REASON)]


def test_on_drops_only_the_copy_and_says_why(tmp_path, settings):
    cache, copy, _stale = _month(tmp_path)
    report = _build(_block(settings, True), cache, tmp_path)
    nos = [r.report_no for r in report.rows]
    assert "U-UT-26-005" not in nos
    assert "U-UT-26-007" in nos                     # not a copy: warned, kept
    assert (copy.name, "report-no mismatch: ad U-UT-26-005 ≠ içəri U-UT-26-004, "
                       "U-UT-26-004 (Platform).docx ilə eyni cədvəl — sətir buraxıldı"
            ) in report.skipped


def test_on_keeps_a_copy_out_of_a_cross_month_pull(tmp_path, settings):
    cache, _copy, _stale = _month(tmp_path)
    _add(tmp_path, cache, "U-UT-26-009 (Platform).docx", "U-UT-26-009", "20.02.2026")
    parent = _add(tmp_path, cache, "U-UT-26-010 (Platform).docx", "U-UT-26-009",
                  "20.02.2026")
    _add(tmp_path, cache, "U-UT-26-010R1 (Platform).docx", "U-UT-26-010R1", "18.05.2026")

    off = _build(_block(settings, False), dict(cache), tmp_path)
    assert off.pulled_parents == 1

    on = _build(_block(settings, True), dict(cache), tmp_path)
    assert on.pulled_parents == 0
    assert "U-UT-26-010" not in [r.report_no for r in on.rows]
    assert "U-UT-26-010R1" in [r.report_no for r in on.rows]
    assert any(name == parent.name and why.startswith(M.BLOCK_REASON)
               for name, why in on.skipped)


def test_a_pull_refusal_reads_back_into_its_parts():
    reason = ("çarpaz-ay valideyn U-RT-26-005 gətirilmədi "
              "(U-RT-26-005R1, U-RT-26-005RW): tikiş QB-4 ≠ QB-5")
    assert rt.parse_refusal(reason) == (
        "U-RT-26-005", "U-RT-26-005R1, U-RT-26-005RW", "tikiş QB-4 ≠ QB-5")
    assert rt.parse_refusal("duplicate Report № U-RT-26-005") is None
    assert rt.parse_refusal("unapproved standard 'X' not listed") is None


class TestStdoutContract:
    """The new console lines must not be read as any line the GUI already parses."""

    LINES = [
        "  [report-no mismatch] U-RT-26-005 (Zığ).docx: ad U-RT-26-005 ≠ içəri "
        "U-RT-26-004 — U-RT-26-004 (Zığ).docx ilə eyni cədvəl",
        "  [report-no mismatch] KF-UT-25-003.pdf: ad KF-UT-25-003 ≠ içəri UT-KF-25-025",
        "  Report-no mismatch: 22 file(s), 9 copy(ies) audited -> "
        "report_no_mismatch_2026-09-21.md",
        "  1 cross-month parent(s) not pulled — the evidence did not match "
        "(retest.pull_weld_check: strict):",
        "    [pull rejected] U-RT-26-005: tikiş QB-4 ≠ QB-5 — valideyn gətirilmədi "
        "(UBOC MAR 2026; U-RT-26-005R1, U-RT-26-005RW)",
    ]

    @pytest.mark.parametrize("line", LINES)
    def test_progress_parser_ignores(self, line):
        assert PipelineProgressParser().feed(line) is None

    @pytest.mark.parametrize("line", LINES)
    def test_quarantine_reasons_ignore(self, line):
        assert quarantine_reasons_service.parse_line(line) is None


def test_the_audit_lists_every_mismatch_with_its_class(tmp_path, settings):
    import main

    cache: dict = {}
    _add(tmp_path, cache, "U-RT-26-005 (Zığ).docx", "U-RT-26-004", "27.02.2026")
    _add(tmp_path, cache, "U-RT-26-004 (Zığ).docx", "U-RT-26-004", "27.02.2026")
    _add(tmp_path, cache, "U-RT-26-070.docx", "U-RT-26-067", "11.09.2026")
    settings.input_dir = str(tmp_path)
    settings.output_dir = str(tmp_path / "out")
    path = main._write_mismatch_audit(settings, M.find_mismatches(cache), cache)
    text = path.read_text(encoding="utf-8")
    assert path.name.startswith("report_no_mismatch_")
    assert "**2 faylda**" in text and "**Surət** (1)" in text
    assert ("| 1 | `U-RT-26-005 (Zığ).docx` | `U-RT-26-005` | `U-RT-26-004` | "
            "27.02.2026 | — | surət | `U-RT-26-004 (Zığ).docx` |") in text
    assert "| 2 | `U-RT-26-070.docx` | `U-RT-26-070` | `U-RT-26-067` |" in text
    assert "surət deyil" in text
    assert main._write_mismatch_audit(settings, [], cache) is None
