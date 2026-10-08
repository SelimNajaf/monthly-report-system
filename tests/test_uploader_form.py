"""Tests for the form-initialisation step uploader.py runs before it fills anything.

The portal's "Yeni sənəd *" control is a MUI Autocomplete, not a <select> — proved
by output/portal_form_probe.json, which found an <input role="combobox"> next to a
button[aria-label="Open"] and no <select> on the page at all. Calling select_option
on it fails outright, so the tests below pin that it is never called.

The other thing the probe proved is that the form's real fields do not exist until a
document type is picked. So this step is what makes every later locator reachable,
and a regression here reads as "every field is missing" rather than as itself.

No browser is launched. The fakes stand in for a Playwright Page exactly as far as
these functions actually use it.
"""

import io
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="the form helpers import playwright's "
                                         "expect()")

import uploader  # noqa: E402
from uploader import (PROBE_FILENAME, _caption_anchor,  # noqa: E402
                      _ensure_on_appeal_form, _field_after_caption,
                      _field_before_caption, _fill_date, _navigate_to_appeal_form,
                      _open_new_document_form, _open_portal, _reach_appeal_form,
                      _report_sidecars, _review_mode_hold, _select_autocomplete,
                      _select_standard, _sidecar_client_code, _sidecar_volume,
                      _Stats, _xpath_literal, assert_director_configured,
                      load_report_json)

APPEAL = "https://e-keyfiyyet.gov.az/uqq/new-appeal"
DASHBOARD = "https://e-keyfiyyet.gov.az/uqq/e-competition/"

DOC_TYPE = "İnspeksiya orqanının rəyi"


class _FakeLocator:
    """Records what was done to it. ``visible``/``n`` are what a test wants found."""

    def __init__(self, page, kind: str, visible=True, n=1, value=""):
        self._page = page
        self.kind = kind
        self._visible = visible
        self._n = n
        self.value = value

    def click(self):
        self._page.actions.append(f"click:{self.kind}")

    def fill(self, text):
        self.value = text
        self._page.actions.append(f"fill:{self.kind}={text}")

    def input_value(self):
        return self.value

    def press_sequentially(self, text):
        # Keystrokes, not a bulk set — the second attempt in _fill_verified, and what
        # a controlled input that discarded a fill() still accepts.
        self.value += text
        self._page.actions.append(f"type:{self.kind}={text}")

    def press(self, key):
        # Select-all + Delete is how a MUI Autocomplete is emptied; model it, because
        # "the box ends up empty" is the whole point of the pre-filled-combobox fix.
        self._page.actions.append(f"press:{self.kind}={key}")
        if key == "Delete":
            self.value = ""

    def is_visible(self):
        return self._visible

    def count(self):
        return self._n

    @property
    def first(self):
        return self

    def select_option(self, **kwargs):
        raise AssertionError("select_option must never be called on an Autocomplete")


class _FakePage:
    """Serves locators by role. ``combo_visible``/``named_roles`` set the scenario.

    ``named_roles`` is which of tab/link/button carry an accessible "Yeni sənəd" —
    the probe cannot say which the portal uses, so the code tries all three.

    ``combo_value`` seeds the document-type box with a value it already holds. That is
    NOT an edge case: from the second report of a batch onwards the portal serves the
    form with the type pre-filled, and re-picking it fires no React change at all.
    """

    def __init__(self, combo_visible=True, named_roles=("tab",), url=None,
                 combo_value=""):
        self.actions = []
        self.combo_visible = combo_visible
        self.named_roles = named_roles
        self.combo = _FakeLocator(self, "combobox", visible=combo_visible,
                                  value=combo_value)
        # Already on the form by default: these tests are about the combobox/tab
        # logic, not the dashboard transition, which has its own tests below.
        self.url = url or "https://e-keyfiyyet.gov.az/uqq/new-appeal"

    def goto(self, url):
        self.actions.append(f"goto:{url}")
        self.url = url
        # A real navigation throws the React tree away — including the stale value in
        # the combobox that made the form refuse to expand.
        self.combo.value = ""

    def wait_for_url(self, predicate, timeout=None):
        assert predicate(self.url), f"never reached the appeal form: {self.url}"

    def get_by_role(self, role, name=None):
        if role == "combobox":
            return self.combo
        if role in ("tab", "link", "button"):
            if name is None:
                # The unnamed fallback: only ever asked for on tabs.
                return _FakeLocator(self, f"{role}-first", n=1)
            n = 1 if role in self.named_roles else 0
            return _FakeLocator(self, f"{role}-named", n=n)
        if role == "option":
            return _FakeLocator(self, "option")
        raise AssertionError(f"unexpected role: {role}")

    def get_by_placeholder(self, placeholder):
        self.actions.append(f"wait_visible:{placeholder}")
        return _FakeLocator(self, f"placeholder:{placeholder}")


@pytest.fixture(autouse=True)
def _no_real_expect(monkeypatch):
    """expect() needs a real Locator. The assertions here are about the calls made."""
    import playwright.sync_api

    class _Noop:
        def __init__(self, locator=None):
            self._locator = locator

        def to_have_value(self, *a, **k):
            pass

        def to_be_visible(self, *a, **k):
            # Auto-waiting, modelled: to_be_visible() BLOCKS until the element is up.
            # The fakes that care implement settle() to mean "the overlay finished
            # rendering". Without this the listbox race could not be reproduced at
            # all, because a no-op expect makes the wait indistinguishable from the
            # missing wait that is the bug.
            settle = getattr(self._locator, "settle", None)
            if settle is not None:
                settle()

    monkeypatch.setattr(playwright.sync_api, "expect",
                        lambda locator=None, *a, **k: _Noop(locator))


# --------------------------------------------------------------------------- #
# _select_autocomplete — the control is not a <select>.
# --------------------------------------------------------------------------- #
def test_autocomplete_is_opened_filtered_and_the_option_clicked():
    page = _FakePage()

    _select_autocomplete(page, uploader._re("Yeni sənəd"), DOC_TYPE)

    assert page.actions == [
        "click:combobox",
        f"fill:combobox={DOC_TYPE}",
        "click:option",
    ]


def test_autocomplete_never_calls_select_option():
    """The regression that would kill a live run: MUI input is not a <select>."""
    page = _FakePage()
    _select_autocomplete(page, uploader._re("Yeni sənəd"), DOC_TYPE)
    assert page.combo.value == DOC_TYPE          # got there by fill, not select_option


def test_option_name_is_matched_literally_not_as_a_regex():
    """'İnspeksiya orqanının rəyi' is data, not a pattern — regex chars must not run."""
    page = _FakePage()
    seen = {}

    def capture(role, name=None):
        if role == "option":
            seen["pattern"] = name.pattern
        return _FakePage.get_by_role(page, role, name)

    page.get_by_role = capture
    _select_autocomplete(page, uploader._re("Yeni sənəd"), "a.b (c)")

    assert "\\(c\\)" in seen["pattern"] or "\\(" in seen["pattern"]


# --------------------------------------------------------------------------- #
# _open_new_document_form — idempotent, and it waits on the real condition.
# --------------------------------------------------------------------------- #
def test_tab_click_is_skipped_when_the_form_is_already_open():
    """The probe found the combobox present with no click — the tab can arrive active."""
    page = _FakePage(combo_visible=True)

    _open_new_document_form(page, DOC_TYPE)

    assert not any(a.startswith("click:tab") for a in page.actions)
    assert "click:combobox" in page.actions, "the type still gets picked"


@pytest.mark.parametrize("role", ["tab", "link", "button"])
def test_new_document_nav_is_found_under_any_of_the_three_roles(role):
    """The probe read the nav strip's text off the container, not off the controls.

    So which role the portal used for "Yeni sənəd" is not knowable from the dump —
    the code tries each rather than betting on one.

    Driven from the DASHBOARD, which is the only place the hunt is reachable: the nav
    strip is how /uqq/e-competition gets to the form, and _click_new_document_tab now
    stands aside on the form itself (see the mid-render tests further down).
    """
    page = _FakeNavPageWithUrl(DASHBOARD, combo_visible=False, named_roles=(role,))

    _open_new_document_form(page, DOC_TYPE)

    assert f"click:{role}-named" in page.actions


def test_falls_back_to_the_only_tab_when_nothing_carries_the_name():
    """The probe captured no accessible name for the one tab on the page."""
    page = _FakeNavPageWithUrl(DASHBOARD, combo_visible=False, named_roles=())

    _open_new_document_form(page, DOC_TYPE)

    assert "click:tab-first" in page.actions
    assert "click:tab-named" not in page.actions


def test_expansion_is_awaited_on_the_date_field_not_a_sleep(monkeypatch):
    """A fixed delay races a slow portal. The gate is the first date field arriving."""
    monkeypatch.setattr("time.sleep", lambda _s: pytest.fail("time.sleep is banned"))
    page = _FakePage()

    _open_new_document_form(page, DOC_TYPE)

    assert "wait_visible:DD.MM.YYYY" in page.actions


def test_expansion_is_awaited_after_the_type_is_picked():
    """Waiting before the pick would pass instantly on a form that never expanded."""
    page = _FakePage()

    _open_new_document_form(page, DOC_TYPE)

    assert page.actions[-1] == "wait_visible:DD.MM.YYYY"


# --------------------------------------------------------------------------- #
# The pre-filled document type — why the second report of a batch used to hang.
# --------------------------------------------------------------------------- #
def test_a_prefilled_document_type_is_cleared_before_it_is_picked_again():
    """THE bug. From the second report onwards the portal serves the form with the type
    already selected. Re-picking the same value writes React the state it already has,
    React fires no change, the fields never mount, and the run dies waiting on a date
    input. Clearing first makes the re-pick a real transition."""
    page = _FakePage(combo_value=DOC_TYPE)

    _open_new_document_form(page, DOC_TYPE)

    cleared = page.actions.index("press:combobox=Delete")
    assert cleared < page.actions.index(f"fill:combobox={DOC_TYPE}")
    assert page.actions[-1] == "wait_visible:DD.MM.YYYY"


def test_an_empty_document_type_is_not_cleared():
    """A fresh form needs no reset, and the extra keystrokes would only be a way to
    fail on a portal that renders the box read-only until it is opened."""
    page = _FakePage(combo_value="")

    _open_new_document_form(page, DOC_TYPE)

    assert not any(a.startswith("press:combobox") for a in page.actions)


def test_a_form_that_still_will_not_expand_is_reloaded_and_retried(monkeypatch):
    """Clearing loses to a React tree that is wedged harder than one field. A fresh
    navigation throws the whole tree away — the one reset that always works."""
    page = _FakePage(combo_value=DOC_TYPE)
    calls = []

    def _expansion(p, timeout_ms=15000):
        calls.append(p.url)
        if len(calls) == 1:
            raise AssertionError("Locator expected to be visible")

    monkeypatch.setattr(uploader, "_wait_for_form_expansion", _expansion)

    _open_new_document_form(page, DOC_TYPE)

    assert f"goto:{APPEAL}" in page.actions
    assert len(calls) == 2, "the type is picked again after the reload"
    assert page.actions.count(f"fill:combobox={DOC_TYPE}") == 2


def test_a_form_that_never_expands_raises_naming_the_page(monkeypatch):
    """Two full attempts is the end of it. A silent return would hand the caller a
    collapsed form and fail later on a date field, naming the wrong culprit."""
    page = _FakePage(combo_value=DOC_TYPE)

    def _never(p, timeout_ms=15000):
        raise AssertionError("Locator expected to be visible")

    monkeypatch.setattr(uploader, "_wait_for_form_expansion", _never)

    with pytest.raises(RuntimeError) as excinfo:
        _open_new_document_form(page, DOC_TYPE)

    message = str(excinfo.value)
    assert APPEAL in message and "DD.MM.YYYY" in message
    assert "--probe" in message, "the operator is told how to re-map"


def test_the_reload_target_is_built_from_the_pages_own_origin(monkeypatch):
    """No hard-coded host: the portal is whatever origin the operator logged in on."""
    page = _FakePage(url="https://staging.example.gov.az/uqq/new-appeal",
                     combo_value=DOC_TYPE)

    def _once(p, timeout_ms=15000, _seen=[]):
        _seen.append(1)
        if len(_seen) == 1:
            raise AssertionError("Locator expected to be visible")

    monkeypatch.setattr(uploader, "_wait_for_form_expansion", _once)

    _open_new_document_form(page, DOC_TYPE)

    assert "goto:https://staging.example.gov.az/uqq/new-appeal" in page.actions


# --------------------------------------------------------------------------- #
# Review Mode — the hold that keeps the filled form on screen.
# --------------------------------------------------------------------------- #
def test_review_hold_returns_on_closed_stdin(monkeypatch, capsys):
    """Nothing is saved and nothing is half-written: EOF is the end, not a failure."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    _review_mode_hold()

    assert "Form successfully filled!" in capsys.readouterr().out


def test_review_hold_returns_on_enter(monkeypatch, capsys):
    """The documented way out: read the screen, press Enter."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n"))

    _review_mode_hold()

    assert "press Enter here to exit" in capsys.readouterr().out


def test_review_hold_returns_on_ctrl_c(monkeypatch):
    class _Interrupting(io.StringIO):
        def readline(self, *a, **k):
            raise KeyboardInterrupt

    monkeypatch.setattr(sys, "stdin", _Interrupting())
    _review_mode_hold()          # must not raise


def test_review_hold_says_nothing_was_saved(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    _review_mode_hold()
    out = capsys.readouterr().out
    assert "Yadda saxla" in out and "NOT clicked" in out


def test_failed_hold_does_not_claim_the_form_was_filled(monkeypatch, capsys):
    """A run that broke partway must not print a success banner over the wreckage."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    _review_mode_hold(failed=True)

    out = capsys.readouterr().out
    assert "Form successfully filled!" not in out
    assert "PAUSED" in out


def test_red_traceback_names_the_line_that_stopped_the_fill(capsys):
    """"Timeout 30000ms exceeded" alone does not say which field — the frame does."""
    try:
        raise RuntimeError("Caption 'Nəticə:' matched 0 elements")
    except RuntimeError as exc:
        uploader._print_red_traceback(exc)

    out = capsys.readouterr().out
    assert "Caption 'Nəticə:' matched 0 elements" in out
    assert "Traceback" in out
    assert uploader._C.RED in out


def test_failed_hold_still_holds_the_browser(monkeypatch, capsys):
    """The window a failure left behind is the one most worth looking at."""
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    _review_mode_hold(failed=True)

    assert "press Enter here to exit" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# _Stats.filled — what Review Mode is allowed to hold the browser open for.
# --------------------------------------------------------------------------- #
def test_filled_defaults_to_zero():
    assert _Stats().filled == 0


def test_filled_is_separate_from_skipped():
    """A ledger skip fills nothing — holding a browser on it shows an empty form."""
    stats = _Stats()
    stats.skipped += 1                    # ledger said already uploaded
    assert stats.filled == 0


def test_each_stats_gets_its_own_unmatched_list():
    """A shared mutable default would carry one run's skips into the next."""
    a, b = _Stats(), _Stats()
    a.unmatched.append(("r", "ASME VIII"))
    assert b.unmatched == []


# --------------------------------------------------------------------------- #
# The unmatched list — every report this run refused to file, and what blocked it.
# NOT a correction list: nothing was filed, so there is nothing to correct.
# --------------------------------------------------------------------------- #
def test_a_clean_run_prints_no_unmatched_list(capsys):
    uploader._print_unmatched_list(_Stats())
    assert capsys.readouterr().out == ""


def test_the_unmatched_list_names_every_report_and_standard(capsys):
    """A long batch buries the first report's warning under the last. This is the list
    the operator takes to whoever owns the portal's option list."""
    stats = _Stats()
    stats.unmatched = [
        ("compiled_monthly_report_DP_UBOC_APR_2026", "ASME VIII"),
        ("compiled_monthly_report_RT_KHF_APR_2026", "ASME B31.3"),
        ("compiled_monthly_report_DP_SDLN_APR_2026", "AWS D1.1"),
    ]

    uploader._print_unmatched_list(stats)
    out = capsys.readouterr().out

    assert "3 report(s) NOT filed" in out
    assert "Nothing was substituted" in out
    for name, standard in stats.unmatched:
        assert name in out and standard in out


def test_the_unmatched_list_counts_reports_not_rows(capsys):
    """Two standards on one report is one report that did not file, not two."""
    stats = _Stats()
    stats.unmatched = [("report_a", "ASME VIII"), ("report_a", "AWS D1.1")]

    uploader._print_unmatched_list(stats)

    assert "1 report(s) NOT filed" in capsys.readouterr().out


def test_the_unmatched_list_says_no_rerun_flag_is_needed(capsys):
    """Nothing durable was written, so these reports come back by themselves. An
    operator who thinks otherwise reaches for --force, which is for a different thing
    entirely."""
    stats = _Stats()
    stats.unmatched = [("report_a", "ASME VIII")]

    uploader._print_unmatched_list(stats)

    assert "upload themselves once the portal lists them" in capsys.readouterr().out


# --------------------------------------------------------------------------- #
# The no-standard list — reports the portal would refuse because they cite nothing.
# Kept apart from the unmatched list: that one is a portal backlog, this one is a
# source-document defect the operator can fix today.
# --------------------------------------------------------------------------- #
def test_a_clean_run_prints_no_no_standard_list(capsys):
    uploader._print_no_standard_list(_Stats())
    assert capsys.readouterr().out == ""


def test_each_stats_gets_its_own_no_standard_list():
    """A shared mutable default would carry one run's skips into the next."""
    a, b = _Stats(), _Stats()
    a.no_standard.append("report_a")
    assert b.no_standard == []


def test_the_no_standard_list_names_every_report(capsys):
    stats = _Stats()
    stats.no_standard = ["compiled_monthly_report_PMI_KHF_MAR_2026",
                         "compiled_monthly_report_FERRITE_KHF_MAR_2026"]

    uploader._print_no_standard_list(stats)
    out = capsys.readouterr().out

    assert "2 report(s) NOT filed" in out
    assert "Nothing was substituted" in out
    for name in stats.no_standard:
        assert name in out


def test_the_no_standard_list_points_at_the_source_document(capsys):
    """The portal is not missing anything here — the report is. An operator sent to
    the portal's option list would wait for a change that is never coming."""
    stats = _Stats()
    stats.no_standard = ["compiled_monthly_report_PMI_KHF_MAR_2026"]

    uploader._print_no_standard_list(stats)

    assert "add the standard to the source document" in capsys.readouterr().out


def test_the_two_refusal_lists_are_printed_separately(capsys):
    """One report cannot be filed because the portal lacks its standard, the other
    because it has none. Merging them would send both fixes to the wrong owner."""
    stats = _Stats()
    stats.unmatched = [("report_a", "ASME B31.3")]
    stats.no_standard = ["report_b"]

    uploader._print_unmatched_list(stats)
    uploader._print_no_standard_list(stats)
    out = capsys.readouterr().out

    assert "not offered by the portal" in out
    assert "no standard on any row" in out


# --------------------------------------------------------------------------- #
# The probe dump shares output/ with the report sidecars.
# --------------------------------------------------------------------------- #
def test_probe_dump_is_not_a_report_sidecar(tmp_path):
    """--probe rewrites its dump every run, making it the NEWEST output/**/*.json.

    Unfiltered, `python uploader.py` straight after a probe — the exact documented
    sequence — resolves the dump as the report it is about to file to a government
    portal.
    """
    (tmp_path / PROBE_FILENAME).write_text("{}", encoding="utf-8")
    real = tmp_path / "compiled_monthly_report_MT_KHF_MAY_2026.json"
    real.write_text("{}", encoding="utf-8")

    assert _report_sidecars(tmp_path) == [real]


def test_probe_dump_is_skipped_in_nested_output_dirs(tmp_path):
    nested = tmp_path / "MPI" / "KHF"
    nested.mkdir(parents=True)
    (nested / PROBE_FILENAME).write_text("{}", encoding="utf-8")

    assert _report_sidecars(tmp_path) == []


# --------------------------------------------------------------------------- #
# Non-sidecar JSON under output/ must never reach the sweep, and the sidecar
# readers must not crash on one that does. Regression for the AttributeError
# `uploader.py --dry-run --all` raised on output/upload_status.json (an ARRAY).
# --------------------------------------------------------------------------- #
def test_report_sidecars_ignores_system_and_non_report_json(tmp_path):
    """The --all sweep returns ONLY compiled_monthly_report_*.json, never the
    array-shaped upload_status.json (the crash source), the probe dump, a hidden
    dotfile, or an arbitrary stray json."""
    (tmp_path / "upload_status.json").write_text(
        '[{"report_key": "x"}]', encoding="utf-8")
    (tmp_path / PROBE_FILENAME).write_text("{}", encoding="utf-8")
    (tmp_path / ".hidden.json").write_text("{}", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    real = tmp_path / "compiled_monthly_report_MT_KHF_MAY_2026.json"
    real.write_text("{}", encoding="utf-8")

    assert _report_sidecars(tmp_path) == [real]


def test_sidecar_client_code_survives_non_dict_json(tmp_path):
    """A JSON array does not crash the retired-client check — returns "" (unknown)."""
    bad = tmp_path / "upload_status.json"
    bad.write_text('[{"report_key": "x"}]', encoding="utf-8")
    assert _sidecar_client_code(bad) == ""


def test_sidecar_volume_survives_non_dict_json(tmp_path):
    """A JSON array cannot gate volume — returns None (cannot gate), no crash."""
    bad = tmp_path / "upload_status.json"
    bad.write_text('[]', encoding="utf-8")
    assert _sidecar_volume(bad) is None


def test_load_report_json_rejects_non_dict(tmp_path):
    """A non-dict sidecar fails precisely at the boundary, not with a cryptic
    missing-keys error (and is caught by _run_batch's ValueError guard)."""
    bad = tmp_path / "compiled_monthly_report_MT_KHF_MAY_2026.json"
    bad.write_text('[]', encoding="utf-8")
    with pytest.raises(ValueError, match="not a JSON object"):
        load_report_json(bad)


# --------------------------------------------------------------------------- #
# _fill_date — the portal ships the end date prefilled with today.
# --------------------------------------------------------------------------- #
class _FakeDateField:
    """A masked input that ignores fill(), the way MUI's date field does."""

    def __init__(self):
        self.value = "17.07.2026"          # what the portal prefills
        self.calls = []

    def click(self):
        self.calls.append("click")

    def press(self, key):
        self.calls.append(f"press:{key}")
        if key == "ControlOrMeta+a":
            self.selected_all = True

    def press_sequentially(self, text):
        self.calls.append(f"type:{text}")
        self.value = text

    def fill(self, text):
        raise AssertionError("fill() is a no-op on this masked input — type instead")


def test_date_field_is_cleared_before_typing():
    """Typing into a prefilled mask without clearing concatenates or is rejected."""
    field = _FakeDateField()

    _fill_date(field, "01.07.2026")

    assert field.calls == ["click", "press:ControlOrMeta+a", "type:01.07.2026"]
    assert field.value == "01.07.2026"


def test_date_field_value_is_verified_not_assumed(monkeypatch):
    """A mask that silently ignored the write leaves today's date on a filed appeal."""
    import playwright.sync_api

    checked = {}

    class _Expect:
        def __init__(self, loc):
            self._loc = loc

        def to_have_value(self, value):
            checked["asserted"] = value
            if self._loc.value != value:
                raise AssertionError(f"{self._loc.value!r} != {value!r}")

    monkeypatch.setattr(playwright.sync_api, "expect", _Expect)

    _fill_date(_FakeDateField(), "01.07.2026")
    assert checked["asserted"] == "01.07.2026"


def test_date_field_that_swallows_the_write_fails_loudly(monkeypatch):
    import playwright.sync_api

    class _Expect:
        def __init__(self, loc):
            self._loc = loc

        def to_have_value(self, value):
            if self._loc.value != value:
                raise AssertionError(f"{self._loc.value!r} != {value!r}")

    monkeypatch.setattr(playwright.sync_api, "expect", _Expect)

    stubborn = _FakeDateField()
    stubborn.press_sequentially = lambda _t: None      # mask ignores the typing

    with pytest.raises(AssertionError):
        _fill_date(stubborn, "01.07.2026")


# --------------------------------------------------------------------------- #
# _fill_verified — a controlled input can be re-rendered over a landed fill.
#
# MR-MT-UBOC-25-12 died here. Its failure dump shows the inspection-object input
# carrying Mui-focused (so the fill reached the right element) and value="" with no
# maxlength on it — React put "" back when the VÖEN tax lookup resolved carrying a
# form state older than what we had just typed.
# --------------------------------------------------------------------------- #
#: The real value that failed, 204 chars: commas, "&", a hyphen, Azerbaijani ə/ü/ı/ş.
LONG_OBJECT = (
    "DB-2, Recovery Unit for Rescueboat, DetailNo, Boat Fall & RemoteControl Unit, "
    "The load-Measuring sensor bracket, Detail No, "
    "Qazma qülləsinin hərəkəti üçün relslər, Qazma qülləsi üçün dayaqlar, KEQ12 kranı")


class _ClobberedInput(_FakeLocator):
    """A controlled input whose first ``clobber`` bulk fills are re-rendered away.

    Typing survives, because by the second attempt the async lookup has resolved and
    there is no stale state left to commit. That asymmetry is the whole bug: fill()
    reaches the element and lands, and then something else puts "" back.
    """

    def __init__(self, page, kind="obyekt", clobber=1):
        super().__init__(page, kind)
        self._clobber = clobber

    def fill(self, text):
        super().fill(text)
        if self._clobber > 0:
            self._clobber -= 1
            self.value = ""                 # React re-renders over it
            self._page.actions.append(f"clobber:{self.kind}")


@pytest.fixture
def checking_expect(monkeypatch):
    """A real to_have_value. The autouse fixture's is a no-op, and a no-op makes the
    retry unobservable — every attempt would "succeed"."""
    import playwright.sync_api

    class _Expect:
        def __init__(self, locator=None, *a, **k):
            self._loc = locator

        def to_have_value(self, value, *a, **k):
            if self._loc.input_value() != value:
                raise AssertionError(
                    f"{self._loc.input_value()!r} != {value!r}")

        def to_be_visible(self, *a, **k):
            pass

    monkeypatch.setattr(playwright.sync_api, "expect", _Expect)


def test_a_long_multi_item_object_string_is_filled_and_verified(checking_expect):
    """The requested case: the 204-char list, verbatim, in one attempt.

    Length is not what broke this field — fill() is atomic, so 204 characters cost
    exactly what 10 do. Pinned anyway, because commas and "&" are the characters a
    future "escape the value" edit would mangle.
    """
    page = _FakePage()
    field = _FakeLocator(page, "obyekt")

    uploader._fill_verified(field, LONG_OBJECT)

    assert field.value == LONG_OBJECT, "not one character may be lost or escaped"
    assert page.actions.count("fill:obyekt=" + LONG_OBJECT) == 1
    assert not any(a.startswith("type:") for a in page.actions), "no retry was needed"


def test_a_clobbered_field_is_retyped_instead_of_ending_the_report(checking_expect):
    """THE regression. The fill lands, React puts "" back, and the report used to die.

    The second attempt types it instead, which is what a controlled component that
    discarded a bulk set still accepts.
    """
    page = _FakePage()
    field = _ClobberedInput(page, clobber=1)

    uploader._fill_verified(field, LONG_OBJECT)          # must not raise

    assert field.value == LONG_OBJECT
    assert "clobber:obyekt" in page.actions, "the fixture really did empty the box"
    assert f"type:obyekt={LONG_OBJECT}" in page.actions, "attempt 2 types it"


def test_a_field_that_never_holds_its_value_fails_with_a_readable_error(checking_expect):
    """Two attempts is where a clobber stops being a race and starts being a re-map.

    Raised as a named RuntimeError, not a bare Playwright AssertionError: in an
    unattended run's log the latter names a locator and no field, no page, no value.
    """
    page = _FakePage()
    field = _ClobberedInput(page, clobber=99)
    field.press_sequentially = lambda _t: None           # nothing sticks, ever

    with pytest.raises(RuntimeError) as excinfo:
        uploader._fill_verified(field, LONG_OBJECT)

    message = str(excinfo.value)
    assert str(len(LONG_OBJECT)) in message, "the operator is told how long the value was"
    assert "--probe" in message


def test_every_fill_is_cleared_first_and_blurred_after(checking_expect):
    """Both halves are load-bearing.

    Clearing, because the second attempt types and typing into a box that still holds
    the first attempt's value concatenates. Blurring, because React commits a
    controlled input on change AND blur, and the value has to be committed before the
    next field's own lookup can fire.
    """
    page = _FakePage()

    uploader._fill_verified(_FakeLocator(page, "obyekt"), "Boru")

    assert page.actions == [
        "click:obyekt", "press:obyekt=ControlOrMeta+a", "press:obyekt=Delete",
        "fill:obyekt=Boru", "press:obyekt=Tab"]


def test_an_empty_value_is_still_cleared_and_verified(checking_expect):
    """DP reports carry no equipment note, so "" is a real value this fills.

    It must clear and verify like any other — and never reach press_sequentially,
    where an empty string is a pointless round trip to the browser.
    """
    page = _FakePage()
    field = _ClobberedInput(page, kind="equipment", clobber=1)

    uploader._fill_verified(field, "")

    assert field.value == ""
    assert not any(a.startswith("type:") for a in page.actions)


def test_the_voen_blur_is_settled_before_the_next_field_is_typed():
    """Source-level, because the race is between two statements, not inside one.

    The tax lookup fired by the VÖEN blur resolves with a form state older than
    anything typed after it. Without a settle between the blur and the next fill, the
    inspection object is filled into a form that is about to be rolled back — which
    is exactly what MR-MT-UBOC-25-12 hit. _fill_verified's retry recovers from it;
    this is what keeps it rare.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]
    real = body.split("--- real browser path ---")[1]

    voen = real.index('get_by_placeholder("VÖEN")')
    blurred = real.index('press("Tab")', voen)
    settled = real.index("wait_for_timeout", blurred)
    obyekt = real.index("İnspeksiyanın olunan obyekt:", voen)

    assert voen < blurred < settled < obyekt, (
        "the VÖEN blur must be settled before the inspection object is filled")


# --------------------------------------------------------------------------- #
# Source-level guard: the class of bug this pass exists to remove.
# --------------------------------------------------------------------------- #
# --------------------------------------------------------------------------- #
# The dashboard -> form transition. "Tanış oldum" lands on /uqq/e-competition/,
# so the takeover claims a tab that has none of the form's fields on it yet.
# --------------------------------------------------------------------------- #
class _FakeNavPageWithUrl(_FakePage):
    """A _FakePage that records the wait_for_url the transition performs."""

    def __init__(self, url, **kw):
        super().__init__(url=url, **kw)
        self.waited_for = None

    def wait_for_url(self, predicate, timeout=None):
        self.waited_for = predicate
        self.url = APPEAL          # the click worked; the portal navigated


def test_dashboard_takeover_clicks_yeni_sened_automatically():
    """The reported bug: the run sat here until a human clicked the tab."""
    page = _FakeNavPageWithUrl(DASHBOARD)

    _ensure_on_appeal_form(page)

    assert "click:tab-named" in page.actions


def test_the_transition_waits_for_the_form_url_not_just_the_click():
    """A click that silently did nothing must not read as arrival."""
    page = _FakeNavPageWithUrl(DASHBOARD)

    _ensure_on_appeal_form(page)

    assert page.waited_for is uploader.is_appeal_url, (
        "the strict predicate is what proves we left the dashboard")


def test_no_transition_click_when_already_on_the_form():
    """Idempotent — and it must not click a tab that would reset a filled form."""
    page = _FakeNavPageWithUrl(APPEAL)

    _ensure_on_appeal_form(page)

    assert page.actions == []
    assert page.waited_for is None


def test_nothing_is_read_or_filled_while_still_on_the_dashboard():
    """The invariant the two predicates exist to keep.

    The takeover now returns on /uqq/e-competition/, so both upload_report and
    --probe can be handed the dashboard. _open_new_document_form must reach the form
    BEFORE it touches the document-type combobox — otherwise a probe dumps the
    Məlumatlar tab and calls it the appeal form.
    """
    page = _FakeNavPageWithUrl(DASHBOARD, combo_visible=False)

    _open_new_document_form(page, DOC_TYPE)

    assert page.url == APPEAL, "the form was driven from the dashboard"
    assert page.waited_for is uploader.is_appeal_url


def test_open_new_document_form_does_not_double_click_the_tab():
    """_ensure_on_appeal_form and the combo-visible guard both click the same tab."""
    page = _FakeNavPageWithUrl(DASHBOARD, combo_visible=True)

    _open_new_document_form(page, DOC_TYPE)

    assert page.actions.count("click:tab-named") == 1


# --------------------------------------------------------------------------- #
# The form mid-render — the batch killer. Report 1 is skipped, the page is left
# (or reloaded) on /uqq/new-appeal, and report 2 asks for the combobox before
# React has mounted it. is_visible() never waits, so it says False, and the old
# code answered that by hunting a "Yeni sənəd" tab on the page that already IS
# the form. Nothing had mounted there either, so the run died with
# "No 'Yeni sənəd' tab" — one report's clean skip taking the whole batch with it.
# --------------------------------------------------------------------------- #
class _UnmountedNavPage(_FakePage):
    """The appeal form mid-render: the URL is right and NOTHING else is up.

    No combobox, and — unlike _FakePage — no nav strip to fall back on either, which
    is the state that made the fallback raise instead of clicking. Modelling the
    empty strip is the whole point: with _FakePage's count-1 unnamed tab the bug is
    invisible, because there is always something to click.
    """

    def get_by_role(self, role, name=None):
        if role in ("tab", "link", "button"):
            suffix = "named" if name is not None else "first"
            return _FakeLocator(self, f"{role}-{suffix}", n=0)
        return super().get_by_role(role, name)


def test_a_report_after_a_skip_waits_for_the_form_instead_of_hunting_nav():
    """THE regression. Already on the appeal form, so there is nowhere to navigate:
    the combobox is not missing, it is late. Hunting nav here raised RuntimeError and
    ended the batch; waiting is both correct and all that was ever needed."""
    page = _UnmountedNavPage(combo_visible=False, url=APPEAL)

    _open_new_document_form(page, DOC_TYPE)

    assert not any(a.startswith("click:tab") or a.startswith("click:link")
                   or a.startswith("click:button") for a in page.actions), (
        "nothing on the form is a navigation target")
    assert f"fill:combobox={DOC_TYPE}" in page.actions, "the type still gets picked"
    assert page.actions[-1] == "wait_visible:DD.MM.YYYY"


def test_two_reports_in_a_row_survive_the_reloaded_form():
    """The batch shape that broke, end to end: fill, skip+reload, fill again.

    _reset_appeal_form reloads and waits only on the URL, so it hands the next report
    a mounted-nothing page. Both reports have to get their type picked off it.
    """
    page = _UnmountedNavPage(combo_visible=True, url=APPEAL)

    _open_new_document_form(page, DOC_TYPE)
    page.combo._visible = False          # the skip's reload threw the tree away
    page.combo.value = ""
    _open_new_document_form(page, DOC_TYPE)

    assert page.actions.count(f"fill:combobox={DOC_TYPE}") == 2
    assert not any("click:tab" in a for a in page.actions)


def test_the_nav_click_is_declined_on_the_appeal_form():
    """Straight at the guard: on the form it returns, clicks nothing, raises nothing."""
    page = _UnmountedNavPage(url=APPEAL)

    uploader._click_new_document_tab(page)

    assert page.actions == []


def test_the_nav_hunt_still_raises_on_a_page_that_is_neither():
    """The guard must not swallow a genuinely changed portal. Off the appeal form,
    a nav strip that carries no "Yeni sənəd" and no tab at all is still a re-map."""
    page = _UnmountedNavPage(url=DASHBOARD)

    with pytest.raises(RuntimeError) as excinfo:
        uploader._click_new_document_tab(page)

    assert DASHBOARD in str(excinfo.value), "the operator is told which page"
    assert "--probe" in str(excinfo.value)


def test_a_combobox_that_never_arrives_names_the_page(monkeypatch):
    """Waiting replaced the nav hunt, so the wait owns the failure message too. A bare
    Playwright AssertionError names a locator and no page — unreadable in the log of a
    run nobody was watching."""
    import playwright.sync_api

    class _Timeout:
        def __init__(self, locator=None):
            pass

        def to_be_visible(self, *a, **k):
            raise AssertionError("Locator expected to be visible")

    monkeypatch.setattr(playwright.sync_api, "expect",
                        lambda locator=None, *a, **k: _Timeout(locator))
    page = _UnmountedNavPage(combo_visible=False, url=APPEAL)

    with pytest.raises(RuntimeError) as excinfo:
        _open_new_document_form(page, DOC_TYPE)

    message = str(excinfo.value)
    assert APPEAL in message and "Yeni sənəd" in message
    assert "--probe" in message


# --------------------------------------------------------------------------- #
# Save confirmation. The portal shows no toast — it redirects to Layihələr, and
# that is the only thing that says "Yadda saxla" committed the draft.
# --------------------------------------------------------------------------- #
PROJECTS = "https://e-keyfiyyet.gov.az/uqq/projects"


class _FakeSavePage(_FakePage):
    """A page whose wait_for_url resolves only if ``redirects_to`` satisfies it."""

    def __init__(self, redirects_to=None):
        super().__init__(url=APPEAL)
        self.redirects_to = redirects_to
        self.waited_for = None
        self.timeout = None

    def wait_for_url(self, predicate, timeout=None):
        from playwright.sync_api import TimeoutError as PWTimeout

        self.waited_for = predicate
        self.timeout = timeout
        if self.redirects_to is None or not predicate(self.redirects_to):
            raise PWTimeout(f"timed out on {self.url}")
        self.url = self.redirects_to


def test_the_save_is_confirmed_by_the_redirect_to_layiheler():
    page = _FakeSavePage(redirects_to=PROJECTS)

    uploader._await_save_redirect(page)

    assert page.waited_for is uploader.is_projects_url
    assert page.url == PROJECTS


def test_a_save_that_never_redirects_raises_rather_than_reporting_success():
    """The bug this whole change exists to remove, in its opposite direction.

    The caller's very next step is ledger.mark_uploaded. A draft that cannot be
    confirmed must abort the batch, not be recorded as sent.
    """
    page = _FakeSavePage(redirects_to=None)

    with pytest.raises(RuntimeError, match="/uqq/projects"):
        uploader._await_save_redirect(page)


def test_staying_on_the_appeal_form_is_not_a_saved_draft():
    """The portal rejecting the form leaves us exactly where we were."""
    page = _FakeSavePage(redirects_to=APPEAL)

    with pytest.raises(RuntimeError):
        uploader._await_save_redirect(page)


def test_a_bounce_to_login_is_not_a_saved_draft():
    """An expired session redirects away from the form without saving anything."""
    page = _FakeSavePage(
        redirects_to="https://e-keyfiyyet.gov.az/login?returnUrl=/uqq/projects")

    with pytest.raises(RuntimeError):
        uploader._await_save_redirect(page)


def test_the_unconfirmed_save_message_does_not_claim_the_draft_was_lost():
    """It cannot know. The click landed; only the operator can look."""
    page = _FakeSavePage(redirects_to=None)

    with pytest.raises(RuntimeError) as caught:
        uploader._await_save_redirect(page)

    assert "may or may not" in str(caught.value)
    assert "--force" in str(caught.value), "the operator is told how to retry"


def test_the_save_wait_is_generous_by_default():
    """A ceiling on failure, not a delay — a tight one only fails a slow portal."""
    page = _FakeSavePage(redirects_to=PROJECTS)

    uploader._await_save_redirect(page)

    assert page.timeout == uploader._SAVE_REDIRECT_TIMEOUT_MS
    assert uploader._SAVE_REDIRECT_TIMEOUT_MS >= 15000


def test_no_success_toast_is_waited_for_anywhere_in_the_save():
    """The regression guard. The portal has no such toast; waiting on one failed
    every save that had in fact worked, stranding real drafts as IN_PROGRESS.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    code = [line for line in source.splitlines()
            if not line.strip().startswith("#")]

    for toast in ("uğurla", "saxlanıldı", "yadda saxlanıl"):
        offenders = [line for line in code if toast in line and "get_by_text" in line]
        assert not offenders, f"a {toast!r} toast wait is back: {offenders}"


# --------------------------------------------------------------------------- #
# The interactive gate — the operator reads the filled form and decides.
#
# Every save this run makes is a real appeal filed under a real director's identity,
# so the last word belongs to the person looking at the screen. These tests drive the
# real prompt through a substituted stdin, exactly as the Review Mode tests above do.
# --------------------------------------------------------------------------- #
class _Tty(io.StringIO):
    """A stdin that claims to be a terminal — what _interactive_enabled requires."""

    def isatty(self):
        return True


def _answers(monkeypatch, keystrokes: str) -> None:
    monkeypatch.setattr(sys, "stdin", _Tty(keystrokes))


@pytest.mark.parametrize("typed", ["\n", "y\n", "Y\n", "  yes \n"])
def test_enter_or_y_means_save(monkeypatch, typed):
    """Enter alone is the frequent answer, so it is the cheapest keystroke."""
    _answers(monkeypatch, typed)
    assert uploader._confirm_before_save("SER-1", "KHF") == "save"


@pytest.mark.parametrize("typed", ["s\n", "S\n", "skip\n"])
def test_s_means_skip(monkeypatch, typed):
    _answers(monkeypatch, typed)
    assert uploader._confirm_before_save("SER-1", "KHF") == "skip"


@pytest.mark.parametrize("typed", ["q\n", "Q\n", "quit\n"])
def test_q_means_quit(monkeypatch, typed):
    _answers(monkeypatch, typed)
    assert uploader._confirm_before_save("SER-1", "KHF") == "quit"


def test_an_unrecognised_answer_asks_again_instead_of_guessing(monkeypatch, capsys):
    """All three answers are irreversible in their own way; none may be inferred."""
    _answers(monkeypatch, "maybe\nx\ns\n")

    assert uploader._confirm_before_save("SER-1", "KHF") == "skip"
    assert capsys.readouterr().out.count("[INTERACTIVE CONFIRMATION]") == 3


def test_a_closed_stdin_quits_rather_than_saving(monkeypatch, capsys):
    """EOF says there is no operator left, and no draft is filed without one."""
    _answers(monkeypatch, "")

    assert uploader._confirm_before_save("SER-1", "KHF") == "quit"
    assert "nothing was saved" in capsys.readouterr().out


def test_ctrl_c_at_the_prompt_quits_rather_than_saving(monkeypatch):
    class _Interrupting(_Tty):
        def readline(self, *a, **k):
            raise KeyboardInterrupt

    monkeypatch.setattr(sys, "stdin", _Interrupting())
    assert uploader._confirm_before_save("SER-1", "KHF") == "quit"   # must not raise


def test_the_prompt_names_the_report_it_is_asking_about(monkeypatch, capsys):
    """A batch of forty forms: "save this one?" is unanswerable without the serial."""
    _answers(monkeypatch, "\n")

    uploader._confirm_before_save("MR-2026-07-014", "UBOC")

    out = capsys.readouterr().out
    assert "[INTERACTIVE CONFIRMATION]" in out
    assert "MR-2026-07-014" in out and "UBOC" in out
    for option in ("[Enter] or 'y'", "'s'", "'q'"):
        assert option in out
    assert "Your choice [Y/s/q]" in out


# --------------------------------------------------------------------------- #
# When the prompt is on. Each condition below makes it wrong, not just unwanted.
# --------------------------------------------------------------------------- #
def _parsed(monkeypatch, argv, tty=True):
    monkeypatch.setattr(sys, "stdin", _Tty() if tty else io.StringIO())
    return uploader.build_parser().parse_args(argv)


def test_a_live_batch_on_a_terminal_asks_by_default(monkeypatch):
    assert uploader._interactive_enabled(_parsed(monkeypatch, ["--live", "--all"]))


def test_asking_can_be_turned_off(monkeypatch):
    args = _parsed(monkeypatch, ["--live", "--all", "--no-interactive"])
    assert not uploader._interactive_enabled(args)


def test_a_run_that_cannot_save_never_asks(monkeypatch):
    """Without --live nothing is ever saved, so there is no decision to take."""
    args = _parsed(monkeypatch, ["--all", "--interactive"])
    assert not uploader._interactive_enabled(args)


def test_a_dry_run_never_asks(monkeypatch):
    """No browser means nothing on screen to inspect — the prompt would be theatre."""
    args = _parsed(monkeypatch, ["--dry-run", "--live", "--all", "--interactive"])
    assert not uploader._interactive_enabled(args)


def test_a_single_named_report_does_not_ask_unless_told_to(monkeypatch):
    """--report names the one report by hand; that IS the operator's choice."""
    assert not uploader._interactive_enabled(
        _parsed(monkeypatch, ["--live", "--report", "x.json"]))
    assert uploader._interactive_enabled(
        _parsed(monkeypatch, ["--live", "--interactive", "--report", "x.json"]))


def test_a_piped_stdin_never_asks(monkeypatch):
    """The guarantee the GUI depends on.

    It runs uploader.py as a child process with piped stdio and passes --live --all,
    so a prompt taken by default there would block forever on a question nobody can
    see or answer.
    """
    args = _parsed(monkeypatch, ["--live", "--all", "--interactive"], tty=False)
    assert not uploader._interactive_enabled(args)


def test_an_ignored_interactive_flag_says_why(monkeypatch, capsys):
    """An operator who asked for the prompt and did not get it must be told, or they
    would sit watching a batch save itself."""
    args = _parsed(monkeypatch, ["--live", "--all", "--interactive"], tty=False)

    note = uploader._why_not_interactive(args)

    assert "stdin is not a terminal" in note


# --------------------------------------------------------------------------- #
# The cap. MAX_REPORTS_PER_RUN=1 stops a bad selector map from filing a hundred
# appeals before anyone reads the screen; a person answering for each save is a
# stronger form of the same brake, so it replaces it rather than stacking with it.
# --------------------------------------------------------------------------- #
def test_an_interactive_run_offers_every_matched_report(monkeypatch):
    args = _parsed(monkeypatch, ["--live", "--all"])
    assert uploader._effective_limit(args, 12) == 12


def test_an_explicit_limit_is_never_overruled_by_the_prompt(monkeypatch):
    """A cap asked for out loud outranks one that was merely defaulted."""
    args = _parsed(monkeypatch, ["--live", "--all", "--limit", "3"])
    assert args.limit_explicit is True
    assert uploader._effective_limit(args, 12) == 3


def test_an_unattended_live_batch_walks_the_whole_queue(monkeypatch):
    """--live --all --no-interactive is the unattended batch: the operator said out
    loud not to be asked, which is a decision about the whole queue rather than about
    one report, so the default cap gives way to it."""
    args = _parsed(monkeypatch, ["--live", "--all", "--no-interactive"])
    assert uploader._effective_limit(args, 12) == 12


def test_an_explicit_limit_still_pins_an_unattended_batch(monkeypatch):
    """The lift is a default giving way, never a cap being overruled."""
    args = _parsed(monkeypatch, ["--live", "--all", "--no-interactive", "--limit", "4"])
    assert uploader._effective_limit(args, 12) == 4


def test_a_piped_run_that_never_asked_for_silence_keeps_the_cap(monkeypatch):
    """The GUI launches this script with piped stdio and --live --all, and the prompt
    disables ITSELF there. Reading that silence as consent would turn every GUI run
    into a full-queue batch nobody asked for — so the lift needs the flag."""
    args = _parsed(monkeypatch, ["--live", "--all"], tty=False)

    assert not uploader._interactive_enabled(args), "the prompt is off either way"
    assert uploader._effective_limit(args, 12) == 1


def test_the_default_limit_is_not_mistaken_for_an_explicit_one(monkeypatch):
    assert uploader.build_parser().parse_args([]).limit_explicit is False


# --------------------------------------------------------------------------- #
# The batch loop under the prompt — one browser session, one decision per report.
# --------------------------------------------------------------------------- #
class _FakeBatchPage:
    """Stands in for the portal page between reports.

    ``dry_run`` keeps output/upload_status.json (the human-readable audit file) out
    of these tests; the ledger, which owns idempotency, is exercised for real.
    """

    dry_run = True

    def __init__(self):
        self.url = APPEAL
        self.reloads = 0

    def reload(self):
        self.reloads += 1

    def wait_for_url(self, predicate, timeout=None):
        assert predicate(self.url)


def _sidecar(tmp_path, name, serial):
    report = tmp_path / f"{name}.json"
    report.write_text(json.dumps({
        "client_name": "KHF", "client_voen": "1234567890",
        "reporting_period": "FEB_2026", "ndt_method": "MT",
        "report_serial_no": serial, "total_records": 1,
        "items_table": [{"item": "pipe"}]}), encoding="utf-8")
    pdf = tmp_path / f"{name}.pdf"
    pdf.write_bytes(b"%PDF-1.4 batch")
    return report, pdf


@pytest.fixture
def batch(tmp_path, monkeypatch):
    """Two pending reports, a real ledger, and upload_report replaced by a stub that
    answers the prompt exactly as the real one does."""
    from monthly_report.upload_ledger import UploadLedger

    targets = [_sidecar(tmp_path, "report_one", "SER-1"),
               _sidecar(tmp_path, "report_two", "SER-2")]
    seen: list[tuple[str, bool]] = []

    def _stub(page, pdf_path, json_data, portal_cfg, live=False, confirm=None):
        seen.append((Path(pdf_path).name, confirm is not None))
        if confirm is None:
            return "OK"
        return {"save": "OK", "skip": "SKIPPED_BY_OPERATOR",
                "quit": "QUIT_BY_OPERATOR"}[confirm()]

    monkeypatch.setattr(uploader, "upload_report", _stub)

    class _Batch:
        page = _FakeBatchPage()
        ledger = UploadLedger(tmp_path / "state.json")
        keys = [uploader._ledger_key(pdf) for _json, pdf in targets]
        calls = seen

        def run(self, keystrokes, argv=("--live", "--all")):
            _answers(monkeypatch, keystrokes)
            args = uploader.build_parser().parse_args(list(argv))
            return uploader._run_batch(self.page, targets, args, self.ledger, {})

    return _Batch()


def test_enter_saves_and_the_batch_walks_on_to_the_next_report(batch):
    """The whole point: two reports, one process, no restart in between."""
    stats = batch.run("\n\n")

    assert [name for name, _asked in batch.calls] == ["report_one.pdf",
                                                      "report_two.pdf"]
    assert all(asked for _name, asked in batch.calls)
    assert [batch.ledger.get(k).status for k in batch.keys] == ["UPLOADED", "UPLOADED"]
    assert stats.uploaded == 2 and stats.quit_requested is False


def test_a_skip_leaves_the_ledger_exactly_as_it_was(batch):
    """CHECKPOINT 1 announced an intent that never happened. Left standing it would
    BLOCK the report on the next run over a submit that was never made."""
    stats = batch.run("s\n\n")

    assert batch.ledger.get(batch.keys[0]) is None, "no trace of the declined report"
    assert batch.ledger.get(batch.keys[1]).status == "UPLOADED"
    assert stats.uploaded == 1 and stats.skipped == 1 and stats.filled == 1


def test_a_skip_does_not_erase_what_the_ledger_already_knew(batch):
    """The report was re-queued by a content change, so the key was already there.
    Declining it must restore that entry, not delete it."""
    batch.ledger.mark_uploaded(batch.keys[0], "an-older-hash", "SER-1")
    before = batch.ledger.get(batch.keys[0])

    batch.run("s\nq\n")
    after = batch.ledger.get(batch.keys[0])

    assert (after.status, after.content_hash, after.serial, after.updated_at) == (
        before.status, before.content_hash, before.serial, before.updated_at)


def test_a_skip_clears_the_form_before_the_next_report(batch):
    """Only a save redirects away. A skipped form is still filled, and the standards
    box is a multiselect where re-clicking a tag REMOVES it."""
    batch.run("s\n\n")

    assert batch.page.reloads == 1


def test_a_save_does_not_reload_anything(batch):
    """The portal's own redirect to Layihələr already left the form behind."""
    batch.run("\n\n")

    assert batch.page.reloads == 0


def test_quit_stops_the_batch_where_the_operator_said_so(batch):
    stats = batch.run("q\n")

    assert [name for name, _asked in batch.calls] == ["report_one.pdf"]
    assert batch.ledger.get(batch.keys[0]) is None
    assert stats.quit_requested is True
    assert stats.not_reached == 1, "the untouched report is counted, not dropped"
    assert batch.page.reloads == 0, "nothing to clear — the browser is closing"


def test_quitting_is_not_a_failure(batch):
    """A run that ended exactly where its operator asked has nothing to report."""
    stats = batch.run("q\n")

    assert stats.failed == 0 and stats.blocked == 0 and stats.aborted is False


def test_the_summary_says_the_operator_stopped_it(batch, capsys):
    stats = batch.run("q\n")
    capsys.readouterr()

    uploader._print_summary(stats, batch.ledger)

    out = capsys.readouterr().out
    assert "operator's request" in out and "1 report(s) were never offered" in out


def test_an_unattended_batch_is_never_handed_a_prompt(batch):
    """--no-interactive fills and saves without a confirm callback: fill, save, next."""
    stats = batch.run("", argv=("--live", "--all", "--no-interactive"))

    assert batch.calls == [("report_one.pdf", False), ("report_two.pdf", False)]
    assert stats.uploaded == 2


def test_an_unattended_batch_runs_every_report_end_to_end_without_stopping(batch):
    """The whole unattended contract in one test.

    Stdin is EMPTY, which is what an operator who walked away looks like: any
    ``input()`` reached here raises EOFError, and ``_confirm_before_save`` reads that
    as QUIT. So a loop that still paused anywhere would stop after report one and be
    visible as an unsaved second report — not as a hang the suite would have to time
    out on.
    """
    stats = batch.run("", argv=("--live", "--all", "--no-interactive"))

    # Every report driven, in order, none handed a confirm callback.
    assert [name for name, _asked in batch.calls] == ["report_one.pdf",
                                                      "report_two.pdf"]
    assert not any(asked for _name, asked in batch.calls), "nothing was asked"
    # Every report saved and recorded — the run got to the end of the queue.
    assert [batch.ledger.get(k).status for k in batch.keys] == ["UPLOADED", "UPLOADED"]
    assert (stats.uploaded, stats.not_reached, stats.filled) == (2, 0, 0)
    assert stats.quit_requested is False, "an empty stdin was never read as a quit"
    assert stats.failed == 0 and stats.blocked == 0 and stats.aborted is False
    assert batch.page.reloads == 0, "every report saved, so none needed clearing"


# --------------------------------------------------------------------------- #
# Where the gate sits in upload_report — read off the source, because its position
# is the whole safety property.
# --------------------------------------------------------------------------- #
def test_the_operator_is_asked_after_the_form_is_filled_and_before_the_save():
    """Asked any earlier and there is nothing on screen to approve; any later and
    the appeal is already filed."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]
    real = body.split("--- real browser path ---")[1]

    attached = real.index("set_input_files(")
    asked = real.index("confirm()")
    # The click itself, not the fill-only message that also names the button.
    saved = real.index(r'name=_re(r"^Yadda saxla$")')
    assert attached < asked < saved


def test_a_fill_only_run_is_never_asked_to_approve_a_save_that_cannot_happen():
    """The `if not live` return has to come first, or a fill-only run would stop and
    ask about a click it is not going to make."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    real = (source.split("def upload_report(")[1].split("\ndef ")[0]
            .split("--- real browser path ---")[1])

    assert real.index('return "FILLED_NOT_SAVED"') < real.index("confirm()")


def test_the_declined_report_returns_a_distinct_outcome():
    """"skipped by the operator" and "filled but not saved" both save nothing, but
    only the first has a ledger checkpoint to roll back."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    assert 'return "SKIPPED_BY_OPERATOR"' in body
    assert 'return "QUIT_BY_OPERATOR"' in body


def test_the_form_reset_proves_it_landed_back_on_the_appeal_form():
    page = _FakeBatchPage()

    uploader._reset_appeal_form(page)

    assert page.reloads == 1


# --------------------------------------------------------------------------- #
# Zero substitution, at the level of a whole report.
# --------------------------------------------------------------------------- #
def test_the_standards_pre_flight_runs_before_anything_is_touched():
    """Position IS the property. Answered from the baseline before the dry-run branch,
    so review, --dry-run and --live agree — and before any navigation, so a report that
    cannot be filed truthfully costs no clicks."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    checked = body.index("unmatched_standards(")
    simulated = body.index("_is_dry(page)")
    opened = body.index("_open_new_document_form(")
    assert checked < simulated < opened


def test_an_unfilable_report_never_reaches_the_save_or_the_attachment():
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    skipped = body.index('return "SKIPPED_UNMATCHED_STANDARD"')
    assert skipped < body.index("set_input_files(")
    assert skipped < body.index(r'name=_re(r"^Yadda saxla$")')


def test_the_unfilable_report_returns_a_distinct_outcome():
    """Distinct from FILLED_NOT_SAVED and SKIPPED_BY_OPERATOR: only this one means
    the report was never fillable in the first place."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    assert 'return "SKIPPED_UNMATCHED_STANDARD"' in body


def _unfilable_batch(batch, monkeypatch):
    """Make every report come back as skipped for an unmatched standard."""
    def _stub(page, pdf_path, json_data, portal_cfg, live=False, confirm=None):
        uploader._UNMATCHED.clear()
        uploader._UNMATCHED.append("ASME B31.3")
        return "SKIPPED_UNMATCHED_STANDARD"

    monkeypatch.setattr(uploader, "upload_report", _stub)


def test_an_unfilable_report_leaves_no_ledger_entry(batch, monkeypatch):
    """Nothing durable, on purpose: the report stays pending and is re-offered by every
    later run, so it uploads itself the day the portal lists the standard. A recorded
    skip would need a flag to undo."""
    _unfilable_batch(batch, monkeypatch)

    # --limit 1 pins the run to the single report this test is about; an unattended
    # batch would otherwise walk both, and the count below is a per-report claim.
    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "1"))

    assert batch.ledger.get(batch.keys[0]) is None, "not even IN_PROGRESS may survive"
    assert stats.uploaded == 0 and stats.skipped == 1


def test_an_unfilable_report_does_not_block_the_one_behind_it(batch, monkeypatch):
    """One report's missing standard is not the batch's problem — unlike a failure,
    which aborts deliberately."""
    _unfilable_batch(batch, monkeypatch)

    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "2"))

    assert stats.skipped == 2
    assert stats.aborted is False and stats.failed == 0


def test_an_unfilable_report_is_not_counted_as_filled(batch, monkeypatch):
    """`filled` is what Review Mode holds the browser open for. Nothing was typed."""
    _unfilable_batch(batch, monkeypatch)

    stats = batch.run("", argv=("--live", "--all", "--no-interactive"))

    assert stats.filled == 0


def test_an_unfilable_report_names_itself_in_the_end_of_run_list(batch, monkeypatch):
    _unfilable_batch(batch, monkeypatch)

    # --limit 1 pins the run to one report, so the list below is exactly the report
    # this test made unfilable rather than every report the batch would reach.
    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "1"))

    assert stats.unmatched == [("report_one", "ASME B31.3")]


def test_a_restored_prior_entry_survives_an_unfilable_report(batch, monkeypatch):
    """The report was re-queued by a content change, so the key was already UPLOADED.
    Skipping it must restore that entry, not delete the history."""
    batch.ledger.mark_uploaded(batch.keys[0], "an-older-hash", "SER-1")
    before = batch.ledger.get(batch.keys[0])
    _unfilable_batch(batch, monkeypatch)

    batch.run("", argv=("--live", "--all", "--no-interactive"))
    after = batch.ledger.get(batch.keys[0])

    assert (after.status, after.content_hash, after.updated_at) == (
        before.status, before.content_hash, before.updated_at)


# --------------------------------------------------------------------------- #
# No standard, no appeal — the portal will not accept a submission that names no
# normative document, so a report citing none is refused before it costs a click.
# --------------------------------------------------------------------------- #
def _report_json(rows, **overrides):
    data = {"client_name": "KHF", "client_voen": "1234567890",
            "reporting_period": "Mart 2026", "ndt_method": "PMI",
            "report_serial_no": "MR-PMI-KHF-26-03", "total_records": len(rows),
            "items_table": rows}
    data.update(overrides)
    return data


def test_a_report_with_no_standard_at_all_is_skipped():
    """The real PMI and ferrite sidecars: every row's standard cell is blank, because
    those disciplines are not assessed against a normative document."""
    data = _report_json([{"item_name": "Boru", "standard": ""},
                         {"item_name": "Flanş", "standard": "   "}])

    # `page` is never touched — the gate answers before the dry-run branch, so None
    # here is the assertion that no browser is consulted to reach this verdict.
    assert uploader.upload_report(None, "r.pdf", data, {}) == "SKIPPED_EMPTY_STANDARD"


def test_a_report_missing_the_standard_key_entirely_is_skipped():
    """A sidecar predating the standards column claims nothing either."""
    data = _report_json([{"item_name": "Boru"}])

    assert uploader.upload_report(None, "r.pdf", data, {}) == "SKIPPED_EMPTY_STANDARD"


@pytest.mark.usefixtures("portal_2026_08_12")
def test_a_report_that_cites_one_standard_on_one_row_is_not_skipped(monkeypatch):
    """Report-level, not row-level. The blank rows are line items detailed in the
    attached PDF; the appeal itself names a document, which is what the portal asks
    for. Skipping here would refuse a filable report."""
    monkeypatch.setattr(uploader, "_simulate_upload", lambda *a, **k: "REACHED_THE_FILL")
    data = _report_json([{"item_name": "Boru", "standard": ""},
                         {"item_name": "Flanş", "standard": "API 1104"}])

    outcome = uploader.upload_report(_FakeBatchPage(), "r.pdf", data, {})

    assert outcome == "REACHED_THE_FILL"


def test_the_empty_standard_gate_runs_before_anything_is_touched():
    """Position IS the property, exactly as for the unmatched pre-flight: decided from
    the sidecar alone, so review, --dry-run and --live agree, and before any navigation,
    so an unfilable report costs no clicks."""
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    checked = body.index('return "SKIPPED_EMPTY_STANDARD"')
    simulated = body.index("_is_dry(page)")
    opened = body.index("_open_new_document_form(")
    assert checked < simulated < opened


def test_a_report_with_no_standard_never_reaches_the_save_or_the_attachment():
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    skipped = body.index('return "SKIPPED_EMPTY_STANDARD"')
    assert skipped < body.index("set_input_files(")
    assert skipped < body.index(r'name=_re(r"^Yadda saxla$")')


def _no_standard_batch(batch, monkeypatch):
    """Make every report come back as skipped for citing no standard."""
    def _stub(page, pdf_path, json_data, portal_cfg, live=False, confirm=None):
        # The real upload_report clears this on entry; a stub that did not would let
        # an earlier report's unfilable standard be attributed to this one.
        uploader._UNMATCHED.clear()
        return "SKIPPED_EMPTY_STANDARD"

    monkeypatch.setattr(uploader, "upload_report", _stub)


def test_a_report_with_no_standard_leaves_no_ledger_entry(batch, monkeypatch):
    """Nothing durable, for the same reason as the unmatched skip: the report stays
    pending and files itself once its source document carries a standard."""
    _no_standard_batch(batch, monkeypatch)

    # --limit 1 pins the run to the single report this test is about.
    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "1"))

    assert batch.ledger.get(batch.keys[0]) is None, "not even IN_PROGRESS may survive"
    assert stats.uploaded == 0 and stats.skipped == 1


def test_a_report_with_no_standard_does_not_block_the_one_behind_it(batch, monkeypatch):
    _no_standard_batch(batch, monkeypatch)

    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "2"))

    assert stats.skipped == 2
    assert stats.aborted is False and stats.failed == 0


def test_a_report_with_no_standard_is_not_counted_as_filled(batch, monkeypatch):
    """`filled` is what Review Mode holds the browser open for. Nothing was typed."""
    _no_standard_batch(batch, monkeypatch)

    stats = batch.run("", argv=("--live", "--all", "--no-interactive"))

    assert stats.filled == 0


def test_a_report_with_no_standard_names_itself_in_the_end_of_run_list(batch,
                                                                      monkeypatch):
    _no_standard_batch(batch, monkeypatch)

    stats = batch.run("", argv=("--live", "--all", "--no-interactive", "--limit", "1"))

    assert stats.no_standard == ["report_one"]
    assert stats.unmatched == [], "the portal is not missing anything here"


def test_a_restored_prior_entry_survives_a_report_with_no_standard(batch, monkeypatch):
    """The key was already UPLOADED and got re-queued by a content change. Skipping it
    must restore that entry, not delete the e-signed history."""
    batch.ledger.mark_uploaded(batch.keys[0], "an-older-hash", "SER-1")
    before = batch.ledger.get(batch.keys[0])
    _no_standard_batch(batch, monkeypatch)

    batch.run("", argv=("--live", "--all", "--no-interactive"))
    after = batch.ledger.get(batch.keys[0])

    assert (after.status, after.content_hash, after.updated_at) == (
        before.status, before.content_hash, before.updated_at)


# --------------------------------------------------------------------------- #
# Standards fallback — the portal's list is not our vocabulary.
# --------------------------------------------------------------------------- #
class _FakeStandardsBox:
    """The multiselect input, modelled as the portal treats it: CLICKS ONLY.

    Every keyboard entry point raises rather than records. A test that asserts on a
    list of actions can only prove the call it thought to look for did not happen;
    this proves no keystroke reached the field by any route at all, including ones
    added later.
    """

    def __init__(self, page=None):
        self.actions = []
        self._page = page
        if page is not None:
            page.box = self

    def click(self):
        self.actions.append("click")
        if self._page is not None:
            self._page.open_from_box()

    def _no_keyboard(self, name, *a):
        raise AssertionError(
            f"{name}{a} on the standards box — the portal rejects keyboard input on "
            f"this field. Selection is click-only; see _open_standards_list.")

    def fill(self, text):
        self._no_keyboard("fill", text)

    def type(self, text):
        self._no_keyboard("type", text)

    def press(self, key):
        self._no_keyboard("press", key)

    def press_sequentially(self, text):
        self._no_keyboard("press_sequentially", text)


class _FakeOptionsPage:
    """The standards listbox, modelled as the MUI overlay it actually is.

    Three properties that the old flat fake could not express, and that between them
    are the whole bug:

    * it is CLOSED until something opens it;
    * it mounts into a React portal ASYNCHRONOUSLY — ``mounts_late=True`` makes the
      first non-waiting read race it and see nothing, which is what really happened;
    * "Seç" is a TOGGLE, so firing it at an open list closes it.
    """

    def __init__(self, options, opener_count=0, open_on_box_click=True,
                 mounts_late=False, starts_open=False):
        self._options = list(options)
        self._opener_count = opener_count
        self._open_on_box_click = open_on_box_click
        self._mounts_late = mounts_late
        self.is_open = starts_open
        self._mounted = starts_open
        self.clicked = []
        self.roles_asked = []
        self.exact_asked = []      # the `exact=` each get_by_role was given
        self.box = None

    # --- what the portal does ------------------------------------------- #
    def open_from_box(self):
        if self._open_on_box_click:
            self.is_open = True
            self._mounted = not self._mounts_late

    def toggle(self):
        """The "Seç" button. Opens a closed list — and CLOSES an open one."""
        self.is_open = not self.is_open
        self._mounted = self.is_open and not self._mounts_late

    def settle(self):
        """What expect(...).to_be_visible() waits for: the overlay finishing render."""
        if self.is_open:
            self._mounted = True

    @property
    def live(self):
        return list(self._options) if (self.is_open and self._mounted) else []

    # --- the Playwright surface ----------------------------------------- #
    def get_by_role(self, role, name=None, exact=None):
        self.roles_asked.append(role)
        if role == "option" and name is not None:
            # Only the targeting call. Reading the list asks for options unnamed.
            self.exact_asked.append(exact)
        page = self

        class _Options:
            def all_inner_texts(self):
                return page.live

            def count(self):
                return page._opener_count if role == "button" else len(page.live)

            def is_visible(self):
                return bool(page.live)

            def settle(self):
                page.settle()

            @property
            def first(self):
                return self

            def click(self):
                if role == "button":
                    page.toggle()
                # The option name is a plain string (exact=True); the "Seç" opener is
                # still a regex. Record whichever this is — same idiom as _FakeNavPage.
                page.clicked.append(
                    getattr(name, "pattern", name) if name is not None else role)

        return _Options()


@pytest.mark.usefixtures("aliases_2026_08_12")
def test_the_option_list_is_read_without_typing_anything():
    """The bug this replaces: fill() filters MUI by SUBSTRING, and "EEMUA 158" is not
    a substring of "EEMUA 153/158" — so typing emptied the list and the match
    could never fire. Nothing may be typed before the options are read."""
    page = _FakeOptionsPage(["EEMUA 153/158"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "EEMUA 158") == "alias"
    assert not any(a.startswith("fill:") for a in box.actions), box.actions


def test_an_exact_standard_is_selected_without_a_warning(capsys):
    page = _FakeOptionsPage(["API 1104", "ISO 17638"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "API 1104") == "exact"
    assert "Standard Fallback" not in capsys.readouterr().out
    assert page.clicked == ["API 1104"]


def test_the_option_click_is_whole_string_not_a_substring():
    """Unmatched, "API 579" would also match an "API 5791" — a different document.

    The anchoring is exact=True rather than a /^...$/ regex: Playwright serializes a
    regex into its own /pattern/flags literal, and the "/" inside a real option name
    ("ASTM E797/E797M") closes that literal early. exact=True is whole-string on the
    plain text, so it survives the slash.
    """
    page = _FakeOptionsPage(["API 579"])
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "API 579")

    assert page.clicked == ["API 579"]
    assert page.exact_asked == [True], "a substring match would tag the wrong standard"


@pytest.mark.usefixtures("aliases_2026_08_12")
def test_a_sub_number_alias_match_is_selected():
    """EEMUA 158 IS EEMUA 153/158 — the same document (wired as a config alias), so it
    is safe to file with no correction warning."""
    page = _FakeOptionsPage(["EEMUA 153/158"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "EEMUA 158") == "alias"
    assert page.clicked == ["EEMUA 153/158"]


def test_a_core_match_is_selected():
    page = _FakeOptionsPage(["EEMUA 153/158"])
    box = _FakeStandardsBox(page)

    assert _select_standard(
        page, box, "EEMUA 158,Edition 3,Section 7.5.4") == "core"


def test_selection_takes_no_live_flag():
    """Review mode is the rehearsal for --live. Now that nothing is refused, a `live`
    parameter here could only mean the rehearsal stopped matching the performance."""
    import inspect

    assert "live" not in inspect.signature(_select_standard).parameters
    assert "live" not in inspect.signature(uploader._simulate_standards).parameters


def test_an_unmatched_standard_selects_nothing(capsys):
    """ZERO SUBSTITUTION. ASME B31.3 is not on the portal, so nothing is clicked —
    not a method standard, not a placeholder, not the nearest-looking option."""
    page = _FakeOptionsPage(["ISO 17638", "API 5L"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "ASME B31.3") == "unmatched"

    assert page.clicked == []
    out = capsys.readouterr().out
    assert '"ASME B31.3" is not offered by the portal' in out
    assert "REPORT SKIPPED" in out


def test_an_unmatched_standard_never_reaches_for_the_method_standard():
    """The exact substitution that is gone: an MT report's ASME B31.3 became ISO 17638,
    which the portal DOES offer — so this can only be proved by it not being clicked."""
    page = _FakeOptionsPage(["ISO 17638"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "ASME B31.3", method="MT") == "unmatched"
    assert page.clicked == []


@pytest.mark.parametrize("method,standard", [
    ("UTM", "ASME VIII"),       # was ASTM E797/E797M
    ("RT", "ASME B31.3"),       # was ISO 17636
    ("HRT", "ASME B31.3"),      # was ISO 6507
    ("UT", "AWS D1.1"),         # was ISO 17640
])
@pytest.mark.usefixtures("portal_2026_08_12")
def test_no_discipline_substitution_survives_for_any_method(method, standard):
    page = _FakeOptionsPage(list(uploader.PORTAL_STANDARDS))
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, standard, method=method) == "unmatched"
    assert page.clicked == []


def test_the_shipped_placeholder_is_never_tagged():
    """API 5L is offered by the portal and was the configured stand-in. It may only be
    selected by a report that actually cites it."""
    page = _FakeOptionsPage(["API 5L", "ISO 17638"])
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "ASME VIII", method="DP")
    assert "API 5L" not in page.clicked

    assert _select_standard(page, box, "API 5L") == "exact"
    assert page.clicked == ["API 5L"], "only the report that cites it tags it"


def test_an_unmatched_standard_names_what_the_portal_actually_offered(capsys):
    """The operator needs to see the gap to take it to whoever owns the portal list."""
    page = _FakeOptionsPage(["ISO 17638", "API 5L"])
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "ASME B31.3")

    out = capsys.readouterr().out
    assert "ISO 17638" in out and "API 5L" in out


def test_an_unmatched_standard_closes_the_list_with_a_click():
    """A listbox left open is a popper floating over the fields below it, and the form
    reset that follows would have its click eaten by the overlay. Closed with the
    portal's own Seç toggle — the field takes no keystrokes."""
    page = _FakeOptionsPage(["ISO 17638"], opener_count=1)
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "ASME B31.3")

    assert page.clicked == ["^Seç$"]
    assert not page.is_open


def test_an_unmatched_standard_is_recorded_for_the_end_of_run_list():
    """_run_batch drains this to say WHICH standard stopped WHICH report."""
    uploader._UNMATCHED.clear()
    page = _FakeOptionsPage(["ISO 17638"])
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "ASME B31.3", method="MT")

    assert uploader._UNMATCHED == ["ASME B31.3"]
    uploader._UNMATCHED.clear()


def test_no_standards_path_can_raise():
    """The guarantee, read off the source: an unfilable standard costs ONE report, and
    a raise here would abort the batch behind it instead."""
    source = Path(uploader.__file__).read_text(encoding="utf-8")
    body = source.split("def _select_standard(")[1].split("\ndef ")[0]
    assert "raise " not in body, "_select_standard can still abort a batch"


def test_the_substitution_helpers_are_gone_from_the_module():
    """Deleted, not merely unreferenced — a helper left behind gets called again."""
    for name in ("placeholder_standard", "_method_standard", "_skip_standard",
                 "METHOD_STANDARDS", "_SUBSTITUTIONS"):
        assert not hasattr(uploader, name), f"{name} is back"


def test_an_ambiguous_standard_is_refused_not_guessed(capsys):
    """"API" is a subset of all three. A coin flip between documents is not a match."""
    page = _FakeOptionsPage(["API 5L", "API 579", "API 1104"])
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "API") == "unmatched"
    assert page.clicked == []


# --- deduping. Rarer without substitution, but the alias rule still collapses. --- #
@pytest.mark.usefixtures("aliases_2026_08_12")
def test_an_option_already_tagged_is_not_clicked_again():
    """MUI toggles: the second click REMOVES the tag this form just set.

    Two revisions of one document — EEMUA 153 and EEMUA 158 — are both TRUE matches
    for the portal's single "EEMUA 153/158" entry, so one report can reach it twice.
    """
    page = _FakeOptionsPage(["EEMUA 153/158"])
    box = _FakeStandardsBox(page)
    selected = set()

    assert _select_standard(page, box, "EEMUA 158", already=selected) == "alias"
    assert _select_standard(page, box, "EEMUA 153", already=selected) == "duplicate"

    assert page.clicked == ["EEMUA 153/158"], "clicked once, not toggled off"
    assert selected == {"EEMUA 153/158"}


def test_distinct_options_are_each_clicked():
    page = _FakeOptionsPage(["EEMUA 153/158", "ISO 17638"])
    box = _FakeStandardsBox(page)
    selected = set()

    _select_standard(page, box, "EEMUA 158", method="MT", already=selected)
    _select_standard(page, box, "ISO 17638", method="MT", already=selected)

    assert page.clicked == ["EEMUA 153/158", "ISO 17638"]


# --- opening the listbox. The bug that stopped standards being tagged at all. --- #
@pytest.mark.usefixtures("aliases_2026_08_12")
def test_a_listbox_that_mounts_late_is_still_read(capsys):
    """THE regression.

    all_inner_texts() does not auto-wait — it reports whatever exists at that instant.
    Read straight after the click it raced this overlay, saw nothing, and every
    standard was skipped for want of a few milliseconds. Nothing else here matters if
    this does not hold.
    """
    page = _FakeOptionsPage(["ASTM E797/E797M"], mounts_late=True)
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "ASTM E797", method="UTM") == "alias"
    assert page.clicked == ["ASTM E797/E797M"]


def test_the_sec_button_is_not_touched_when_the_box_click_opened_the_list():
    """"Seç" is MUI's toggle. Fired at a list that is already up, it CLOSES it — which
    is how the race turned one slow render into zero standards tagged."""
    page = _FakeOptionsPage(["API 1104"], opener_count=1, mounts_late=True)
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "API 1104")

    assert page.clicked == ["API 1104"], "the toggle must not have been clicked"
    assert page.is_open, "the list must still be open"


def test_the_sec_button_opens_a_listbox_the_input_click_did_not():
    """Probe idx 20: a "Seç" button sits beside this combobox. Fallback, not default."""
    page = _FakeOptionsPage(["API 1104"], opener_count=1, open_on_box_click=False)
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "API 1104") == "exact"

    assert "button" in page.roles_asked
    assert page.clicked == ["^Seç$", "API 1104"]


def test_an_already_open_list_is_not_clicked_shut():
    """The second standard. MUI multiple-mode leaves the list up after a pick, so an
    unconditional box click would toggle it closed and lose every later standard."""
    page = _FakeOptionsPage(["EEMUA 153/158", "ISO 17638"], starts_open=True)
    box = _FakeStandardsBox(page)

    _select_standard(page, box, "EEMUA 158", method="MT")

    assert box.actions == [], "an open list must not be clicked at all"
    assert page.clicked == ["EEMUA 153/158"]


def test_two_standards_in_sequence_both_get_tagged():
    """End to end over the helper: the list stays open between picks, as MUI does."""
    page = _FakeOptionsPage(["EEMUA 153/158", "ISO 17638"], mounts_late=True)
    box = _FakeStandardsBox(page)
    selected = set()

    _select_standard(page, box, "EEMUA 158", method="MT", already=selected)
    _select_standard(page, box, "ISO 17638", method="MT", already=selected)

    assert page.clicked == ["EEMUA 153/158", "ISO 17638"]


def test_a_list_that_never_opens_skips_without_raising_in_review(capsys):
    page = _FakeOptionsPage(["ISO 17638"], open_on_box_click=False)
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "ISO 17638", method="MT") == "unmatched"
    assert page.clicked == []
    assert "REPORT SKIPPED" in capsys.readouterr().out


def test_a_list_that_never_opens_clicks_nothing_it_did_not_read():
    """A list that never opened offers NOTHING. Clicking an option we never saw would
    tag whatever the portal happened to render there — worse than skipping."""
    page = _FakeOptionsPage(["API 1104"], open_on_box_click=False)
    box = _FakeStandardsBox(page)

    assert _select_standard(page, box, "API 1104", method="RT") == "unmatched"
    assert page.clicked == []


def test_nothing_is_ever_typed_into_the_standards_box():
    """The constraint, over every path the box can take: exact, alias, method
    fallback, skip. _FakeStandardsBox RAISES on fill/type/press/press_sequentially,
    so this passes only if no keystroke reached the field by any route."""
    for standard, method, options in (
        ("API 1104", "RT", ["API 1104"]),                    # exact
        ("EEMUA 158", "MT", ["EEMUA 153/158"]),              # alias
        ("EEMUA 158,Edition 3", "MT", ["EEMUA 153/158"]),    # core
        ("ASME VIII", "DP", ["ISO 17638"]),                  # unmatched
    ):
        page = _FakeOptionsPage(options, opener_count=1, mounts_late=True)
        box = _FakeStandardsBox(page)

        _select_standard(page, box, standard, method=method)

        assert box.actions == ["click"], (
            f"{standard} ({method}) did more than click: {box.actions}")


def test_the_close_does_not_reopen_a_list_that_is_already_shut():
    """Seç is a toggle. Fired at a closed list it would OPEN it, leaving a popper over
    the fields below — the exact thing the close exists to prevent."""
    page = _FakeOptionsPage(["ASTM E797/E797M"], opener_count=1)
    box = _FakeStandardsBox(page)

    # A real match selects, and MUI closes the popup on select.
    _select_standard(page, box, "ASTM E797", method="UTM")
    page.is_open = False
    uploader._close_standards_list(page)

    assert not page.is_open
    assert page.clicked == ["ASTM E797/E797M"], "Seç must not have been clicked"


# --------------------------------------------------------------------------- #
# Caption-anchored locators — how the un-labelled fields are found at all.
# --------------------------------------------------------------------------- #
class _FakeAnchorPage:
    """Serves one xpath locator whose count() is scripted per test."""

    def __init__(self, count=1):
        self._count = count
        self.selectors = []

    def locator(self, selector):
        self.selectors.append(selector)
        return _FakeAnchorLocator(self, self._count)


class _FakeAnchorLocator:
    def __init__(self, page, count):
        self._page = page
        self._count = count

    def count(self):
        return self._count

    def locator(self, selector):
        self._page.selectors.append(selector)
        return self


def test_caption_anchor_matches_the_captions_own_text_not_its_ancestors():
    """contains(., ...) would match every ancestor up to <body> — text() does not."""
    page = _FakeAnchorPage()

    _caption_anchor(page, "Nəticə:")

    assert "normalize-space(text())" in page.selectors[0]
    assert "contains(" not in page.selectors[0]


def test_field_after_caption_follows_the_caption():
    page = _FakeAnchorPage()
    _field_after_caption(page, "İnspeksiyanın olunan obyekt:")
    assert page.selectors[-1] == "xpath=following::input[1]"


def test_the_equipment_note_is_anchored_by_caption_not_by_position():
    """:r2c: has no label, name, placeholder or role — the caption is the only handle,
    and its React id regenerates every render, so an id selector would rot."""
    page = _FakeAnchorPage()

    _field_after_caption(page, "İstifadə olunmuş avadanlıqlar barədə qeyd:")

    assert "İstifadə olunmuş avadanlıqlar barədə qeyd:" in page.selectors[0]
    assert "normalize-space(text())" in page.selectors[0]
    assert page.selectors[-1] == "xpath=following::input[1]"


def test_field_before_caption_precedes_the_caption():
    """The director's markers render UNDER their boxes, so the input is behind them."""
    page = _FakeAnchorPage()
    _field_before_caption(page, "(ad/name)")
    assert page.selectors[-1] == "xpath=preceding::input[1]"


@pytest.mark.parametrize("count", [0, 2])
def test_ambiguous_caption_raises_before_anything_is_typed(count):
    """An anchor matching two elements silently picks one — on a government form."""
    page = _FakeAnchorPage(count=count)

    with pytest.raises(RuntimeError, match="re-run --probe"):
        _field_after_caption(page, "Nəticə:")


def test_xpath_literal_survives_a_caption_containing_a_quote():
    """XPath 1.0 has no escape char — naive quoting yields a malformed expression."""
    assert _xpath_literal("it's") == '"it\'s"'
    assert _xpath_literal('say "hi"') == "'say \"hi\"'"
    both = _xpath_literal("it's a \"quote\"")
    assert both.startswith("concat(")


# --------------------------------------------------------------------------- #
# Automated navigation — a shortcut that must never cost us the manual path.
# --------------------------------------------------------------------------- #
class _FakeNavPage:
    """Records the click order. ``fail_at`` makes one step raise like the portal."""

    def __init__(self, fail_at=None):
        self.clicks = []
        self.fail_at = fail_at
        self.url = "https://e-keyfiyyet.gov.az/home"

    def _maybe_fail(self, step):
        if self.fail_at == step:
            from playwright.sync_api import TimeoutError as PWTimeout
            raise PWTimeout(f"simulated failure at {step}")

    def get_by_role(self, role, name=None):
        return _FakeNavLocator(self, f"{role}:{getattr(name, 'pattern', name)}")

    def get_by_text(self, text):
        return _FakeNavLocator(self, "card")

    def wait_for_url(self, predicate, timeout=None):
        self._maybe_fail("wait")


class _FakeNavLocator:
    def __init__(self, page, kind):
        self._page = page
        self.kind = kind

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_by_role(self, role, name=None):
        return _FakeNavLocator(self._page, f"dialog-{role}")

    def click(self):
        self._page._maybe_fail(self.kind)
        self._page.clicks.append(self.kind)


def test_navigation_clicks_e_services_then_the_card_then_the_modal():
    page = _FakeNavPage()

    assert _navigate_to_appeal_form(page) is True

    assert page.clicks == ["link:E-Xidmətlər", "card", "dialog-button"]


@pytest.mark.parametrize("fail_at", ["link:E-Xidmətlər", "wait", "card"])
def test_a_navigation_failure_is_swallowed_not_raised(fail_at):
    """An expired session bounces every step to login. That is not a crash — the
    takeover wait runs next and asks the operator to walk there by hand."""
    page = _FakeNavPage(fail_at=fail_at)

    assert _navigate_to_appeal_form(page) is False       # must not raise


# --------------------------------------------------------------------------- #
# What _reach_appeal_form hands back. This is a contract, not a detail: the page
# it returns is driven directly by upload_report, so a pair returned here reaches
# the fill as `page` and dies on the first locator with
# "'tuple' object has no attribute 'get_by_role'".
#
# Nothing covered this until it broke a live run, because the shield tests below
# monkeypatch _reach_appeal_form — they stubbed the one function that was wrong,
# so its real return value was never looked at by anything.
# --------------------------------------------------------------------------- #
class _PortalPage:
    """The tab the takeover claims. Only what _reach_appeal_form touches."""

    def __init__(self, url="https://e-keyfiyyet.gov.az/home"):
        self.url = url

    def goto(self, url):
        self.url = url

    def wait_for_load_state(self, state):
        pass


class _PortalContext:
    def __init__(self, page):
        self.pages = [page]
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def portal(monkeypatch):
    """A launched context whose takeover succeeds. No browser, no network."""
    page = _PortalPage()
    ctx = _PortalContext(page)
    monkeypatch.setattr(uploader, "_navigate_to_appeal_form", lambda p: True)
    monkeypatch.setattr(uploader, "_await_takeover", lambda c, timeout_s: page)
    monkeypatch.setattr(uploader, "_launch_context", lambda pw, cfg: ctx)
    return {"page": page, "context": ctx, "cfg": {"landing_url": "https://x/home"}}


def test_reach_appeal_form_returns_the_page_not_a_pair(portal):
    """The regression: a (context, page) here becomes `page` in upload_report."""
    got = _reach_appeal_form(portal["context"], portal["cfg"], "https://x/uqq/new-appeal")

    assert got is portal["page"]
    assert not isinstance(got, tuple)


def test_reach_appeal_form_returns_the_tab_the_takeover_claimed(monkeypatch, portal):
    """The form can open in a NEW tab — the returned page must be that one."""
    other = _PortalPage("https://e-keyfiyyet.gov.az/uqq/new-appeal")
    monkeypatch.setattr(uploader, "_await_takeover", lambda c, timeout_s: other)

    got = _reach_appeal_form(portal["context"], portal["cfg"], "https://x")

    assert got is other


def test_open_portal_returns_a_flat_context_page_pair(portal):
    """--probe unpacks this. A nested pair breaks the probe exactly like the fill."""
    context, page = _open_portal(object(), portal["cfg"], "https://x/uqq/new-appeal")

    assert context is portal["context"]
    assert page is portal["page"]
    assert not isinstance(page, tuple)


def test_the_page_open_portal_returns_can_actually_be_driven(portal):
    """A page-shaped assert, not an identity one: this is what upload_report needs."""
    _context, page = _open_portal(object(), portal["cfg"], "https://x/uqq/new-appeal")

    assert hasattr(page, "url"), "upload_report drives this object directly"


# --------------------------------------------------------------------------- #
# The error-resilient shield — a failure must never cost the operator the window.
# --------------------------------------------------------------------------- #
class _FakeContext:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


@pytest.fixture
def shield(monkeypatch, tmp_path):
    """Drives main()'s browser branch with every real dependency stubbed out."""
    state = {"held": None, "context": _FakeContext(), "close_order": []}

    class _PW:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(uploader, "_sync_playwright", lambda: _PW())
    monkeypatch.setattr(uploader, "_launch_context", lambda pw, cfg: state["context"])
    monkeypatch.setattr(uploader, "_load_portal_config_cached", None, raising=False)
    monkeypatch.setattr(uploader, "load_portal_config",
                        lambda *a, **k: {"url": "https://x/uqq/new-appeal",
                                         "director": {}})
    monkeypatch.setattr(uploader, "_resolve_targets",
                        lambda args: [(tmp_path / "r.json", tmp_path / "r.pdf")])
    (tmp_path / "r.pdf").write_bytes(b"%PDF-1.4")
    # "r" has no month, which portal.upload_closed_months_only refuses; these tests are
    # about the browser shield, so the month check is pinned off, not read from the
    # live config (tests/test_closed_months_only.py covers it).
    monkeypatch.setattr(uploader, "_closed_months_only", lambda: False)

    def _hold(failed=False):
        state["held"] = {"failed": failed}
        state["close_order"].append("hold")

    monkeypatch.setattr(uploader, "_review_mode_hold", _hold)

    real_close = state["context"].close

    def _close():
        state["close_order"].append("close")
        real_close()

    state["context"].close = _close
    return state


def test_a_failure_in_fill_only_holds_the_browser_open(shield, monkeypatch, capsys):
    """The whole point: the window stays on whatever the failure left on screen."""
    def _boom(*a, **k):
        raise RuntimeError("locator resolved nothing")

    monkeypatch.setattr(uploader, "_reach_appeal_form", _boom)

    uploader.main(["--report", "r.json"])

    assert shield["held"] == {"failed": True}
    assert "locator resolved nothing" in capsys.readouterr().out


def test_the_hold_runs_before_the_context_is_closed(shield, monkeypatch):
    """Held after the close, it would hold a window that is already gone."""
    monkeypatch.setattr(uploader, "_reach_appeal_form",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))

    uploader.main(["--report", "r.json"])

    assert shield["close_order"] == ["hold", "close"]


def test_a_takeover_timeout_still_holds_the_browser(shield, monkeypatch):
    """SystemExit mid-login must not slam the window shut on a half-done e-İmza."""
    def _timeout(*a, **k):
        raise SystemExit("Timed out after 900s waiting for /uqq/new-appeal")

    monkeypatch.setattr(uploader, "_reach_appeal_form", _timeout)

    uploader.main(["--report", "r.json"])

    assert shield["held"] == {"failed": True}


def test_live_does_not_swallow_the_failure(shield, monkeypatch):
    """--live keeps its old contract: failures propagate, the ledger stays honest."""
    monkeypatch.setattr(uploader, "_reach_appeal_form",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(uploader, "assert_director_configured", lambda cfg: None)

    with pytest.raises(RuntimeError, match="boom"):
        uploader.main(["--live", "--report", "r.json"])

    assert shield["held"] is None
    assert shield["context"].closed is True


def test_a_clean_fill_only_run_holds_too(shield, monkeypatch):
    """Not gated on stats.filled — a skipped report still leaves a window open."""
    # A _PortalPage, not a bare object(): a stub that cannot be told apart from a
    # tuple is how the (context, page) return survived 353 green tests.
    monkeypatch.setattr(uploader, "_reach_appeal_form", lambda *a, **k: _PortalPage())
    monkeypatch.setattr(uploader, "_run_batch",
                        lambda *a, **k: _Stats(skipped=1))

    uploader.main(["--report", "r.json"])

    assert shield["held"] == {"failed": False}


def test_the_shield_passes_the_page_straight_through_to_the_batch(shield, monkeypatch):
    """main must hand _run_batch what _reach_appeal_form returned, unwrapped."""
    page = _PortalPage()
    seen = {}

    def _batch(p, *a, **k):
        seen["page"] = p
        return _Stats()

    monkeypatch.setattr(uploader, "_reach_appeal_form", lambda *a, **k: page)
    monkeypatch.setattr(uploader, "_run_batch", _batch)

    uploader.main(["--report", "r.json"])

    assert seen["page"] is page, "main re-wrapped or re-ordered the page"


# --------------------------------------------------------------------------- #
# --live may not proceed without the two identifiers the form actually receives.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("missing", ["fin", "seriya_nomresi"])
def test_live_refuses_when_a_director_identifier_is_blank(missing):
    director = {"ad": "A", "soyadi": "B", "atasinin_adi": "C", "fin": "1",
                "seriya_nomresi": "2"}
    director[missing] = "  "

    with pytest.raises(SystemExit, match=missing):
        assert_director_configured({"director": director})


@pytest.mark.parametrize("blank", ["ad", "soyadi", "atasinin_adi"])
def test_live_proceeds_when_only_a_name_part_is_blank(blank):
    """The name boxes are auto-searched by the portal, so we never type them.

    Gating --live on config that is never sent would block a run for no reason.
    The keys stay in settings.yaml only as the value the dry-run prints for the
    operator to check the portal's lookup against.
    """
    director = {"ad": "A", "soyadi": "B", "atasinin_adi": "C", "fin": "1",
                "seriya_nomresi": "2"}
    director[blank] = "  "

    assert_director_configured({"director": director})


def test_live_proceeds_on_a_complete_director():
    assert_director_configured({"director": {
        "ad": "TEST", "soyadi": "TESTƏROV", "atasinin_adi": "ƏLİ",
        "fin": "1234567", "seriya_nomresi": "AZE123"}})


def test_mapped_fields_do_not_use_get_by_label():
    """The probe proves these carry no <label>. get_by_label on them matches nothing.

    Cheap to reintroduce by muscle memory (the labels are printed right there on the
    page), and the symptom is a timeout thirty seconds into a live run.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    for field in ("VÖEN", "FİN", "Seriya nömrəsi", "Müvafiq sənədi yükləyin",
                  "İnspeksiyanın olunan obyekt", "Nəticə:", "inspeksiya:"):
        for line in body.splitlines():
            if field in line and "get_by_label" in line and not line.strip().startswith("#"):
                pytest.fail(f"{field} has no <label> in the probe dump: {line.strip()}")


def test_the_directors_name_is_never_typed_into_the_form():
    """FİN + Seriya go in; the portal's own lookup supplies the three name boxes.

    Typing them back races that search, and whichever wins decides the name printed
    on an appeal a real person signs. The blur + settle is what triggers and then
    waits for the lookup, so its absence is as much a bug as re-adding the fills.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]
    real = body.split("--- real browser path ---")[1]

    for caption in ("(ad/name)", "(soyadı/surname)", "(atasının adı/middle name)"):
        for line in real.splitlines():
            if caption in line and "_fill_verified" in line:
                pytest.fail(f"the director's name is being typed: {line.strip()}")

    seriya = real.index('get_by_placeholder("Seriya nömrəsi")')
    blurred = real.index('press("Tab")', seriya)
    settled = real.index("wait_for_timeout", blurred)
    assert seriya < blurred < settled, (
        "the Seriya fill must be followed by a blur and then a settle, so the "
        "portal's auto-search is both triggered and waited for")


def test_the_client_name_is_never_typed_into_the_form():
    """:r26:/:r27: are the tax database's answer, and it outranks our registry.

    A future edit that "fills in the missing field" would be writing a display name
    ("UBOC") over a legal one, into a box nobody has identified.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]

    for line in body.splitlines():
        if line.strip().startswith("#"):
            continue
        assert 'payload["client_name"]' not in line, (
            f"client_name is being written to the form: {line.strip()}")


# --------------------------------------------------------------------------- #
# Upload integrity — the PDF we attach is the PDF the browser registers.
# --------------------------------------------------------------------------- #
def test_file_integrity_returns_size_and_sha256(tmp_path):
    """The value logged before the attach must be the real file's size and hash."""
    import hashlib

    blob = b"%PDF-1.4\n" + b"integrity" * 5000
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(blob)

    size, digest = uploader._file_integrity(pdf)

    assert size == len(blob)
    assert digest == hashlib.sha256(blob).hexdigest()


def test_file_integrity_streams_a_file_larger_than_one_block(tmp_path):
    """The 1 MiB streaming loop must hash every block, not just the first."""
    import hashlib

    blob = b"x" * ((1 << 20) * 2 + 7)   # two full blocks plus a remainder
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(blob)

    size, digest = uploader._file_integrity(pdf)

    assert size == len(blob)
    assert digest == hashlib.sha256(blob).hexdigest()


def test_file_integrity_raises_on_a_missing_file(tmp_path):
    """An unhashable PDF must stop the upload, not be attached blind."""
    with pytest.raises(OSError):
        uploader._file_integrity(tmp_path / "does-not-exist.pdf")


def test_the_attach_step_logs_a_hash_then_attaches_without_reading_el_files():
    """The attach must log the SHA-256 then attach — but never read el.files back.

    The portal's React input clears its DOM .files list right after attach, so a
    post-attach el.files check reads empty and falsely fails a real upload. This guards
    against that check being reintroduced. Source-inspected because no test drives
    upload_report's real browser branch.
    """
    source = (_ROOT / "uploader.py").read_text(encoding="utf-8")
    body = source.split("def upload_report(")[1].split("\ndef ")[0]
    real = body.split("--- real browser path ---")[1]

    hashed = real.index("_file_integrity(pdf_path)")
    attached = real.index("set_input_files(str(pdf_path))")
    # Searched from the attach onwards: an earlier wait_for_timeout (the director
    # auto-search settle) would otherwise satisfy this and hide a missing one here.
    settled = real.index("wait_for_timeout", attached)

    assert hashed < attached, "the SHA-256 must be logged BEFORE the file is attached"
    assert attached < settled, "the attach must be followed by a settle, not an assertion"
    assert ".evaluate(" not in real, (
        "the file input must NOT be read back — the React input clears its file "
        "list after attach, so any evaluate() round-trip falsely fails")
