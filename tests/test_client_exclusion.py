"""The global client blacklist — retired accounts never reach a compiled report.

Reads the REAL config/settings.yaml: the guarantee being tested is that the
shipped config actually excludes SIENMAR and Qafqaz Trans Service, not that the
predicate works on a fixture.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings                      # noqa: E402
from monthly_report.method_registry import (is_excluded_client,      # noqa: E402
                                            resolve_client_by_field)


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


@pytest.mark.parametrize("code", ["SNM", "QTS", "snm", "  qts  "])
def test_retired_accounts_are_excluded(code, settings):
    assert is_excluded_client(code, settings)


@pytest.mark.parametrize("code", ["UBOC", "KHF", "KHE", "AZF", "UP", "BS",
                                  "GEMZA", "NOV", "SDLN"])
def test_active_clients_are_not_excluded(code, settings):
    assert not is_excluded_client(code, settings)


@pytest.mark.parametrize("code", ["", "   ", "ZZZ"])
def test_blank_and_unknown_codes_are_not_excluded(code, settings):
    """An unresolvable client is not a retired one — it still compiles."""
    assert not is_excluded_client(code, settings)


def test_a_missing_excluded_clients_list_excludes_nothing():
    class _Bare:
        raw: dict = {}

    assert not is_excluded_client("SNM", _Bare())


@pytest.mark.parametrize("client_field,report_no", [
    ("SIENMAR", "S-MT-26-001"),
    ("Qafqaz Trans Service MMC", "QTS-UT-26-014"),
])
def test_the_registry_still_resolves_the_clients_it_excludes(client_field, report_no,
                                                             settings):
    """The registry entries are KEPT on purpose.

    Recognition is what makes exclusion possible: delete the aliases and these
    documents become unresolvable strangers that compile under their own prefix,
    which is the opposite of excluded.
    """
    code, _name = resolve_client_by_field({"client": client_field}, report_no, settings)
    assert is_excluded_client(code, settings), (
        f"{client_field} resolved to {code!r}, which is not on the blacklist")
