"""Shared fixtures.

The 2026-08-12 portal list. Until 2026-10-06 ``uploader.PORTAL_STANDARDS`` held the 16
options measured by ``--probe`` on 2026-08-12; on 2026-10-06 the portal replaced them
with 21 others (provisional, see ADR-010). Many matcher tests were written against the
old 16 because they make good test data — "EEMUA 153/158" is the only slashed option
and "API 1104" the only option with a sibling family. Those tests check how the matcher
behaves, not what the portal offers today, so they pin the old list here instead of
reading whatever ``PORTAL_STANDARDS`` and the local ``config/settings.yaml`` hold.

Tests that check what the portal offers TODAY use ``PORTAL_STANDARDS`` directly.

A fresh clone has no ``config/settings.yaml`` (gitignored: it holds client IDs). Tests
that load it then fail with "Settings file not found: <that path>"; the hook at
the bottom reports exactly that failure as a skip, and only while the file is absent,
so on the workstation nothing changes.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

#: The 16 options the 2026-08-12 probe measured, in its order (standarts/in_portal_2026-08-12.md).
PORTAL_2026_08_12 = (
    "ASTM E 384", "ISO 27895", "ASTM E 1351", "ГОСТ Р ЕН 13018-2014",
    "ISO 15549", "ГОСТ Р 55611-2013", "ISO 34352-1-4", "ISO 17638",
    "ISO 17636", "ASTM E797/E797M", "API 5L", "API 579", "API 1104",
    "EEMUA 153/158", "ISO 6507", "ISO 17640",
)

#: The sub-number aliases the live config carried for that list.
ALIASES_2026_08_12 = {
    "EEMUA 153/158": [r"^EEMUA\s+153$", r"^EEMUA\s+158$"],
    "ASTM E797/E797M": [r"^ASTM\s+E\s*797M?$"],
}


@pytest.fixture
def portal_2026_08_12(monkeypatch, request):
    """Run the test against the 2026-08-12 list (uploader and the test module's import)."""
    import uploader
    monkeypatch.setattr(uploader, "PORTAL_STANDARDS", PORTAL_2026_08_12)
    if hasattr(request.module, "PORTAL_STANDARDS"):
        monkeypatch.setattr(request.module, "PORTAL_STANDARDS", PORTAL_2026_08_12)


@pytest.fixture
def aliases_2026_08_12(monkeypatch):
    """The 2026-08-12 sub-number aliases, instead of the local config's."""
    import uploader
    monkeypatch.setattr(uploader, "_standard_aliases", lambda: dict(ALIASES_2026_08_12))


_LIVE_SETTINGS = _ROOT / "config" / "settings.yaml"
_NO_LIVE_SETTINGS = ("config/settings.yaml not present (gitignored live config; "
                     "copy it from the workstation to run this test)")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Report "live config missing" as a skip on a fresh clone, never on the workstation."""
    outcome = yield
    rep = outcome.get_result()
    if (rep.failed and call.excinfo is not None
            and not _LIVE_SETTINGS.is_file()
            # uploader.load_portal_config exits with the same message instead.
            and call.excinfo.errisinstance((FileNotFoundError, SystemExit))
            and str(_LIVE_SETTINGS) in str(call.excinfo.value)):
        rep.outcome = "skipped"
        rep.longrepr = (str(item.path), (item.location[1] or 0) + 1,
                        f"Skipped: {_NO_LIVE_SETTINGS}")
