"""Characterization tests for the config-driven method/client registry."""

import hashlib
from pathlib import Path

import pytest

from monthly_report import config, method_registry as mr

_SETTINGS = str(Path(__file__).resolve().parents[1] / "config" / "settings.yaml")


@pytest.fixture(scope="module")
def settings():
    return config.load_settings(_SETTINGS)


def test_detect_method(settings):
    assert mr.detect_method("KF-MT-26-001", settings) == "MT"
    assert mr.detect_method("U-UT-26-010", settings) == "UT"
    assert mr.detect_method("U-UTM-26-001", settings) == "UTM"   # UTM before UT
    assert mr.detect_method("KF-DP-26-001", settings) == "DP"
    assert mr.detect_method("SDLN-PMI-26-001", settings) == "PMI"
    assert mr.detect_method("no-token-here", settings) == "NDT"


def test_detect_client_prefix_and_method_first(settings):
    assert mr.detect_client("AZF-RT-W1-26-304", settings) == "AZF"
    assert mr.detect_client("U-UT-26-010", settings) == "U"
    assert mr.detect_client("UT-SDLN-26-042", settings) == "SDLN"   # method-first fallback


def test_method_folder_mapping(settings):
    assert mr.method_folder("FC", settings) == "FERRITE"
    assert mr.method_folder("MT", settings) == "MPI"
    assert mr.method_folder("ZZZ", settings) == "ZZZ"   # unregistered -> token itself


def test_is_informational(settings):
    assert mr.is_informational("UTM", settings)
    assert not mr.is_informational("UT", settings)
    assert not mr.is_informational("RT", settings)


def test_client_voen_is_string(settings):
    registry = settings.raw.get("clients", {}) or {}
    for key, spec in registry.items():
        code = str((spec or {}).get("code", key))
        voen = mr.client_voen(code, settings)
        assert isinstance(voen, str)
    assert mr.client_voen("UNREGISTERED", settings) == ""


def _voen_digest(code: str, voen: str) -> str:
    """Salted, slow digest of a VÖEN: the test pins it without the repo holding the ID."""
    return hashlib.pbkdf2_hmac("sha256", voen.encode(), f"voen:{code}".encode(),
                               200_000).hex()[:16]


def test_client_voen_registered_values(settings):
    # The VERIFIED client VÖENs — config-driven, resolved by client code. Pins the
    # values so a future settings edit that fat-fingers a tax ID is caught here.
    # Pinned as digests (_voen_digest), not as the IDs: no real VÖEN in the repo.
    expected = {
        "UBOC": "0e6a2d88db2068ee",
        "KHF": "07dc1362a63b724a",
        "AZF": "6e512de6d8c3059b",
        "BS": "c07362c6ed51895f",
        "GEMZA": "4489c178208b5232",
        "NOV": "704fee5cc9740036",
    }
    for code, digest in expected.items():
        voen = mr.client_voen(code, settings)
        assert len(voen) == 10 and voen.isdigit(), code
        assert _voen_digest(code, voen) == digest, code


def test_unverified_clients_carry_no_voen(settings):
    """A client whose tax ID is not independently verified ships a blank VÖEN.

    Blank is the deliberate marker, not an oversight: these clients still RESOLVE
    and still compile, but an empty identifier is what keeps a wrong VÖEN from ever
    being exported into a sidecar and filed. Each one is also off `approved_clients`
    — the two states are set together, which is what the second assert pins.
    """
    for code in ("KHE", "UP", "SNM", "QTS", "SDLN"):
        assert mr.client_voen(code, settings) == ""
        assert not mr.is_approved_client(code, settings)


def test_resolve_client_by_field_alias_beats_prefix(settings):
    # Internal Client: field resolves via aliases; prefix is only the fallback.
    registry = settings.raw.get("clients", {}) or {}
    for key, spec in registry.items():
        spec = spec or {}
        aliases = spec.get("aliases") or []
        if not aliases:
            continue
        code = str(spec.get("code", key))
        got_code, got_name = mr.resolve_client_by_field(
            {"client": f"xx {aliases[0]} yy"}, "ZZ-MT-26-001", settings)
        assert got_code == code
        break
    # Empty field falls back to prefix resolution.
    code, _ = mr.resolve_client_by_field({"client": ""}, "AZF-RT-W1-26-304", settings)
    assert code == mr.resolve_client("AZF-RT-W1-26-304", settings)[0]


def test_compile_sort_registry_shapes(settings):
    compiled = mr.compile_sort_registry(settings)
    assert compiled, "registry must compile at least one pattern"
    for code, folder, rx in compiled:
        assert isinstance(code, str) and isinstance(folder, str)
        assert hasattr(rx, "search")
    # A pattern must match its own method filenames case-insensitively.
    assert any(rx.search("kf-mt-26-001 (2165).docx") for _c, f, rx in compiled
               if f == "MPI")


# --------------------------------------------------------------------------- #
# Corpus-wide client filtration — active blacklist + cumulative volume
# --------------------------------------------------------------------------- #
from types import SimpleNamespace   # noqa: E402
from pathlib import Path as _Path   # noqa: E402


def _doc(report_no: str, client: str, date_str: str, standard: str = "ISO 11666"):
    """A minimal ``(Path, tables)`` corpus entry extract_meta/resolve can read."""
    tables = [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", client],
        ["ACC Standard:", standard],
    ]]
    return _Path(report_no + ".docx"), tables


def test_is_active_client(settings):
    assert not mr.is_active_client("QTS", settings)      # active: false in settings
    assert not mr.is_active_client("SNM", settings)
    assert mr.is_active_client("UBOC", settings)          # no flag -> active
    assert mr.is_active_client("ZZZ", settings)           # unregistered -> active
    assert mr.is_active_client("", settings)              # blank -> active (no gate)


def test_is_approved_client(settings):
    # Real settings.yaml lists exactly the 6 clients with a VERIFIED VÖEN.
    for code in ("UBOC", "KHF", "AZF", "BS", "GEMZA", "NOV"):
        assert mr.is_approved_client(code, settings)
    for code in ("KHE", "SDLN", "UP"):                    # registered, unverified
        assert not mr.is_approved_client(code, settings)
    assert not mr.is_approved_client("ZZZ", settings)     # unregistered -> refused
    assert mr.is_approved_client("", settings)            # blank -> pass (no gate)


def test_the_approved_list_is_exactly_the_six_verified_clients(settings):
    """No client may be on the allowlist without a VÖEN, and vice versa.

    The pairing IS the safety rule — an approved client with a blank tax ID would
    file an appeal under an empty identifier — so it is pinned on the shipped config
    rather than left to the two edits being remembered together.
    """
    approved = settings.raw.get("approved_clients") or []
    assert sorted(approved) == sorted(["UBOC", "KHF", "AZF", "BS", "GEMZA", "NOV"])
    for code in approved:
        assert mr.client_voen(code, settings).strip(), f"{code} approved with no VÖEN"


def test_is_uploadable_client(settings):
    # The upload-side gate: approved AND not retired, with blank failing CLOSED.
    for code in ("UBOC", "KHF", "AZF", "BS", "GEMZA", "NOV"):
        assert mr.is_uploadable_client(code, settings)
    for code in ("KHE", "SDLN", "UP"):        # registered + active, but unapproved
        assert not mr.is_uploadable_client(code, settings)
    for code in ("SNM", "QTS"):               # retired AND unapproved
        assert not mr.is_uploadable_client(code, settings)
    assert not mr.is_uploadable_client("ZZZ", settings)   # unregistered -> refused
    # Blank: refused while the allowlist is populated (a report whose client cannot
    # be read is not one of the six), allowed once the allowlist is off.
    assert not mr.is_uploadable_client("", settings)
    assert not mr.is_uploadable_client("   ", settings)
    assert mr.is_uploadable_client("", SimpleNamespace(raw={}))
    assert mr.is_uploadable_client("", SimpleNamespace(raw={"approved_clients": []}))


def test_is_uploadable_client_off_by_default():
    """With no allowlist the gate degrades to the retire rules alone."""
    off = SimpleNamespace(raw={"clients": {"SNM": {"code": "SNM", "active": False}},
                               "excluded_clients": []})
    assert mr.is_uploadable_client("UP", off)      # unapproved is meaningless here
    assert mr.is_uploadable_client("ZZZ", off)     # unregistered -> active default
    assert not mr.is_uploadable_client("SNM", off)  # retired still refused


def test_is_approved_client_off_by_default():
    # Empty / absent approved_clients disables the allowlist: everything passes.
    off = SimpleNamespace(raw={})
    assert mr.is_approved_client("UP", off)
    assert mr.is_approved_client("ZZZ", off)
    empty = SimpleNamespace(raw={"approved_clients": []})
    assert mr.is_approved_client("UP", empty)


def test_min_total_client_volume(settings):
    assert mr.min_total_client_volume(settings) == 5


def test_corpus_client_stats_is_cumulative_across_months(settings):
    # 1 SDLN report in April + 3 in May -> cumulative (4, {2026-04, 2026-05}); a
    # single NOV one-off in May -> (1, {2026-05}). ASR is excluded from the tally.
    items = [
        _doc("UT-SDLN-26-001", "SDLN", "15.04.2026"),
        _doc("UT-SDLN-26-002", "SDLN", "15.05.2026"),
        _doc("UT-SDLN-26-003", "SDLN", "16.05.2026"),
        _doc("UT-SDLN-26-004", "SDLN", "17.05.2026"),
        _doc("NOV-UT-26-001", "NOV", "15.05.2026"),
        _doc("UT-SDLN-26-005-ASR", "SDLN", "18.05.2026"),   # ASR — never counted
    ]
    stats = mr.corpus_client_stats(items, settings)
    assert stats["SDLN"] == (4, {"2026-04", "2026-05"})
    assert stats["NOV"] == (1, {"2026-05"})


def test_client_volume_ok_rules(settings):
    # floor is 5 in real settings.
    single_low = {"NOV": (1, {"2026-05"})}
    multi_low = {"SDLN": (2, {"2026-04", "2026-05"})}
    over_floor = {"UBOC": (6, {"2026-05"})}
    assert not mr.client_volume_ok("NOV", single_low, settings)     # 1<5, one month
    assert mr.client_volume_ok("SDLN", multi_low, settings)         # spans 2 months
    assert mr.client_volume_ok("UBOC", over_floor, settings)        # 6>=5
    assert not mr.client_volume_ok("MISSING", {}, settings)         # absent -> (0,{})
    # Filter OFF (floor 0/absent) -> every client passes regardless of count.
    off = SimpleNamespace(raw={"filtering": {"min_total_client_volume": 0}})
    assert mr.client_volume_ok("NOV", single_low, off)
    no_block = SimpleNamespace(raw={})
    assert mr.client_volume_ok("NOV", single_low, no_block)


def test_is_admitted_client(settings):
    stats = {
        "SDLN": (2, {"2026-04", "2026-05"}),   # multi-month low count -> admitted
        "NOV": (1, {"2026-05"}),               # single-month one-off -> not admitted
        "QTS": (9, {"2026-04", "2026-05"}),    # high volume but inactive -> not admitted
    }
    assert mr.is_admitted_client("SDLN", stats, settings)
    assert not mr.is_admitted_client("NOV", stats, settings)
    assert not mr.is_admitted_client("QTS", stats, settings)
