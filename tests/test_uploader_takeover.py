"""Tests for uploader.py's multi-tab takeover wait.

The portal does not redirect the tab we launched: after the e-İmza login it
spawns ``/uqq/new-appeal`` in a NEW tab. A wait pinned to ``pages[0]`` therefore
sits on the login page until the timeout expires and the run dies having filled
nothing. These tests pin the behaviour that fixes that — the form is found in
whichever tab it lands in, and that tab becomes the one the run drives.

No browser is launched. The fakes below stand in for a Playwright BrowserContext
and Page, exactly as far as _await_takeover actually uses them.
"""

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

pytest.importorskip("playwright", reason="_await_takeover imports playwright's "
                                         "error classes")

from playwright.sync_api import Error as PWError  # noqa: E402
from playwright.sync_api import TimeoutError as PWTimeout  # noqa: E402

from uploader import _await_takeover  # noqa: E402

FORM = "https://e-keyfiyyet.gov.az/uqq/new-appeal"
LOGIN = "https://e-keyfiyyet.gov.az/login"
HOME = "https://e-keyfiyyet.gov.az/home"
#: Where "Tanış oldum" actually lands — the dashboard, one "Yeni sənəd" from the form.
DASHBOARD = "https://e-keyfiyyet.gov.az/uqq/e-competition/"


class _FakePage:
    """A Page that never navigates unless a test says it does.

    ``navigates_to`` makes wait_for_url succeed once (the same-tab redirect
    case); ``raises`` makes it blow up the way a closed tab does.
    """

    def __init__(self, url, navigates_to=None, raises=None, close_raises=False):
        self.url = url
        self._navigates_to = navigates_to
        self._raises = raises
        self._close_raises = close_raises
        self.closed = False
        self.brought_to_front = False

    def wait_for_url(self, predicate, timeout=None):
        if self._raises is not None:
            raise self._raises
        if self._navigates_to is not None:
            self.url = self._navigates_to
            self._navigates_to = None
            if predicate(self.url):
                return None
        raise PWTimeout("no navigation")

    def bring_to_front(self):
        self.brought_to_front = True

    def close(self):
        if self._close_raises:
            raise PWError("tab is being closed")
        self.closed = True


class _FakeContext:
    def __init__(self, *pages):
        self.pages = list(pages)


# --------------------------------------------------------------------------- #
# Finding the form, wherever the portal decided to put it.
# --------------------------------------------------------------------------- #
def test_form_already_open_in_the_first_tab_is_taken_over_immediately():
    form = _FakePage(FORM)
    ctx = _FakeContext(form)

    assert _await_takeover(ctx, timeout_s=5) is form
    assert form.closed is False
    assert form.brought_to_front is True


def test_form_in_a_second_tab_is_found_and_becomes_the_active_page():
    """The reported bug: the form opens in a NEW tab, pages[0] stays on login."""
    login = _FakePage(LOGIN)
    form = _FakePage(FORM)
    ctx = _FakeContext(login, form)

    got = _await_takeover(ctx, timeout_s=5)

    assert got is form
    assert form.brought_to_front is True
    assert login.closed is True, "idle login tab should be cleaned up"
    assert form.closed is False


def test_form_arriving_later_in_a_new_tab_is_picked_up_by_the_rescan():
    """A tab that appears mid-wait — nothing about it is knowable up front."""
    home = _FakePage(HOME)
    ctx = _FakeContext(home)
    form = _FakePage(FORM)

    def spawn_tab(predicate, timeout=None):
        ctx.pages.append(form)
        raise PWTimeout("still on home")

    home.wait_for_url = spawn_tab

    assert _await_takeover(ctx, timeout_s=5) is form
    assert home.closed is True


def test_the_dashboard_is_taken_over_immediately():
    """The reported bug: "Tanış oldum" lands here, and the wait ignored it — the run
    sat on a perfectly drivable tab until a human clicked "Yeni sənəd"."""
    dashboard = _FakePage(DASHBOARD)
    ctx = _FakeContext(dashboard)

    assert _await_takeover(ctx, timeout_s=5) is dashboard
    assert dashboard.brought_to_front is True


def test_a_tab_navigating_to_the_dashboard_mid_wait_is_claimed():
    login = _FakePage(LOGIN, navigates_to=DASHBOARD)
    ctx = _FakeContext(login)

    got = _await_takeover(ctx, timeout_s=5)

    assert got is login
    assert got.url == DASHBOARD


def test_same_tab_navigation_still_works():
    """The old single-tab redirect path must not regress."""
    page = _FakePage(HOME, navigates_to=FORM)
    ctx = _FakeContext(page)

    got = _await_takeover(ctx, timeout_s=5)

    assert got is page
    assert got.url == FORM
    assert page.brought_to_front is True


# --------------------------------------------------------------------------- #
# What must NOT count as arrival.
# --------------------------------------------------------------------------- #
def test_login_redirect_carrying_the_form_in_its_query_is_not_a_match():
    """The path-only rule, now across tabs: this URL is the bounce AWAY."""
    bounced = _FakePage(f"{LOGIN}?returnUrl=%2Fuqq%2Fnew-appeal")
    ctx = _FakeContext(bounced)

    with pytest.raises(SystemExit) as exc:
        _await_takeover(ctx, timeout_s=0)

    assert "Timed out" in str(exc.value)
    assert bounced.closed is False, "nothing may be closed on the failure path"


# --------------------------------------------------------------------------- #
# Failures around the form must not cost us the form.
# --------------------------------------------------------------------------- #
def test_an_idle_tab_that_refuses_to_close_does_not_fail_the_run():
    stubborn = _FakePage(HOME, close_raises=True)
    form = _FakePage(FORM)
    ctx = _FakeContext(stubborn, form)

    assert _await_takeover(ctx, timeout_s=5) is form
    assert stubborn.closed is False


def test_a_watched_tab_closing_does_not_end_a_wait_other_tabs_can_still_win():
    """Closing the stale login tab is routine once tabs multiply."""
    dying = _FakePage(LOGIN, raises=PWError("Target page closed"))
    ctx = _FakeContext(dying)
    form = _FakePage(FORM)

    def die_then_the_form_opens(predicate, timeout=None):
        ctx.pages.remove(dying)
        ctx.pages.append(form)
        raise PWError("Target page closed")

    dying.wait_for_url = die_then_the_form_opens

    assert _await_takeover(ctx, timeout_s=5) is form


def test_closing_every_tab_ends_the_run_without_a_traceback():
    page = _FakePage(HOME)
    ctx = _FakeContext(page)

    def close_everything(predicate, timeout=None):
        ctx.pages.clear()
        raise PWTimeout("gone")

    page.wait_for_url = close_everything

    with pytest.raises(SystemExit) as exc:
        _await_takeover(ctx, timeout_s=5)

    assert "closed before reaching" in str(exc.value)
    assert "nothing was filled" in str(exc.value)


def test_timeout_message_names_every_open_tab():
    ctx = _FakeContext(_FakePage(LOGIN), _FakePage(HOME))

    with pytest.raises(SystemExit) as exc:
        _await_takeover(ctx, timeout_s=0)

    msg = str(exc.value)
    assert LOGIN in msg and HOME in msg
    assert "Nothing was filled, nothing was saved." in msg
