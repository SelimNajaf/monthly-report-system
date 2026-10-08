#!/usr/bin/env python
"""E-Keyfiyyet portal upload orchestrator (Playwright, sync API).

Command-line browser automation for the digital-integration phase. Reads a compiled
monthly report's JSON sidecar (produced by ``main.py``) and drives the government
appeal form at ``https://e-keyfiyyet.gov.az/uqq/new-appeal``: document type, the
inspection date range, the client's VÖEN, the distinct inspected items and
standards, the overall verdict, the signing director's credentials, and the PDF.

Safety model (read this before running anything)
------------------------------------------------
This writes to a live government system, so three independent brakes apply:

1. ``MAX_REPORTS_PER_RUN = 1`` — one report per run by default, even with ``--all``.
   ``--limit N`` raises the cap deliberately, and only a ``--live`` run can chain:
   a fill-only run stops after one form so the operator's review is not overwritten.
   An INTERACTIVE live run (``--interactive``, the default for ``--live --all`` on a
   terminal) lifts the default cap instead, because a human answering for every save
   is a stronger brake than a number: the batch walks every matched report, pausing
   on each filled form until the operator presses Enter (save), ``s`` (skip) or
   ``q`` (end the run). ``--live --all --no-interactive`` lifts it the same way for an
   UNATTENDED batch: every matched report is filled and saved in one continuous loop,
   with no prompt of any kind. An explicit ``--limit`` still pins the cap either way.
2. ``--live`` is required to click ``Yadda saxla``. Without it the form is filled
   and left for review, and the ledger entry is rolled back so nothing is recorded
   as sent. The same rollback covers a report the operator declines at the prompt.
3. ``E-imza ilə təsdiqlə`` is never located and never clicked. The e-signature is
   always a human decision, made in the browser window this script leaves open.

Authentication
--------------
Manual and persisted, never scripted: the run opens a Chrome window against the
profile at ``portal.user_data_dir``. Log in there ONCE by hand; the session cookie
lives in that directory and later runs reuse it. This script never sees a password.

Not CDP, and why
----------------
The original design called for ``connect_over_cdp("http://localhost:9222")`` to take
over the operator's already-open, already-authenticated Chrome. That is not
achievable: port 9222 only exists when Chrome is *started* with
``--remote-debugging-port=9222``, and Chrome 136+ refuses that flag on the default
profile directory — so the window you already have open cannot be attached to
without relaunching it, which defeats the point. A dedicated persistent profile
gives the same "log in once, stay logged in" property with no flags and no port.

Selectors
---------
Every locator in ``upload_report`` is mapped from ``output/portal_form_probe.json``
and marked in-line with the probe id it came from. ``--probe`` regenerates that dump
from the live form; re-run it and re-check the mapping whenever the portal changes.

Most of this form's fields carry NO accessible attribute — no label, no placeholder,
no name, only a React ``useId`` (``:r28:``) that regenerates on every render. Their
captions are loose text beside the box rather than a ``<label for>``, so they are
located by that caption text (see ``_field_after_caption``). Each anchor asserts it
matched exactly one element before anything is typed.

Standards
---------
The portal names normative documents its own way, and only offers a fixed list of
them — see ``PORTAL_STANDARDS``. ``match_portal_standard`` reconciles ours against
its: exact (separator-blind), then whole-token subset (``EEMUA 158`` is
``EEMUA 153/158``), then the same after dropping an edition/section suffix. Every
rule names the SAME document, so all are safe to file.

ZERO SUBSTITUTION. Anything the portal cannot name is never stood in for — not by the
discipline's method standard, not by a placeholder. A report carrying even ONE such
standard is skipped whole (``SKIPPED_UNMATCHED_STANDARD``): nothing is typed, nothing is
saved, and the ledger is left untouched so the report uploads itself on a later run,
the day the portal lists the standard. See ``unmatched_standards``.

``portal.standard_policy: any`` (ADR-010; default ``all`` is the rule above) files the
offered standards instead and prints the rest; still nothing is substituted, and a
report with none offered is still skipped whole.

The mirror image of that is a report citing NO standard at all — every ``standard`` cell
blank, as the PMI and ferrite families are. The portal will not accept an appeal that
names no normative document, so such a report is skipped whole too
(``SKIPPED_EMPTY_STANDARD``), on the same terms: nothing typed, nothing saved, nothing
recorded. The fix is upstream in the source document, not here — no standard is ever
invented to fill the box.

This replaces an earlier policy that substituted and warned, on the grounds that
``--live`` only saves an unsigned DRAFT a human corrects before signing. A government
appeal must not name a normative document the inspection was not assessed against, in
draft or otherwise, so the substitution is gone rather than merely flagged.

Only ~21% of our corpus by row count can be named exactly: the portal has no ASME
entry, and ``ASME B31.3`` alone is 223 rows. Under this policy that is not a warning
but a skip, so most reports will not file until the portal's list grows. ``--dry-run``
reports exactly which, per report, without a browser; ``--probe`` measures the live
list. The gap is a portal/process question and not one this script can solve.

What is eligible at all
-----------------------
The portal takes appeals for **December 2025 onward**. A report whose reporting month
starts before ``PORTAL_UPLOAD_CUTOFF`` (2025-12-01) is refused in ``_resolve_targets``
as ``SKIPPED_PRE_DEC_2025``, before any other gate and on both invocation paths: the
``--all`` sweep drops it and carries on, a hand-picked ``--report`` exits. Without this
the sweep matched the whole back catalogue — hundreds of 2024 / early-2025 sidecars
that are history, not work. The month is read from the sidecar's ``reporting_period``,
falling back to the filename's month token (``..._DEC_2025.json``).

Navigation
----------
``_navigate_to_appeal_form`` drives E-Xidmətlər -> service card -> "Tanış oldum" ->
the form, but never raises: it is a shortcut for when the saved session is still
alive. ``_await_takeover`` remains the only authority on having arrived, and it waits
for the operator to walk there by hand whenever the shortcut does not work.

Dry-run first
-------------
``python uploader.py --dry-run`` prints a colored, step-by-step simulation of the
whole flow WITHOUT launching a browser: ``upload_report`` detects the ``DryRunPage``
sentinel and narrates each locator and value instead of touching a page. The payload
it prints is built by the same ``build_portal_payload`` a live run uses, so what you
read is what would be typed.

Automation design (per the web-automation rules)
------------------------------------------------
* Approach: UI automation — no portal API is known. The README's "E-Keyfiyyet Portal
  Integration" section documents how to find a hidden internal REST/Fetch endpoint
  with DevTools; PREFER that over this UI flow once found.
* Locators target meaning (role / label / placeholder), never DOM position. No
  absolute XPath, no nth-child indexing into the layout.
* Wait strategy: Playwright auto-waiting + ``expect(...)`` + ``wait_for_load_state``.
  NO ``time.sleep`` anywhere. Two ``page.wait_for_timeout`` calls remain — Playwright's
  own wait, which yields to the event loop rather than blocking the driver — and both
  wait on something the DOM does not announce: the portal's registry lookup filling the
  director's name after FİN + Seriya blur, and React re-rendering the file input, whose
  DOM file list it clears right after attach so a read-back would falsely fail.
* The save is confirmed by the redirect to ``/uqq/projects``, not by a toast — the
  portal shows none. See PROJECTS_PATH.

Idempotency
-----------
Uploading is a side effect on the portal's database, so every run is gated by a
durable state ledger (``upload_ledger.py``): a report that has already been sent,
and whose content has not changed, is skipped. A report that was regenerated after
a data correction hashes differently and is re-sent. A report whose upload was
interrupted mid-submit is flagged rather than blindly retried — see the module
docstring in ``monthly_report/upload_ledger.py`` for the full rationale.

The ledger is checkpointed after every report, so a batch that dies at report 5 of
10 resumes at 5 on the next run instead of re-sending 1-4.

``--dry-run`` uses its own ledger file, so simulating never marks a real report as
uploaded.

Usage
-----
    python uploader.py --dry-run                       # newest sidecar, no browser
    python uploader.py --dry-run --all                 # still sends at most 1
    python uploader.py --dry-run --all --method MT --client KHF --month FEB_2026
    python uploader.py --probe                         # dump the real form, save nothing
    python uploader.py --report <json>                 # fill, do NOT save, hold open
    python uploader.py --live --report <json>          # fill AND click Yadda saxla
    python uploader.py --reset output/MPI/KHF/compiled_monthly_report_MT_KHF_FEB_2026.pdf
"""

from __future__ import annotations

import argparse
import calendar
import datetime as _dt
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

_ROOT = Path(__file__).resolve().parent

# Make the src/ package importable when run as a plain script (same bootstrap as
# main.py — the package is not installed).
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.config import load_settings  # noqa: E402
from monthly_report.method_registry import (is_active_client,  # noqa: E402
                                            is_excluded_client,
                                            is_informational,
                                            is_uploadable_client,
                                            meets_volume,
                                            resolve_client_by_field)
from monthly_report.naming import AZ_MONTHS, MONTH_ABBR  # noqa: E402
# Re-exported, not redefined: the exporter builds equipment_used with the very
# same helper, so the sidecar's join order and this module's field order cannot
# drift apart.
from monthly_report.text_norm import unique_ordered  # noqa: E402,F401
# Aliased to keep the private spelling the standard matcher below reads with. ONE
# definition, shared with method_registry.is_allowed_standard, so the compile-time
# quarantine gate and the portal gate cannot fold typography differently.
from monthly_report.text_norm import     fold_typography as _normalize_typography  # noqa: E402
from monthly_report.upload_ledger import (Action, LedgerError,  # noqa: E402
                                          UploadLedger, hash_report)

# One report per run by DEFAULT. The portal writes real appeal records under a
# real director's identity, so a mistake is expensive and manual to undo: the blast
# radius of a bad selector map or a wrong payload is capped at one row unless the
# operator raises the cap on purpose with --limit N.
# --all still decides WHICH reports are candidates; this caps how many are sent.
MAX_REPORTS_PER_RUN = 1

# Used only if the portal: block predates these keys — settings.yaml is the
# source of truth (portal.landing_url / portal.takeover_timeout_seconds).
_LANDING_FALLBACK = "https://e-keyfiyyet.gov.az/home"
_TAKEOVER_TIMEOUT_FALLBACK = 300

# How long one wait_for_url slice blocks before every tab is rescanned, and how
# often the wait prints that it is still alive. The slice is short because a tab
# spawned by the portal is only seen by a rescan; the heartbeat is not, so the
# console stays as quiet as it was when the wait watched a single page.
_TAKEOVER_SLICE_S = 2.0
_TAKEOVER_HEARTBEAT_S = 15.0

# Ceiling for the two waits inside _navigate_to_appeal_form's best-effort walk.
#
# Short on purpose, and the ONLY waits here that are. These are spent exclusively on
# the failure path — an expired session bounces every step to login, and the walk then
# sits on a wait that will never be satisfied. Every second of that is a second before
# the run falls back to asking the operator to navigate by hand, which is the thing
# that actually works. On the success path they resolve in milliseconds.
#
# The other waits in this file (form expansion, the combobox, the save confirmation)
# are deliberately NOT cut to match. Playwright auto-waits: a timeout is a ceiling on
# failure, not a delay, so lowering them cannot make a working run faster — it can only
# turn a slow portal into a failed run.
_NAV_FALLBACK_TIMEOUT_MS = 5000

# Ceiling for the standards listbox to render after its box is clicked. A success-path
# wait, so it costs nothing when the list opens in milliseconds — which is the normal
# case, the options having arrived with the form. Generous rather than 3-5s because it
# is not known whether the portal fetches this list on open, and the failure mode of
# being too tight is the worst one available here: the Seç fallback fires at a list
# that was about to appear, and toggles it shut.
_LISTBOX_TIMEOUT_MS = 10000

# Ceiling for the portal to redirect to Layihələr after "Yadda saxla" is clicked. The
# save confirmation named above, now a hard gate: exceeding it aborts the batch and
# leaves the report IN_PROGRESS. Generous for that reason — on the success path the
# redirect lands in well under a second, so the only thing a tighter value can buy is
# a slow portal being reported as a failed save.
_SAVE_REDIRECT_TIMEOUT_MS = 20000

# --probe's dump. It lives in output/ next to the report sidecars and is rewritten
# on every probe run, which makes it the NEWEST output/**/*.json — so the sidecar
# scanners must skip it by name or a default `python uploader.py` straight after a
# probe resolves the dump as its upload target instead of a report.
PROBE_FILENAME = "portal_form_probe.json"

# Shape of the probe dump. 4 added standard_options — the multiselect's real option
# list, which the controls dump cannot see (it mounts only while the listbox is open).
# 3 added caption/wrapper_html/dom_path — without them most of this portal's fields
# carry no identifying attribute at all.
PROBE_SCHEMA = 4


# --------------------------------------------------------------------------- #
# Colored terminal output (ANSI). No external dependency: VT processing is
# enabled on Windows via ctypes so colors render in PowerShell / cmd too.
# --------------------------------------------------------------------------- #
class _C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GREY = "\033[90m"


def _enable_windows_ansi() -> None:
    """Turn on ANSI escape processing + UTF-8 output on the Windows console.

    The simulation prints box-drawing characters and Azerbaijani glyphs
    (``İ ə ş ...``); a default cp125x console would raise UnicodeEncodeError, so
    stdout/stderr are reconfigured to UTF-8 (errors replaced, never fatal). No-op
    on non-Windows platforms, which already default to UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004 on the stdout handle (-11).
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass  # colors are cosmetic — never let this break the run


def _c(text: str, *codes: str) -> str:
    return "".join(codes) + text + _C.RESET


def _step(n, total, msg: str) -> None:
    print(f"  {_c(f'[{n}/{total}]', _C.BOLD, _C.CYAN)} {msg}")


def _sim(msg: str) -> None:
    """One simulated browser action line (dry-run)."""
    print(f"        {_c('▷', _C.MAGENTA)} {_c(msg, _C.GREY)}")


def _match(locator: str) -> None:
    """One simulated element-match line (dry-run)."""
    print(f"        {_c('✔', _C.GREEN)} matched {_c(locator, _C.YELLOW)}")


def _info(label: str, value: str) -> None:
    print(f"        {_c('·', _C.BLUE)} {label}: {_c(value, _C.BOLD)}")


def _warn(message: str) -> None:
    """One bold-yellow warning line. The loudest thing short of an error.

    Reserved for the reason a report was not filed — a standard the portal does not
    offer. Nothing is substituted for it any more, so this line is the operator's
    only notice that a report they expected to see on the portal is not there, and
    the end-of-run list gathers every one of them in one place.
    """
    print(f"        {_c('⚠', _C.BOLD, _C.YELLOW)} {_c(message, _C.BOLD, _C.YELLOW)}")


#: Standards the portal could not name on the CURRENT report, which is what made the
#: report skip. Module-level because the check runs deep inside the form fill and knows
#: nothing about which report it is on; upload_report clears it at the start of each
#: report and _run_batch drains it afterwards, labelling each entry with the report
#: name for the end-of-run "not filed" list.
_UNMATCHED: list[str] = []

#: Standards left off the CURRENT report's appeal under ``portal.standard_policy: any``
#: (ADR-010): the portal does not offer them, but at least one of the report's other
#: standards it does, so the report is filed naming only those. Same lifecycle as
#: _UNMATCHED — cleared per report by upload_report, drained by _run_batch — and kept
#: apart from it, because these reports were NOT refused.
_POLICY_SKIPPED: list[str] = []

#: ``portal.standard_policy`` values. "all" (default) is the zero-substitution rule:
#: one unoffered standard refuses the whole report. "any" files the offered ones and
#: names the rest on stdout; zero offered still refuses (ADR-010).
STANDARD_POLICIES = ("all", "any")


def _standard_policy() -> str:
    """The configured ``portal.standard_policy``; ``"all"`` when absent.

    An unknown value raises rather than guessing: "all" is the safe reading, but a
    typo the operator meant as "any" must not silently behave as "all" either.
    """
    portal = _settings().raw.get("portal") or {}
    value = portal.get("standard_policy")
    if value is None:
        return "all"
    policy = str(value).strip().casefold()
    if policy not in STANDARD_POLICIES:
        raise ValueError(f"portal.standard_policy must be one of {STANDARD_POLICIES}, "
                         f"got {value!r}")
    return policy


def _hold_documents() -> frozenset[str]:
    """The configured ``portal.hold_documents``; empty when absent.

    Document IDs ``<CLIENT>_<MON>_<YYYY>`` (``UBOC_FEB_2026``): the tail of the compiled
    document's filename (naming.default_output). The operator holds a document back
    while its SOURCES are being fixed; releasing it is removing the ID. A malformed
    entry raises rather than guessing: an ID that can never match would silently
    release the very document it was meant to hold.
    """
    import re
    portal = _settings().raw.get("portal") or {}
    value = portal.get("hold_documents")
    if value is None:
        return frozenset()
    if not isinstance(value, list):
        raise ValueError(f"portal.hold_documents must be a list of document IDs like "
                         f"'UBOC_FEB_2026', got {value!r}")
    shape = re.compile(rf"[A-Z0-9]+_(?:{'|'.join(MONTH_ABBR.values())})_\d{{4}}")
    bad = [v for v in value if not isinstance(v, str) or not shape.fullmatch(v)]
    if bad:
        raise ValueError(f"portal.hold_documents: {bad!r} not in the form "
                         f"<CLIENT>_<MON>_<YYYY> (e.g. 'UBOC_FEB_2026', upper case)")
    return frozenset(value)


def _document_id(path: Path) -> str:
    """``UBOC_FEB_2026`` for ``compiled_monthly_report_UBOC_FEB_2026.json``.

    The last three ``_`` tokens of the stem, so a legacy name that still carries a
    method token (``..._MT_UBOC_FEB_2026``) is held under the same ID.
    """
    return "_".join(path.stem.split("_")[-3:])


def _apply_hold(targets: list[tuple[Path, Path]]
                ) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Split off the documents ``portal.hold_documents`` holds: (kept, held IDs).

    Runs before any browser exists and before the ledger is consulted, in every mode,
    so a held document is neither filled, nor saved, nor recorded. Prints nothing and
    returns ``targets`` unchanged when the list is empty (the default).
    """
    hold = _hold_documents()
    if not hold:
        return targets, []
    kept: list[tuple[Path, Path]] = []
    held: list[str] = []
    for sidecar, pdf in targets:
        doc = _document_id(sidecar)
        if doc in hold:
            print(f"  HELD by operator (portal.hold_documents): {doc}")
            held.append(doc)
        else:
            kept.append((sidecar, pdf))
    return kept, held


def _closed_months_only() -> bool:
    """The configured ``portal.upload_closed_months_only``; ``False`` when absent.

    Only a real YAML boolean is accepted: ``"false"`` as a string would read as true,
    and ``"yes"`` the operator meant as true must not silently mean false either.
    """
    portal = _settings().raw.get("portal") or {}
    value = portal.get("upload_closed_months_only")
    if value is None:
        return False
    if not isinstance(value, bool):
        raise ValueError(f"portal.upload_closed_months_only must be true or false, "
                         f"got {value!r}")
    return value


def _today_baku() -> _dt.date:
    """Today's date in Azerbaijan (Asia/Baku), whatever the workstation clock zone.

    ``zoneinfo`` needs the ``tzdata`` package on Windows, which is not installed here;
    without it the fixed UTC+04:00 offset is used. Azerbaijan has kept UTC+04:00 all
    year since it abolished daylight saving time in 2016, so both give the same date.
    """
    try:
        from zoneinfo import ZoneInfo
        tz: _dt.tzinfo = ZoneInfo("Asia/Baku")
    except Exception:  # ZoneInfoNotFoundError: no tzdata on this machine
        tz = _dt.timezone(_dt.timedelta(hours=4), "Asia/Baku")
    return _dt.datetime.now(tz).date()


def _apply_closed_months(targets: list[tuple[Path, Path]],
                         today: _dt.date | None = None
                         ) -> tuple[list[tuple[Path, Path]], list[str]]:
    """Split off the documents whose month has not ended yet: (kept, not-yet IDs).

    Under ``portal.upload_closed_months_only: true`` a document whose reporting month
    (``_sidecar_period_start``) is the current month or later is refused: more
    reports for it can still arrive. Same place as the hold — before the limit, the
    ledger and any browser. An undatable sidecar is refused too: closed is what must
    be proven. ``today`` is injectable for tests; the default is ``_today_baku()``.
    Prints nothing and returns ``targets`` unchanged when the key is off (default).
    """
    if not _closed_months_only():
        return targets, []
    current = (today or _today_baku()).replace(day=1)
    kept: list[tuple[Path, Path]] = []
    not_yet: list[str] = []
    for sidecar, pdf in targets:
        start = _sidecar_period_start(sidecar)
        if start is None or start >= current:
            doc = _document_id(sidecar)
            print(f"  NOT YET (month not closed): {doc}")
            not_yet.append(doc)
        else:
            kept.append((sidecar, pdf))
    return kept, not_yet


def _file_integrity(path: Path) -> tuple[int, str]:
    """(size in bytes, SHA-256 hex) of a file, streamed in 1 MiB blocks.

    Raises on an unreadable file — a PDF we cannot hash must stop the upload,
    never be attached blind. (pre_processor._sha256 is the streaming twin used
    for prune dedup; it is not imported here because that module pulls in the
    whole pre-processing stack, and this CLI must stay lean.)
    """
    size = path.stat().st_size
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return size, h.hexdigest()


def _banner(title: str) -> None:
    line = "═" * 68
    print(_c(line, _C.BLUE))
    print(_c(f"  {title}", _C.BOLD, _C.BLUE))
    print(_c(line, _C.BLUE))


# --------------------------------------------------------------------------- #
# Dry-run sentinel. Passed as ``page`` when --dry-run is set; each automation
# method checks getattr(page, "dry_run", False) and narrates instead of driving.
# --------------------------------------------------------------------------- #
class DryRunPage:
    """A stand-in for a Playwright ``Page`` that performs no real navigation."""

    dry_run = True

    def __init__(self, url: str):
        self.url = url


def _is_dry(page) -> bool:
    return getattr(page, "dry_run", False)


# --------------------------------------------------------------------------- #
# Core orchestrator methods (exact signatures per the spec).
# --------------------------------------------------------------------------- #
def load_report_json(filepath: str | Path) -> dict:
    """Load a compiled monthly report ``.json`` sidecar and validate the contract.

    Enforces the data-contract invariants the exporter guarantees: the file parses,
    the required keys are present, and ``client_voen`` is a STRING (an opaque Tax ID
    — a numeric VÖEN would have silently lost a leading zero upstream). Raises
    ``ValueError`` on any breach so a malformed payload is rejected at the boundary
    rather than half-uploaded.
    """
    path = Path(filepath)
    if not path.is_file():
        raise FileNotFoundError(f"Report JSON not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(
            f"{path.name}: not a JSON object (a compiled report sidecar is a dict, "
            f"got {type(data).__name__})")

    required = ("client_name", "client_voen", "reporting_period", "ndt_method",
                "report_serial_no", "total_records", "items_table")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"{path.name}: missing required key(s): {missing}")
    if not isinstance(data["client_voen"], str):
        raise ValueError(
            f"{path.name}: client_voen must be a string (opaque Tax ID), "
            f"got {type(data['client_voen']).__name__}")
    if not isinstance(data["items_table"], list):
        raise ValueError(f"{path.name}: items_table must be a list")
    return data


# --------------------------------------------------------------------------- #
# Portal payload derivation.
#
# Pure functions: no browser, no I/O, no Playwright import. The dry run and the
# live run both build the payload through here, so simulating proves the exact
# values a real submit would type — and these are the parts worth unit-testing
# (see tests/test_uploader_mapping.py). The portal fill below is then a dumb
# typist over an already-validated dict.
# --------------------------------------------------------------------------- #

# reporting_period is written by naming.reporting_period() in AZERBAIJANI
# ("İyul 2026"), not English — so the reverse map must come from the same table
# the exporter used, or July silently fails to parse.
_AZ_MONTH_NUMBER = {name.casefold(): num for num, name in AZ_MONTHS.items()}

# The filename's own month token (compiled_monthly_report_MT_KHF_FEB_2026.json ->
# "FEB"), the fallback the date gate reads when a sidecar's reporting_period cannot
# be. Same table naming.default_output wrote the name with.
_ABBR_MONTH_NUMBER = {abbr.casefold(): num for num, abbr in MONTH_ABBR.items()}

#: Portal upload cutoff. The portal takes appeals for December 2025 onward; a report
#: for an earlier month (the 2024 / early-2025 back catalogue still sitting in
#: output/) is history, not something to file. Compared against the FIRST day of the
#: reporting month, so the whole of December 2025 is eligible and the whole of
#: November 2025 is not. Same date reset_and_sync_input._DEFAULT_CUTOFF syncs the
#: input tree against — what is not ingested is not filed either.
PORTAL_UPLOAD_CUTOFF = _dt.date(2025, 12, 1)

RESULT_UNFIT = "Yarasız"
RESULT_INFORMATIONAL = "Məlumat üçün"
RESULT_FIT = "Yararlı"

#: Path of the appeal form. Matched on the path alone — see is_appeal_url.
APPEAL_PATH = "/uqq/new-appeal"

#: The workspace dashboard. "Tanış oldum" lands HERE, not on the form — the form is
#: one "Yeni sənəd" click away. A takeover target, never a fill target.
E_COMPETITION_PATH = "/uqq/e-competition"

#: Where a saved draft lands — the "Layihələr" tab. The portal shows NO success toast
#: when "Yadda saxla" commits; this redirect is the only signal that it did.
PROJECTS_PATH = "/uqq/projects"

#: Path of the e-services catalogue, one hop before the form.
E_SERVICES_PATH = "/e-services"

#: The service card that leads to the appeal form. Matched as a substring, so the
#: card's surrounding chrome (icon, "ətraflı" link) does not have to be reproduced
#: here — but the text itself is the portal's, verbatim.
SERVICE_CARD_TEXT = ("Uyğunluğu qiymətləndirən qurumların fəaliyyətinin nəticələri "
                     "barədə digər sənədlərin elektron yaradılması")

#: The normative documents the portal's "inspeksiya:" multiselect offers.
#:
#: A BASELINE, not the source of truth. What gets clicked is always the live listbox
#: (_select_standard reads it); this list is the --dry-run oracle, so an operator can
#: see which standards will be skipped without launching a browser, and the drift
#: baseline that --probe reconciles against.
#:
#: PROVENANCE — PROVISIONAL, NOT probe-verified (2026-10-06). The portal REPLACED its
#: list: the operator reports (from a screenshot, 2026-10-06) that it now offers
#: exactly these 21 and that the 16 measured by `--probe` on 2026-08-12 (EEMUA 153/158,
#: API 1104, ISO 17636, ISO 17640, ...) are gone. The spelling below is the operator's,
#: typed from that screenshot; the exact listbox text is UNKNOWN until a new probe.
#: The old list is kept in standarts/in_portal_2026-08-12.md, and the 2026-08-12 dump
#: at output/portal_form_probe.json still holds the old 16, so
#: test_registered_standards_match_the_portal_exactly is xfail ("probe pending
#: (TODO P0)") until a new dump exists. A probe is required before the first --live.
#:
#: standarts/in_portal.md lists these same 21 (test_in_portal_md_equals_portal_standards);
#: test_portal_standards_is_the_exact_live_list pins the order, so a silent edit fails
#: CI instead of the portal. Re-run --probe after any portal change — a dump is a
#: snapshot, not a live subscription.
#:
#: DO NOT widen this from standarts/butun_standartlar.md. That file (37 rows) is the
#: COMPANY's master list of standards we inspect against, not the portal's. Pasting it
#: in here would make --dry-run report reports as filable that the live listbox will
#: refuse, i.e. turn the oracle green on exactly the cases it exists to catch. Section
#: spellings that a combined option covers ("ASME VIII" -> "ASME I-XII") are wired in
#: `portal.standard_aliases`, not here.
PORTAL_STANDARDS = ("API 510", "API 570", "API 620", "API 650", "ASME B31.1",
                    "ASME B31.3", "ASME I-XII", "ASTM E 572", "ASTM E 1476",
                    "AWS D1.1", "ISO 3057", "ISO 10863", "ISO 16809", "ISO 17637",
                    "ISO 19285", "ГОСТ 7512-82", "ГОСТ 18442-80", "ГОСТ 26790",
                    "ГОСТ Р 51780", "ГОСТ Р 55724-2013", "ГОСТ Р 56512-2015")


def _url_path(url: str | None) -> str | None:
    """The path of ``url``, casefolded and de-slashed. None if there isn't one.

    Path ONLY, deliberately. A substring test over the whole URL would accept the
    login page's ``?returnUrl=/uqq/new-appeal`` — which is the redirect *away* from
    the form, i.e. exactly the state that must not count as arrival.
    """
    if not url:
        return None
    try:
        return urlsplit(str(url)).path.casefold().rstrip("/")
    except ValueError:
        return None


def is_appeal_url(url: str | None) -> bool:
    """True once the browser is actually ON the appeal form.

    The strict gate: this is what says "it is safe to fill". It stays FALSE on the
    e-competition dashboard even though the takeover happily claims that tab —
    upload_report drives the form's fields, and --probe dumps them, so both would be
    reading the wrong page. See is_takeover_url for the looser question.
    """
    return _url_path(url) == APPEAL_PATH


def is_projects_url(url: str | None) -> bool:
    """True once the browser has landed on Layihələr — i.e. the draft was committed.

    Path-matched through _url_path for the same reason is_appeal_url is: an expired
    session bounces to ``/login?returnUrl=/uqq/projects``, which contains the path as a
    substring while being the opposite of a saved draft.
    """
    return _url_path(url) == PROJECTS_PATH


def is_takeover_url(url: str | None) -> bool:
    """True once a tab is OURS to drive — the form, or one click away from it.

    The portal's "Tanış oldum" lands on /uqq/e-competition/ (the Məlumatlar tab), not
    on the appeal form, so a takeover that waits for the form alone sits there until a
    human clicks "Yeni sənəd". This is the predicate the tab hunt uses; the transition
    to the form is then _ensure_on_appeal_form's job, and is_appeal_url's to confirm.
    """
    return _url_path(url) in (APPEAL_PATH, E_COMPETITION_PATH)


def month_bounds(reporting_period: str) -> tuple[str, str]:
    """``"May 2026"`` -> ``("01.05.2026", "31.05.2026")`` (the portal's DD.MM.YYYY).

    The inspection range the portal wants is the whole reporting month, and the
    last day is computed with ``calendar.monthrange`` rather than a 30/31 table so
    February and leap years are right.
    """
    parts = str(reporting_period).split()
    if len(parts) != 2:
        raise ValueError(f"Unparseable reporting_period: {reporting_period!r} "
                         f"(expected '<Ay> <İl>', e.g. 'May 2026')")
    name, year_text = parts
    month = _AZ_MONTH_NUMBER.get(name.casefold())
    if month is None:
        raise ValueError(f"Unknown Azerbaijani month name: {name!r}")
    try:
        year = int(year_text)
    except ValueError:
        raise ValueError(f"Unparseable year in reporting_period: {year_text!r}") from None
    last_day = calendar.monthrange(year, month)[1]
    return f"01.{month:02d}.{year}", f"{last_day:02d}.{month:02d}.{year}"


_SETTINGS = None


def _settings():
    """Lazily load config/settings.yaml once (for the informational-method flags)."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = load_settings(str(_ROOT / "config" / "settings.yaml"))
    return _SETTINGS


def portal_result(method: str) -> str:
    """The ONLY two verdicts the portal's "Nəticə:" field accepts.

    Method-driven, not row-driven: informational methods (UTM / HrT / PMI —
    config/settings.yaml methods.*.informational) carry no pass/fail verdict, so they
    file as "Məlumat üçün"; every other method files as "Yararlı". "Yarasız" is never
    sent — a monthly summary states that inspections were performed, and the portal
    rejects any other value here. Reuses is_informational (the aggregator's own call)
    so this verdict cannot drift from the rest of the pipeline.

    ADR-004 made the sidecar's ``ndt_method`` a "/"-joined token list, because one
    document now covers every method of a client-month — and the portal still has
    exactly one Nəticə box for it. The rule: "Məlumat üçün" only when EVERY method in
    the document is informational; one real inspection (UT/MT/RT/DP/FC) makes the
    whole filing "Yararlı". The weaker claim would be the wrong one to make about a
    document that does contain pass/fail work. The PDF is unaffected — its own Nəticə
    column stays per row, so the informational rows still read "Məlumat üçün" there.

    A single token behaves exactly as before, so every pre-ADR-004 sidecar is
    unchanged. An empty/blank method is "Yararlı", also as before.
    """
    tokens = [t for t in str(method or "").split("/") if t.strip()]
    if tokens and all(is_informational(t, _settings()) for t in tokens):
        return RESULT_INFORMATIONAL
    return RESULT_FIT


#: A self-imposed bound on "İnspeksiyanın olunan obyekt:". The portal publishes no
#: limit — there is no maxlength on that input, or on any other, in the probe dump or
#: in any saved failure HTML. This is a ceiling we choose, not one we were given.
INSPECTION_OBJECT_MAX_CHARS = 200

#: What replaces the items the bound dropped. A visible mark, so a short list on a
#: filed appeal reads as "trimmed" rather than as "that was all of them".
_TRIMMED_MARK = " …"


def fit_item_list(value: str, limit: int = INSPECTION_OBJECT_MAX_CHARS) -> str:
    """Trim a ", "-joined list to ``limit`` characters by dropping WHOLE items.

    Whole ones, from the end, never a partial: this string is read by a person as a
    list of the things that were inspected, and "KEQ1..." names nothing. A short list
    that is honest about being short beats a full-length one whose last entry is a
    fragment.

    Returns ``value`` untouched when it already fits — the common case by far; of the
    99 sidecars on disk exactly two exceed the bound.

    One item longer than the whole limit has nothing to drop and the field is
    ``required``, so that case alone is cut hard rather than emptied.
    """
    text = str(value or "")
    if len(text) <= limit:
        return text

    items = text.split(", ")
    kept = list(items)
    while len(kept) > 1 and len(", ".join(kept)) + len(_TRIMMED_MARK) > limit:
        kept.pop()

    if len(kept) == 1 and len(kept[0]) + len(_TRIMMED_MARK) > limit:
        # A single name that does not fit. Nothing to drop, and a blank fails the
        # form's own required check, so this is the one place a word gets cut.
        trimmed = text[:limit - 1].rstrip() + "…"
        _warn(f"the inspection object is one {len(text)}-character item and cannot be "
              f"shortened by dropping entries — it was CUT to {len(trimmed)} chars. "
              f"Check the draft before signing.")
        return trimmed

    trimmed = ", ".join(kept) + _TRIMMED_MARK
    dropped = items[len(kept):]
    _warn(f"the inspection object was {len(text)} chars, over the "
          f"{limit}-char bound — {len(dropped)} item(s) DROPPED, now {len(trimmed)} "
          f"chars. Not filed: {', '.join(dropped)}")
    _info("obyekt", _c("the dropped items are named in the attached PDF; the portal "
                       "field is a summary of it", _C.GREY))
    return trimmed


def build_portal_payload(json_data: dict, portal_cfg: dict) -> dict:
    """Everything the ``/uqq/new-appeal`` form needs, derived from one sidecar.

    Built and validated BEFORE a browser opens, so a bad sidecar fails on the
    command line instead of half-way through a live government form.
    """
    rows = json_data.get("items_table", [])
    date_from, date_to = month_bounds(json_data.get("reporting_period", ""))
    director = portal_cfg.get("director") or {}
    return {
        "document_type": portal_cfg.get("document_type", ""),
        "date_from": date_from,
        "date_to": date_to,
        "client_voen": json_data.get("client_voen", ""),
        "client_name": json_data.get("client_name", ""),
        # Bounded here rather than at the fill site, so --dry-run prints the string
        # that will really be filed instead of one the browser would then shorten.
        "inspection_object": fit_item_list(", ".join(
            unique_ordered(r.get("item_name") for r in rows))),
        # Each row's cell may name several standards ("ASME VIII / ISO 17636"); split
        # them so each is matched and tagged on its own. unique_ordered then dedupes
        # tokens shared across rows (the _select_standard/already set dedupes options).
        "standards": unique_ordered(
            tok for r in rows for tok in split_standards(r.get("standard"))),
        # Already joined by the exporter (it reads the source documents; we never
        # do). Defaulted rather than required: a sidecar generated before the
        # equipment pipeline existed is still a valid appeal — see load_report_json.
        "equipment_used": json_data.get("equipment_used", ""),
        # Not typed into any field, and no longer used to choose a standard either —
        # nothing is substituted by discipline. Kept because it labels the report in
        # the console and picks the verdict text (portal_result, below).
        "ndt_method": json_data.get("ndt_method", ""),
        "result": portal_result(json_data.get("ndt_method", "")),
        # Three fields, because the form has three boxes — see upload_report. A
        # single full_name would have to be split by guessing which token is the
        # given name, and "TESTƏROV TEST" does not say.
        "director_ad": director.get("ad", ""),
        "director_soyadi": director.get("soyadi", ""),
        "director_atasinin_adi": director.get("atasinin_adi", ""),
        "director_fin": director.get("fin", ""),
        "director_seriya": director.get("seriya_nomresi", ""),
        "serial": json_data.get("report_serial_no", ""),
    }


def load_portal_config(settings_path: Path | None = None) -> dict:
    """Read the ``portal:`` block from config/settings.yaml."""
    import yaml

    path = settings_path or (_ROOT / "config" / "settings.yaml")
    if not path.is_file():
        raise SystemExit(f"Settings file not found: {path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    portal = raw.get("portal")
    if not portal:
        raise SystemExit(f"{path}: missing the required 'portal:' block.")
    return portal


def assert_director_configured(portal_cfg: dict) -> None:
    """Refuse a live submit while the director block is still blank.

    Checked before the browser opens: an appeal filed without the signing
    director's identity is not a recoverable mistake on a government portal — it is
    a bad record someone has to go and withdraw.

    "The director block" here means FİN + Seriya nömrəsi. Those two are what the
    form actually receives; the name boxes are filled by the portal's own lookup.
    """
    director = portal_cfg.get("director") or {}
    # Only the two identifiers are required. The portal auto-searches the name from
    # FİN + Seriya nömrəsi and we no longer type ad / soyadı / atasının adı, so
    # refusing to run without them would be a gate on config that is never sent.
    # They stay in settings.yaml as the value the dry-run prints for the operator to
    # check the auto-search against.
    missing = [k for k in ("fin", "seriya_nomresi")
               if not str(director.get(k, "")).strip()]
    if missing:
        raise SystemExit(
            "Cannot run --live: config/settings.yaml portal.director is incomplete.\n"
            f"    Missing / blank: {', '.join(missing)}\n"
            "    Fill these in with the signing director's real values, then re-run.")


def probe_form(page, out_path: Path) -> dict:
    """Dump every control currently on the page to JSON. Fills nothing.

    The portal needs an authenticated session, so its markup cannot be read while
    writing this script — every locator below would otherwise be a guess from the
    field's printed label. This is how the guesses get replaced by facts: run it
    against the live form, then map the real ids/labels/roles from its output.

    Reads the page as it finds it. Call ``_open_new_document_form`` first, or the
    dump is of the collapsed page and contains none of the fields worth mapping.

    Schema 4 adds ``standard_options`` — see _probe_standard_options. Schema 3 added
    ``caption`` / ``wrapper_html`` / ``dom_path``. Schema 2 recorded only the
    accessible attributes, and on this portal most fields have none of them — 10 of
    its inputs came back with an empty label, an empty placeholder and nothing else
    but a React ``useId``. Their captions are loose text NEXT to the input rather than
    a ``<label for>``, so they are invisible to ``el.labels`` and unreachable by
    ``get_by_label``. ``caption`` is what makes them identifiable.
    """
    controls = page.evaluate("""() => {
        const clean = (s) => (s || '').replace(/\\s+/g, ' ').trim();

        const labelFor = (el) => {
            if (el.labels && el.labels.length) {
                return Array.from(el.labels).map(l => clean(l.innerText)).join(' | ');
            }
            const wrapper = el.closest('label');
            if (wrapper) return clean(wrapper.innerText);
            return '';
        };

        // The caption a HUMAN reads for this field. MUI renders it as loose text
        // beside the input, not as a <label for>, so el.labels never sees it.
        // Walk out through the ancestors and take the first text that is short
        // enough to be a caption rather than the whole form's prose.
        const captionFor = (el) => {
            let node = el;
            for (let depth = 0; depth < 5 && node; depth++) {
                let sib = node.previousElementSibling;
                while (sib) {
                    const t = clean(sib.innerText);
                    if (t && t.length <= 120) return t;
                    sib = sib.previousElementSibling;
                }
                node = node.parentElement;
            }
            return '';
        };

        const domPath = (el) => {
            const parts = [];
            let node = el;
            for (let depth = 0; depth < 4 && node && node.tagName; depth++) {
                let part = node.tagName.toLowerCase();
                const cls = (node.getAttribute('class') || '').split(/\\s+/)
                    .filter(c => c && !/^css-/.test(c))[0];
                if (cls) part += '.' + cls;
                parts.unshift(part);
                node = node.parentElement;
            }
            return parts.join(' > ');
        };

        return Array.from(
            document.querySelectorAll('input, select, textarea, button')
        ).map(el => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute('type') || '',
            id: el.id || '',
            name: el.getAttribute('name') || '',
            placeholder: el.getAttribute('placeholder') || '',
            label: labelFor(el),
            caption: captionFor(el),
            aria_label: el.getAttribute('aria-label') || '',
            role: el.getAttribute('role') || '',
            text: clean(el.innerText).slice(0, 80),
            dom_path: domPath(el),
            wrapper_html: (el.closest('div')
                ? el.closest('div').outerHTML.replace(/\\s+/g, ' ') : '').slice(0, 400),
            options: el.tagName.toLowerCase() === 'select'
                ? Array.from(el.options).map(o => clean(o.text))
                : undefined,
        }));
    }""")
    payload = {
        # Bumped whenever the dump's shape changes. A mapping read from a stale
        # schema is a mapping made from fields the probe never looked for.
        "probe_schema": PROBE_SCHEMA,
        "probed_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "url": page.url,
        "control_count": len(controls),
        "standard_options": _probe_standard_options(page),
        "standard_field_label": _probe_standard_field_label(page),
        "controls": controls,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    return payload


def _probe_standard_field_label(page) -> str:
    """The full text of the block that labels the "inspeksiya:" multiselect.

    `controls[].caption` only ever caught the fragment "inspeksiya:", because
    captionFor takes the first previous sibling text and this label is split across
    elements. That fragment cannot say whether the field asks for the normative
    documents USED during the inspection, or the criteria the object was ASSESSED
    AGAINST.

    It used to decide whether a method-standard substitution was honest. It no longer
    has to: nothing is substituted, so an unreadable caption cannot license a wrong
    document. Still captured — it is the one field whose meaning we infer rather than
    read, and knowing it would settle whether our standards are even the right kind of
    answer for this box.

    Never raises — a probe that dumped 33 controls and 16 options should not be lost
    because one label would not read.
    """
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        return _field_after_caption(page, "inspeksiya:").evaluate("""el => {
            // Out to the labelled group, not just the input's own wrapper: the
            // caption is a sibling block, which is why get_by_label sees nothing.
            let node = el;
            for (let depth = 0; depth < 6 && node; depth++) {
                const text = (node.innerText || '').replace(/\\s+/g, ' ').trim();
                if (text.length > 20) return text.slice(0, 400);
                node = node.parentElement;
            }
            return '';
        }""")
    except (PWTimeout, PWError, RuntimeError) as exc:
        _info("standards", _c(f"could not read the field's label "
                              f"({type(exc).__name__})", _C.YELLOW))
        return ""


def _probe_standard_options(page) -> list[str]:
    """Read every normative document the "inspeksiya:" multiselect offers.

    The controls dump cannot capture these: the options live in a React portal that
    only mounts while the listbox is open, so a querySelectorAll over the closed form
    sees nothing. That is why PORTAL_STANDARDS was a transcription from screenshots
    and not a measurement — this closes that gap.

    Opening a dropdown is a mutation, and this mode is nominally read-only. It is done
    anyway on the same reasoning that already justifies picking the document type: the
    thing worth measuring does not exist in the DOM until something is clicked.
    Nothing is typed, nothing is selected, and the list is clicked shut again.

    Never raises — a probe that dumped 33 controls should not be thrown away because
    one dropdown would not open.
    """
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        box = _field_after_caption(page, "inspeksiya:")
        options = _open_standards_list(page, box)
        _close_standards_list(page)
        return options
    except (PWTimeout, PWError, RuntimeError) as exc:
        _info("standards", _c(f"could not read the option list ({type(exc).__name__}) "
                              f"— PORTAL_STANDARDS stays unverified", _C.YELLOW))
        return []


def _select_autocomplete(page, name_re, option_text: str) -> None:
    """Pick ``option_text`` from a MUI Autocomplete.

    The probe proves "Yeni sənəd *" is an ``<input role="combobox">`` paired with a
    ``button[aria-label="Open"]`` — a MUI Autocomplete, NOT a ``<select>``.
    ``select_option`` therefore cannot be used on it: Playwright rejects it with
    "Element is not a <select> element". The control is driven the way a person
    drives it — open it, type to filter, click the option.

    The popup listbox is rendered in a React portal at ``<body>`` level, outside the
    combobox's subtree, so the option is located on ``page`` and not scoped under
    the input.
    """
    from playwright.sync_api import expect

    combo = page.get_by_role("combobox", name=name_re)
    combo.click()
    combo.fill(option_text)
    page.get_by_role("option", name=_re(_escape(option_text))).first.click()
    # The click landing is not the same thing as the value being taken: a filter
    # that matched nothing leaves the box on whatever was typed into it.
    expect(combo).to_have_value(option_text)


def _expansion_errors() -> tuple[type[BaseException], ...]:
    """What "the form did not expand" arrives as.

    ``expect(...).to_be_visible()`` reports a timeout as an AssertionError, while the
    same wait taken through a locator raises Playwright's own TimeoutError. Both mean
    the one thing the caller acts on, so both are caught — and neither is broad enough
    to swallow a mis-mapped selector, which raises RuntimeError instead.

    Imported lazily like every other Playwright reference here, so --dry-run still
    needs no browser installed.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    return (AssertionError, PWTimeout)


def _appeal_url(page) -> str:
    """The absolute URL of the appeal form, built from the page's own origin.

    No hard-coded host: the portal is reached through whatever origin the operator
    logged in on, and APPEAL_PATH is the only part this module is entitled to know.
    """
    parts = urlsplit(page.url or "")
    if not parts.scheme or not parts.netloc:
        raise RuntimeError(
            f"Cannot build the appeal URL — the page is on {page.url!r}, which has no "
            f"origin to take. Navigate to the portal before opening the form.")
    return f"{parts.scheme}://{parts.netloc}{APPEAL_PATH}"


def _document_type_value(combo) -> str:
    """What the document-type combobox currently holds. "" when it is empty."""
    return str(combo.input_value() or "").strip()


def _clear_document_type(combo) -> None:
    """Empty a pre-filled document-type combobox.

    THE BUG THIS FIXES. After a save the portal returns to the appeal form with the
    type combobox already holding "İnspeksiya orqanının rəyi". Re-picking the same
    value writes React the state it already has, React fires no change, the type's
    fields never mount, and the run dies 15s later in _wait_for_form_expansion waiting
    on a date input that was never going to appear.

    Clearing first makes the re-pick a REAL transition — empty, then the value — which
    is the edge React actually reacts to. Typed, not filled: the box is an
    Autocomplete, and MUI wants the keystrokes.
    """
    combo.click()
    combo.press("ControlOrMeta+a")
    combo.press("Delete")


def _open_new_document_form(page, document_type: str) -> None:
    """Get from the bare appeal page to an expanded, fillable form.

    Three steps the rest of the fill assumes have already happened: the "Yeni sənəd"
    tab is active, a document type is chosen, and the fields that type unlocks
    (dates, VÖEN, object, standard, result, attachment) have rendered. None of them
    exist in the DOM until the type is picked — the probe caught the page in exactly
    that state, with 6 controls and no form.

    Two of those steps have to survive a page that is NOT freshly loaded, which is the
    normal case from the second report of a batch onwards: see _clear_document_type
    for the pre-filled combobox, and the reload below for when clearing was not enough.
    """
    from playwright.sync_api import expect

    _ensure_on_appeal_form(page)

    combo = page.get_by_role("combobox", name=_re("Yeni sənəd"))

    # Idempotent: the probe found the combobox already present without any click, so
    # the tab can arrive active. Clicking a tab that is already active is harmless on
    # most portals and not worth betting a run on. (No double-click with the
    # transition above: reaching the form is what makes this combobox visible.)
    #
    # is_visible() is INSTANTANEOUS — it never waits. So a False here answers two very
    # different questions with the same word: "on the dashboard, the form is a click
    # away", and "on the form, React has not mounted yet". _click_new_document_tab
    # handles the first and declines the second; the wait below is what the second
    # actually needed all along.
    if not combo.is_visible():
        _click_new_document_tab(page)
        try:
            expect(combo).to_be_visible(timeout=15000)
        except _expansion_errors() as exc:
            # Without this the batch died on a bare Playwright AssertionError naming
            # a locator and no page — unreadable in an unattended run's log.
            raise RuntimeError(
                f"The 'Yeni sənəd' document-type combobox never appeared within 15s. "
                f"The portal is on {page.url}. If that is the appeal form, the page "
                f"never finished rendering; re-run --probe to confirm the combobox is "
                f"still named 'Yeni sənəd'.") from exc

    if _document_type_value(combo):
        _info("form", _c("document type arrived pre-filled — clearing it so the "
                         "re-selection is a real React change", _C.GREY))
        _clear_document_type(combo)

    _select_autocomplete(page, _re("Yeni sənəd"), document_type)

    try:
        _wait_for_form_expansion(page)
        return
    except _expansion_errors():
        pass

    # Clearing did not do it, so the React tree itself is in a state this page cannot
    # be talked out of. A fresh navigation is the one reset that always works: it
    # throws the whole component tree away rather than trying to drive it back to a
    # good state. goto rather than reload, because a reload of a form the portal
    # bounced elsewhere would reload the wrong page.
    _info("form", _c("the form did not expand — reloading the appeal page and picking "
                     "the type again", _C.YELLOW))
    page.goto(_appeal_url(page))
    page.wait_for_url(is_appeal_url, timeout=15000)
    _select_autocomplete(page, _re("Yeni sənəd"), document_type)

    try:
        _wait_for_form_expansion(page)
    except _expansion_errors() as exc:
        raise RuntimeError(
            f"The document type '{document_type}' was selected twice — once on the "
            f"page as found, once after a full reload — and the form never expanded: "
            f"no field with placeholder 'DD.MM.YYYY' appeared. The portal is on "
            f"{page.url}. Re-run --probe: either the type no longer unlocks these "
            f"fields, or the date placeholder changed.") from exc


def _ensure_on_appeal_form(page, timeout_ms: int = 15000) -> None:
    """Walk the dashboard to the appeal form. No-op if already there.

    The takeover deliberately claims /uqq/e-competition/ — that is where the portal's
    "Tanış oldum" lands, and refusing it means waiting for a human to click one tab.
    But the dashboard is NOT the form: nothing below it exists there. So the run gets
    itself the rest of the way, and then proves it arrived.

    is_appeal_url is the proof, and it is why that predicate stayed strict while
    is_takeover_url got broadened. Without this pairing, a takeover on the dashboard
    would hand upload_report the Məlumatlar tab and a --probe would dump it.
    """
    if is_appeal_url(page.url):
        return
    _info("transition", _c("on the dashboard — clicking 'Yeni sənəd' to reach the form",
                           _C.GREY))
    _click_new_document_tab(page)
    page.wait_for_url(is_appeal_url, timeout=timeout_ms)


def _await_save_redirect(page, timeout_ms: int = _SAVE_REDIRECT_TIMEOUT_MS) -> None:
    """Prove "Yadda saxla" committed the draft. Raises if it cannot be proved.

    The portal shows NO success toast. It answers a committed draft by leaving the
    appeal form for Layihələr (PROJECTS_PATH), and by nothing else — so this redirect
    is the entire save confirmation. An earlier version waited on toast text instead
    and failed every save that had in fact worked, stranding real drafts as
    IN_PROGRESS in the ledger and aborting the batch behind them.

    Raising rather than warning is the point: the caller's next step is
    ledger.mark_uploaded, and a draft that cannot be confirmed must not be recorded
    as sent. The message says "may or may not" deliberately — the click landed, so
    this genuinely does not know which, and only the operator can look.

    Also the batch's hand-off. The next report re-enters through the "Yeni sənəd"
    tab; clicking that mid-redirect clicks a page already on its way out.
    """
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        page.wait_for_url(is_projects_url, timeout=timeout_ms)
    except PWTimeout:
        raise RuntimeError(
            f"'Yadda saxla' was clicked but the portal never reached {PROJECTS_PATH} "
            f"within {timeout_ms}ms — it is on {page.url}. The draft may or may not "
            f"have been saved; check Layihələr on the portal before re-running this "
            f"report with --force.") from None

    _info("saved", _c(f"draft committed → {page.url}", _C.GREEN))


def _click_new_document_tab(page) -> None:
    """Click the "Yeni sənəd" entry in the workspace's top navigation.

    Tried as a tab, then a link, then a button, because the probe cannot say which it
    is: it captured the strip as buttons with an EMPTY accessible name, while the
    caption walk read the whole row of labels off the container
    ("Məlumatlar Yeni sənəd Layihələr …"). So the text is on the page but not on the
    control, and which role the portal used is a guess either way — try each rather
    than bet on one.

    NAVIGATION ONLY, and a deliberate no-op once the browser is already on the appeal
    form: there is nowhere left to navigate to. Being on /uqq/new-appeal with the
    combobox not yet visible does NOT mean the form is a click away — it means the
    React tree has not mounted, and the nav strip has not mounted either. Hunting a
    tab in that window found nothing, fell through to the raise below, and killed a
    whole unattended batch on the report following a skip. The caller's auto-waiting
    expect() is the right answer there; this function's is to stand aside.
    """
    if is_appeal_url(page.url):
        return

    for role in ("tab", "link", "button"):
        candidate = page.get_by_role(role, name=_re("Yeni sənəd"))
        if candidate.count():
            candidate.first.click()
            return

    # Nothing carried the name. The probe found exactly one tab on the page, so with
    # one candidate there is nothing to disambiguate and no wrong choice to make.
    fallback = page.get_by_role("tab")
    if fallback.count() == 0:
        raise RuntimeError(
            "No 'Yeni sənəd' tab, link or button on the page, and no tab to fall back "
            "on. The portal's navigation changed — re-run --probe and re-map.\n"
            # In a batch this fires on the page the portal redirected to AFTER a save
            # (Layihələr), whose nav strip may differ from the appeal form's. Naming
            # the URL is the difference between a fixable report and a blind timeout.
            f"    Page it was looking at: {page.url}")
    fallback.first.click()


def _wait_for_form_expansion(page, timeout_ms: int = 15000) -> None:
    """Block until the document type has actually rendered its fields.

    Waits on the first date field becoming visible — a real condition, not a delay.
    It used to count controls entering the DOM, which was a workaround for not
    knowing what the new fields were called. The probe knows now: both date inputs
    carry placeholder "DD.MM.YYYY", and the first one appearing is what "the form
    expanded" actually means.
    """
    from playwright.sync_api import expect

    expect(page.get_by_placeholder("DD.MM.YYYY").first).to_be_visible(
        timeout=timeout_ms)


def _fill_date(locator, value: str) -> None:
    """Type a DD.MM.YYYY value into a MUI date field and prove it landed.

    Two reasons this is not a ``fill()``. The field is a masked input, which
    commonly ignores a bulk fill and keeps whatever it had. And the portal ships
    the second date PREFILLED with today — the probe caught it as
    ``aria-label="Choose date, selected date is Jul 17, 2026"`` — so a write that
    silently does nothing does not leave a blank anyone would notice. It leaves
    today's date, on a filed government appeal, in place of the reporting period.

    Hence: clear it, type it like a person, then assert the value is what we meant.
    """
    from playwright.sync_api import expect

    locator.click()
    locator.press("ControlOrMeta+a")
    locator.press_sequentially(value)
    expect(locator).to_have_value(value)


#: Everything that separates one token of a standard's name from the next.
_STANDARD_SEPARATORS = r"[\s\-_/,:]+"


def _standard_key(text: str) -> str:
    """Separator-free comparison key. "ASTM E 384" and "ASTM E384" collapse to one.

    Used for the exact rule only. Deliberately blind to punctuation, because a space
    or a dash between a letter and its number is a transcription habit, not a
    different document.
    """
    import re
    return re.sub(_STANDARD_SEPARATORS, "", _normalize_typography(text)).casefold()


def _standard_tokens(text: str) -> frozenset[str]:
    """The whole tokens of a standard's name, casefolded.

    WHOLE tokens, never substrings — this is the property that makes the matcher
    safe. "ASTM E1476" shares only "astm" with "ASTM E 384", and "1476" is not a
    token of it, so it correctly matches nothing. A substring or first-word rule
    would hand back "ASTM E 384" and file the wrong normative document.
    """
    import re
    return frozenset(
        t for t in re.split(_STANDARD_SEPARATORS, _normalize_typography(text).casefold())
        if t)


def _standard_core(text: str) -> frozenset[str]:
    """Tokens up to and INCLUDING the first that carries a digit.

    "EEMUA 158,Edition 3,Section 7.5.4" -> {eemua, 158}. The edition and section
    narrow WHICH PART of EEMUA 158 was applied; they do not name a different
    document, and the portal has nowhere to record them anyway.

    Applied to the wanted standard only, never to a portal option — reducing
    "EEMUA 153/158" would strip it to {eemua, 153} and destroy the very match this
    exists to make.
    """
    import re
    core: list[str] = []
    for token in re.split(_STANDARD_SEPARATORS,
                          _normalize_typography(text).casefold()):
        if not token:
            continue
        core.append(token)
        if any(c.isdigit() for c in token):
            break
    return frozenset(core)


#: Delimiters that separate two DISTINCT standards inside one "Standart" cell. Comma,
#: slash and plus split ONLY when whitespace flanks them, because all three also occur
#: INSIDE a single name or suffix ("EEMUA 153/158", "ASTM E797/E797M",
#: "EEMUA 158,Edition 3,Section 7.5.4") or inside an acceptance criterion the source
#: documents write unspaced ("SET TO 80% FSH+2dB"), where they must not split.
#: Semicolon, "&" and the word "and" never occur mid-name, so they split unconditionally.
#:
#: The separators that actually occur in this corpus, counted over the raw source cells:
#: "&" (88 cells — "API 1104 & ASME IX" 85, "API 1104 & ASME B31.3" 3) and " + "
#: (4 cells — "API 1104 + ASME B31.8"). The plus was added on 2026-09-09: without it
#: that cell matched WHOLE against "API 1104" on the core rule, so the appeal named one
#: of the two documents the inspection was judged by and silently dropped ASME B31.8 —
#: the same failure unmatched_standards exists to prevent, arriving through the splitter
#: instead of the matcher.
#:
#: COPIED, byte for byte, in ``monthly_report.method_registry`` (task 11-D), where
#: the same cell is split to decide whether a row compiles at all. Change one and you
#: must change the other: ``tests/test_composite_standards.py`` asserts they are equal,
#: so a drift fails the suite instead of producing rows that compile but cannot be filed.
_STANDARD_ITEM_SPLIT = (
    r"\s*;\s*"          # semicolon
    r"|\s*&\s*"         # ampersand
    r"|\s+and\s+"       # the English word 'and'
    r"|\s+/\s*|/\s+"    # slash flanked by whitespace on at least one side
    r"|\s+,\s*|,\s+"    # comma flanked by whitespace on at least one side
    r"|\s+\+\s*|\+\s+"  # plus flanked by whitespace on at least one side
)


def split_standards(raw) -> list[str]:
    """Split a possibly multi-standard "Standart" cell into its individual standards.

    "ASME VIII / ISO 17636" -> ["ASME VIII", "ISO 17636"]; a lone standard returns
    ``[itself]``; blank/None returns ``[]``. Each token is then matched and tagged on
    its own, so a report citing two documents names both on the appeal. See
    _STANDARD_ITEM_SPLIT for why "/", "," and "+" split only when whitespace flanks
    them.

    Splitting does NOT soften the gate. Each part is matched separately and
    unmatched_standards collects every part that misses, so a composite passes only
    when EVERY part is offered and one unoffered part refuses the whole report exactly
    as a lone unoffered standard does. There is no partial filing: an appeal naming
    the half of "API 1104 & ASME IX" that happens to be listed would claim an
    assessment narrower than the one performed.

    A part carrying no letter and no digit is dropped rather than returned: a cell
    left as a bare "+" or "-" names no document, and returning it would make
    unmatched_standards refuse a report over a punctuation mark.
    """
    import re
    text = _normalize_typography(raw).strip()
    if not text:
        return []
    return [tok.strip()
            for tok in re.split(_STANDARD_ITEM_SPLIT, text, flags=re.IGNORECASE)
            if tok and any(c.isalnum() for c in tok)]


def _standard_aliases() -> dict[str, list[str]]:
    """The config ``portal.standard_aliases`` range map: ``{option: [pattern, ...]}``.

    A range/alias entry maps a whole FAMILY of parsed standards onto one portal option
    the portal offers as an aggregate — e.g. "ASME VIII" onto "ASME I-XII", which is on
    the provisional 21-standard list (operator, 2026-10-06; NOT yet probe-verified).
    Absent config yields ``{}`` (feature off). See _alias_match.
    """
    portal = _settings().raw.get("portal") or {}
    return portal.get("standard_aliases") or {}


def _baseline_options() -> list[str]:
    """The dry-run option universe: measured PORTAL_STANDARDS plus alias TARGETS.

    PORTAL_STANDARDS is what --probe measured off the live listbox; the alias-map keys
    are option names the config asserts the portal ALSO offers. A key that is not on the
    live listbox makes --dry-run falsely green ("ASME I-XII" did exactly that on the
    2026-08-12 list; since 2026-10-06 it is itself in PORTAL_STANDARDS, provisionally).
    Both are legitimate --dry-run options, but only
    PORTAL_STANDARDS is the drift baseline test_uploader_probe_contract reconciles — so
    the alias targets are unioned in here rather than baked into the constant.
    """
    known = {_standard_key(o) for o in PORTAL_STANDARDS}
    extra = [o for o in _standard_aliases() if _standard_key(o) not in known]
    return list(PORTAL_STANDARDS) + extra


def _alias_match(wanted: str, options, aliases: dict[str, list[str]]) -> str | None:
    """The portal option ``wanted`` maps onto via the range/alias map, or None.

    Same regex/literal convention as ``is_allowed_standard``: an entry with ``^``/``$``
    /``\\`` is a case-insensitive ``re.fullmatch`` (separators normalized to single
    spaces), else a separator-blind literal equality. Only an option the CALLER'S list
    actually offers can be returned — the live listbox is the authority, so a config
    that names an option the portal has since dropped simply does not fire.

    AMBIGUITY REFUSES, like the exact/token rules in match_portal_standard: a wanted
    that matches TWO offered options returns None, not the first one. A bare "EEMUA 158"
    is a sub-number of both "EEMUA 153/158" and a (hypothetical) "EEMUA 157/158", and a
    coin flip between two normative documents is not a match. With one combined option
    offered per family this is inert; it makes the sub-spec aliases safe to grow.
    """
    import re
    normalized = re.sub(r"[\s_-]+", " ", _normalize_typography(wanted).strip())
    if not normalized:
        return None
    offered = {_standard_key(o) for o in options}
    hits: list[str] = []
    for option, patterns in (aliases or {}).items():
        if _standard_key(option) not in offered:
            continue
        for pat in patterns or []:
            pat = str(pat)
            matched = (re.fullmatch(pat, normalized, re.IGNORECASE)
                       if pat.startswith("^") or pat.endswith("$") or "\\" in pat
                       else _standard_key(pat) == _standard_key(wanted))
            if matched:
                hits.append(option)
                break
    unique = list(dict.fromkeys(hits))
    return unique[0] if len(unique) == 1 else None


def match_portal_standard(wanted: str,
                          options=None,
                          aliases: dict[str, list[str]] | None = None
                          ) -> tuple[str | None, str]:
    """Match a parsed standard against the portal's option list.

    -> (option, "alias" | "exact" | "token" | "core" | "none"). ``options`` defaults to
    _baseline_options() (measured options + alias targets) so this is callable without a
    browser (--dry-run); ``aliases`` defaults to the config range map.

    Four rules, first hit wins:

      alias  config range map, option offered  "ASME VIII" -> "ASME I-XII"
                                                "EEMUA 158" -> "EEMUA 153/158"
      exact  separator-blind equality          "ASTM E384"  == "ASTM E 384"
      token  wanted's tokens ⊆ option's        "ISO 176"    ⊄  "ISO 17638"
      core   ditto, after _standard_core       "EEMUA 158,Edition 3,…" -> "EEMUA 158"

    ALIAS is a TRUE match, not a substitution: "ASME VIII" IS one of the Sections the
    portal's "ASME I-XII" option aggregates, and "EEMUA 158" IS one revision of the
    portal's "EEMUA 153/158" — each names the same document family and is filed without
    a correction warning. A slashed
    sub-number would also match on tokens, but the alias makes it deterministic config,
    not an incidental subset, and lets the config vouch for the family.

    AMBIGUITY REFUSES, in every rule including alias. A rule matching two options
    returns "none" rather than pick one: "API" alone is a subset of "API 5L",
    "API 579" AND "API 1104", and a coin flip between three normative documents is not
    a match. (No PORTAL_STANDARDS entry is a token-subset of another, so no real
    standard is lost to this guard — there is a test pinning that.)

    Every rule here names the SAME document as the wanted one, which is why the caller
    may select a "token"/"core"/"alias" hit under --live. The old first-word rule did
    not have that property and is gone.
    """
    if options is None:
        options = _baseline_options()
    options = list(options)
    if aliases is None:
        aliases = _standard_aliases()

    key = _standard_key(wanted)
    if not key:
        return None, "none"

    aliased = _alias_match(wanted, options, aliases)
    if aliased is not None:
        return aliased, "alias"

    exact = [o for o in options if _standard_key(o) == key]
    if len(exact) == 1:
        return exact[0], "exact"
    if exact:
        return None, "none"

    for kind, tokens in (("token", _standard_tokens(wanted)),
                         ("core", _standard_core(wanted))):
        if not tokens:
            continue
        hits = [o for o in options if tokens <= _standard_tokens(o)]
        if len(hits) == 1:
            return hits[0], kind
        if hits:
            return None, "none"

    return None, "none"


def unmatched_standards(standards, options=None) -> list[str]:
    """Every standard the portal cannot name, in the order the report lists them.

    ``[]`` means the report is filable; anything else means it is not, and the WHOLE
    report is skipped rather than filed naming a document it was not assessed against
    (see upload_report's SKIPPED_UNMATCHED_STANDARD). One unfilable standard is enough:
    an appeal that silently omits one of the codes an inspection was judged by is as
    wrong as one that names a code it was not.

    ``options`` defaults to match_portal_standard's baseline, so this answers without a
    browser — that is what lets --dry-run and the pre-flight give the same verdict the
    live listbox will. Pass the live options to re-ask the portal itself.

    Blank entries are dropped, not counted: a report whose standard cell is empty
    claims nothing, and there is nothing for the portal to fail to offer.
    """
    missing = []
    for standard in standards or ():
        if not str(standard or "").strip():
            continue
        choice, _kind = match_portal_standard(standard, options)
        if choice is None:
            missing.append(standard)
    return missing


def _xpath_literal(text: str) -> str:
    """Quote ``text`` as an XPath string literal.

    XPath 1.0 has no escape character, so a value containing both quote kinds can
    only be expressed as a concat(). None of our captions do, but a caption is portal
    text that can change under us, and the failure mode of naive quoting is a
    malformed expression that matches something unintended.
    """
    if "'" not in text:
        return f"'{text}'"
    if '"' not in text:
        return f'"{text}"'
    parts = "', \"'\", '".join(text.split("'"))
    return f"concat('{parts}')"


def _caption_anchor(page, caption: str):
    """The single element whose own text is ``caption``. Raises if it is not single.

    ``text()`` — direct text children only — is load-bearing. ``contains(., ...)``
    would also match every ancestor up to <body>, since an ancestor's text contains
    its descendants'.

    The count check is the safety rail: these anchors are how the un-labelled fields
    are found, and an anchor that matched two elements is an anchor that picks one of
    them arbitrarily. On this form that means typing a verdict into whatever input
    happened to come first in the document.
    """
    anchor = page.locator(f"xpath=//*[normalize-space(text())={_xpath_literal(caption)}]")
    found = anchor.count()
    if found != 1:
        raise RuntimeError(
            f"Caption {caption!r} matched {found} elements on the form, expected "
            f"exactly 1. The portal's markup changed — re-run --probe and re-map "
            f"before uploading.")
    return anchor


def _field_after_caption(page, caption: str):
    """The first ``<input>`` that follows ``caption``'s text in the document.

    This portal renders most captions as loose text NEXT to the input rather than as
    a ``<label for>``, so ``get_by_label`` matches nothing for them and there is no
    id worth using — the ids are React ``useId``s (``:r28:``) that regenerate on every
    render. Following the caption is how a person reads the form, and it is anchored
    on meaning rather than on DOM position.
    """
    return _caption_anchor(page, caption).locator("xpath=following::input[1]")


def _field_before_caption(page, caption: str):
    """The nearest ``<input>`` that PRECEDES ``caption``'s text in the document.

    For the director's name, the portal puts the caption UNDER each box — the markers
    "(ad/name)", "(soyadı/surname)", "(atasının adı/middle name)". The ``preceding``
    axis is reverse-ordered, so ``[1]`` is the closest one, i.e. the box the marker
    is captioning.
    """
    return _caption_anchor(page, caption).locator("xpath=preceding::input[1]")


def _fill_verified(locator, value: str, attempts: int = 2) -> None:
    """Fill a plain text input and prove the value landed — retrying a clobber.

    Cheap, and it is what turns a mis-resolved caption anchor into a failed run
    instead of a wrong value sitting quietly on a government appeal.

    THE RETRY. A MUI controlled input can be re-rendered out from under a completed
    fill: an async portal lookup resolves carrying a state snapshot taken before we
    typed, and the box goes back to "". That is what emptied "İnspeksiyanın olunan
    obyekt:" mid-run on MR-MT-UBOC-25-12. Its failure dump settles the mechanism —
    the input's wrapper carries Mui-focused, so the fill reached the right element,
    and it still reads value="" with no maxlength on it or on any other input the
    probe has ever seen.

    A missed synthetic event would look different, and quieter: Playwright's native
    setter writes the DOM value, which is what to_have_value reads, so the assertion
    would PASS while React's state stayed empty. Only a re-render puts "" back.

    So the check is no longer only a check. A mismatch buys one more attempt, typed
    keystroke by keystroke — what survives a component that discarded a bulk set —
    then blurred so React commits, then proved again. Failing twice is a real
    failure and costs one report rather than the batch.
    """
    from playwright.sync_api import expect

    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        # The clear that _clear_document_type already proved against this portal.
        locator.click()
        locator.press("ControlOrMeta+a")
        locator.press("Delete")
        if attempt == 1:
            locator.fill(value)
        elif value:
            locator.press_sequentially(value)
        locator.press("Tab")        # blur — React commits on change + blur
        try:
            expect(locator).to_have_value(value)
            return
        except _expansion_errors() as exc:
            last = exc
            if attempt < attempts:
                _info("field", _c(f"the box did not hold its value ({len(value)} "
                                  f"chars) — retyping it", _C.YELLOW))

    raise RuntimeError(
        f"A form field would not hold its value after {attempts} attempts "
        f"({len(value)} chars). Either the portal re-rendered over it, or the "
        f"caption anchor resolved a read-only box. The saved failure HTML shows "
        f"which; re-run --probe if the form has been re-laid-out.") from last


def _select_standard(page, standards_box, standard: str,
                     method: str = "", already: set | None = None) -> str:
    """Tag one normative document, spelling it the portal's way.

    Returns "exact" | "token" | "core" | "alias" | "duplicate" | "unmatched".

    Every returned match names the SAME document as ``standard``. There is no other
    kind left: a standard the portal does not offer is NOT substituted with the
    discipline's method standard or a placeholder — it returns "unmatched", nothing is
    clicked, and the caller abandons the whole report (see unmatched_standards and
    upload_report's SKIPPED_UNMATCHED_STANDARD).

    Not raising is deliberate and unchanged: the caller decides what an unfilable
    standard costs, and it costs one report rather than the batch.

    ``method`` is accepted and unused — it survives only so callers reading a report's
    payload need no special case. It used to pick the substitute.

    ``already`` is the set of option texts this form has selected so far. Two of our
    standards can still land on one portal option through the alias rule, and
    re-clicking a tagged option in a MUI multiselect REMOVES it.

    There is deliberately no ``live`` parameter: which option gets tagged is identical
    in review and --live, so the rehearsal always matches the performance.
    """
    options = _open_standards_list(page, standards_box)
    choice, kind = match_portal_standard(standard, options)

    if choice is None:
        _warn(f'"{standard}" is not offered by the portal — REPORT SKIPPED. Nothing '
              f'was selected; no substitute is ever filed in its place.')
        _info("offered", _c(f"{options}", _C.GREY))
        _close_standards_list(page)
        _UNMATCHED.append(standard)
        return "unmatched"

    if already is not None and choice in already:
        # Not a no-op: MUI toggles, so the second click would un-tag the option this
        # form already set. Two of our standards collapsing onto one portal option is
        # rare now that nothing is substituted, but the alias rule can still do it.
        _info("standard", _c(f'"{standard}" -> "{choice}" — already tagged, not '
                             f'clicked again', _C.GREY))
        return "duplicate"

    # Whole-string, so "API 579" cannot also match an "API 5791" and tag a different
    # document by accident. Not a regex: Playwright serializes one into its own
    # selector as /pattern/flags, and a "/" inside an option name — "ASTM E797/E797M"
    # — closes that literal early. re.escape does not help; "/" is not special to
    # Python's re. choice is always verbatim portal text, so exact matching fits.
    page.get_by_role("option", name=choice, exact=True).first.click()
    if already is not None:
        already.add(choice)
    if kind != "exact":
        _info("standard", _c(f'"{standard}" -> "{choice}" ({kind} match)', _C.GREY))
    return kind


def _open_standards_list(page, standards_box) -> list[str]:
    """Open the multiselect and read every option it offers. [] if it will not open.

    Click-to-select, strictly: nothing is ever typed here. Beyond the portal refusing
    it, typing FILTERS the MUI list by substring, and the portal's names are not
    substrings of ours — "EEMUA 158" does not occur inside "EEMUA 153/158" — so a
    filter would empty the list and the token match could never be made.

    Idempotent, and that is load-bearing. In MUI multiple mode the list stays open
    after an option is picked, so an unconditional click would TOGGLE IT SHUT on the
    second standard. is_visible() is the right question precisely because it does not
    wait: "is the list up now", not "will it come up".
    """
    if page.get_by_role("option").first.is_visible():
        return _visible_options(page)

    standards_box.click()
    options = _listbox_options(page)
    if options:
        return options

    # The probe found a "Seç" button beside this combobox (idx 20) — MUI's open/close
    # toggle. Reached ONLY once the click above provably opened nothing, because
    # firing it at an open list is what closes it.
    opener = page.get_by_role("button", name=_re(r"^Seç$"))
    if opener.count():
        opener.first.click()
        options = _listbox_options(page)
    return options


def _listbox_options(page) -> list[str]:
    """Wait for the listbox to render, then read it. [] if it never came up.

    THE fix for standards silently not being tagged. _visible_options is built on
    all_inner_texts(), which is one of Playwright's non-retrying APIs: it does not
    auto-wait, it reports whatever exists at that instant. Called straight after the
    click it raced the listbox — which mounts into a React portal at <body> level —
    read [], and every standard was skipped for want of a few milliseconds.

    Returns [] rather than raising: the caller distinguishes "the portal does not offer
    this standard" from "the portal offered nothing at all", and both are handled.
    """
    from playwright.sync_api import expect

    try:
        expect(page.get_by_role("option").first).to_be_visible(
            timeout=_LISTBOX_TIMEOUT_MS)
    except AssertionError:
        return []
    return _visible_options(page)


def _close_standards_list(page) -> None:
    """Close the listbox with a CLICK. No keystroke reaches this field, ever.

    Not cosmetic: a listbox left open is a MUI popper floating over the fields below
    it, and the next fill would have its click intercepted by the overlay rather than
    land on "Nəticə:".

    Escape would be the obvious way and is what this used to do. It is gone because
    the field takes clicks only — so the close reuses the portal's own "Seç" toggle
    (probe idx 20), guarded on the list actually being open, since firing a toggle at
    a closed list would OPEN it.
    """
    if not page.get_by_role("option").first.is_visible():
        return
    opener = page.get_by_role("button", name=_re(r"^Seç$"))
    if opener.count():
        opener.first.click()


def _visible_options(page) -> list[str]:
    """The option texts in the listbox RIGHT NOW. Does not wait — see _listbox_options."""
    return [t.strip() for t in page.get_by_role("option").all_inner_texts()]


def upload_report(page, pdf_path: str | Path, json_data: dict,
                  portal_cfg: dict, live: bool = False, confirm=None):
    """Fill ``/uqq/new-appeal`` from one sidecar and attach its PDF.

    Locators target meaning (role / label / placeholder), never DOM position — the
    portal's markup is unversioned and an index-based selector is already broken.
    Readiness is always awaited on a real condition; there is no ``time.sleep``
    anywhere, because a fixed delay is simultaneously too slow when the page is
    ready early and too flaky when it is not.

    Every locator here is mapped from output/portal_form_probe.json (schema 3) and
    marked in-line with the probe id it came from, so the next reader can re-verify
    against the dump rather than trust this code. Three kinds of anchor, in order of
    preference: a real accessible name (the document type, the Hüquqi şəxs radio),
    a placeholder (VÖEN, the dates, FİN, Seriya nömrəsi), and — for the fields this
    portal ships with no accessible attribute at all — the caption text a human
    reads next to the box.

    NOT filled, deliberately: the client's name. The two inputs after VÖEN (``:r26:``
    / ``:r27:``) carry no caption, label or placeholder, so which is the name and
    which the address is not knowable from the dump. It does not need to be: the
    portal populates them from the tax database on the VÖEN blur, and that database
    is the authority on a company's legal name — our registry holds a display name
    ("UBOC"). Writing ours over the state's would be wrong even if we picked the
    right box.

    ``Yadda saxla`` is only clicked when ``live`` is True. ``E-imza ilə təsdiqlə``
    is never located and never clicked — the signature stays a human decision. The
    probe confirms that button is on the page; the safeguard is that no code here
    can find it.

    ``confirm`` is the optional human gate: a zero-argument callable asked, once the
    form is filled and immediately before the save, whether to ``"save"``, ``"skip"``
    or ``"quit"`` (see :func:`_confirm_before_save`). It is consulted only on the path
    that would otherwise click — a fill-only run has already returned by then, so the
    operator is never asked to approve something that was never going to happen.
    """
    pdf_path = Path(pdf_path)
    payload = build_portal_payload(json_data, portal_cfg)

    # This report's unfilable standards, drained by the caller once the fill is over.
    _UNMATCHED.clear()
    _POLICY_SKIPPED.clear()

    # NO STANDARD, NO APPEAL. The portal will not accept a submission that names no
    # normative document, so a report whose every standard cell is blank is refused
    # here rather than at the end of a filled form. Decided alongside the pre-flight
    # below and for the same reason: without a browser, so review, --dry-run and --live
    # agree, and so a report that cannot be filed truthfully costs no clicks.
    #
    # Nothing is invented to fill the box — the batch's own most common standard least
    # of all (see document_aggregator._fill_missing_standards, which deliberately leaves
    # these blank rather than lending a PMI report an ASTM E1476 it was not judged by).
    # The fix belongs in the source document; this report files itself once it has one.
    if not payload["standards"]:
        _warn("SKIPPED — the portal requires a standard; report has no standard. "
              "Nothing was filled and nothing was saved.")
        _info("standards", _c("add the standard to the source document and re-run; "
                              "no substitute is ever filed in its place", _C.GREY))
        return "SKIPPED_EMPTY_STANDARD"

    # ZERO SUBSTITUTION, decided BEFORE anything is touched. The baseline answers this
    # without a browser, so review, --dry-run and --live reach the same verdict and a
    # report that cannot be filed truthfully costs nothing — no navigation, no typing,
    # no attachment, and no ledger entry (see _run_batch). The live listbox re-asks the
    # same question at step 5 and is what actually decides.
    missing = unmatched_standards(payload["standards"])
    # portal.standard_policy: any (ADR-010). The same baseline answer, split instead of
    # all-or-nothing: the offered standards are filed, the rest are named here and left
    # off the appeal. Zero offered falls through to the refusal below, unchanged. The
    # live listbox still re-asks at step 5 — and a FILABLE one it lacks refuses the
    # whole report there, exactly as under "all".
    if missing and _standard_policy() == "any":
        filable = [s for s in payload["standards"] if s not in missing]
        if filable:
            _POLICY_SKIPPED.extend(missing)
            print(f"  standards skipped (policy any): {missing}")
            payload["standards"] = filable
            missing = []
    if missing:
        _UNMATCHED.extend(missing)
        _warn(f"SKIPPED — the portal does not offer {missing}. Nothing was filled and "
              f"nothing was saved; no substitute is ever filed in their place.")
        _info("standards", _c("this report uploads itself on a later run, once the "
                              "portal lists them", _C.GREY))
        return "SKIPPED_UNMATCHED_STANDARD"

    if _is_dry(page):
        return _simulate_upload(payload, pdf_path, json_data, live)

    # --- real browser path ---
    from playwright.sync_api import expect

    # 1. Open the "Yeni sənəd" tab and choose the document type. Everything below
    #    only exists in the DOM once this has run.
    _open_new_document_form(page, payload["document_type"])

    # 2. Inspection date range — the whole reporting month.
    #    Probe: :r20: and :r22:, both placeholder "DD.MM.YYYY". :r22: arrives
    #    prefilled with today, which is why _fill_date verifies rather than trusts.
    date_fields = page.get_by_placeholder("DD.MM.YYYY")
    _fill_date(date_fields.nth(0), payload["date_from"])
    _fill_date(date_fields.nth(1), payload["date_to"])

    # 3. Client: legal entity, identified by VÖEN.
    #    Probe: radio label "Hüquqi şəxs" (a real <label for>), VÖEN is :r25: —
    #    placeholder only, no label, so get_by_label finds nothing here.
    page.get_by_role("radio", name=_re("Hüquqi şəxs")).check()
    voen_field = page.get_by_placeholder("VÖEN")
    _fill_verified(voen_field, payload["client_voen"])
    # Blur is what triggers the portal's tax-database lookup. The name and address it
    # writes back (:r26: / :r27:) are the state's own record of this company, so we
    # neither write them nor race them — see the note above this function.
    voen_field.press("Tab")
    # And racing it is not only about those two boxes. The lookup resolves with a form
    # state captured BEFORE anything typed after the blur, so committing it wipes the
    # next field we filled — which is exactly how the inspection object came back empty
    # on MR-MT-UBOC-25-12. Let it land first, as the director's registry search below
    # already is. _fill_verified's retry is the backstop; this is what makes it rare.
    page.wait_for_timeout(1500)

    # 4. Inspection object — every distinct item in the batch.
    #    Probe: :r28:, caption "İnspeksiyanın olunan obyekt:".
    _fill_verified(_field_after_caption(page, "İnspeksiyanın olunan obyekt:"),
                   payload["inspection_object"])

    # 5. Normative documents — one tag per distinct PORTAL OPTION, not per standard.
    #    Probe: :r29:, caption "inspeksiya:", role=combobox with an aria-label="Seç"
    #    button beside it — a MUI Autocomplete in multiple mode, so each standard is
    #    picked from the portal's own list.
    #
    #    `selected` is what makes that distinction hold: two of our standards can land
    #    on one portal option through the alias rule, and re-clicking a tagged option
    #    in a MUI multiselect REMOVES it.
    #
    #    THE LIVE BACKSTOP. The pre-flight above answered from PORTAL_STANDARDS; this
    #    loop asks the portal itself. If the live list disagrees, the report is
    #    abandoned here — nothing has been saved, the only state is React's, and
    #    _reset_appeal_form reloads it away so the next report starts clean.
    standards_box = _field_after_caption(page, "inspeksiya:")
    selected: set[str] = set()
    for standard in payload["standards"]:
        if _select_standard(page, standards_box, standard,
                            method=payload.get("ndt_method", ""),
                            already=selected) == "unmatched":
            _info("state", _c("the live listbox does not offer it — the baseline "
                              "PORTAL_STANDARDS is stale, re-run --probe", _C.YELLOW))
            _reset_appeal_form(page)
            return "SKIPPED_UNMATCHED_STANDARD"

    # 6. Equipment note, verdict + signing director.
    #    Probe: :r2c:, caption "İstifadə olunmuş avadanlıqlar barədə qeyd:" — the
    #    instruments this batch was inspected with. The value comes from the
    #    sidecar's equipment_used, which the exporter joined from the source
    #    documents' Equipment blocks; it appears nowhere in the PDF.
    _fill_verified(_field_after_caption(page, "İstifadə olunmuş avadanlıqlar barədə qeyd:"),
                   payload["equipment_used"])
    #    Probe: :r2e:, caption "Nəticə:". Note :r2d: ("Əlavə məlumat:") sits between
    #    the equipment note and this one, and is deliberately left alone.
    _fill_verified(_field_after_caption(page, "Nəticə:"), payload["result"])
    # Probe: :r2f: placeholder "FİN", :r2g: placeholder "Seriya nömrəsi".
    _fill_verified(page.get_by_placeholder("FİN"), payload["director_fin"])
    _fill_verified(page.get_by_placeholder("Seriya nömrəsi"), payload["director_seriya"])

    # The three name boxes (:r2h: :r2i: :r2j: — ad / soyadı / atasının adı) are NOT
    # typed. The portal runs its own registry lookup on FİN + Seriya nömrəsi and
    # fills all three itself; typing over that races the search, and whichever wins
    # decides the name printed on an appeal a real person signs. Blur to trigger the
    # lookup, then give it time to answer.
    page.get_by_placeholder("Seriya nömrəsi").press("Tab")
    page.wait_for_timeout(1500)
    _info("director", _c("FİN + Seriya entered — name auto-searched by the portal",
                         _C.GREY))

    # 7. Attach the compiled monthly PDF.
    #    Probe: a single input[type=file] with no id, name or label — the type IS
    #    the identity here. Asserted, because a second uploader appearing on the
    #    page would make nth(0) a coin flip over which field gets the report.
    file_input = page.locator('input[type="file"]')
    if file_input.count() != 1:
        raise RuntimeError(
            f"Expected exactly 1 file input on the form, found {file_input.count()}. "
            f"The form changed — re-run --probe and re-map before uploading.")

    # Integrity: record exactly what is about to be attached, so a truncated or
    # swapped PDF is visible in the terminal before it ever reaches the form.
    size, digest = _file_integrity(pdf_path)
    _info("PDF path", str(pdf_path.resolve()))
    _info("PDF size", f"{size} bytes")
    _info("PDF SHA-256", digest)

    file_input.set_input_files(str(pdf_path))

    # The portal's React file input clears its DOM file list right after attach, so a
    # post-attach read-back reads empty and would falsely fail. The upload is visible
    # on screen; give React a moment to render it, then proceed. wait_for_timeout is
    # Playwright's own wait, not a static time.sleep — it yields to the event loop.
    page.wait_for_timeout(1500)
    _info("PDF attached", _c(f"{pdf_path.name} ({size} bytes)", _C.GREEN))

    if not live:
        _info("submit", _c("SKIPPED — form filled but NOT saved. Re-run with --live "
                           "to click 'Yadda saxla'.", _C.YELLOW))
        return "FILLED_NOT_SAVED"

    # The human gate. Everything above is reversible — nothing has reached the portal
    # yet — and everything below is not, so this is the last place a person can look
    # at the screen and still change their mind.
    if confirm is not None:
        choice = confirm()
        if choice == "skip":
            _info("submit", _c("SKIPPED by the operator — nothing saved, ledger "
                               "untouched.", _C.YELLOW))
            return "SKIPPED_BY_OPERATOR"
        if choice == "quit":
            _info("submit", _c("QUIT by the operator — nothing saved for this report.",
                               _C.YELLOW))
            return "QUIT_BY_OPERATOR"

    page.get_by_role("button", name=_re(r"^Yadda saxla$")).click()
    _await_save_redirect(page)
    return "OK"


def _simulate_standards(standards: list[str], method: str,
                        skipped: list[str] | tuple = ()) -> None:
    """Narrate how every standard will be named on the form. No browser.

    Only ever reached for a report that PASSED the pre-flight — upload_report returns
    SKIPPED_EMPTY_STANDARD and SKIPPED_UNMATCHED_STANDARD before the dry-run branch — so
    there is at least one standard here and every one of them has a portal option. Both
    refusals are narrated by their own skip, not by this function.

    Predictions, since the live listbox is what actually decides; but PORTAL_STANDARDS
    has been confirmed against it by --probe, and the live backstop in the real fill
    re-asks, so they are good ones.

    Takes no ``live``: _select_standard does not either. The mirror scores exactly what
    the real fill would do, in either mode. ``method`` is unused since nothing is
    substituted by discipline any more; it stays for call-site symmetry.

    ``skipped`` is what ``portal.standard_policy: any`` left off this appeal (ADR-010).
    Those are narrated as not filed — never as "WILL SKIP REPORT", because the report
    itself is filed. Empty under the default "all", so that output is unchanged.
    """
    seen: set[str] = set()

    for standard in skipped:
        _sim(f"{_c(standard, _C.BOLD)}  "
             f"{_c('not filed — not offered by the portal (policy any)', _C.YELLOW)}")

    for standard in standards:
        choice, kind = match_portal_standard(standard)
        if choice is None:
            # Unreachable via upload_report, and not worth a lie if it ever is.
            _sim(f"{_c(standard, _C.BOLD)}  "
                 f"{_c('WILL SKIP REPORT — not offered by the portal', _C.BOLD, _C.YELLOW)}")
            continue
        if choice in seen:
            _sim(f"{_c(standard, _C.BOLD)}  "
                 f"{_c(f'-> \"{choice}\" — already tagged, click skipped', _C.GREY)}")
            continue
        seen.add(choice)
        if kind == "exact":
            _sim(f"{_c(standard, _C.BOLD)}  {_c('exact', _C.GREEN)}")
        else:
            _sim(f"{_c(standard, _C.BOLD)}  {_c(f'{kind} -> \"{choice}\"', _C.GREEN)}")


def _simulate_upload(payload: dict, pdf_path: Path, json_data: dict, live: bool):
    """Narrate the whole fill without a browser (dry-run branch of upload_report)."""
    _step(1, 7, "Navigate to the form, then open the new-document form")
    _sim("get_by_role('link', name=/E-Xidmətlər/).click() → wait_for_url(/e-services)")
    _sim("get_by_text(<service card>).click() → dialog button /Tanış oldum/ .click()")
    _sim(_c("(best-effort — any failure falls back to waiting for you to navigate)",
            _C.GREY))
    _sim(f"takeover on {E_COMPETITION_PATH} or {APPEAL_PATH}  "
         f"{_c('(Tanış oldum lands on the dashboard)', _C.GREY)}")
    _sim(f"if on the dashboard: click 'Yeni sənəd' → wait_for_url({APPEAL_PATH})")
    _sim("if not combobox visible: 'Yeni sənəd' tab → link → button")
    _sim("expect(get_by_role('combobox', name=/Yeni sənəd/)).to_be_visible()")

    _step(2, 7, "Select the document type (MUI Autocomplete, not a <select>)")
    _match("get_by_role('combobox', name=/Yeni sənəd/)   [probe :r1r:]")
    _info("Yeni sənəd", payload["document_type"])
    _sim(f"click + fill + get_by_role('option', name=/{payload['document_type']}/).click()")
    _sim("expect(get_by_placeholder('DD.MM.YYYY').first).to_be_visible()  "
         f"{_c('(the form expanded — no fixed delay)', _C.GREY)}")

    _step(3, 7, "Fill the inspection date range")
    _match("get_by_placeholder('DD.MM.YYYY') nth(0), nth(1)   [probe :r20: :r22:]")
    _info("Tarix (from → to)",
          f'{payload["date_from"]}  →  {payload["date_to"]}   '
          f'(derived from reporting_period="{json_data.get("reporting_period")}")')
    _sim("click + select-all + press_sequentially + expect(to_have_value)  "
         f"{_c('(:r22: ships prefilled with today)', _C.GREY)}")

    _step(4, 7, "Register the client as a legal entity")
    _match("get_by_role('radio', name=/Hüquqi şəxs/)")
    _match("get_by_placeholder('VÖEN')   [probe :r25:]")
    _info("VÖEN", payload["client_voen"])
    _sim("press('Tab') — the portal's tax-database lookup fills the name/address")
    _sim(_c("then settle 1.5s: the lookup resolves with a form state older than "
            "anything typed after the blur", _C.GREY))
    _info("client name", _c(f'{payload["client_name"]} — NOT typed; :r26:/:r27: are the '
                            f'tax DB\'s, and it is the authority', _C.GREY))

    _step(5, 7, "Fill the inspection object and normative documents")
    _match("_field_after_caption('İnspeksiyanın olunan obyekt:')   [probe :r28:]")
    _info("Obyekt", payload["inspection_object"] or _c("(empty!)", _C.RED))
    _match("_field_after_caption('inspeksiya:')   [probe :r29:]")
    _sim("click to open + read EVERY option (no typing — a typed filter is a substring "
         "test, and 'EEMUA 158' is not a substring of 'EEMUA 153/158')")
    if not payload["standards"]:
        _sim(_c("no standards in items_table — nothing to tag", _C.RED))
    _simulate_standards(payload["standards"], payload.get("ndt_method", ""),
                        skipped=_POLICY_SKIPPED)

    _step(6, 7, "Fill the equipment note, the verdict and the director's credentials")
    _match("_field_after_caption('İstifadə olunmuş avadanlıqlar barədə qeyd:')   "
           "[probe :r2c:]")
    _info("Avadanlıq", payload["equipment_used"] or
          _c("(empty — this method's reports carry no equipment field, e.g. DP)",
             _C.YELLOW))
    _match("_field_after_caption('Nəticə:')   [probe :r2e:]")
    result_color = (_C.GREEN if payload["result"] == RESULT_FIT
                    else _C.RED if payload["result"] == RESULT_UNFIT else _C.YELLOW)
    _info("Nəticə", _c(payload["result"], result_color, _C.BOLD) +
          _c("   (informational → Məlumat üçün, else Yararlı)", _C.GREY))
    _match("get_by_placeholder('FİN')   [probe :r2f:]")
    _info("FİN", payload["director_fin"] or _c("(blank — settings.yaml portal.director "
                                               "not filled)", _C.YELLOW))
    _match("get_by_placeholder('Seriya nömrəsi')   [probe :r2g:]")
    _info("Seriya nömrəsi", payload["director_seriya"] or
          _c("(blank — settings.yaml portal.director not filled)", _C.YELLOW))
    _sim("get_by_placeholder('Seriya nömrəsi').press('Tab') → wait_for_timeout(1500)")
    _info("director", _c("ad / soyadı / atasının adı are NOT typed — the portal "
                         "auto-searches them from FİN + Seriya", _C.GREY))
    # Printed as what the portal is EXPECTED to find, not as what gets typed: this is
    # how an operator watching the browser spots a FİN that resolves to someone else.
    for label, value in (("Ad", payload["director_ad"]),
                         ("Soyadı", payload["director_soyadi"]),
                         ("Atasının adı", payload["director_atasinin_adi"])):
        _info(f"{label} (expected)",
              value or _c("(not configured — nothing to check the auto-search against)",
                          _C.YELLOW))

    _step(7, 7, "Attach the compiled PDF, then stop before the save")
    exists = pdf_path.is_file()
    _match("locator('input[type=\"file\"]')   [probe: the only one on the form]")
    if exists:
        # Same integrity read the live path logs — the file is on disk in dry-run too.
        size, digest = _file_integrity(pdf_path)
        _info("PDF path", str(pdf_path.resolve()))
        _info("PDF size", f"{size} bytes")
        _info("PDF SHA-256", digest)
    _sim(f"assert count == 1, then set_input_files('{pdf_path.name}')")
    _sim("wait_for_timeout(1500) — React settles, no post-attach assertion")
    _info("PDF attach", _c(f"{pdf_path.name}  ({'found' if exists else 'MISSING on disk'})",
                           _C.GREEN if exists else _C.RED))
    _info("E-imza", _c("never touched — signature stays manual", _C.GREY))
    if not live:
        _info("submit", _c("SKIPPED — no --live flag, 'Yadda saxla' not clicked",
                           _C.YELLOW))
        # Mirror the live path exactly: nothing was saved, so the run must not
        # report an upload. A simulation that scores differently from the thing it
        # simulates is worse than no simulation.
        return "FILLED_NOT_SAVED"
    _sim("get_by_role('button', name='Yadda saxla').click()")
    _sim(f"wait_for_url({PROJECTS_PATH}) — the portal's only save confirmation; it "
         f"shows no toast")
    _info("next", _c("the following report re-enters via the 'Yeni sənəd' tab",
                     _C.GREY))
    _info("submit", _c("SIMULATED SAVE", _C.GREEN))
    return "SIMULATED_OK"


def _re(pattern: str):
    """A compiled case-insensitive regex for Playwright name/label matching."""
    import re
    return re.compile(pattern, re.IGNORECASE)


def _escape(literal: str) -> str:
    """Quote a literal so it can be dropped into a name regex verbatim."""
    import re
    return re.escape(literal)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _report_sidecars(out: Path) -> list[Path]:
    """Every compiled report sidecar under ``out`` — which is not every .json under it.

    Matched on the exporter's own filename contract
    (``compiled_monthly_report_<tokens>_<MON>_<YYYY>.json``, see naming.default_output)
    rather than "any .json", so the sweep never mistakes a system file for a report to
    file to a government portal. This excludes, by construction:

    * ``upload_status.json`` — a JSON ARRAY audit log (_write_upload_status), which a
      list-blind ``.get()`` downstream would crash on,
    * ``portal_form_probe.json`` — --probe's dump, rewritten every run,
    * anything under ``output/failures/`` and any hidden dotfile.

    The former one-off ``PROBE_FILENAME`` skip is now redundant — the prefix match
    already drops it.
    """
    return [p for p in out.rglob("compiled_monthly_report_*.json")
            if not p.name.startswith(".")]


def _newest_report_json() -> Path | None:
    """Return the most recently modified ``output/**/*.json`` sidecar, or None."""
    files = sorted(_report_sidecars(_ROOT / "output"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


class _ExplicitLimit(argparse.Action):
    """Store --limit and remember that the operator, not the default, set it.

    ``_effective_limit`` lifts the one-report cap for an interactive live run, and
    that lift must never overrule a cap that was asked for out loud. argparse cannot
    tell ``--limit 1`` from the default 1, so the flag being present is recorded here.
    """

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.limit_explicit = True


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="uploader",
        description="Upload compiled monthly reports to the E-Keyfiyyet portal.")
    p.add_argument("--dry-run", action="store_true",
                   help="Print a colored step-by-step simulation; launch NO browser.")
    p.add_argument("--report", metavar="JSON",
                   help="Path to the compiled report .json sidecar "
                        "(default: newest output/**/*.json).")
    p.add_argument("--all", action="store_true",
                   help="Upload every output/**/*.json sidecar (resumable; already-"
                        "uploaded reports are skipped). Combine with the filters below.")
    p.add_argument("--pdf", metavar="PDF",
                   help="Path to the PDF to upload (default: the report's .pdf twin). "
                        "Single-report mode only.")
    p.add_argument("--method", metavar="TOKEN",
                   help="--all filter: only reports whose filename carries this method "
                        "token (e.g. MT, UT, DP). Case-insensitive.")
    p.add_argument("--client", metavar="CODE",
                   help="--all filter: only reports for this client code (e.g. KHF).")
    p.add_argument("--month", metavar="MON_YYYY",
                   help="--all filter: only reports for this month token (e.g. FEB_2026).")
    p.add_argument("--limit", metavar="N", type=int, default=MAX_REPORTS_PER_RUN,
                   action=_ExplicitLimit,
                   help=f"--all: process at most N reports in one run "
                        f"(default {MAX_REPORTS_PER_RUN}). Chaining past the first "
                        f"report needs --live: without it the filled form is left on "
                        f"screen for review, and the next report would overwrite it. "
                        f"An interactive live run lifts the default cap by itself "
                        f"(see --interactive), and so does an unattended "
                        f"--live --all --no-interactive batch; passing --limit still "
                        f"pins it.")
    p.add_argument("--force", action="store_true",
                   help="Upload even if the ledger flags the report as interrupted "
                        "mid-submit. Only after verifying on the portal that it is "
                        "genuinely absent — this can create a duplicate.")
    p.add_argument("--ledger", metavar="JSON",
                   help="Override the upload-state ledger path "
                        "(default: .upload_state.json; .upload_state.dryrun.json "
                        "under --dry-run).")
    p.add_argument("--reset", metavar="PDF", nargs="+",
                   help="Forget the upload state of these report PDFs and exit, so a "
                        "later run re-uploads them. (Equivalent to deleting their keys "
                        "from the ledger by hand.)")
    p.add_argument("--probe", action="store_true",
                   help="Open the appeal form, pick the document type so its fields "
                        "render, and dump every control to "
                        "output/portal_form_probe.json, then exit. Fills nothing, "
                        "saves nothing. Run this to map real selectors.")
    p.add_argument("--probe-chips", nargs="?", const="", default=None, metavar="A,B",
                   help="--probe, then tag standards in the 'inspeksiya:' box and read "
                        "the chips back into output/portal_form_probe.json "
                        "(chip_readback). Comma-separated option texts; without a "
                        "value, the first two PORTAL_STANDARDS the live listbox "
                        "offers. The form is then reloaded. Fills nothing else, "
                        "attaches nothing, never clicks 'Yadda saxla'.")
    p.add_argument("--live", action="store_true",
                   help="Actually click 'Yadda saxla' and save a draft appeal on the "
                        "portal. WITHOUT this flag the form is filled but never "
                        "saved. Requires portal.director to be filled in "
                        "config/settings.yaml. Never clicks 'E-imza ilə təsdiqlə'.")
    p.add_argument("--url", default=None,
                   help="Override the portal URL (default: portal.url in "
                        "config/settings.yaml).")
    p.add_argument("--slow", metavar="MS", type=int, default=0,
                   help="Slow-motion debug: pause this many milliseconds before every "
                        "browser action so you can watch the form fill (e.g. 2000). "
                        "Default 0 (full speed). Ignored under --dry-run (no browser).")
    p.add_argument("--interactive", action="store_true",
                   help="Ask in the terminal before every 'Yadda saxla': inspect the "
                        "filled form on screen, then [Enter]/y to save and move on, "
                        "'s' to skip this report, 'q' to end the run. Already the "
                        "default for a --live --all batch on a terminal. Needs --live "
                        "(a run that cannot save has nothing to confirm).")
    p.add_argument("--no-interactive", action="store_true",
                   help="Never prompt — save every report the ledger selected without "
                        "asking. For unattended and GUI-driven runs. Also the automatic "
                        "behaviour when stdin is not a terminal. With --live --all this "
                        "lifts the default one-report cap and walks the whole queue in "
                        "one continuous loop (--limit still pins it).")
    # Explicitness is tracked, not inferred: --limit 1 and the default 1 mean
    # different things to an interactive run (a pinned cap vs. an unset one).
    p.set_defaults(limit_explicit=False)
    return p


def _ledger_path(args) -> Path:
    """Where upload state lives.

    A dry run gets its OWN ledger: simulating a flow must never be able to mark a
    real report as uploaded and thereby suppress its real upload later.
    """
    if args.ledger:
        return Path(args.ledger)
    return _ROOT / (".upload_state.dryrun.json" if args.dry_run
                    else ".upload_state.json")


def _ledger_key(pdf_path: Path) -> str:
    """The ledger's identity for one report: its project-root-relative POSIX path.

    Stable across runs, unique per compiled report (one PDF = one portal
    submission), and readable enough that an operator can find and delete the right
    key by eye. Paths outside the project fall back to the absolute path.
    """
    try:
        return pdf_path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return pdf_path.resolve().as_posix()


def _resolve_paths(args) -> tuple[Path, Path]:
    """Resolve the report JSON and its PDF twin from CLI args / defaults."""
    if args.report:
        report_json = Path(args.report)
    else:
        report_json = _newest_report_json()
        if report_json is None:
            raise SystemExit(
                "No --report given and no output/**/*.json found. "
                "Run `python main.py` first, or pass --report <file>.json")
    pdf_path = Path(args.pdf) if args.pdf else report_json.with_suffix(".pdf")
    return report_json, pdf_path


def _sidecar_client_code(sidecar: Path) -> str:
    """Resolve a sidecar's registry client code, or ``""`` when it cannot be read.

    The sidecar carries ``client_name`` (the display name), not the code, so the
    name is put back through the registry's own alias resolution — the same call
    the compiler used to decide the client in the first place.

    Deliberately silent on a malformed file: deciding whether to *consider* a
    report is not the place to fail a batch. A broken sidecar still reaches
    _run_batch, which reports it properly as SKIP (invalid).
    """
    try:
        with open(sidecar, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return ""
    # A non-dict JSON (e.g. an array log that slipped into the tree) is not a sidecar;
    # deciding whether to CONSIDER a report is not the place to crash on it.
    if not isinstance(data, dict):
        return ""
    name = str(data.get("client_name", "") or "")
    code, _display = resolve_client_by_field({"client": name}, "", _settings())
    return code


def _sidecar_period_start(sidecar: Path) -> _dt.date | None:
    """First day of a sidecar's reporting month, or ``None`` when it cannot be read.

    Two sources, in order of authority:

    1. the sidecar's ``reporting_period`` — Azerbaijani, as naming.reporting_period()
       wrote it ("Dekabr 2025"), read back through the same table month_bounds uses;
    2. the filename's month token (``..._DEC_2025.json``), for a sidecar that is
       unreadable or predates the field.

    ``None`` means undatable, and an undatable report is NOT skipped by the date
    gate: proving a report is historical is what the gate is for, and a sidecar this
    broken is already refused by the client allowlist above (its client_code cannot
    be read either) and reported as SKIP (invalid) by _run_batch if it gets that far.
    """
    try:
        with open(sidecar, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        data = None
    if isinstance(data, dict):
        parts = str(data.get("reporting_period", "") or "").split()
        if len(parts) == 2:
            month = _AZ_MONTH_NUMBER.get(parts[0].casefold())
            if month and len(parts[1]) == 4 and parts[1].isdigit():
                return _dt.date(int(parts[1]), month, 1)
    tokens = sidecar.stem.rsplit("_", 2)
    if len(tokens) == 3:
        month = _ABBR_MONTH_NUMBER.get(tokens[1].casefold())
        if month and len(tokens[2]) == 4 and tokens[2].isdigit():
            return _dt.date(int(tokens[2]), month, 1)
    return None


def _sidecar_volume(sidecar: Path) -> tuple[str, int, int] | None:
    """``(method, reports, items)`` from a sidecar, or ``None`` when it cannot gate.

    Returns ``None`` on a malformed file OR a legacy sidecar written before the
    volume feature (no ``source_report_count``): such a report is simply NOT
    pruned — deciding whether to *consider* a report is not the place to fail, and
    compilation is the authoritative gate anyway. The counts read here are the very
    fields the exporter mirrors from the compiled report, so the upload floor sees
    the same numbers ``main.py`` filtered on.
    """
    try:
        with open(sidecar, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    # Non-dict JSON cannot gate a volume decision — treat it as "cannot gate", like a
    # legacy sidecar, and let compilation stay the authoritative floor.
    if not isinstance(data, dict) or "source_report_count" not in data:
        return None
    method = str(data.get("ndt_method", "") or "")
    reports = int(data.get("source_report_count", 0) or 0)
    items = int(data.get("total_records", len(data.get("items_table", []))) or 0)
    return method, reports, items


def _resolve_targets(args) -> list[tuple[Path, Path]]:
    """The (sidecar, pdf) pairs this run should consider, in a stable order.

    ``--all`` sweeps the output tree; otherwise it is the single --report/--pdf pair.
    The user's filters match against the filename, which already encodes
    method/client/month (compiled_monthly_report_MT_KHF_FEB_2026.json). Only the
    client checks open the sidecar, because those are safety rules rather than
    preferences and must read the same field the payload is built from.

    The client gate applies to BOTH paths. A hand-picked ``--report`` is not a
    smaller version of the sweep — it is the one invocation an operator reaches for
    under time pressure, so naming a file explicitly must not be a way around the
    allowlist. The sweep SKIPS a refused report (the other targets are still worth
    filing); the single-report form has nothing left to do, so it exits.

    The PORTAL_UPLOAD_CUTOFF date gate applies on both paths too, and first: a
    report for a month before December 2025 is refused as SKIPPED_PRE_DEC_2025
    before any other check, whoever its client is. Without it, ``--all`` swept the
    whole back catalogue (227 sidecars, most of them 2024 / early 2025 history).
    """
    if not args.all:
        sidecar, pdf = _resolve_paths(args)
        start = _sidecar_period_start(sidecar)
        if start is not None and start < PORTAL_UPLOAD_CUTOFF:
            raise SystemExit(
                f"{sidecar.name}: SKIPPED_PRE_DEC_2025 — Report date is prior to "
                f"December 2025 portal upload cutoff "
                f"(reporting month {start:%Y-%m}, cutoff "
                f"{PORTAL_UPLOAD_CUTOFF:%Y-%m-%d}).\nOnly reports dated December "
                f"2025 or later are eligible for portal upload.")
        code = _sidecar_client_code(sidecar)
        if not is_uploadable_client(code, _settings()):
            raise SystemExit(
                f"{sidecar.name}: client {code or '<unresolved>'} is not cleared for "
                f"upload.\nOnly the clients listed in settings.yaml `approved_clients` "
                f"may be filed (retired clients are refused too).")
        return [(sidecar, pdf)]

    if args.pdf:
        raise SystemExit("--pdf applies to a single report; it cannot be used with --all.")

    out = _ROOT / "output"
    if not out.is_dir():
        raise SystemExit(f"No output directory to sweep: {out}\n"
                         f"Run `python main.py` first.")

    targets: list[tuple[Path, Path]] = []
    excluded: list[str] = []
    unapproved: list[str] = []
    low_volume: list[str] = []
    pre_cutoff: list[str] = []
    for sidecar in sorted(_report_sidecars(out)):
        name = sidecar.name.casefold()
        # --client / --month stay filename tests: ADR-004 kept both tokens in the
        # name. --method cannot — the name carries no method any more, and one
        # document holds several — so it asks the sidecar which methods are
        # actually inside and keeps the document when this one is among them.
        if args.method and not _sidecar_has_method(sidecar, args.method):
            continue
        if args.client and f"_{args.client.casefold()}_" not in name:
            continue
        if args.month and args.month.casefold() not in name:
            continue
        # Portal upload date gate (PORTAL_UPLOAD_CUTOFF): a report for a month before
        # December 2025 is history and is dropped here, before any sidecar-reading
        # gate below. This is what keeps the sweep off the 2024 / early-2025 back
        # catalogue that output/ still holds.
        start = _sidecar_period_start(sidecar)
        if start is not None and start < PORTAL_UPLOAD_CUTOFF:
            pre_cutoff.append(f"{sidecar.name} ({start:%Y-%m})")
            continue
        # A retired client (settings.yaml excluded_clients) is never filed, even if a
        # report compiled BEFORE it was retired is still sitting in output/. The
        # pipeline stopped producing these; this stops the sweep from sending the
        # leftovers. The sidecar's own client_code is read rather than the filename
        # token, because the sidecar is what the payload is built from.
        code = _sidecar_client_code(sidecar)
        if code and (is_excluded_client(code, _settings())
                     or not is_active_client(code, _settings())):
            excluded.append(f"{sidecar.name} ({code})")
            continue
        # STRICT allowlist (settings.yaml approved_clients): only the approved live
        # clients may be filed. Distinct from the retire checks above, which default
        # to allow — this refuses any code NOT on the list, including an unregistered
        # one, closing the default-allow hole. Off when the list is empty. Reads the
        # sidecar's own client_code, like the retire gate. Deliberately NOT guarded by
        # `if code`: while the allowlist is populated, a sidecar whose client cannot be
        # read at all is refused rather than filed on a guess.
        if not is_uploadable_client(code, _settings()):
            unapproved.append(f"{sidecar.name} ({code or '<unresolved>'})")
            continue
        # Dynamic volume floor (settings.yaml volume_thresholds): the same rule the
        # compiler applied, re-checked here so a sidecar compiled BEFORE the floor
        # was set is still pruned. Opt-in/off by default; a legacy sidecar without
        # the count field returns None and is left untouched.
        vol = _sidecar_volume(sidecar)
        if vol and not meets_volume(vol[0], vol[1], vol[2], _settings()):
            low_volume.append(f"{sidecar.name} ({vol[1]} report(s), {vol[2]} item(s))")
            continue
        targets.append((sidecar, sidecar.with_suffix(".pdf")))

    if pre_cutoff:
        # Named in full only while the list is short. The back catalogue runs to
        # hundreds of sidecars, and printing every one of them buries the gates
        # below it — the ones an operator actually has to act on.
        shown = ", ".join(pre_cutoff[:8])
        if len(pre_cutoff) > 8:
            shown += f", … and {len(pre_cutoff) - 8} more"
        _info("SKIPPED_PRE_DEC_2025",
              _c(f"{len(pre_cutoff)} report(s) skipped: report date is prior to the "
                 f"December 2025 portal upload cutoff: {shown}", _C.YELLOW))
    if excluded:
        _info("excluded", _c(f"{len(excluded)} stale report(s) for retired clients "
                             f"skipped: {', '.join(excluded)}", _C.YELLOW))
    if unapproved:
        _info("unapproved", _c(f"{len(unapproved)} report(s) for non-approved clients "
                               f"skipped: {', '.join(unapproved)}", _C.YELLOW))
    if low_volume:
        _info("skipped", _c(f"{len(low_volume)} low-volume report(s) skipped: "
                            f"{', '.join(low_volume)}", _C.YELLOW))

    if not targets:
        if pre_cutoff:
            raise SystemExit(
                f"No sidecars matched: all {len(pre_cutoff)} candidate(s) are dated "
                f"before the December 2025 portal upload cutoff "
                f"(SKIPPED_PRE_DEC_2025). Only reports dated December 2025 or later "
                f"are eligible for portal upload.")
        raise SystemExit("No sidecars matched. Check --method / --client / --month.")
    return targets


def _do_reset(args, ledger: UploadLedger) -> int:
    """Handle --reset: forget the given reports' upload state, then exit."""
    for raw in args.reset:
        key = _ledger_key(Path(raw))
        if ledger.reset(key):
            _info("reset", _c(f"{key} — will re-upload on the next run", _C.GREEN))
        else:
            _info("reset", _c(f"{key} — no ledger entry (nothing to do)", _C.YELLOW))
    return 0


def _capture_failure(page, serial: str) -> Path | None:
    """Screenshot + DOM dump on a failed fill, so the next attempt has evidence.

    A bare traceback against a form nobody can open offline says nothing about WHY
    a locator missed. The screenshot shows what the page actually looked like.
    Best-effort: a capture failure must never mask the original error.
    """
    if _is_dry(page):
        return None
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    base = _ROOT / "output" / "failures" / f"{serial or 'unknown'}_{stamp}"
    try:
        base.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
        return base
    except Exception:
        return None


def _write_upload_status(key: str, payload: dict, json_data: dict) -> Path:
    """Append a SUCCESS record to output/upload_status.json (the audit artifact).

    Deliberately NOT a second source of truth: .upload_state.json (upload_ledger)
    still owns idempotency. This file exists so a human can read what was filed
    without decoding the ledger's hashes.
    """
    path = _ROOT / "output" / "upload_status.json"
    records = []
    if path.is_file():
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                records = []
        except json.JSONDecodeError:
            records = []   # a corrupt audit file must not block the audit trail
    records.append({
        "report_key": key,
        "serial": payload["serial"],
        "status": "SUCCESS",
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "client_name": json_data.get("client_name", ""),
        "reporting_period": json_data.get("reporting_period", ""),
        "result": payload["result"],
    })
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


@dataclass
class _Stats:
    """Outcome tally for one run — drives the summary and the exit code."""

    uploaded: int = 0
    skipped: int = 0
    blocked: int = 0
    failed: int = 0
    aborted: bool = False
    # The operator answered 'q' at a confirmation prompt. Not a failure — a run that
    # ended exactly where its operator asked it to — so it never colours the exit code.
    quit_requested: bool = False
    not_reached: int = 0   # pending reports the run's cap left untouched
    limit: int = MAX_REPORTS_PER_RUN   # the cap that produced not_reached
    # Reports whose form was actually driven but deliberately not saved. Distinct
    # from `skipped`, which also counts reports the ledger never touched: Review
    # Mode holds the browser open on this count, and a ledger skip leaves an empty
    # form on screen with nothing to review.
    filled: int = 0
    # (report name, standard the portal does not offer) for every report this run
    # refused to file. NOT a correction list — there is nothing on the portal to
    # correct, because nothing was filed. It is the list of standards the portal has
    # to add before these reports can be sent at all.
    unmatched: list[tuple[str, str]] = field(default_factory=list)
    # Report names that cite no standard at all, so the portal would refuse them. Kept
    # apart from `unmatched`: that list is a portal backlog nobody here can clear, this
    # one is actionable today — the standard is missing from the source document.
    no_standard: list[str] = field(default_factory=list)
    # What ONE unmatched standard actually cost, per refused document:
    # ``(report name, rows in the document, [(standard, methods, rows), ...])``.
    # ADR-004 merged every method of a client-month into one document, so a single
    # standard the portal does not list now holds back the WHOLE month for that
    # client rather than one method's sheet. The gate is unchanged — nothing is
    # substituted, nothing is part-filed — but the blast radius has to be visible,
    # or an operator cannot tell a 3-row problem from a 30-row one.
    blocked_standards: list[tuple[str, int, list[tuple[str, str, int]]]] = field(
        default_factory=list)
    # (report name, standard) left OFF a report that WAS filed, under
    # portal.standard_policy: any (ADR-010). Empty under the default "all".
    policy_skipped: list[tuple[str, str]] = field(default_factory=list)
    # Document IDs refused by portal.hold_documents before the batch began. Neither
    # skipped nor failed: the operator holds them while their sources are fixed.
    held: list[str] = field(default_factory=list)
    # Document IDs refused by portal.upload_closed_months_only before the batch began:
    # their month has not ended. Neither skipped nor failed.
    not_yet: list[str] = field(default_factory=list)


def _interactive_enabled(args) -> bool:
    """Whether this run asks the operator before every save.

    Five conditions, each of which alone makes the prompt wrong rather than merely
    unwanted:

    * ``--no-interactive`` — asked for silence out loud.
    * no ``--live`` — nothing is ever saved, so there is no decision to take.
    * ``--dry-run`` — no browser, so there is nothing on screen to inspect.
    * neither ``--interactive`` nor ``--all`` — a single fixed report is the one case
      where the operator already chose it by name on the command line.
    * stdin is not a terminal. This one is load-bearing: the GUI runs this script as
      a child process with piped stdio and passes ``--live --all``, so a prompt taken
      by default there would block on a question nobody can see or answer.
    """
    if args.no_interactive:
        return False
    if not args.live or args.dry_run:
        return False
    if not (args.interactive or args.all):
        return False
    return bool(sys.stdin.isatty())


def _why_not_interactive(args) -> str:
    """Why an explicit ``--interactive`` is not taking effect. One line, for the banner."""
    if args.no_interactive:
        return "DISABLED — --no-interactive was passed too, and silence wins"
    if args.dry_run:
        return "DISABLED — a dry run opens no browser, so there is nothing to inspect"
    if not args.live:
        return ("DISABLED — without --live nothing is ever saved, so there is no save "
                "to confirm")
    return ("DISABLED — stdin is not a terminal (piped or GUI-launched), so the prompt "
            "could not be answered. Run it from a terminal to confirm each save.")


def _confirm_before_save(serial: str, client: str) -> str:
    """Ask the operator what to do with the form now filled on screen.

    Returns ``"save"``, ``"skip"`` or ``"quit"`` — never anything else, and never
    raises. Unrecognised input re-asks rather than guessing, because every one of the
    three answers is irreversible in its own way: a wrong "save" files a real appeal,
    a wrong "skip" silently omits a month's report.

    Enter alone means save. It is the common answer by a wide margin (the operator is
    looking at a form they asked this run to fill), and making the frequent answer the
    cheapest keystroke is what makes a 40-report batch bearable.

    A closed stdin and Ctrl-C both mean *quit*, not save: both say there is no longer
    an operator at the terminal, and the entire point of this gate is that no draft is
    filed without one. Quitting leaves every remaining report untouched and re-runnable.

    Does NOT check ``isatty`` — see :func:`_interactive_enabled`, which decides whether
    this is called at all. Keeping the check there leaves this function driveable from
    a test with a substituted stdin.
    """
    rule = _c("-" * 70, _C.CYAN)
    while True:
        print()
        print(rule)
        print(_c(f"[INTERACTIVE CONFIRMATION] Report {serial or '?'} "
                 f"({client or '?'}) form filled on screen.", _C.BOLD, _C.CYAN))
        print(_c("Inspect the open browser window. Choose action:", _C.CYAN))
        print(_c("  [Enter] or 'y' : SAVE draft appeal & proceed to next report",
                 _C.GREEN))
        print(_c("  's'            : SKIP this report (do not save)", _C.YELLOW))
        print(_c("  'q'            : QUIT batch upload session", _C.RED))
        print(rule)
        try:
            answer = input(_c("Your choice [Y/s/q]: ", _C.BOLD)).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            _info("operator", _c("no answer possible (stdin closed / interrupted) — "
                                 "treating it as QUIT; nothing was saved", _C.YELLOW))
            return "quit"

        if answer in ("", "y", "yes"):
            return "save"
        if answer in ("s", "skip"):
            return "skip"
        if answer in ("q", "quit"):
            return "quit"
        _info("operator", _c(f"{answer!r} is not one of [Enter]/y, s, q — asking again",
                             _C.YELLOW))


def _reset_appeal_form(page, timeout_ms: int = 15000) -> None:
    """Throw away a filled-but-unsaved form so the next report starts clean.

    Only a SAVE leaves the portal on Layihələr; an operator SKIP leaves the browser
    sitting on the form it just declined, where ``_ensure_on_appeal_form`` is a no-op
    and the next report would type on top of it. That is not merely untidy: the
    standards box is a MUI multiselect where clicking a tagged option REMOVES it, so
    two reports sharing a standard would end up filing an appeal that names neither —
    and the declined report's PDF would still be attached.

    A reload is the cheapest true reset: the URL is already the appeal form, and the
    React state that holds every filled value does not survive it.
    """
    page.reload()
    page.wait_for_url(is_appeal_url, timeout=timeout_ms)
    _info("form", _c("reloaded — the skipped report's values are gone", _C.GREY))


def _effective_limit(args, total: int | None = None) -> int:
    """How many reports this run may actually process.

    ``--limit`` is honoured only when the run can SAVE. A fill-only run ends with
    the form filled and left on screen for the operator to read (that is its whole
    point); opening the next report would type straight over the thing they were
    asked to check. So a run without ``--live`` caps at one, whatever --limit says.

    Two kinds of run drop the default cap instead of enforcing it, both because the
    operator has already answered the question the cap exists to ask.
    ``MAX_REPORTS_PER_RUN = 1`` stops a bad selector map from filing a hundred appeals
    before anyone reads the screen, so the lift needs a substitute brake:

    * an INTERACTIVE run — a human answering for every single save is a strictly
      stronger version of the same brake.
    * ``--live --all --no-interactive`` — the unattended batch. The substitute brake is
      that the flag combination cannot be reached by accident: ``--no-interactive`` is
      typed by an operator who means "walk the whole queue without asking me", and
      saying it while also asking for one report would be a contradiction. Gated on the
      FLAG, not on ``not _interactive_enabled(...)`` — the prompt also disables itself
      when stdin is a pipe, and the GUI launches this script exactly that way with
      ``--live --all``. Inferring the lift from silence would turn every GUI run into a
      full-queue batch nobody asked for.

    Either way the lift needs the caller to know how many reports matched (``total``).
    An explicit ``--limit`` still wins: a cap asked for out loud is never overruled.
    """
    if not args.live:
        return 1
    if (total is not None and not getattr(args, "limit_explicit", False)
            and (_interactive_enabled(args) or args.no_interactive)):
        return total
    return args.limit


def _run_batch(page, targets: list[tuple[Path, Path]], args, ledger: UploadLedger,
               portal_cfg: dict) -> _Stats:
    """Consider every target, upload the ones the ledger says need it.

    The ledger is consulted BEFORE the report is touched and checkpointed twice
    around every submit (intent, then outcome). That ordering is what makes an
    interrupted batch resumable rather than ambiguous.

    Stops after :func:`_effective_limit` reports are processed, however many
    matched. Between reports the portal redirects to Layihələr after each save;
    the next iteration re-enters the form through the "Yeni sənəd" tab
    (``_ensure_on_appeal_form``), so the loop needs no navigation of its own — with
    one exception, the operator SKIP, which never leaves the form (see
    ``_reset_appeal_form``).

    Under ``--interactive`` the loop pauses on every filled form and asks. That is
    what lets one process walk a whole month's reports: the browser and the portal
    session stay up across all of them, and only the decision is per-report.
    """
    total = len(targets)
    limit = _effective_limit(args, total)
    interactive = _interactive_enabled(args)
    stats = _Stats(limit=limit)
    # Counts reports whose FORM WAS DRIVEN, not reports saved. Filling is the
    # expensive, risky part: a --live-less run against a real browser would
    # otherwise walk every pending report and type into 100+ government forms
    # before anyone could read the first one.
    processed = 0

    for index, (report_json, pdf_path) in enumerate(targets, start=1):
        if processed >= limit:
            # Everything from here is still pending — count it so the summary can
            # say so out loud. A batch that quietly stopped early looks identical
            # to a batch that finished, and that is how reports get forgotten.
            stats.not_reached = total - index + 1
            break

        key = _ledger_key(pdf_path)
        label = _c(f"[{index}/{total}]", _C.BOLD, _C.CYAN)

        # A malformed sidecar is this report's problem, not the batch's: flag it and
        # keep going (graceful partial failure).
        try:
            data = load_report_json(report_json)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            print(f"  {label} {_c('SKIP (invalid)', _C.RED)} {key}")
            _info("reason", _c(str(exc), _C.RED))
            stats.failed += 1
            continue

        content_hash = hash_report(report_json, pdf_path)
        action, reason = ledger.decide(key, content_hash, force=args.force)

        if action is Action.SKIP:
            print(f"  {label} {_c('SKIP', _C.GREY)} {key} {_c(f'({reason})', _C.GREY)}")
            stats.skipped += 1
            continue

        if action is Action.BLOCKED:
            print(f"  {label} {_c('BLOCKED', _C.BOLD, _C.RED)} {key}")
            _info("reason", _c(reason, _C.YELLOW))
            stats.blocked += 1
            continue

        print(f"  {label} {_c('UPLOAD', _C.BOLD, _C.GREEN)} {key} "
              f"{_c(f'({reason})', _C.GREY)}")
        _info("loaded", _c(f"{data.get('client_name','?')} · "
                           f"{data.get('ndt_method','?')} · "
                           f"{data.get('reporting_period','?')} · "
                           f"{len(data.get('items_table', []))} record(s)", _C.CYAN))
        serial = data.get("report_serial_no", "")

        # CHECKPOINT 1 — announce the intent before the side effect. If the process
        # dies during the submit below, this is the record that tells the next run
        # the outcome is unknown, instead of letting it duplicate the row.
        #
        # ONLY when the run can actually save. Filling a form changes nothing on the
        # portal, so a fill-only run has no side effect to checkpoint — and writing
        # here anyway would be destructive: rolling the intent back afterwards would
        # erase whatever the ledger already knew about a previously-uploaded report.
        #
        # Snapshotted first so an operator who declines this report at the prompt
        # below can be given back the exact ledger they started with — including a
        # previous UPLOADED entry that a content change had re-queued.
        prior = ledger.get(key)
        if args.live:
            ledger.mark_in_progress(key, content_hash, serial)
        processed += 1
        # Bound to THIS report, so the prompt can name what it is asking about.
        confirm = None
        if interactive:
            def confirm(_serial=serial, _client=data.get("client_name", "")) -> str:
                return _confirm_before_save(_serial, _client)
        try:
            outcome = upload_report(page, pdf_path, data, portal_cfg, live=args.live,
                                    confirm=confirm)
        except Exception as exc:                      # noqa: BLE001 — see below
            # Drained even on failure: a report whose standards were rejected and that
            # THEN died on some later field must still name them, or the operator has
            # no way to see why it would not have filed. See the note on _UNMATCHED.
            stats.unmatched.extend((pdf_path.stem, s) for s in _UNMATCHED)
            # Abort the whole batch on the first upload failure. A dropped
            # connection would fail every remaining report too, and each one would
            # be left flagged IN_PROGRESS — turning one ambiguous report into ten.
            # Stopping here leaves the untouched reports clean for the next run.
            print(f"        {_c('✖ upload failed', _C.BOLD, _C.RED)}: {exc}")
            # The full traceback, not just the message: this is the one place that
            # knows WHICH field the fill stopped on, and in fill-only mode the
            # operator is about to look at the browser it stopped in.
            _print_red_traceback(exc)
            artifact = _capture_failure(page, serial)
            if artifact:
                _info("artifacts", _c(f"{artifact.with_suffix('.png')} (+ .html)", _C.CYAN))
            if args.live:
                _info("state", _c(f"{key} left IN_PROGRESS — verify on the portal "
                                  f"before re-running (use --force to send it anyway)",
                                  _C.YELLOW))
            else:
                _info("state", _c(f"{key} unchanged — the fill failed before anything "
                                  f"could be saved", _C.GREY))
            stats.failed += 1
            stats.aborted = True
            break

        stats.unmatched.extend((pdf_path.stem, s) for s in _UNMATCHED)
        if outcome not in ("SKIPPED_UNMATCHED_STANDARD", "SKIPPED_EMPTY_STANDARD"):
            stats.policy_skipped.extend((pdf_path.stem, s) for s in _POLICY_SKIPPED)

        if outcome == "SKIPPED_UNMATCHED_STANDARD":
            # The portal cannot name one of this report's standards, so it was not
            # filed. CHECKPOINT 1 announced an intent that never happened — roll it
            # back, or the report would be BLOCKED as interrupted on the next run over
            # a submit that never occurred.
            #
            # Nothing durable is written about the skip ON PURPOSE: the report stays
            # pending, is re-offered by every future run, and uploads itself the day
            # the portal lists the standard. Not counted in `filled` either — the
            # pre-flight returns before anything is typed, and the live backstop
            # reloads the form away, so there is nothing on screen to review.
            ledger.restore(key, prior)
            stats.skipped += 1
            # What the refusal actually held back. Read off the same sidecar the
            # gate refused, so the two can never disagree.
            blocked = _blocked_standard_detail(data, _UNMATCHED)
            if blocked:
                stats.blocked_standards.append(
                    (pdf_path.stem, len(data.get("items_table", []) or []), blocked))
            continue

        if outcome == "SKIPPED_EMPTY_STANDARD":
            # The report names no normative document, so the portal would refuse the
            # appeal. Same rollback and the same silence as the unmatched case above:
            # CHECKPOINT 1 announced an intent that never happened, and recording the
            # skip would only need undoing. The report stays pending and files itself
            # once its source document carries a standard — which changes its content
            # hash too, so the ledger re-offers it either way.
            ledger.restore(key, prior)
            stats.skipped += 1
            stats.no_standard.append(pdf_path.stem)
            continue

        if outcome == "FILLED_NOT_SAVED":
            # Nothing reached the portal and nothing was checkpointed, so there is
            # no state to undo. The form is left filled in the open window for review.
            stats.skipped += 1
            stats.filled += 1
            continue

        if outcome in ("SKIPPED_BY_OPERATOR", "QUIT_BY_OPERATOR"):
            # The operator looked at the filled form and declined it. Nothing was
            # clicked, so CHECKPOINT 1 announced an intent that never happened —
            # roll it back rather than leave the report flagged IN_PROGRESS, which
            # would BLOCK it on the next run over a submit that never occurred.
            ledger.restore(key, prior)
            stats.skipped += 1
            stats.filled += 1
            if outcome == "QUIT_BY_OPERATOR":
                # Everything after this one is untouched and still pending. Counted,
                # not silently dropped: a batch that stopped early must say so.
                stats.quit_requested = True
                stats.not_reached = total - index
                break
            # Only a SAVE redirects away from the form. A skip leaves it filled on
            # screen, and the next report must not be typed on top of it.
            _reset_appeal_form(page)
            continue

        # CHECKPOINT 2 — confirmed. From here the report is idempotently skipped.
        ledger.mark_uploaded(key, content_hash, serial)
        if not _is_dry(page):
            status_path = _write_upload_status(
                key, build_portal_payload(data, portal_cfg), data)
            _info("status", _c(f"SUCCESS recorded in {status_path}", _C.GREEN))
        stats.uploaded += 1

    return stats


def _print_summary(stats: _Stats, ledger: UploadLedger) -> None:
    parts = [
        _c(f"{stats.uploaded} uploaded", _C.GREEN if stats.uploaded else _C.GREY),
        _c(f"{stats.skipped} skipped", _C.GREY),
        _c(f"{stats.blocked} blocked", _C.RED if stats.blocked else _C.GREY),
        _c(f"{stats.failed} failed", _C.RED if stats.failed else _C.GREY),
    ]
    print()
    _info("result", "  ".join(parts))
    _info("ledger", f"{ledger.path} ({len(ledger)} report(s) tracked)")
    if stats.held:
        _info("held", _c(f"{len(stats.held)} document(s) held by operator "
                         f"(portal.hold_documents), not filed: "
                         f"{', '.join(stats.held)}", _C.YELLOW))
    if stats.not_yet:
        _info("not yet", _c(f"{len(stats.not_yet)} document(s) for a month not yet "
                            f"closed (portal.upload_closed_months_only), not filed: "
                            f"{', '.join(stats.not_yet)}", _C.YELLOW))
    if stats.quit_requested:
        _info("stopped", _c(f"ended at the operator's request — "
                            f"{stats.not_reached} report(s) were never offered. "
                            f"Nothing was left half-done; re-run to continue.",
                            _C.YELLOW))
    elif stats.not_reached:
        _info("limit", _c(f"{stats.not_reached} further pending report(s) NOT sent — "
                          f"{stats.limit}-report limit for this run. Re-run to "
                          f"continue, or raise --limit.", _C.YELLOW))
    if stats.aborted:
        _info("aborted", _c("batch stopped at the first failure — re-run to resume "
                            "from where it left off", _C.YELLOW))
    _print_unmatched_list(stats)
    _print_blocked_standards_list(stats)
    _print_no_standard_list(stats)
    _print_policy_skipped_list(stats)


def _print_policy_skipped_list(stats: _Stats) -> None:
    """Standards left off reports that went through under ``standard_policy: any``.

    Prints nothing under the default "all" (the list is empty), so that run's output
    is unchanged. These reports were NOT refused — they are absent from the "NOT
    filed" list above — but each appeal names fewer documents than the inspection was
    judged by, and the operator must be able to see which (ADR-010).
    """
    if not stats.policy_skipped:
        return
    reports = list(dict.fromkeys(name for name, _ in stats.policy_skipped))
    print()
    print(f"  standards skipped (policy any): {len(reports)} report(s) went through "
          f"naming only the standards the portal offers:")
    for name in reports:
        dropped = [s for n, s in stats.policy_skipped if n == name]
        print(f"          {name}  {dropped}")


def _print_no_standard_list(stats: _Stats) -> None:
    """Every report this run refused to file because it cites no standard at all.

    Unlike the unmatched list this one is ACTIONABLE here: the portal is not missing
    anything, the source document is. Each report listed needs a standard in its
    ``(...)`` filename group or its body, after which it uploads itself with no flag.
    """
    if not stats.no_standard:
        return
    print()
    _warn(f"{len(stats.no_standard)} report(s) NOT filed — they name no standard, and "
          f"the portal requires one. Nothing was substituted.")
    for name in stats.no_standard:
        print(f"          {_c(name, _C.GREY)}  "
              f"{_c('[no standard on any row]', _C.YELLOW)}")
    _info("fix", _c("add the standard to the source document and re-run the pipeline; "
                    "no re-run flag is needed", _C.GREY))


def _sidecar_has_method(sidecar: Path, method: str) -> bool:
    """Whether a compiled document contains rows of ``method``.

    ADR-004: one document per client-month, every NDT method inside it, so the
    filename no longer carries a method token to substring-match on. The row-level
    ``items_table[].method`` is the authority — it is the value the PDF's Üsul
    column draws — with the root ``ndt_method`` (``"DP/MPI/RT/UTM"``, or a single
    token on a pre-ADR-004 sidecar) as the fallback.

    An unreadable sidecar answers False: --method is a narrowing filter, and a
    document that cannot state its methods has not shown it belongs in the
    narrowed set. It is still offered by an unfiltered run.
    """
    wanted = str(method or "").strip().casefold()
    if not wanted:
        return True
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    tokens = {str(r.get("method", "")).strip().casefold()
              for r in data.get("items_table", []) or []
              if isinstance(r, dict)}
    tokens.discard("")
    if not tokens:
        tokens = {t.strip().casefold()
                  for t in str(data.get("ndt_method", "") or "").split("/")}
        tokens.discard("")
    return wanted in tokens


def _blocked_standard_detail(data: dict,
                             unmatched) -> list[tuple[str, str, int]]:
    """``[(standard, "UT/RT", rows), ...]`` — who inside the document blocked it.

    Pure reporting. It changes no gate and files nothing: the document was already
    refused whole by the zero-substitution rule, and this only answers "by which
    standard, from which method, at what cost in rows".

    ``unmatched`` is the run's live list of standards the portal does not offer, so
    the rows counted here are exactly the ones the gate looked at. Row methods come
    from ``items_table[].method``; a row with none is counted under ``"?"`` rather
    than dropped, because it still contributed to the refusal.
    """
    wanted = {str(s).strip() for s in unmatched if str(s).strip()}
    if not wanted:
        return []
    rows = [r for r in (data.get("items_table", []) or []) if isinstance(r, dict)]
    detail: list[tuple[str, str, int]] = []
    for standard in sorted(wanted):
        hits = [r for r in rows
                if standard in split_standards(r.get("standard"))]
        methods = unique_ordered(str(r.get("method", "")).strip() or "?"
                                 for r in hits)
        detail.append((standard, "/".join(methods), len(hits)))
    return detail


def _print_blocked_standards_list(stats: _Stats) -> None:
    """What each unmatched standard held back, in rows and methods.

    The sibling of :func:`_print_unmatched_list`, which names the standards the
    portal has to add. This one names the PRICE of each: since ADR-004 a compiled
    document is a whole client-month across every method, so one standard the
    portal does not list stops the month — not just the sheet for the method that
    cited it. Nothing here is a substitution or a partial filing; the gate is
    untouched. It exists so the operator can rank the backlog by what it costs.
    """
    if not stats.blocked_standards:
        return
    print()
    total = sum(rows for _n, rows, _d in stats.blocked_standards)
    _warn(f"{len(stats.blocked_standards)} client-month document(s) held back — "
          f"{total} row(s) in total. One unlisted standard refuses the whole "
          f"document; nothing was part-filed.")
    for name, rows, detail in stats.blocked_standards:
        print(f"          {_c(name, _C.GREY)}  "
              f"{_c(f'{rows} row(s) blocked', _C.YELLOW)}")
        for standard, methods, hits in detail:
            print(f"              {_c(standard, _C.BOLD)}  "
                  f"{_c(f'({methods}, {hits} row(s))', _C.GREY)}")


def _print_unmatched_list(stats: _Stats) -> None:
    """Every report this run refused to file, and the standard that blocked it.

    NOT a correction list — nothing was filed, so there is nothing on the portal to
    correct. It is a portal/process backlog: each distinct standard here has to appear
    in the portal's own list before its reports can be sent at all.

    Worth gathering because the per-report warning already went past during the run,
    and a long batch buries the first skip under the last.
    """
    if not stats.unmatched:
        return
    reports = {name for name, _ in stats.unmatched}
    wanted = sorted({standard for _, standard in stats.unmatched})
    print()
    _warn(f"{len(reports)} report(s) NOT filed — the portal offers no entry for "
          f"{len(wanted)} of the standard(s) they cite. Nothing was substituted.")
    for name, standard in stats.unmatched:
        print(f"          {_c(name, _C.GREY)}  {_c(standard, _C.BOLD)}  "
              f"{_c('[not offered by the portal]', _C.YELLOW)}")
    _info("needed", _c(f"{wanted} — these reports upload themselves once the portal "
                       f"lists them; no re-run flag is needed", _C.GREY))


def _tab_urls(context) -> list[str]:
    """URLs of every open tab, best-effort — a tab closing mid-read is not fatal."""
    urls = []
    for p in list(context.pages):
        try:
            urls.append(str(p.url))
        except Exception:
            continue
    return urls


def _find_appeal_page(context):
    """The first open tab we can take over — the form or the dashboard — or None.

    The portal opens the form in a NEW tab after the e-İmza login rather than
    redirecting the tab we launched, so it can be any member of ``context.pages`` —
    never assume ``pages[0]``.
    """
    for p in list(context.pages):
        try:
            if is_takeover_url(p.url):
                return p
        except Exception:
            # Tab closed between the snapshot and the read: not our tab anyway.
            continue
    return None


def _claim_appeal_page(context, page):
    """Make ``page`` the tab the run drives, and clear the idle tabs away.

    Closing the leftover login/home tabs is cosmetic, so every failure here is
    swallowed: an idle tab that refuses to close must never take down a run whose
    real target is already open and ready.
    """
    try:
        page.bring_to_front()
    except Exception:
        pass

    closed = 0
    for p in list(context.pages):
        if p is page:
            continue
        try:
            p.close()
            closed += 1
        except Exception:
            continue

    msg = f"On {page.url} — taking over this tab."
    if closed:
        msg += f" Closed {closed} idle tab(s)."
    _info("takeover", _c(msg, _C.GREEN))
    return page


def _await_takeover(context, timeout_s: int):
    """Block until a drivable tab exists, and return it.

    Drivable means the appeal form OR the e-competition dashboard, which is where
    "Tanış oldum" actually lands and which is one "Yeni sənəd" click from the form.
    Until then no locator, expectation or fill runs — a login page has neither the
    dropdown nor the tab.

    Note the split: this returns on the DASHBOARD too, so the caller must still get
    to the form before filling. _ensure_on_appeal_form does that and is_appeal_url
    proves it.

    Every tab in the context is watched, not just the one we launched: after the
    Asan İmza / e-İmza login the portal spawns the form in a new tab, so a wait
    pinned to ``pages[0]`` sits on the login page until the timeout expires.

    The wait itself is Playwright's ``wait_for_url`` keyed on real navigation (it
    fires on SPA pushState too), sliced short so a tab that appears elsewhere in
    the context is picked up by the next rescan. It is not a sleep-poll.
    """
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout

    found = _find_appeal_page(context)
    if found is not None:
        return _claim_appeal_page(context, found)

    _info("takeover", _c(
        f"Waiting up to {timeout_s}s. In the open window: log in (Asan İmza / "
        f"e-İmza) and reach {E_COMPETITION_PATH} or {APPEAL_PATH} — a new tab is "
        f"fine, every tab is watched. Nothing is typed into any form until you get "
        f"there.", _C.CYAN))

    deadline = time.monotonic() + timeout_s
    next_heartbeat = time.monotonic() + _TAKEOVER_HEARTBEAT_S
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break

        found = _find_appeal_page(context)
        if found is not None:
            return _claim_appeal_page(context, found)

        if not context.pages:
            raise SystemExit(
                f"Every browser tab was closed before reaching {E_COMPETITION_PATH} "
                f"or {APPEAL_PATH} — nothing was filled, nothing was saved.")

        # Watch the newest tab: after a login the form arrives there, and a
        # navigation of any OTHER tab is caught by the rescan at the top.
        watched = context.pages[-1]
        try:
            watched.wait_for_url(
                is_takeover_url,
                timeout=min(_TAKEOVER_SLICE_S, remaining) * 1000)
        except PWTimeout:
            pass
        except PWError:
            # This tab went away (operator closed the stale login tab — routine
            # once tabs multiply). Other tabs may still be walking to the form,
            # so keep waiting; only an empty context ends the run, above.
            continue
        else:
            return _claim_appeal_page(context, watched)

        now = time.monotonic()
        if now >= next_heartbeat:
            next_heartbeat = now + _TAKEOVER_HEARTBEAT_S
            left = int(max(0, deadline - now))
            urls = ", ".join(_tab_urls(context)) or "no open tabs"
            _info("waiting", _c(f"still on {urls}  ({left}s left)", _C.GREY))

    urls = "; ".join(_tab_urls(context)) or "no open tabs"
    raise SystemExit(
        f"Timed out after {timeout_s}s waiting for {E_COMPETITION_PATH} or "
        f"{APPEAL_PATH} (open tabs: {urls}). Nothing was filled, nothing was saved. "
        f"Re-run once you are logged in, or raise portal.takeover_timeout_seconds.")


def _navigate_to_appeal_form(page) -> bool:
    """Best-effort walk from the landing page to the appeal form. Never raises.

    E-Xidmətlər -> the service card -> the "Tanış oldum" modal -> the form. This is a
    convenience, not a contract: it saves the operator four clicks when the session in
    .browser_profile/ is still alive, and does nothing useful when it is not.

    Hence "never raises". Every step here can legitimately fail — an expired session
    bounces the whole chain to login, and the portal is free to re-word a card
    tomorrow. The authority on whether we actually reached the form is
    _await_takeover, which runs next either way and waits for the operator to walk it
    by hand. Letting a failed click abort the run would trade a working manual path
    for a broken automatic one.

    Returns True if the form was reached, False otherwise — for the log line only.
    """
    from playwright.sync_api import Error as PWError
    from playwright.sync_api import TimeoutError as PWTimeout

    try:
        _info("navigate", _c("E-Xidmətlər", _C.GREY))
        page.get_by_role("link", name=_re(r"E-Xidmətlər")).first.click()
        page.wait_for_url(
            lambda u: urlsplit(str(u)).path.casefold().rstrip("/") == E_SERVICES_PATH,
            timeout=_NAV_FALLBACK_TIMEOUT_MS)

        _info("navigate", _c("service card", _C.GREY))
        page.get_by_text(SERVICE_CARD_TEXT).first.click()

        # The portal gates the service behind a "read this" dialog. Scoped to the
        # dialog: "Tanış oldum" is a common enough phrase that a page-wide match
        # could find a different one.
        _info("navigate", _c("'Tanış oldum' modal", _C.GREY))
        modal = page.get_by_role("dialog")
        button = modal.get_by_role("button", name=_re(r"Tanış oldum"))
        if button.count() == 0:
            button = page.get_by_role("button", name=_re(r"Tanış oldum"))
        button.first.click()

        # The modal lands on the DASHBOARD, not the form — waiting for the appeal
        # path here is what made a walk that actually worked report itself as failed.
        page.wait_for_url(is_takeover_url, timeout=_NAV_FALLBACK_TIMEOUT_MS)
        return True
    except (PWTimeout, PWError) as exc:
        # One line, not a traceback: this is an expected outcome (not logged in yet),
        # not a fault. The takeover wait below prints what to do next.
        _info("navigate", _c(
            f"could not auto-navigate ({type(exc).__name__}) — falling back to "
            f"waiting for you to reach the form by hand", _C.YELLOW))
        return False


def _launch_context(pw, portal_cfg: dict):
    """Launch the browser against the persistent profile. Does not navigate.

    Separate from _reach_appeal_form so the caller holds the context BEFORE anything
    that can fail: the takeover wait raises SystemExit on a timeout, and if that
    happened before the context was bound, the shield would have nothing to keep open
    and would close the window on an operator who is halfway through an e-İmza login.
    """
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(_ROOT / portal_cfg.get("user_data_dir", ".browser_profile")),
        headless=False,       # the operator must be able to log in and review the draft
        accept_downloads=True,
        slow_mo=int(portal_cfg.get("slow_mo", 0)),  # 0 = full speed; --slow sets a per-action delay
    )


def _open_portal(pw, portal_cfg: dict, url: str):
    """Open the portal in the persistent profile and hand it to the operator.

    Auth is manual-and-persisted, not scripted. The profile directory keeps the
    session cookie from the operator's own login, so the automation never handles
    portal credentials at all.

    Navigation goes to the PUBLIC landing page, never straight to ``url``: the
    appeal form is behind an authorization guard, so a cold ``goto`` there just
    bounces to login and every form locator then runs against the wrong page.
    Instead we land somewhere public and wait for the operator to walk to the
    form themselves — which is also what the e-İmza flow requires anyway.

    (This replaces the CDP takeover the spec asked for. Attaching to an
    already-running Chrome needs it started with --remote-debugging-port=9222, and
    Chrome 136+ refuses that flag on the default profile — so the "already open,
    already logged-in window" cannot be attached to without a relaunch anyway. A
    dedicated profile gets the same persisted session with no flags and no port.)
    """
    context = _launch_context(pw, portal_cfg)
    return context, _reach_appeal_form(context, portal_cfg, url)


def _reach_appeal_form(context, portal_cfg: dict, url: str):
    """Get an already-launched context onto the appeal form, and return that TAB.

    Returns a Page, not a (context, page) pair — the caller already holds the
    context, which is the whole reason this is separate from _open_portal.
    """
    page = context.pages[0] if context.pages else context.new_page()
    # Takeover-wide, not form-strict: a profile that reopens on the dashboard is
    # already where the walk would have put it, so navigating again is pure churn.
    if not is_takeover_url(page.url):
        landing = portal_cfg.get("landing_url") or _LANDING_FALLBACK
        _info("landing", landing)
        page.goto(landing)
        # Not networkidle: the portal keeps background XHR running, so "idle"
        # may never arrive. The takeover wait below is the real condition.
        page.wait_for_load_state("domcontentloaded")
        _navigate_to_appeal_form(page)
    # Rebind: the form may well arrive in a tab that is not the one we launched,
    # and the returned page is the one the batch/probe must drive.
    page = _await_takeover(context, int(portal_cfg.get(
        "takeover_timeout_seconds", _TAKEOVER_TIMEOUT_FALLBACK)))
    return page


def main(argv: list[str] | None = None) -> int:
    # BEFORE parse_args: --help is printed from inside parse_args, and the help text
    # carries Azerbaijani glyphs ("Yadda saxla", "E-imza ilə təsdiqlə"). On a default
    # cp125x/cp1251 Windows console that raises UnicodeEncodeError and --help dies.
    _enable_windows_ansi()
    args = build_parser().parse_args(argv)
    if args.limit < 1:
        raise SystemExit("--limit must be at least 1 (it caps how many reports one "
                         "run sends; 0 would make the run a no-op).")

    portal_cfg = load_portal_config()
    url = args.url or portal_cfg.get("url", "")
    portal_cfg["slow_mo"] = args.slow  # --slow: per-action delay for _launch_context

    try:
        ledger = UploadLedger.load(_ledger_path(args))
    except LedgerError as exc:
        raise SystemExit(str(exc))

    if args.reset:
        _banner("E-KEYFIYYET UPLOAD ORCHESTRATOR — RESET STATE")
        _info("ledger", str(ledger.path))
        return _do_reset(args, ledger)

    # A live submit files a real appeal under a real person's identity — refuse
    # before a browser opens if we do not know who is signing it.
    if args.live and not args.dry_run:
        assert_director_configured(portal_cfg)

    if args.probe_chips is not None:
        return _do_probe(portal_cfg, url, chips=args.probe_chips)
    if args.probe:
        return _do_probe(portal_cfg, url)

    interactive = _interactive_enabled(args)
    if args.dry_run:
        mode = _c("DRY-RUN (no browser)", _C.BOLD, _C.YELLOW)
    elif args.live and interactive:
        mode = _c("LIVE + INTERACTIVE — asks before every 'Yadda saxla'",
                  _C.BOLD, _C.RED)
    elif args.live:
        mode = _c("LIVE — will click 'Yadda saxla'", _C.BOLD, _C.RED)
    else:
        mode = _c("FILL ONLY — form filled, NOT saved (pass --live to save)",
                  _C.BOLD, _C.YELLOW)
    _banner("E-KEYFIYYET UPLOAD ORCHESTRATOR")
    _info("mode", mode)
    # Said out loud rather than silently honoured: an operator who asked for the
    # prompt and did not get it would otherwise watch a batch save itself.
    if args.interactive and not interactive:
        _info("interactive", _c(_why_not_interactive(args), _C.YELLOW))
    elif interactive:
        _info("interactive", _c("[Enter]/y saves, 's' skips, 'q' ends the run — asked "
                                "once per report, with the filled form on screen",
                                _C.CYAN))

    # After the banner: the sweep reports what it excluded, and that note belongs
    # inside the run's output rather than above its heading.
    targets = _resolve_targets(args)
    # Operator hold (portal.hold_documents): before the limit, the ledger and any
    # browser, on every path. A no-op under the default empty list.
    # Closed months only (portal.upload_closed_months_only): same place, same reason.
    try:
        targets, held = _apply_hold(targets)
        targets, not_yet = _apply_closed_months(targets)
    except ValueError as exc:
        raise SystemExit(f"config/settings.yaml: {exc}")

    limit = _effective_limit(args, len(targets))
    capped = _c(f" · at most {limit} will be processed", _C.YELLOW)
    if limit < args.limit:
        capped += _c(f" (--limit {args.limit} needs --live: a fill-only run stops "
                     f"after one form so it stays readable)", _C.GREY)
    elif interactive and limit > args.limit:
        capped = _c(f" · all {limit} offered one at a time", _C.YELLOW) + _c(
            " (the confirmation prompt replaces the one-report cap)", _C.GREY)
    elif limit > args.limit:
        # The unattended lift. Louder than the interactive one on purpose: nobody is
        # watching, so the run says how many appeals it is about to file before it
        # files the first.
        capped = _c(f" · UNATTENDED BATCH — all {limit} will be filled and saved "
                    f"without prompting", _C.BOLD, _C.YELLOW) + _c(
            " (--no-interactive lifted the one-report cap; --limit N pins it)", _C.GREY)
    _info("targets", _c(f"{len(targets)} report(s) matched", _C.BOLD) + capped)
    _info("ledger", f"{ledger.path} ({len(ledger)} report(s) already tracked)")
    _info("portal", url)
    print()

    if not targets:
        # Every matched document is held or not yet closed: nothing to fill, so no
        # browser either.
        _print_summary(_Stats(held=held, not_yet=not_yet), ledger)
        return 0

    if args.dry_run:
        page = DryRunPage(url)
        stats = _run_batch(page, targets, args, ledger, portal_cfg)
        stats.held = held
        stats.not_yet = not_yet
        _print_summary(stats, ledger)
        print()
        _banner("DRY-RUN COMPLETE — 0 browser instances, 0 network calls")
        return 1 if (stats.blocked or stats.failed) else 0

    # --- real browser run ---
    missing = [pdf for _json, pdf in targets if not pdf.is_file()]
    if missing:
        raise SystemExit("PDF not found: " + ", ".join(str(p) for p in missing))
    pw_ctx = _sync_playwright()

    # The error-resilient shield. Everything lives INSIDE the `with`, deliberately:
    # leaving it stops the Playwright driver, which kills the window no matter what
    # context.close() does — a hold placed after the block would hold nothing.
    with pw_ctx as pw:
        # Launched before the try, so the shield below always has a window to hold —
        # including when the takeover wait times out on an operator who is still
        # logging in. That is the case where closing the browser costs the most.
        context = _launch_context(pw, portal_cfg)
        try:
            page = _reach_appeal_form(context, portal_cfg, url)
            stats = _run_batch(page, targets, args, ledger, portal_cfg)
        except BaseException as exc:
            # A live run keeps its old behaviour: it is unattended-ish and its
            # failures are ledger events, not things to stare at. A fill-only run
            # exists to be looked at, so it stops where it broke and waits.
            if args.live:
                raise
            print()
            _banner("RUN FAILED — BROWSER LEFT OPEN ANYWAY")
            _print_red_traceback(exc)
            _review_mode_hold(failed=True)
            stats = _Stats(failed=1)
        else:
            # Unconditional in fill-only, NOT gated on stats.filled: _run_batch
            # swallows a report's failure into stats.failed rather than raising, so
            # a locator that missed lands here with filled == 0 and the browser
            # sitting on the half-filled form. That is exactly the window to hold.
            if not args.live:
                _review_mode_hold(failed=bool(stats.failed))
        finally:
            context.close()
    stats.held = held
    stats.not_yet = not_yet
    _print_summary(stats, ledger)
    _banner("UPLOAD COMPLETE")
    return 1 if (stats.blocked or stats.failed) else 0


def _print_red_traceback(exc: BaseException) -> None:
    """Print the failure in red, in full.

    Full traceback rather than str(exc): the operator is about to look at a browser
    frozen mid-form, and "which line stopped" is what makes that screen
    interpretable. A bare "Timeout 30000ms exceeded" does not say which field.
    """
    import traceback

    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    for line in text.rstrip().splitlines():
        print(_c(f"  {line}", _C.RED))


def _review_mode_hold(failed: bool = False) -> None:
    """Hold the browser on screen until the operator says they are done.

    A fill-only run exists to be looked at. Returning here would drop out of the
    Playwright context manager and take the window down with it, so the review would
    be over before it started.

    ``failed`` only changes what is said, never what is done — a run that broke leaves
    a window worth MORE inspection than one that worked, not less, so it is held on
    exactly the same terms.

    Ctrl-C and a closed stdin both end the hold normally rather than raising: nothing
    has been saved and nothing is half-written, so there is no failure to report — the
    operator asking for their prompt back is the hold working, not breaking.
    """
    print()
    if failed:
        _banner("REVIEW MODE — PAUSED AT A FAILURE, BROWSER LEFT OPEN")
        print(_c("  [Review Mode] Form processing PAUSED — the error above stopped the "
                 "fill partway.", _C.BOLD, _C.YELLOW))
        print(_c("  The browser window is kept open exactly where it stopped so you "
                 "can see which", _C.BOLD, _C.YELLOW))
        print(_c("  field it reached.", _C.BOLD, _C.YELLOW))
    else:
        _banner("REVIEW MODE — BROWSER LEFT OPEN")
        print(_c("  [Review Mode] Form successfully filled! The browser window is kept "
                 "open for your", _C.BOLD, _C.GREEN))
        print(_c("  manual inspection. Please review the filled data and close the "
                 "browser window", _C.BOLD, _C.GREEN))
        print(_c("  yourself when finished.", _C.BOLD, _C.GREEN))
    print()
    _info("not saved", _c("'Yadda saxla' was NOT clicked — pass --live to save",
                          _C.YELLOW))
    _info("e-imza", _c("never touched — signature stays manual", _C.GREY))
    print()
    try:
        input(_c("  [Review Mode] Form processing complete/paused. Review your browser "
                 "screen, then press Enter here to exit and close the browser...",
                 _C.BOLD, _C.CYAN))
    except (KeyboardInterrupt, EOFError):
        pass
    print()
    _info("review", _c("done — closing the browser", _C.GREY))


def _sync_playwright():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit(
            "Playwright is not installed. Run:\n"
            "    pip install -r requirements.txt\n"
            "    playwright install chromium")
    return sync_playwright()


def _do_probe(portal_cfg: dict, url: str, chips: str | None = None) -> int:
    """--probe: open the form, expand it, dump its controls, save nothing.

    ``chips`` (--probe-chips) adds one step after the dump: tag standards in the
    standards box, read the chips back into the dump, reload the form (_probe_chips).

    The tab click and the document-type pick are NOT read-only, and pretending
    otherwise would be the lie that matters here. They are done anyway because the
    alternative is worse: the fields this whole mode exists to map do not enter the
    DOM until a type is chosen, so a probe that clicks nothing dumps 6 controls and
    no form — which is exactly what the first probe run produced.

    Nothing is filled, 'Yadda saxla' is never located, and e-imza is never touched.
    """
    _banner("E-KEYFIYYET FORM PROBE")
    _info("mode", _c("PROBE — opens the form and picks the document type, then dumps "
                     "it. Fills nothing, saves nothing.", _C.BOLD, _C.CYAN))
    _info("portal", url)
    print()
    out_path = _ROOT / "output" / PROBE_FILENAME
    with _sync_playwright() as pw:
        context, page = _open_portal(pw, portal_cfg, url)
        try:
            # No "are we on the form?" check here, but note it is no longer
            # _open_portal that guarantees it — that now returns on the e-competition
            # dashboard too. _open_new_document_form's _ensure_on_appeal_form is what
            # gets us to the form and waits on is_appeal_url before anything is read.
            # Without it this would dump the Məlumatlar tab and call it the form.
            _open_new_document_form(page, portal_cfg.get(
                "document_type", "İnspeksiya orqanının rəyi"))
            payload = probe_form(page, out_path)
            _info("controls", _c(str(payload["control_count"]), _C.BOLD, _C.GREEN))
            _info("written", _c(str(out_path), _C.GREEN))
            _print_standard_reconciliation(payload.get("standard_options") or [])
            _print_standard_field_label(payload.get("standard_field_label") or "")
            if chips is not None:
                payload.update(_probe_chips(page, chips,
                                            payload.get("standard_options") or []))
                out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
                _info("written", _c(str(out_path), _C.GREEN))
        finally:
            context.close()
    print()
    if chips is not None:
        _banner("PROBE COMPLETE — standards tagged, read back and discarded by a "
                "reload; nothing was saved")
        return 0
    _banner("PROBE COMPLETE — nothing was filled, nothing was saved")
    return 0


#: How many standards --probe-chips tags when it is given no list.
PROBE_CHIPS_DEFAULT_COUNT = 2


def _probe_chip_choices(chips: str, live_options: list[str]) -> list[str]:
    """The standards --probe-chips tags.

    An explicit ``"A,B"`` is used as given (blank parts dropped). Without one, the
    first PROBE_CHIPS_DEFAULT_COUNT entries of PORTAL_STANDARDS that the live listbox
    offers, in the listbox's own spelling, so the run tests the options the uploader
    will actually click.
    """
    explicit = [c.strip() for c in (chips or "").split(",") if c.strip()]
    if explicit:
        return explicit
    live = {_standard_key(o): o for o in live_options}
    picked = [live[_standard_key(o)] for o in PORTAL_STANDARDS
              if _standard_key(o) in live]
    return picked[:PROBE_CHIPS_DEFAULT_COUNT]


def _read_standard_chips(standards_box) -> list[str]:
    """The chip labels shown in the standards box, in order. [] if none are found.

    MUI renders a multiselect's tags as ``.MuiChip-label`` elements inside the
    Autocomplete root that holds the input. The 2026-08-12 probe measured that root
    (``div.MuiAutocomplete-root``); the chip markup itself has not been measured yet,
    which is what this read exists to do.
    """
    root = standards_box.locator(
        "xpath=ancestor::div[contains(@class,'MuiAutocomplete-root')][1]")
    try:
        return [t.strip() for t in root.locator(".MuiChip-label").all_inner_texts()]
    except Exception:
        return []


def _probe_chips(page, chips: str, live_options: list[str]) -> dict:
    """--probe-chips: tag standards, read the chips back, reload the form.

    Uses the same _select_standard the real fill uses, so the chips read back are the
    ones an upload would leave. Nothing else is touched: no other field, no PDF, no
    'Yadda saxla', no ledger. _reset_appeal_form reloads the page at the end, which
    drops the tags (they were never saved).

    Returns the keys added to the probe dump: ``chip_request`` (what was asked for),
    ``chip_results`` (each standard's _select_standard result), ``chip_expected``
    (the option texts clicked), ``chip_readback`` (the chip labels read) and
    ``chip_match`` (readback == expected, order-blind).
    """
    choices = _probe_chip_choices(chips, live_options)
    result: dict = {"chip_request": choices, "chip_results": {},
                    "chip_expected": [], "chip_readback": [], "chip_match": False}
    if not choices:
        _warn("chips: no standard to tag — the live listbox offered none of "
              "PORTAL_STANDARDS. Nothing was tagged.")
        return result
    standards_box = _field_after_caption(page, "inspeksiya:")
    selected: set[str] = set()
    for standard in choices:
        result["chip_results"][standard] = _select_standard(
            page, standards_box, standard, already=selected)
    readback = _read_standard_chips(standards_box)
    result["chip_expected"] = sorted(selected)
    result["chip_readback"] = readback
    result["chip_match"] = bool(selected) and sorted(readback) == sorted(selected)
    _info("chips asked", _c(str(choices), _C.BOLD))
    _info("chips read", _c(str(readback), _C.BOLD,
                           _C.GREEN if result["chip_match"] else _C.YELLOW))
    _info("chips", _c("MATCH" if result["chip_match"] else
                      "MISMATCH — compare chip_expected and chip_readback in the dump",
                      _C.BOLD, _C.GREEN if result["chip_match"] else _C.YELLOW))
    _reset_appeal_form(page)
    return result


def _print_standard_field_label(label: str) -> None:
    """Show the standards field's label — the one field whose meaning we infer.

    It no longer licenses anything: nothing is substituted, so a misread caption
    cannot put a wrong document on an appeal. It still says whether our standards are
    the right KIND of answer for this box, which decides how much of the corpus can
    ever be filed.
    """
    print()
    if not label:
        _info("field label", _c("could not be read — the 'documents used' vs "
                                "'assessed against' question stays open", _C.YELLOW))
        return
    _info("field label", _c(label, _C.BOLD, _C.CYAN))
    _info("means", _c("if this asks what the object was ASSESSED AGAINST, our "
                      "acceptance codes are the right answer and the portal's list is "
                      "simply too short. If it asks which documents were USED, the "
                      "reports do not record that at all.", _C.GREY))


def _print_standard_reconciliation(live: list[str]) -> None:
    """Compare the live option list against PORTAL_STANDARDS and say where they differ.

    The whole point of the probe: PORTAL_STANDARDS was transcribed from screenshots,
    and this is the run that turns it into a measurement. "only in code" means we
    would look for an option that is not there; "only on the portal" means we are
    skipping standards we could actually have filed.
    """
    print()
    if not live:
        _info("standards", _c("the option list could not be read — PORTAL_STANDARDS "
                              "remains UNVERIFIED", _C.BOLD, _C.YELLOW))
        return

    registered = list(PORTAL_STANDARDS)
    live_keys = {_standard_key(o) for o in live}
    code_keys = {_standard_key(o) for o in registered}
    only_live = [o for o in live if _standard_key(o) not in code_keys]
    only_code = [o for o in registered if _standard_key(o) not in live_keys]

    _info("offered", _c(f"{len(live)} options on the portal", _C.BOLD, _C.GREEN))
    for option in live:
        print(f"        {_c('•', _C.GREY)} {option}")

    if not only_live and not only_code:
        _info("drift", _c("none — PORTAL_STANDARDS matches the portal exactly", _C.GREEN))
        return
    if only_code:
        _info("only in code", _c(f"{only_code} — remove from PORTAL_STANDARDS",
                                 _C.BOLD, _C.YELLOW))
    if only_live:
        _info("only on portal", _c(f"{only_live} — add to PORTAL_STANDARDS",
                                   _C.BOLD, _C.YELLOW))


if __name__ == "__main__":
    raise SystemExit(main())
