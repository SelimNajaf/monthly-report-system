"""The İnspektor assignment matrix — who signs a compiled monthly report.

Reads the REAL config/settings.yaml, not a fixture: the point of these tests is
that the shipped matrix routes every active client to the intended inspector.
A synthetic settings object would pass while the real file was wrong.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings          # noqa: E402
from monthly_report.inspector_registry import as_date, resolve_inspector  # noqa: E402

# The SDLN cutover configured in settings.yaml. Written out here rather than read
# back from the config so a typo in the date is a test failure, not a silent
# agreement between two copies of the same mistake.
BOUNDARY = dt.date(2026, 3, 1)


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


@pytest.mark.parametrize("code,expected", [
    ("UBOC", "Azadxan Əhmədov"),
    ("GEMZA", "Azadxan Əhmədov"),
    ("NOV", "Azadxan Əhmədov"),
    ("KHF", "Taleh Məmmədov"),
    ("KHE", "Taleh Məmmədov"),
    ("AZF", "Taleh Məmmədov"),
    ("BS", "Taleh Məmmədov"),
    ("UP", "Emin Nəcəfov"),
])
def test_flat_clients_route_to_their_inspector(code, expected, settings):
    """A flat-mapped client gets the same inspector whatever month it is."""
    assert resolve_inspector(code, dt.date(2026, 1, 15), settings) == expected
    assert resolve_inspector(code, dt.date(2026, 9, 15), settings) == expected
    assert resolve_inspector(code, None, settings) == expected


# --- SDLN: routed by date, not by what the batch contains ------------------ #
@pytest.mark.parametrize("day,expected", [
    (dt.date(2026, 1, 1), "Emil Ağalarov"),
    (dt.date(2026, 2, 1), "Emil Ağalarov"),
    (dt.date(2026, 2, 28), "Emil Ağalarov"),
    (dt.date(2026, 3, 1), "Emin Nəcəfov"),      # boundary day itself
    (dt.date(2026, 3, 15), "Emin Nəcəfov"),
    (dt.date(2026, 7, 1), "Emin Nəcəfov"),
])
def test_sdln_routes_on_the_report_date(day, expected, settings):
    assert resolve_inspector("SDLN", day, settings) == expected


def test_the_sdln_boundary_is_where_settings_says_it_is(settings):
    """Pins the configured cutover itself. Moving the date in settings.yaml without
    meaning to would otherwise only show up months later, on a signed report."""
    assert resolve_inspector("SDLN", BOUNDARY - dt.timedelta(days=1),
                             settings) == "Emil Ağalarov"
    assert resolve_inspector("SDLN", BOUNDARY, settings) == "Emin Nəcəfov"


def test_sdln_with_no_date_keeps_the_scrape(settings):
    """A date-routed client with no date has no answer. "" keeps whatever the source
    documents said, which is a name; guessing a side would put the wrong one there."""
    assert resolve_inspector("SDLN", None, settings) == ""


def test_a_malformed_boundary_declines_rather_than_guesses():
    class _Broken:
        raw = {"inspector_matrix": {"date_routing": {
            "SDLN": {"boundary": "not-a-date", "before": "A", "on_or_after": "B"}}}}

    assert resolve_inspector("SDLN", dt.date(2026, 7, 1), _Broken()) == ""


def test_client_codes_are_matched_case_insensitively(settings):
    assert resolve_inspector("uboc", None, settings) == "Azadxan Əhmədov"
    assert resolve_inspector("sdln", dt.date(2026, 5, 1), settings) == "Emin Nəcəfov"


@pytest.mark.parametrize("code", ["", "   ", "ZZZ", "NOT-A-CLIENT"])
def test_an_unmapped_client_returns_empty_not_a_default(code, settings):
    """Unmapped must be "" — the caller keeps the name scraped from the documents.

    Substituting a default here would silently sign one client's report with
    another client's inspector, which is worse than the blank it replaces.
    """
    assert resolve_inspector(code, dt.date(2026, 7, 1), settings) == ""


def test_a_missing_matrix_block_is_not_an_error(settings):
    """No inspector_matrix in settings.yaml -> every client falls back to the scrape."""
    class _Bare:
        raw: dict = {}

    assert resolve_inspector("UBOC", dt.date(2026, 7, 1), _Bare()) == ""


# --- as_date: config is hand-edited YAML, so the date arrives in any shape -- #
@pytest.mark.parametrize("value,expected", [
    ("2026-03-01", dt.date(2026, 3, 1)),          # quoted in YAML -> str
    (dt.date(2026, 3, 1), dt.date(2026, 3, 1)),   # unquoted -> PyYAML date
    (dt.datetime(2026, 3, 1, 9, 30), dt.date(2026, 3, 1)),
    ("  2026-03-01  ", dt.date(2026, 3, 1)),
    ("01.03.2026", None),
    ("", None),
    (None, None),
    (2026, None),
])
def test_as_date_parses_what_yaml_can_produce(value, expected):
    assert as_date(value) == expected
