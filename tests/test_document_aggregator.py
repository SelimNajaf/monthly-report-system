"""Standard ingestion gate — unapproved standards never reach compiled output.

Two layers:

* ``is_allowed_standard_lenient`` unit cases — the prefix-tolerant allowlist check
  the aggregator gate calls (spares an approved standard's edition/section suffix,
  still rejects a genuinely foreign code or a project doc-ref).
* an end-to-end ``build_monthly_report`` run proving a report whose in-body
  ACC-Standard cell holds an unapproved code (``EP-GIS-42-103``) is omitted from
  ``report.rows`` (= the PDF + JSON sidecar, which both render ``report.rows``) and
  its file LEFT IN PLACE, while a sibling on an approved standard still compiles.

Two regressions, one gate:

* ``EP-GIS-42-103`` (an internal client spec) reached compiled report
  ``MR-MPI-SDLN-26-05`` because the pre_processor guardrail reads the clean FILENAME
  standard only, and this code came from the noisy in-body fallback. Hence the gate.
* the gate then *quarantined* the file, and that was its own bug: it removed a source
  from the corpus after main.py had already printed the group count from it, so three
  consecutive runs reported 104, 102, 101 groups. STAGE 3 omits rows; it does not
  move files. See tests/test_pipeline_determinism.py.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings                        # noqa: E402
from monthly_report.document_aggregator import (UNAPPROVED_STANDARD_REASON,  # noqa: E402
                                                build_monthly_report)
from monthly_report.method_registry import is_allowed_standard_lenient  # noqa: E402


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


# --------------------------------------------------------------------------- #
# is_allowed_standard_lenient — the prefix-tolerant allowlist check
# --------------------------------------------------------------------------- #
class TestLenientStandard:
    @pytest.mark.parametrize("std", [
        "EEMUA 158",                              # bare approved literal
        "EEMUA 158,Edition 3,Section 7.5.4",      # approved + edition/section noise
        "ISO 17636 Table 5",                      # approved + trailing table ref
        "ASME VIII",                              # approved via the ASME regex alias
        "ISOP 10675-1",                           # recurring body-cell typo of ISO 10675-1
        # AZFEN client doc-refs, approved as literals in task 11-C. Not norms — the
        # client's own document numbers, allowed only so AZF reports compile.
        "Doc No: Q00255 criteria Table 5",
        "Doc No: Q01906  criteria Table 3",    # double-spaced variant the templates emit
        "Sec 11, Q02412 Rev C",                # passes WHOLE; its head "Sec 11" does not
        "", "   ", None,                          # blank — owned by the fallback
    ])
    def test_allowed(self, std, settings):
        assert is_allowed_standard_lenient(std, settings)

    @pytest.mark.parametrize("std", [
        "EP-GIS-42-103",                          # internal client spec — the regression
        # SDLN's own doc-refs were NOT approved: approving AZF's seven literals
        # must not open the gate to every client document number.
        "EP-GIS-18-016",
        "GIS-42-103 / 341.4",
        "Doc No: Q09999 criteria Table 1",        # unlisted doc-ref, same shape
        "Sec 11",                                 # the head of an allowed literal
        "DNV-OS-F101",                            # foreign standard, no alias
    ])
    def test_rejected(self, std, settings):
        assert not is_allowed_standard_lenient(std, settings)


# --------------------------------------------------------------------------- #
# build_monthly_report — the ingestion gate omits the row, keeps the file
# --------------------------------------------------------------------------- #
def _tables(report_no: str, standard: str):
    """A minimal metadata block extract_meta/extract_standard can read."""
    return [[
        ["Report No:", report_no],
        ["Date:", "15.05.2026"],
        ["Client:", "SDLN"],
        ["ACC Standard:", standard],
    ]]


def test_unapproved_standard_row_is_omitted_and_the_file_is_left_in_place(tmp_path):
    # Fresh settings so mutating input_dir/target_month never leaks to other tests.
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.target_month = "2026-05"
    # Isolate the standard gate from the (separately tested) corpus-volume gate:
    # this tiny two-file cache is below min_total_client_volume, which would
    # otherwise drop the approved sibling too. Volume filtration has its own test.
    cfg.raw["filtering"] = {"min_total_client_volume": 0}

    bad = tmp_path / "DP-SDLN-26-050.docx"        # body standard = internal spec code
    good = tmp_path / "DP-SDLN-26-051.docx"       # body standard = approved EEMUA 158
    bad.write_bytes(b"")                           # only the NAME is parsed; tables supplied
    good.write_bytes(b"")

    cache = {
        bad: _tables("DP-SDLN-26-050", "EP-GIS-42-103"),
        good: _tables("DP-SDLN-26-051", "EEMUA 158"),
    }
    translator = SimpleNamespace(untranslated=set())

    report = build_monthly_report(cfg, translator, cache=cache)

    report_nos = {r.report_no for r in report.rows}
    assert "DP-SDLN-26-050" not in report_nos          # rejected: omitted from output
    assert "DP-SDLN-26-051" in report_nos              # approved: still compiles

    # NOTHING is moved: STAGE 3 must not mutate the corpus STAGE 2 already decided on.
    assert bad.exists()
    assert good.exists()
    assert not (tmp_path / "SKIPPED_REPORTS").exists()

    # The exact rejection reason is recorded on the report — main.py's run-end summary
    # keys off the UNAPPROVED_STANDARD_REASON prefix, so the prefix is a contract.
    reasons = dict(report.skipped)
    assert reasons.get("DP-SDLN-26-050.docx") == (
        "unapproved standard 'EP-GIS-42-103' "
        "not listed in butun_standartlar.md — row omitted"
    )
    assert reasons["DP-SDLN-26-050.docx"].startswith(UNAPPROVED_STANDARD_REASON)


# --------------------------------------------------------------------------- #
# Corpus-wide client filtration — build_monthly_report honours active + volume
# --------------------------------------------------------------------------- #
def _client_tables(report_no: str, client: str, date_str: str,
                   standard: str = "ISO 11666"):
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", client],
        ["ACC Standard:", standard],
    ]]


def test_corpus_volume_and_active_client_filter(tmp_path):
    """One build proves all three corpus rules at once (floor is 5 in settings):

    * SDLN — only 2 reports total BUT they span April+May -> recurring -> compiles.
    * NOV  — a single-month one-off (1 report) -> below floor -> excluded in place.
    * SNM  — SIENMAR, ``active: false`` -> retired -> excluded regardless of volume.
    """
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.target_month = "2026-05"

    specs = [
        ("UT-SDLN-26-001.docx", "UT-SDLN-26-001", "SDLN", "15.04.2026"),   # prior month
        ("UT-SDLN-26-002.docx", "UT-SDLN-26-002", "SDLN", "15.05.2026"),   # in month
        ("NOV-UT-26-001.docx", "NOV-UT-26-001", "NOV", "16.05.2026"),      # one-off
        ("S-UT-26-001.docx", "S-UT-26-001", "SIENMAR", "17.05.2026"),      # inactive
    ]
    cache = {}
    for fname, report_no, client, date_str in specs:
        path = tmp_path / fname
        path.write_bytes(b"")
        cache[path] = _client_tables(report_no, client, date_str)

    translator = SimpleNamespace(untranslated=set())
    report = build_monthly_report(cfg, translator, method="UT", cache=cache)

    report_nos = {r.report_no for r in report.rows}
    assert "UT-SDLN-26-002" in report_nos          # multi-month -> kept
    assert "NOV-UT-26-001" not in report_nos       # single-month one-off -> dropped
    assert "S-UT-26-001" not in report_nos         # inactive client -> dropped

    reasons = dict(report.skipped)
    assert reasons.get("NOV-UT-26-001.docx") == "client NOV below min_total_client_volume"
    assert reasons.get("S-UT-26-001.docx") == "client SNM inactive/excluded"

    # Nothing is quarantined by the corpus/active gate — the files stay in place.
    assert (tmp_path / "NOV-UT-26-001.docx").exists()
    assert (tmp_path / "S-UT-26-001.docx").exists()
    assert not (tmp_path / "SKIPPED_REPORTS").exists()


# --------------------------------------------------------------------------- #
# Transposed Report № merge — end to end through build_monthly_report
# --------------------------------------------------------------------------- #
def _weld_tables(report_no: str, *weld_ids: str):
    """Metadata block + a weld table, for a document the merge can fingerprint."""
    meta = [
        ["Report No:", report_no],
        ["Date:", "15.05.2026"],
        ["Client:", "SDLN"],
        ["ACC Standard:", "EEMUA 158"],
    ]
    welds = [["Weld No", "Result"]] + [[wid, "Accept"] for wid in weld_ids]
    return [meta, welds]


def test_duplicate_identity_merge_is_opt_in_and_frees_the_sequence_number(tmp_path):
    """One report under two spellings compiles as ONE row — only with the flag on.

    ``SDLN-DP-26-060`` is the archived PDF original; ``DP-SDLN-26-060`` is the
    renamed live ``.docx``. ``report_key`` keeps segment order (correctly), so the
    twin dedup never meets them and both reach ``records``. With the flag off that
    is the shipped behaviour and stays so; with it on the live document wins and
    the row it freed is renumbered by ``_assign_sequence_numbers``.
    """
    live = tmp_path / "DP-SDLN-26-060.docx"
    archived = tmp_path / "PDF_ARCHIVE" / "SDLN-DP-26-060.pdf"
    archived.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(b"")
    archived.write_bytes(b"")
    cache = {live: _weld_tables("DP-SDLN-26-060", "W1", "W2"),
             archived: _weld_tables("SDLN-DP-26-060", "W1")}
    translator = SimpleNamespace(untranslated=set())

    def _build(merge: bool):
        cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
        cfg.input_dir = str(tmp_path)
        cfg.target_month = "2026-05"
        cfg.raw["filtering"] = {"min_total_client_volume": 0,
                                "merge_duplicate_identities": merge}
        return build_monthly_report(cfg, translator, cache=cache)

    off = _build(False)
    assert sorted(r.report_no for r in off.rows) == ["DP-SDLN-26-060",
                                                     "SDLN-DP-26-060"]
    assert [r.seq for r in off.rows] == ["1", "2"]

    on = _build(True)
    assert [r.report_no for r in on.rows] == ["DP-SDLN-26-060"]   # live .docx wins
    assert [r.seq for r in on.rows] == ["1"]

    # Reads only: neither copy is moved, renamed or removed.
    assert live.exists() and archived.exists()
