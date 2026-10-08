"""The dynamic volume filter — small (month x method x client) groups are skipped.

Two layers, mirroring ``test_client_exclusion`` / ``test_allowed_standards``:

* :func:`volume_threshold` / :func:`meets_volume` in isolation — the predicate,
  including the shipped ``config/settings.yaml`` (which must ship the feature OFF).
* the OR gate's full truth table on fixture settings, incl. single-dimension and
  legacy/malformed sidecar handling on the uploader side.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import uploader                                                        # noqa: E402
from monthly_report.config import load_settings                       # noqa: E402
from monthly_report.method_registry import (meets_volume,             # noqa: E402
                                            volume_threshold)
from uploader import build_parser                                     # noqa: E402


def _settings(block):
    """A settings stand-in carrying only a ``volume_thresholds`` block."""
    return SimpleNamespace(raw={} if block is None else {"volume_thresholds": block})


@pytest.fixture(scope="module")
def shipped():
    """The REAL config/settings.yaml — the shipped feature must be off (opt-in)."""
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


# --------------------------------------------------------------------------- #
# volume_threshold — per-method lookup with default fallback
# --------------------------------------------------------------------------- #
class TestVolumeThreshold:
    def test_per_method_entry_wins(self):
        s = _settings({"default": {"min_reports": 1, "min_items": 1},
                       "UT": {"min_reports": 2, "min_items": 3}})
        assert volume_threshold("UT", s) == (2, 3)
        assert volume_threshold("ut", s) == (2, 3)   # token is upper-cased

    def test_falls_back_to_default(self):
        s = _settings({"default": {"min_reports": 4, "min_items": 5},
                       "UT": {"min_reports": 2, "min_items": 3}})
        assert volume_threshold("RT", s) == (4, 5)

    def test_missing_block_is_zero(self):
        assert volume_threshold("UT", _settings(None)) == (0, 0)

    def test_missing_keys_default_to_zero(self):
        s = _settings({"UT": {"min_reports": 2}})   # min_items omitted
        assert volume_threshold("UT", s) == (2, 0)


# --------------------------------------------------------------------------- #
# meets_volume — the OR gate
# --------------------------------------------------------------------------- #
class TestMeetsVolume:
    def test_all_zero_keeps_everything(self):
        s = _settings({"default": {"min_reports": 0, "min_items": 0}})
        assert meets_volume("UT", 1, 1, s)
        assert meets_volume("UT", 0, 0, s)

    def test_missing_block_keeps_everything(self):
        assert meets_volume("UT", 0, 0, _settings(None))

    @pytest.mark.parametrize("reports,items,kept", [
        (1, 1, False),   # fails both -> skip
        (2, 1, True),    # clears reports -> keep (OR)
        (1, 3, True),    # clears items   -> keep (OR)
        (2, 3, True),    # clears both    -> keep
    ])
    def test_both_active_is_or(self, reports, items, kept):
        s = _settings({"UT": {"min_reports": 2, "min_items": 3}})
        assert meets_volume("UT", reports, items, s) is kept

    @pytest.mark.parametrize("items,kept", [(2, False), (3, True), (5, True)])
    def test_items_only_gate(self, items, kept):
        """min_reports 0 -> that dimension is off; gate on items alone."""
        s = _settings({"UT": {"min_reports": 0, "min_items": 3}})
        # reports=1 would trivially satisfy a >=0 check; it must NOT keep the group.
        assert meets_volume("UT", 1, items, s) is kept

    @pytest.mark.parametrize("reports,kept", [(1, False), (2, True), (9, True)])
    def test_reports_only_gate(self, reports, kept):
        s = _settings({"UT": {"min_reports": 2, "min_items": 0}})
        assert meets_volume("UT", reports, 0, s) is kept


# --------------------------------------------------------------------------- #
# The shipped config must ship the feature OFF (opt-in)
# --------------------------------------------------------------------------- #
class TestShippedConfigIsOptIn:
    @pytest.mark.parametrize("method", ["UT", "RT", "MT", "DP", "PMI", "ZZZ"])
    def test_no_method_has_a_positive_floor(self, method, shipped):
        assert volume_threshold(method, shipped) == (0, 0)

    @pytest.mark.parametrize("method", ["UT", "RT", "ZZZ"])
    def test_a_single_document_group_still_compiles(self, method, shipped):
        assert meets_volume(method, 1, 1, shipped)


# --------------------------------------------------------------------------- #
# uploader._sidecar_volume — reads the same counts the compiler filtered on
# --------------------------------------------------------------------------- #
class TestSidecarVolume:
    def _write(self, path, payload):
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_method_reports_items(self, tmp_path):
        sc = self._write(tmp_path / "r.json",
                         {"ndt_method": "UT", "source_report_count": 3,
                          "total_records": 7})
        assert uploader._sidecar_volume(sc) == ("UT", 3, 7)

    def test_items_falls_back_to_items_table_length(self, tmp_path):
        sc = self._write(tmp_path / "r.json",
                         {"ndt_method": "UT", "source_report_count": 2,
                          "items_table": [{}, {}, {}]})
        assert uploader._sidecar_volume(sc) == ("UT", 2, 3)

    def test_legacy_sidecar_without_the_count_is_not_gated(self, tmp_path):
        """No source_report_count -> None -> the sweep leaves it untouched."""
        sc = self._write(tmp_path / "r.json",
                         {"ndt_method": "UT", "total_records": 1})
        assert uploader._sidecar_volume(sc) is None

    def test_a_malformed_sidecar_is_not_gated(self, tmp_path):
        sc = tmp_path / "r.json"
        sc.write_text("{ not json", encoding="utf-8")
        assert uploader._sidecar_volume(sc) is None


# --------------------------------------------------------------------------- #
# uploader._resolve_targets — the sweep-time prune, mirroring excluded_clients
# --------------------------------------------------------------------------- #
class TestResolveTargetsPrune:
    @pytest.fixture
    def swept(self, tmp_path, monkeypatch):
        out = tmp_path / "output"
        out.mkdir()

        def sidecar(name, reports, items, legacy=False):
            data = {"ndt_method": "UT", "total_records": items, "client_name": "x"}
            if not legacy:
                data["source_report_count"] = reports
            (out / name).write_text(json.dumps(data), encoding="utf-8")

        sidecar("compiled_monthly_report_UT_UBOC_MAY_2026.json", reports=5, items=9)
        sidecar("compiled_monthly_report_UT_AZF_MAY_2026.json", reports=1, items=1)
        sidecar("compiled_monthly_report_UT_KHF_MAY_2026.json", reports=1, items=1,
                legacy=True)

        # Redirect the sweep root; neutralise the retired-client check so only the
        # volume floor decides; feed a UT floor of (2, 3).
        monkeypatch.setattr(uploader, "_ROOT", tmp_path)
        monkeypatch.setattr(uploader, "_sidecar_client_code", lambda s: "")
        monkeypatch.setattr(uploader, "_settings", lambda: SimpleNamespace(
            raw={"volume_thresholds": {"UT": {"min_reports": 2, "min_items": 3}}}))
        return out

    def test_low_volume_pruned_legacy_kept(self, swept):
        targets = uploader._resolve_targets(build_parser().parse_args(["--all"]))
        names = {sidecar.name for sidecar, _pdf in targets}
        # AZF (1 report, 1 item) fails both -> pruned; UBOC clears -> kept; the
        # legacy KHF sidecar has no count field -> not gated -> kept.
        assert names == {"compiled_monthly_report_UT_UBOC_MAY_2026.json",
                         "compiled_monthly_report_UT_KHF_MAY_2026.json"}
