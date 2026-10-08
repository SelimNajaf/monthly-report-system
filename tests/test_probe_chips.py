"""--probe-chips: tag standards, read the chips back, reload — and touch nothing else.

The chip check (TODO P0) must run against the live portal before the first --live. These
tests pin what it may and may not do without a browser: it tags only through
_select_standard, reads the chips, reloads the form, and never reaches the save button,
the file input, any other field or the ledger.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="uploader imports playwright helpers")

import uploader  # noqa: E402
from uploader import (PORTAL_STANDARDS, _probe_chip_choices,  # noqa: E402
                      _probe_chips, build_parser)


# --------------------------------------------------------------------------- #
# the flag
# --------------------------------------------------------------------------- #
def test_the_flag_is_off_by_default():
    assert build_parser().parse_args([]).probe_chips is None


def test_the_flag_without_a_value_means_the_default_choice():
    assert build_parser().parse_args(["--probe-chips"]).probe_chips == ""


def test_the_flag_takes_a_comma_separated_list():
    args = build_parser().parse_args(["--probe-chips", "API 510,ISO 3057"])
    assert args.probe_chips == "API 510,ISO 3057"


@pytest.mark.parametrize("argv,chips", [
    (["--probe-chips"], ""),
    (["--probe-chips", "API 510"], "API 510"),
])
def test_main_routes_the_flag_to_the_probe(monkeypatch, argv, chips):
    seen = []
    monkeypatch.setattr(uploader, "_do_probe",
                        lambda cfg, url, chips=None: seen.append(chips) or 0)
    assert uploader.main(argv) == 0
    assert seen == [chips]


def test_plain_probe_still_runs_without_chips(monkeypatch):
    seen = []
    monkeypatch.setattr(uploader, "_do_probe",
                        lambda cfg, url, chips=None: seen.append(chips) or 0)
    assert uploader.main(["--probe"]) == 0
    assert seen == [None]


# --------------------------------------------------------------------------- #
# which standards get tagged
# --------------------------------------------------------------------------- #
def test_an_explicit_list_is_used_as_given():
    assert _probe_chip_choices(" API 510 , ISO 3057 ,", []) == ["API 510", "ISO 3057"]


def test_the_default_is_the_first_two_offered_in_the_live_spelling():
    live = ["ISO 3057", "API-510", "API 570", "SOMETHING ELSE"]
    # PORTAL_STANDARDS order decides; the live listbox's text is what gets clicked.
    assert PORTAL_STANDARDS[:2] == ("API 510", "API 570")
    assert uploader.PROBE_CHIPS_DEFAULT_COUNT == 2
    assert _probe_chip_choices("", live) == ["API-510", "API 570"]


def test_the_default_is_empty_when_the_listbox_offers_none_of_them():
    assert _probe_chip_choices("", ["NOT A PORTAL STANDARD"]) == []


# --------------------------------------------------------------------------- #
# what the step does on the page
# --------------------------------------------------------------------------- #
class _NoTouchPage:
    """A page that fails the test on anything but the calls the chip step may make."""

    def __getattr__(self, name):
        raise AssertionError(f"--probe-chips touched page.{name}")


@pytest.fixture
def recorder(monkeypatch):
    calls = []
    box = object()
    monkeypatch.setattr(uploader, "_field_after_caption",
                        lambda page, caption: calls.append(("box", caption)) or box)

    def _select(page, standards_box, standard, method="", already=None):
        assert standards_box is box
        calls.append(("select", standard))
        already.add(standard.upper())
        return "exact"

    monkeypatch.setattr(uploader, "_select_standard", _select)
    monkeypatch.setattr(uploader, "_read_standard_chips",
                        lambda b: calls.append(("read",)) or ["API 510", "API 570"])
    monkeypatch.setattr(uploader, "_reset_appeal_form",
                        lambda page: calls.append(("reload",)))

    def _no_ledger(*a, **k):
        raise AssertionError("--probe-chips touched the ledger")

    monkeypatch.setattr(uploader, "UploadLedger", _no_ledger)
    return calls


def test_tags_reads_back_then_reloads_in_that_order(recorder):
    result = _probe_chips(_NoTouchPage(), "API 510,API 570", [])
    assert recorder == [("box", "inspeksiya:"), ("select", "API 510"),
                        ("select", "API 570"), ("read",), ("reload",)]
    assert result["chip_request"] == ["API 510", "API 570"]
    assert result["chip_results"] == {"API 510": "exact", "API 570": "exact"}
    assert result["chip_expected"] == ["API 510", "API 570"]
    assert result["chip_readback"] == ["API 510", "API 570"]
    assert result["chip_match"] is True


def test_a_readback_that_differs_is_a_mismatch(recorder, monkeypatch):
    monkeypatch.setattr(uploader, "_read_standard_chips", lambda b: ["API 510"])
    result = _probe_chips(_NoTouchPage(), "API 510,API 570", [])
    assert result["chip_match"] is False
    assert result["chip_readback"] == ["API 510"]


def test_nothing_to_tag_touches_nothing(recorder, capsys):
    result = _probe_chips(_NoTouchPage(), "", ["NOT A PORTAL STANDARD"])
    assert recorder == []
    assert result["chip_request"] == [] and result["chip_match"] is False
    assert "Nothing was tagged" in capsys.readouterr().out


def _body(name: str) -> str:
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    return source.split(f"def {name}(")[1].split("\ndef ")[0]


def _code_of(name: str) -> tuple[set[str], list[str]]:
    """(attribute and function names used, string literals) of one uploader function,
    docstring excluded — the docstring may NAME the save button to say it is not used."""
    import ast
    tree = ast.parse((_ROOT / "uploader.py").read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    body = fn.body[1:] if ast.get_docstring(fn) else fn.body
    names: set[str] = set()
    strings: list[str] = []
    for stmt in body:
        for node in ast.walk(stmt):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                strings.append(node.value)
    return names, strings


_CHIP_CODE = ["_probe_chips", "_probe_chip_choices", "_read_standard_chips"]


@pytest.mark.parametrize("name", _CHIP_CODE)
@pytest.mark.parametrize("forbidden", ["set_input_files", "mark_in_progress",
                                       "mark_uploaded", "_write_upload_status",
                                       "UploadLedger", "fill", "type", "press",
                                       "_fill_verified", "upload_report"])
def test_the_chip_code_never_reaches_attach_ledger_or_keyboard(name, forbidden):
    names, _strings = _code_of(name)
    assert forbidden not in names


@pytest.mark.parametrize("name", _CHIP_CODE)
@pytest.mark.parametrize("button", ["Yadda saxla", "E-imza"])
def test_the_chip_code_never_names_the_save_or_sign_button(name, button):
    _names, strings = _code_of(name)
    assert not any(button in s for s in strings)


def test_the_chip_step_runs_only_after_the_dump_is_written():
    body = _body("_do_probe")
    assert body.index("probe_form(page, out_path)") < body.index("_probe_chips(")
