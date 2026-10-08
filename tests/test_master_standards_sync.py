"""Drift guard: the enforced allowlist must mirror the master standards document.

``standarts/butun_standartlar.md`` is the company's authoritative list of approved
NDT norms. The pipeline does not read it directly — it enforces ``allowed_standards``
in ``config/settings.yaml`` — so the two can drift. These tests pin them together:

* ``master_standards`` parses the .md table (format guard).
* every master-list standard resolves as ``is_allowed_standard`` against the SHIPPED
  ``config/settings.yaml`` (the sync guard — fails the moment a master row is added
  without extending the allowlist).
* a standard that is neither on the master list nor aliased is REJECTED (proving the
  superset did not silently widen into an allow-all).
* a blank standard is still allowed (the fallback owns it, not the guardrail).
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings                              # noqa: E402
from monthly_report.method_registry import is_allowed_standard, master_standards  # noqa: E402

_MASTER_MD = _ROOT / "standarts" / "butun_standartlar.md"


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


@pytest.fixture(scope="module")
def master():
    return master_standards(_MASTER_MD)


# --------------------------------------------------------------------------- #
# master_standards — the .md parser
# --------------------------------------------------------------------------- #
def test_master_list_parses(master):
    """37 data rows, header/separator skipped, Cyrillic ГОСТ rows preserved."""
    assert len(master) == 37
    # First/last data rows and a couple of interior anchors, incl. Cyrillic.
    assert master[0] == "API 510"
    assert master[-1] == "ГОСТ Р ЕН 13018"
    assert "ASME I-XII" in master
    assert "ASTM E797/E797M" in master
    assert "ГОСТ Р 55724-2013" in master
    # No header/separator artefacts leaked in.
    assert "Standart" not in master
    assert not any(set(s) <= set("-: ") for s in master)


# --------------------------------------------------------------------------- #
# sync guard — every master standard is allowed by the shipped config
# --------------------------------------------------------------------------- #
def test_every_master_standard_is_allowed(master, settings):
    """The drift guard: settings.yaml `allowed_standards` must cover the master list.

    Parametrization is dynamic (over the parsed .md) rather than a hardcoded copy,
    so adding a row to butun_standartlar.md without extending the allowlist fails
    HERE — exactly at the seam that would otherwise silently quarantine it.
    """
    missing = [s for s in master if not is_allowed_standard(s, settings)]
    assert not missing, f"master standards not on allowed_standards: {missing}"


# --------------------------------------------------------------------------- #
# strict rejection — unlisted, unaliased standards are disallowed
# --------------------------------------------------------------------------- #
class TestStrictRejection:
    @pytest.mark.parametrize("std", [
        "DNV-OS-F101", "ISO 9712", "EEMUA 197", "ASTM A388", "SNT-TC-1A",
        "API 653", "ISO 9001", "ГОСТ 12345-99",
    ])
    def test_unlisted_standards_are_rejected(self, std, settings, master):
        assert std not in master                       # guard the fixtures themselves
        assert not is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["", "   ", None])
    def test_blank_is_allowed(self, std, settings):
        """A standard we cannot read is not disproved — the fallback owns it."""
        assert is_allowed_standard(std, settings)

    def test_empty_allowlist_is_not_how_this_config_ships(self, settings):
        """Sanity: the shipped guardrail is ON (non-empty), so rejection is real."""
        assert settings.raw.get("allowed_standards")

    def test_guardrail_off_allows_a_foreign_standard(self):
        off = SimpleNamespace(raw={"allowed_standards": []})
        assert is_allowed_standard("DNV-OS-F101", off)
