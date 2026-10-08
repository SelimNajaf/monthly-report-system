"""The document serial names the report's OWN month, not a borrowed row's.

Regression B1. ``build_monthly_report`` pulls a retest's ORIGINAL forward from an
earlier month so a failure and its repair render on one sheet
(``retest_tracker.pull_cross_month_parents``). That pulled parent is a rank-0 row
carrying its own earlier date, so it sorts to ``records[0]`` — and the serial used
to be built from ``records[0].date``. A May report with a February parent was
therefore filed as ``MR-UT-UBOC-26-02``.

Why that mattered enough to pin: the serial is what the E-Keyfiyyet portal files the
appeal under, and it disagreed with the three other month-bearing fields on the SAME
document (the PDF's "Hesabat dövrü" line, the sidecar's ``reporting_period``, and the
output filename) — all of which are keyed on ``settings.target_month``. Twenty of the
304 compiled sidecars in the corpus carried a wrong-month serial, and two distinct
months were filed under one serial (``MR-UT-UBOC-26-02`` named both FEB and MAY 2026),
which is a duplicate identity on a government submission.

The fix is one expression: the serial reads ``settings.target_month`` like everything
else. These tests pin the AGREEMENT, not the expression — any future rewrite has to
keep the four fields naming one month.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings                    # noqa: E402
from monthly_report.document_aggregator import build_monthly_report  # noqa: E402
from monthly_report.json_exporter import build_report_json         # noqa: E402
from monthly_report.naming import default_output                   # noqa: E402


class _Translator:
    """Identity translation — these assertions are about months, not wording."""
    untranslated: set = set()

    def term(self, text):
        return text


def _tables(report_no: str, date_str: str, standard: str = "ISO 11666"):
    """A minimal metadata block extract_meta / extract_standard can read."""
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", "UBOC"],
        ["ACC Standard:", standard],
    ]]


@pytest.fixture
def cross_month_cache(tmp_path):
    """One May retest whose ONLY original sits in February — the pull case.

    Five in-month siblings keep the group above ``min_total_client_volume``; the
    corpus-volume gate has its own tests and must not be what this one measures.
    """
    cache = {}
    for n in range(1, 6):                      # in-month siblings, May
        p = tmp_path / f"U-UT-26-{n:03d} (Platform).docx"
        p.write_bytes(b"")
        cache[p] = _tables(f"U-UT-26-{n:03d}", "15.05.2026")

    retest = tmp_path / "U-UT-26-010R1 (Platform).docx"     # May: the repair
    parent = tmp_path / "U-UT-26-010 (Platform).docx"       # February: the original
    retest.write_bytes(b"")
    parent.write_bytes(b"")
    cache[retest] = _tables("U-UT-26-010R1", "18.05.2026")
    cache[parent] = _tables("U-UT-26-010", "20.02.2026")
    return cache


@pytest.fixture
def may_report(tmp_path, cross_month_cache):
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.target_month = "2026-05"
    report = build_monthly_report(cfg, _Translator(), method="UT",
                                  client_code="UBOC", cache=cross_month_cache)
    return cfg, report


def test_the_fixture_really_pulls_a_parent_from_an_earlier_month(may_report):
    """Guards the fixture: without a pulled parent this whole file proves nothing."""
    _cfg, report = may_report
    assert report.pulled_parents == 1
    pulled = [r for r in report.rows if r.is_pulled_parent]
    assert [r.date.month for r in pulled] == [2]
    # And it really is the row the serial used to be read off.
    assert report.rows[0].is_pulled_parent


def test_the_serial_names_the_target_month_not_the_pulled_parents(may_report):
    _cfg, report = may_report
    assert report.document_number == "MR-UBOC-26-05"


def test_the_sidecar_serial_and_period_name_the_same_month(may_report):
    cfg, report = may_report
    data = build_report_json(report, cfg, _Translator())
    assert data["report_serial_no"] == "MR-UBOC-26-05"
    assert data["reporting_period"] == "May 2026"
    assert data["report_serial_no"].endswith("-26-05")


def test_the_serial_agrees_with_the_output_filename(may_report):
    """The fourth month-bearing field on the same deliverable."""
    cfg, report = may_report
    # ADR-004 tree and name: output/<CLIENT>/, no method token anywhere.
    path = default_output(cfg, cfg.target_month, subdir="UBOC", client="UBOC")
    assert path.name == "compiled_monthly_report_UBOC_MAY_2026.pdf"
    assert report.document_number.endswith("-26-05")


def test_two_months_of_the_same_client_never_share_a_serial(tmp_path,
                                                            cross_month_cache):
    """The concrete corpus failure: FEB and MAY 2026 both filed MR-UT-UBOC-26-02."""
    feb = tmp_path / "U-UT-26-020 (Platform).docx"
    feb.write_bytes(b"")
    cache = dict(cross_month_cache)
    for n in range(20, 26):                    # February siblings, over the floor
        p = tmp_path / f"U-UT-26-{n:03d} (Platform).docx"
        p.write_bytes(b"")
        cache[p] = _tables(f"U-UT-26-{n:03d}", "10.02.2026")

    serials = {}
    for month in ("2026-02", "2026-05"):
        cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
        cfg.input_dir = str(tmp_path)
        cfg.target_month = month
        report = build_monthly_report(cfg, _Translator(), method="UT",
                                      client_code="UBOC", cache=cache)
        serials[month] = report.document_number

    assert serials["2026-02"] == "MR-UBOC-26-02"
    assert serials["2026-05"] == "MR-UBOC-26-05"
    assert serials["2026-02"] != serials["2026-05"]


def test_an_empty_group_still_serialises_to_its_target_month(tmp_path):
    """No rows at all — the serial has no row to read and must not blow up."""
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.target_month = "2026-05"
    report = build_monthly_report(cfg, _Translator(), method="UT",
                                  client_code="UBOC", cache={})
    assert report.rows == []
    assert report.document_number == "MR-UBOC-26-05"
