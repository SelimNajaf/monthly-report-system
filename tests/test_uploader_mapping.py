"""Tests for uploader.py's portal-payload derivation.

These are the parts of the portal integration that can be tested honestly: pure
functions over a sidecar dict, no browser, no network, no live form. The locators
themselves cannot be tested without the authenticated portal — see --probe.

The value here is the boundaries: a wrong last-of-month date or a verdict that
hides a rejection would be filed into a government system before anyone noticed.
"""

import datetime
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import uploader  # noqa: E402
from conftest import PORTAL_2026_08_12  # noqa: E402
from uploader import (MAX_REPORTS_PER_RUN, PORTAL_STANDARDS,  # noqa: E402
                      _effective_limit, _standard_core, _standard_key,
                      _standard_tokens, build_parser, build_portal_payload,
                      is_appeal_url, is_projects_url, is_takeover_url, main,
                      match_portal_standard, month_bounds, portal_result,
                      split_standards, unique_ordered, unmatched_standards)

#: An explicit alias map + option list mirroring the shipped ``portal.standard_aliases``
#: config, so the alias tests are isolated from whatever settings.yaml holds locally.
_ASME_ALIASES = {
    "ASME I-XII": [
        r"^ASME\s+(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)$",
        r"^ASME\s+B31(\.\d+)?$",
    ]
}
#: Built on the 2026-08-12 list (tests/conftest.py), which had no "ASME I-XII" option:
#: these alias tests exercise the machinery, not today's portal.
_OPTIONS_WITH_ASME = list(PORTAL_2026_08_12) + ["ASME I-XII"]

#: The sub-specification aliases the live config carried for the 2026-08-12 list: a
#: single sub-number of a slashed/combined portal option maps to that option. Both
#: targets were in that list; tests using them pin it (fixture portal_2026_08_12).
_SUBSPEC_ALIASES = {
    "EEMUA 153/158": [r"^EEMUA\s+153$", r"^EEMUA\s+158$"],
    "ASTM E797/E797M": [r"^ASTM\s+E\s*797M?$"],
}

APPEAL_URL = "https://e-keyfiyyet.gov.az/uqq/new-appeal"
PROJECTS_URL = "https://e-keyfiyyet.gov.az/uqq/projects"


# --------------------------------------------------------------------------- #
# is_appeal_url — the gate that decides whether the form fill may start at all.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/uqq/new-appeal",
    "https://e-keyfiyyet.gov.az/uqq/new-appeal/",        # trailing slash
    "https://e-keyfiyyet.gov.az/uqq/new-appeal?id=7",    # portal adds query strings
    "https://E-KEYFIYYET.GOV.AZ/uqq/new-appeal",         # host casing
    "https://e-keyfiyyet.gov.az/uqq/new-appeal#step2",
])
def test_is_appeal_url_accepts_the_form(url):
    assert is_appeal_url(url) is True


@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/home",
    "https://e-keyfiyyet.gov.az/login",
    "https://e-keyfiyyet.gov.az/uqq/appeals",
    "https://e-keyfiyyet.gov.az/uqq/new-appeal-draft",   # not the same page
    "about:blank",
    "",
    None,
])
def test_is_appeal_url_rejects_everything_else(url):
    assert is_appeal_url(url) is False


def test_login_redirect_carrying_the_form_in_its_query_is_not_arrival():
    """The whole point of the path-only match.

    A cold goto to the form bounces here. Treating this URL as "we made it" is
    what put the form locators on a login page in the first place.
    """
    assert is_appeal_url(
        "https://e-keyfiyyet.gov.az/login?returnUrl=%2Fuqq%2Fnew-appeal") is False
    assert is_appeal_url(
        "https://e-keyfiyyet.gov.az/login?returnUrl=/uqq/new-appeal") is False


# --------------------------------------------------------------------------- #
# is_projects_url — the gate that decides whether a draft was actually saved.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/uqq/projects",
    "https://e-keyfiyyet.gov.az/uqq/projects/",           # trailing slash
    "https://e-keyfiyyet.gov.az/uqq/projects?tab=1",      # portal adds query strings
    "https://E-KEYFIYYET.GOV.AZ/UQQ/PROJECTS",
])
def test_is_projects_url_accepts_layihelerin_tab(url):
    assert is_projects_url(url) is True


@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/uqq/new-appeal",          # the save never landed
    "https://e-keyfiyyet.gov.az/uqq/e-competition",
    "https://e-keyfiyyet.gov.az/uqq/projects-archive",    # not the same page
    "https://e-keyfiyyet.gov.az/home",
    "",
    None,
])
def test_is_projects_url_rejects_everything_else(url):
    assert is_projects_url(url) is False


def test_a_session_bounce_carrying_projects_in_its_query_is_not_a_saved_draft():
    """The reason this is path-matched and not a substring test.

    An expired session redirects to login with the destination in returnUrl. Reading
    that as "the draft was committed" would mark an unsent report UPLOADED, and the
    ledger would then skip it forever.
    """
    assert is_projects_url(
        "https://e-keyfiyyet.gov.az/login?returnUrl=/uqq/projects") is False
    assert is_projects_url(
        "https://e-keyfiyyet.gov.az/login?returnUrl=%2Fuqq%2Fprojects") is False


def test_the_appeal_form_and_the_projects_tab_are_never_confused():
    """Save confirmation is the transition BETWEEN these two, so they must not overlap."""
    assert is_appeal_url(APPEAL_URL) is True
    assert is_projects_url(APPEAL_URL) is False
    assert is_projects_url(PROJECTS_URL) is True
    assert is_appeal_url(PROJECTS_URL) is False


# --------------------------------------------------------------------------- #
# is_takeover_url — the looser question: is this tab ours to drive?
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/uqq/new-appeal",
    "https://e-keyfiyyet.gov.az/uqq/e-competition",
    "https://e-keyfiyyet.gov.az/uqq/e-competition/",       # where Tanış oldum lands
    "https://e-keyfiyyet.gov.az/uqq/e-competition?tab=1",
    "https://E-KEYFIYYET.GOV.AZ/UQQ/E-COMPETITION",
])
def test_is_takeover_url_accepts_the_form_and_the_dashboard(url):
    assert is_takeover_url(url) is True


@pytest.mark.parametrize("url", [
    "https://e-keyfiyyet.gov.az/home",
    "https://e-keyfiyyet.gov.az/e-services",
    "https://e-keyfiyyet.gov.az/uqq/e-competition-archive",   # not the same page
    "https://e-keyfiyyet.gov.az/login?returnUrl=/uqq/e-competition",
    None,
])
def test_is_takeover_url_rejects_everything_else(url):
    assert is_takeover_url(url) is False


def test_the_dashboard_is_never_mistaken_for_the_form():
    """The reason there are two predicates and not one broadened match.

    upload_report drives the form's fields and --probe dumps them. If the strict gate
    accepted the dashboard, a takeover there would fill/dump the Məlumatlar tab.
    """
    dashboard = "https://e-keyfiyyet.gov.az/uqq/e-competition/"
    assert is_takeover_url(dashboard) is True
    assert is_appeal_url(dashboard) is False


# --------------------------------------------------------------------------- #
# Standard matching — the portal's list is not our vocabulary.
#
# What makes these worth writing: the matcher decides which normative document is
# named on a filed government appeal. Matching the wrong one is worse than matching
# none, so most of what is pinned below is what must NOT match.
# --------------------------------------------------------------------------- #
def test_the_tokenizer_splits_on_every_separator_the_portal_uses():
    assert _standard_tokens("EEMUA 153/158") == {"eemua", "153", "158"}
    assert _standard_tokens("EEMUA 158,Edition 3") == {"eemua", "158", "edition", "3"}
    assert _standard_tokens("ГОСТ Р 55611-2013") == {"гост", "р", "55611", "2013"}


def test_the_key_is_blind_to_separators():
    """A space or dash between a letter and its number is a habit, not a document."""
    assert _standard_key("ASTM E 384") == _standard_key("ASTM E384")
    assert _standard_key("ISO-23278") == _standard_key("ISO 23278")


def test_the_core_stops_at_the_first_number():
    assert _standard_core("EEMUA 158,Edition 3,Section 7.5.4") == {"eemua", "158"}
    assert _standard_core("API 1104") == {"api", "1104"}


def test_the_core_of_a_nameless_standard_is_every_token():
    """No digit anywhere: nothing to truncate at, so core == tokens."""
    assert _standard_core("ASME") == {"asme"}


# --- the three rules ------------------------------------------------------- #
@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_an_exact_match_survives_a_separator_difference():
    assert match_portal_standard("ASTM E384") == ("ASTM E 384", "exact")
    assert match_portal_standard("api 1104") == ("API 1104", "exact")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_the_brief_s_example_matches_on_the_alias():
    """EEMUA 158 IS EEMUA 153/158 — the portal names both revisions at once, and the
    shipped standard_aliases config makes it a deterministic 'alias', not a token subset."""
    assert match_portal_standard("EEMUA 158") == ("EEMUA 153/158", "alias")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_an_edition_suffix_matches_on_the_core():
    """30 rows carry this. The section narrows the document; it is not another one."""
    assert match_portal_standard(
        "EEMUA 158,Edition 3,Section 7.5.4") == ("EEMUA 153/158", "core")


def test_exact_beats_token_when_both_could_fire():
    choice, kind = match_portal_standard("ISO 17638", ["ISO 17638", "ISO 17638 part 2"])
    assert (choice, kind) == ("ISO 17638", "exact")


# --- what must NOT match. The heart of it. --------------------------------- #
@pytest.mark.parametrize("wanted", [
    "ASTM E1476",   # 37 rows — the first-word rule gave this "ASTM E 384"
    "ASTM A388",    #  3 rows — likewise
    "ISO 11666",    #  7 rows — the first-word rule gave this "ISO 27895"
    "ISO 23278",    # 12 rows
    "ISO-23278",
    "ISO 3452-1",
    "EEMUA 197",    # shares EEMUA, is a different document
    "AWS D1.1",
    "AWS A4.2M",
    "DNV-ST-EN 271",
    "EP-GIS-42-103",
    "ISOP 10675-1",
    "Doc No: Q00255 criteria Table 5",
])
@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_standard_the_portal_does_not_offer_matches_nothing(wanted):
    """Every one of these is a real value from output/**/compiled_monthly_report_*.json.

    This is the regression that matters. The deleted first-word matcher answered
    "ASTM E 384" for ASTM E1476 and ASTM A388, and "ISO 27895" for ISO 11666 —
    a different normative document, selected silently, on 47 rows.
    """
    assert match_portal_standard(wanted) == (None, "none")


# --- the ASME range/alias map. -------------------------------------------- #
@pytest.mark.parametrize("wanted", [
    "ASME VIII",   # 12 Sections, all one portal option
    "ASME V",
    "ASME IX",
    "ASME I",
    "ASME XII",
    "ASME-VIII",   # separator-blind
    "asme viii",   # case-insensitive
    "ASME B31.3",  # 223 rows — the B31.x piping codes map too
    "ASME B31.1",
    "ASME B31",
])
def test_asme_sections_map_to_the_range_option(wanted):
    """Every ASME Section and B31.x code is one of the documents "ASME I-XII" aggregates,
    so it is a TRUE match ("alias") — not the API 5L placeholder it used to become."""
    assert match_portal_standard(
        wanted, _OPTIONS_WITH_ASME, _ASME_ALIASES) == ("ASME I-XII", "alias")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_the_alias_only_fires_when_the_portal_offers_the_option():
    """The live listbox is the authority. If "ASME I-XII" is not offered, the alias must
    NOT fire — the standard falls through to the method/placeholder path unchanged."""
    assert match_portal_standard(
        "ASME VIII", list(PORTAL_STANDARDS), _ASME_ALIASES) == (None, "none")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_non_asme_standard_is_untouched_by_the_asme_alias():
    """The alias patterns are ASME-only; an ISO/API standard still matches on its own."""
    assert match_portal_standard(
        "API 1104", _OPTIONS_WITH_ASME, _ASME_ALIASES) == ("API 1104", "exact")
    assert match_portal_standard(
        "AWS D1.1", _OPTIONS_WITH_ASME, _ASME_ALIASES) == (None, "none")


# --- the sub-specification alias map (slashed/combined options). ----------- #
@pytest.mark.parametrize("wanted,expected", [
    ("EEMUA 153", "EEMUA 153/158"),      # one revision of the combined option
    ("EEMUA 158", "EEMUA 153/158"),      # the other revision
    ("eemua 158", "EEMUA 153/158"),      # case-insensitive
    ("EEMUA-158", "EEMUA 153/158"),      # separator-blind (normalized to a space)
    ("EEMUA_153", "EEMUA 153/158"),
    ("ASTM E797", "ASTM E797/E797M"),    # the E797 half of the slashed option
    ("ASTM E797M", "ASTM E797/E797M"),   # the E797M half
    ("astm e797", "ASTM E797/E797M"),    # case-insensitive
])
@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_single_sub_number_maps_to_its_slashed_option(wanted, expected):
    """A report cites one sub-number ("EEMUA 158"); the portal lists the combined pair
    ("EEMUA 153/158"). The config alias makes it a TRUE match — no warning, no
    placeholder — the same way ASME Sections resolve to "ASME I-XII"."""
    assert match_portal_standard(
        wanted, list(PORTAL_STANDARDS), _SUBSPEC_ALIASES) == (expected, "alias")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_the_full_slashed_name_is_still_an_exact_match_not_the_alias():
    """The alias patterns are ^...$-anchored to a single sub-number, so the full combined
    name falls through to the exact rule — the self-match invariant is preserved."""
    assert match_portal_standard(
        "EEMUA 153/158", list(PORTAL_STANDARDS), _SUBSPEC_ALIASES) == (
        "EEMUA 153/158", "exact")
    assert match_portal_standard(
        "ASTM E797/E797M", list(PORTAL_STANDARDS), _SUBSPEC_ALIASES) == (
        "ASTM E797/E797M", "exact")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_sub_number_alias_only_fires_when_the_combined_option_is_offered():
    """Same authority rule as the ASME alias: if the portal does not list the combined
    option, the alias must not fire and the standard falls through unchanged."""
    without_eemua = [o for o in PORTAL_STANDARDS if o != "EEMUA 153/158"]
    assert match_portal_standard(
        "EEMUA 158", without_eemua, _SUBSPEC_ALIASES) == (None, "none")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_sub_number_matching_two_offered_options_refuses():
    """The ambiguity guard on the alias rule. A bare "EEMUA 158" belongs to both
    "EEMUA 153/158" and a "EEMUA 157/158"; offered together, a coin flip is not a match."""
    aliases = {
        "EEMUA 153/158": [r"^EEMUA\s+153$", r"^EEMUA\s+158$"],
        "EEMUA 157/158": [r"^EEMUA\s+157$", r"^EEMUA\s+158$"],
    }
    options = list(PORTAL_STANDARDS) + ["EEMUA 157/158"]
    assert match_portal_standard("EEMUA 158", options, aliases) == (None, "none")
    # ...but a sub-number unique to one of them still resolves cleanly.
    assert match_portal_standard("EEMUA 153", options, aliases) == (
        "EEMUA 153/158", "alias")
    assert match_portal_standard("EEMUA 157", options, aliases) == (
        "EEMUA 157/158", "alias")


# --- splitting a multi-standard cell. ------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("ASME VIII / ISO 17636", ["ASME VIII", "ISO 17636"]),   # slash + spaces splits
    ("ASME B31.3, ASME V", ["ASME B31.3", "ASME V"]),        # comma + space splits
    ("ASME VIII & ASME IX", ["ASME VIII", "ASME IX"]),       # ampersand splits
    ("ASME VIII and ISO 17636", ["ASME VIII", "ISO 17636"]), # the word 'and' splits
    ("ISO 17636; ISO 17640", ["ISO 17636", "ISO 17640"]),    # semicolon splits
    ("EEMUA 153/158", ["EEMUA 153/158"]),                    # bare slash does NOT split
    ("ASTM E797/E797M", ["ASTM E797/E797M"]),                # bare slash does NOT split
    ("EEMUA 158,Edition 3,Section 7.5.4", ["EEMUA 158,Edition 3,Section 7.5.4"]),
    ("DNV-ST-EN 271", ["DNV-ST-EN 271"]),                    # hyphens are not delimiters
    ("ASME VIII", ["ASME VIII"]),                            # a lone standard is itself
    ("", []),                                                # blank -> nothing
    ("   ", []),
])
def test_split_standards(raw, expected):
    assert split_standards(raw) == expected


def test_split_standards_handles_none():
    assert split_standards(None) == []


def test_build_payload_splits_and_tags_multi_standard_rows():
    """A row citing two documents must contribute BOTH to the multiselect, deduped."""
    json_data = {
        "reporting_period": "Aprel 2026",
        "items_table": [
            {"item_name": "Pipe A", "standard": "ASME VIII / ISO 17636"},
            {"item_name": "Pipe B", "standard": "ISO 17636"},   # dup token across rows
        ],
    }
    payload = build_portal_payload(json_data, {})
    assert payload["standards"] == ["ASME VIII", "ISO 17636"]


def test_a_bare_family_name_is_ambiguous_and_refuses():
    """"API" is a subset of API 5L, API 579 AND API 1104. A coin flip is not a match."""
    assert match_portal_standard("API") == (None, "none")


def test_ambiguity_refuses_rather_than_taking_the_first():
    choice, kind = match_portal_standard("ASME", ["ASME B31.1", "ASME B31.3"])
    assert (choice, kind) == (None, "none")


def test_an_empty_option_list_is_no_match():
    assert match_portal_standard("EEMUA 158", []) == (None, "none")


def test_a_blank_standard_matches_nothing():
    """unique_ordered drops blanks, but a matcher that guessed on "" would be worse."""
    assert match_portal_standard("", ["ASME B31.3"]) == (None, "none")


def test_tokens_are_matched_whole_never_as_substrings():
    """The property the whole design rests on: 1476 is not "inside" 384."""
    assert match_portal_standard("ASTM E1476", ["ASTM E 384"]) == (None, "none")
    assert match_portal_standard("ISO 176", ["ISO 17638"]) == (None, "none")


# --- the registered list --------------------------------------------------- #
def test_every_registered_option_matches_itself_exactly():
    for option in PORTAL_STANDARDS:
        assert match_portal_standard(option) == (option, "exact")


def test_no_registered_option_is_a_token_subset_of_another():
    """Guards the ambiguity rule: if one were, it could never be matched at all."""
    collisions = [(a, b) for a in PORTAL_STANDARDS for b in PORTAL_STANDARDS
                  if a != b and _standard_tokens(a) <= _standard_tokens(b)]
    assert collisions == []


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_either_revision_of_a_combined_option_matches_it():
    """"EEMUA 153/158" names two revisions; both of ours are that same option, wired
    as aliases in settings.yaml so each is a TRUE match with no correction warning."""
    assert match_portal_standard("EEMUA 153") == ("EEMUA 153/158", "alias")
    assert match_portal_standard("EEMUA 158") == ("EEMUA 153/158", "alias")


def test_the_option_is_compared_on_its_full_tokens_not_its_core():
    """The guard on the brief's whole case.

    Core reduction is for the WANTED side only. If it were applied to the option too,
    "EEMUA 153/158" would collapse to {eemua, 153} and "EEMUA 158" — 137 rows — would
    stop matching. Pinned against an option list of exactly one so nothing else can
    carry the assertion. Aliases disabled (``{}``) so this exercises the token rule
    itself, not the settings.yaml sub-spec alias that would otherwise short-circuit it.
    """
    assert match_portal_standard("EEMUA 158", ["EEMUA 153/158"], {}) == (
        "EEMUA 153/158", "token")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_matching_is_case_and_script_agnostic():
    assert match_portal_standard("гост р 55611-2013") == ("ГОСТ Р 55611-2013", "exact")


# --- swept over the real corpus -------------------------------------------- #
def _corpus_standards() -> list[str]:
    """Every distinct `standard` in every compiled report on disk."""
    import json
    found = set()
    for path in (_ROOT / "output").rglob("compiled_monthly_report_*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for row in data.get("items_table") or []:
            if row.get("standard"):
                found.add(str(row["standard"]))
    return sorted(found)


def test_no_real_standard_is_ever_matched_across_families():
    """The durable invariant, swept over whatever is on disk today.

    The parametrized cases above pin the corpus as it stands; this one keeps holding
    when new reports land. A match must share its first token with what we asked for
    — "ASTM E1476" resolving to "ASTM E 384" shares "astm" and would pass, so this is
    a floor and not a ceiling. It catches the gross failure: an ISO standard coming
    back as an API one because some rule matched on nothing at all.
    """
    corpus = _corpus_standards()
    if not corpus:
        pytest.skip("no compiled reports on disk to sweep")

    for wanted in corpus:
        choice, kind = match_portal_standard(wanted)
        if choice is None:
            continue
        assert _standard_tokens(wanted) & _standard_tokens(choice), (
            f"{wanted!r} matched {choice!r} ({kind}) sharing NO token at all")


def test_the_corpus_never_silently_resolves_an_astm_to_the_wrong_number():
    """The 47-row regression, asserted against live files rather than literals."""
    for wanted in _corpus_standards():
        choice, kind = match_portal_standard(wanted)
        if choice is None:
            continue
        if kind == "alias":
            # A range/alias option ("ASME I-XII") deliberately does NOT carry the
            # section number — the config vouches that the family is the same document.
            # The number-preservation invariant is for the exact/token/core rules.
            continue
        wanted_numbers = {t for t in _standard_tokens(wanted) if any(c.isdigit() for c in t)}
        if not wanted_numbers:
            continue
        assert wanted_numbers & _standard_tokens(choice), (
            f"{wanted!r} matched {choice!r}, which shares none of its numbers "
            f"{sorted(wanted_numbers)} — that is a different normative document")


# --------------------------------------------------------------------------- #
# ZERO SUBSTITUTION — unmatched_standards, and the code that must stay deleted.
#
# The stakes: nothing may put a document on a government filing that the report never
# named. There is no longer any code that COULD; what is pinned below is that fact.
# --------------------------------------------------------------------------- #
def test_there_is_no_placeholder_substitution_left():
    """The policy cannot come back quietly. API 5L was the shipped placeholder."""
    assert not hasattr(uploader, "placeholder_standard")
    assert not hasattr(uploader, "_skip_standard")


def test_there_is_no_method_standard_fallback_left():
    """An MT report's ASME B31.3 used to become ISO 17638 — the wrong question's answer."""
    assert not hasattr(uploader, "METHOD_STANDARDS")
    assert not hasattr(uploader, "_method_standard")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_matching_report_has_nothing_unmatched():
    assert unmatched_standards(["API 1104", "ISO 17638"]) == []


@pytest.mark.parametrize("standard", [
    "ASME VIII",        # the MEASURED list has no ASME entry (see the alias test below)
    "ASME B31.3",       # 223 rows of our corpus, and still not on the measured list
    "AWS D1.1",
    "ASTM E1476",       # PMI: no alloy-identification standard on the portal
])
@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_standard_the_portal_does_not_offer_is_reported_unmatched(standard):
    # Against the MEASURED options, so the result does not move with whatever
    # standard_aliases the local settings.yaml happens to assert.
    assert unmatched_standards([standard], list(PORTAL_STANDARDS)) == [standard]


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_the_whole_report_is_blocked_by_one_unmatched_standard():
    """ANY unmatched standard skips the report. Filing the other two would name an
    inspection as judged by less than it was judged by."""
    wanted = ["ISO 17638", "ASME B31.3", "API 1104"]
    assert unmatched_standards(wanted, list(PORTAL_STANDARDS)) == ["ASME B31.3"]


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_unmatched_standards_keeps_the_reports_own_order():
    assert unmatched_standards(["AWS D1.1", "API 1104", "ASME VIII"],
                               list(PORTAL_STANDARDS)) == ["AWS D1.1", "ASME VIII"]


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_configured_alias_target_counts_as_offered_in_the_pre_flight():
    """The pre-flight answers from _baseline_options: measured options PLUS the
    aggregate options the config asserts the portal has since added ("ASME I-XII").

    So an ASME report is not pre-flight-skipped when the config vouches for that
    option — and if the live listbox does not in fact offer it, the backstop inside
    upload_report skips the report there instead. The config decides how far the
    baseline is trusted; the portal always decides what is filed.
    """
    aliases = {"ASME I-XII": [r"^ASME\s+B31(\.\d+)?$"]}
    offered = list(PORTAL_STANDARDS) + ["ASME I-XII"]
    assert match_portal_standard("ASME B31.3", offered, aliases) == (
        "ASME I-XII", "alias")
    assert match_portal_standard("ASME B31.3", list(PORTAL_STANDARDS), aliases) == (
        None, "none")


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_a_blank_standard_is_not_unmatched():
    """A report that claims no standard is not a report the portal failed to express."""
    assert unmatched_standards(["", "   ", None, "API 1104"]) == []


def test_unmatched_standards_asks_the_live_list_when_given_one():
    """The baseline is our reading of the portal; a live listbox is the portal."""
    assert unmatched_standards(["API 1104"], ["API 5L"]) == ["API 1104"]
    assert unmatched_standards(["API 1104"], ["API 1104"]) == []


@pytest.mark.usefixtures("portal_2026_08_12", "aliases_2026_08_12")
def test_an_aliased_standard_is_matched_not_skipped():
    """EEMUA 158 IS the portal's EEMUA 153/158 — a true match, so the report files."""
    assert unmatched_standards(["EEMUA 158"]) == []


def test_no_method_is_ever_consulted_to_resolve_a_standard():
    """_select_standard still takes `method`, but nothing may read it into a choice."""
    import inspect
    body = inspect.getsource(uploader._select_standard)
    assert "method" not in body.split('"""')[2], (
        "the method token is back in _select_standard's logic — that is the "
        "discipline fallback returning")


# --------------------------------------------------------------------------- #
# month_bounds — reporting_period is AZERBAIJANI (naming.AZ_MONTHS), not English.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("period, expected", [
    ("May 2026", ("01.05.2026", "31.05.2026")),
    ("Fevral 2026", ("01.02.2026", "28.02.2026")),      # 28 days
    ("Fevral 2024", ("01.02.2024", "29.02.2024")),      # leap year
    ("Fevral 2028", ("01.02.2028", "29.02.2028")),      # leap year
    ("Fevral 2100", ("01.02.2100", "28.02.2100")),      # century, NOT a leap year
    ("Yanvar 2026", ("01.01.2026", "31.01.2026")),
    ("İyul 2026", ("01.07.2026", "31.07.2026")),        # dotted İ
    ("İyun 2026", ("01.06.2026", "30.06.2026")),        # 30 days
    ("Aprel 2026", ("01.04.2026", "30.04.2026")),
    ("Dekabr 2026", ("01.12.2026", "31.12.2026")),
])
def test_month_bounds(period, expected):
    assert month_bounds(period) == expected


def test_month_bounds_is_zero_padded():
    """The portal's date format is DD.MM.YYYY — a bare '1.5.2026' is not valid."""
    start, end = month_bounds("May 2026")
    assert start == "01.05.2026"
    assert len(start) == len(end) == 10


def test_month_bounds_rejects_english_month():
    """English would mean the sidecar was not written by naming.reporting_period()."""
    with pytest.raises(ValueError, match="Unknown Azerbaijani month"):
        month_bounds("July 2026")


@pytest.mark.parametrize("bad", ["", "May", "2026", "May 2026 extra", "Mayy 2026"])
def test_month_bounds_rejects_malformed(bad):
    with pytest.raises(ValueError):
        month_bounds(bad)


def test_month_bounds_rejects_non_numeric_year():
    with pytest.raises(ValueError, match="Unparseable year"):
        month_bounds("May MMXXVI")


# --------------------------------------------------------------------------- #
# unique_ordered
# --------------------------------------------------------------------------- #
def test_unique_ordered_dedupes_preserving_first_seen_order():
    assert unique_ordered(["Boru", "Konstruktiv tikiş", "Boru"]) == \
        ["Boru", "Konstruktiv tikiş"]


def test_unique_ordered_drops_blanks_and_none():
    assert unique_ordered(["Boru", "", None, "   ", "Flanec"]) == ["Boru", "Flanec"]


def test_unique_ordered_strips_whitespace():
    assert unique_ordered(["  Boru  ", "Boru"]) == ["Boru"]


def test_unique_ordered_empty():
    assert unique_ordered([]) == []


# --------------------------------------------------------------------------- #
# portal_result — the portal accepts only Yararlı or Məlumat üçün, keyed on method.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", ["UTM", "HRT", "PMI", "utm", "hrt", "pmi"])
def test_informational_methods_report_melumat_ucun(method):
    """UTM/HrT/PMI carry no pass/fail verdict — they file as 'Məlumat üçün'."""
    assert portal_result(method) == "Məlumat üçün"


@pytest.mark.parametrize("method", ["UT", "MT", "RT", "DP", "FC", "MPI"])
def test_standard_methods_report_yararli(method):
    """Every non-informational method files as 'Yararlı' — never 'Yarasız'."""
    assert portal_result(method) == "Yararlı"


def test_portal_result_never_emits_yarasiz():
    """The portal rejects 'Yarasız'; no method may ever produce it."""
    for method in ("UTM", "HRT", "PMI", "UT", "MT", "RT", "DP", "FC", "MPI", "", "???"):
        assert portal_result(method) != "Yarasız"


# --------------------------------------------------------------------------- #
# build_portal_payload — the whole dict a live fill would type.
# --------------------------------------------------------------------------- #
@pytest.fixture
def sidecar():
    return {
        "client_name": "Khazar Fabrication",
        "client_voen": "1509876543",
        "reporting_period": "May 2026",
        "ndt_method": "MT",
        "report_serial_no": "MR-MT-KHF-26-05",
        "total_records": 3,
        "equipment_used": "El/Magnet (S/N:B1261), El/Magnet (S/N:5803)",
        "items_table": [
            {"seq_no": "1", "date": "21.05.2026", "report_no": "KF-MT-26-038",
             "standard": "ASME B31.3", "item_name": "Boru", "result": "Yararlı"},
            {"seq_no": "2", "date": "22.05.2026", "report_no": "KF-MT-26-039",
             "standard": "AWS D1.1", "item_name": "Konstruktiv tikiş",
             "result": "Yararlı"},
            {"seq_no": "3", "date": "23.05.2026", "report_no": "KF-MT-26-040",
             "standard": "ASME B31.3", "item_name": "Boru", "result": "Yararlı"},
        ],
    }


@pytest.fixture
def portal_cfg():
    return {
        "document_type": "İnspeksiya orqanının rəyi",
        "director": {"ad": "Test", "soyadi": "Testərov", "atasinin_adi": "Əli",
                     "fin": "1A2B3C4", "seriya_nomresi": "AZE12345678"},
    }


def test_payload_joins_unique_items_comma_separated(sidecar, portal_cfg):
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["inspection_object"] == "Boru, Konstruktiv tikiş"


# --------------------------------------------------------------------------- #
# fit_item_list — the self-imposed bound on the inspection object.
#
# The portal publishes no limit: there is no maxlength on that input in the probe
# dump or in any saved failure HTML. So this is a ceiling we chose, and the rule it
# follows matters more than the number. A person reads that field as a list of the
# things that were inspected, and a fragment names nothing.
# --------------------------------------------------------------------------- #
LIMIT = uploader.INSPECTION_OBJECT_MAX_CHARS


def test_a_list_that_fits_is_returned_untouched():
    """The common case: 97 of the 99 sidecars on disk are already under the bound."""
    assert uploader.fit_item_list("Boru, Konstruktiv tikiş") == "Boru, Konstruktiv tikiş"
    assert uploader.fit_item_list("") == ""

    exact = "x" * LIMIT
    assert uploader.fit_item_list(exact) == exact, "the bound itself is not over it"


def test_a_long_item_list_drops_whole_items():
    """WHOLE ones, from the end. "KEQ12 kranı" cut to "KEQ1..." names nothing.

    Uses the real 204-char value that failed on MR-MT-UBOC-25-12.
    """
    items = ["DB-2", "Recovery Unit for Rescueboat", "DetailNo",
             "Boat Fall & RemoteControl Unit", "The load-Measuring sensor bracket",
             "Detail No", "Qazma qülləsinin hərəkəti üçün relslər",
             "Qazma qülləsi üçün dayaqlar", "KEQ12 kranı"]
    value = ", ".join(items)
    assert len(value) == 204, "the fixture is the value that actually failed"

    trimmed = uploader.fit_item_list(value)

    assert len(trimmed) <= LIMIT
    assert trimmed.endswith(" …"), "a short list must read as trimmed, not as complete"
    kept = trimmed[:-2].split(", ")
    assert kept == items[:len(kept)], "the survivors are whole, in order, unaltered"
    assert len(kept) < len(items), "something was actually dropped"


def test_the_bound_drops_no_more_than_it_has_to():
    """A greedy trim that dropped half the list would be as wrong as a mid-word cut."""
    items = [f"Item{n:02d}" for n in range(1, 40)]     # 8 chars each, well over 200

    kept = uploader.fit_item_list(", ".join(items))[:-2].split(", ")

    assert len(", ".join(kept + [items[len(kept)]])) + 2 > LIMIT, (
        "one more item would have fitted — the trim gave up too early")


def test_one_over_long_item_is_cut_because_there_is_nothing_to_drop():
    """The field is `required`, so it can never come back empty.

    A single name longer than the whole bound is the one case where a word gets cut,
    and fit_item_list warns separately about it.
    """
    single = "Q" * (LIMIT + 50)

    trimmed = uploader.fit_item_list(single)

    assert len(trimmed) <= LIMIT
    assert trimmed, "an empty value would fail the form's own required check"
    assert trimmed.endswith("…")


def test_the_payload_applies_the_bound(sidecar, portal_cfg):
    """Bounded in the payload, not at the fill site, so --dry-run prints what is filed.

    A dry run that showed the full string and a live run that filed a shorter one
    would make the rehearsal a different form from the performance.
    """
    sidecar["items_table"] = [
        {"seq_no": str(n), "date": "21.05.2026", "report_no": f"KF-MT-26-{n:03d}",
         "standard": "ASME B31.3", "item_name": f"Uzun obyekt adı nömrə {n:02d}",
         "result": "Yararlı"}
        for n in range(1, 15)]

    payload = build_portal_payload(sidecar, portal_cfg)

    assert len(payload["inspection_object"]) <= LIMIT
    assert payload["inspection_object"].startswith("Uzun obyekt adı nömrə 01")


def test_payload_passes_the_equipment_note_through_untouched(sidecar, portal_cfg):
    """The exporter already joined and de-duplicated it from the source documents.

    The uploader re-deriving it would mean re-parsing reports the sidecar exists to
    stand in for — and the two joins could then disagree.
    """
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["equipment_used"] == "El/Magnet (S/N:B1261), El/Magnet (S/N:5803)"


def test_payload_tolerates_a_sidecar_written_before_equipment_existed(sidecar, portal_cfg):
    """Older sidecars on disk have no equipment_used. They are still valid appeals:
    the note is a new field, not a new requirement — the fill just types ""."""
    del sidecar["equipment_used"]
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["equipment_used"] == ""


def test_payload_carries_an_empty_equipment_note_for_a_method_that_has_none(
        sidecar, portal_cfg):
    """DP reports carry no equipment field at all, so the exporter writes ""."""
    sidecar["equipment_used"] = ""
    assert build_portal_payload(sidecar, portal_cfg)["equipment_used"] == ""


def test_payload_dedupes_standards(sidecar, portal_cfg):
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["standards"] == ["ASME B31.3", "AWS D1.1"]


def test_payload_derives_date_range_from_reporting_period(sidecar, portal_cfg):
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["date_from"] == "01.05.2026"
    assert payload["date_to"] == "31.05.2026"


def test_payload_keeps_voen_a_string(sidecar, portal_cfg):
    """A numeric VÖEN would have lost a leading zero upstream."""
    payload = build_portal_payload(sidecar, portal_cfg)
    assert isinstance(payload["client_voen"], str)
    assert payload["client_voen"] == "1509876543"


def test_payload_carries_director_from_config(sidecar, portal_cfg):
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["director_fin"] == "1A2B3C4"
    assert payload["director_seriya"] == "AZE12345678"


def test_payload_keeps_the_directors_name_in_three_parts(sidecar, portal_cfg):
    """The form has three boxes (ad / soyadı / atasının adı). Joining them here and
    re-splitting at fill time would reintroduce the word-order guess this avoids."""
    payload = build_portal_payload(sidecar, portal_cfg)
    assert payload["director_ad"] == "Test"
    assert payload["director_soyadi"] == "Testərov"
    assert payload["director_atasinin_adi"] == "Əli"


def test_payload_tolerates_blank_director_block(sidecar):
    """Building must not explode — assert_director_configured is the gate, not this."""
    payload = build_portal_payload(sidecar, {"document_type": "X", "director": {}})
    assert payload["director_fin"] == ""


def test_payload_verdict_is_method_driven_not_row_driven(sidecar, portal_cfg):
    """A Yarasız row must NOT reach the portal: the sidecar's method (MT, standard)
    fixes the verdict at Yararlı. The portal rejects any value but Yararlı/Məlumat üçün."""
    sidecar["items_table"][1]["result"] = "Yarasız"
    assert build_portal_payload(sidecar, portal_cfg)["result"] == "Yararlı"


def test_payload_verdict_informational_method(sidecar, portal_cfg):
    """An informational method (UTM) files Məlumat üçün regardless of row results."""
    sidecar["ndt_method"] = "UTM"
    assert build_portal_payload(sidecar, portal_cfg)["result"] == "Məlumat üçün"


# --------------------------------------------------------------------------- #
# --limit — how many reports one run may process, and when chaining is allowed.
# --------------------------------------------------------------------------- #
def _args(argv):
    return build_parser().parse_args(argv)


def test_limit_defaults_to_one_report():
    """The default cap is the safety brake, not a convenience: a bad selector map
    must not be able to file more than one appeal before anyone reads the screen."""
    assert _args([]).limit == MAX_REPORTS_PER_RUN == 1


def test_limit_raises_the_cap_for_a_live_run():
    args = _args(["--all", "--live", "--limit", "3"])
    assert _effective_limit(args) == 3


def test_a_fill_only_run_never_chains_however_high_the_limit():
    """Without --live the filled form is left on screen for review; opening the
    next report would type straight over the thing the operator was asked to check."""
    assert _effective_limit(_args(["--all", "--limit", "3"])) == 1


@pytest.mark.parametrize("bad", ["0", "-1"])
def test_a_limit_below_one_is_refused(bad):
    with pytest.raises(SystemExit, match="at least 1"):
        main(["--all", "--limit", bad])


# --------------------------------------------------------------------------- #
# Master-list ↔ portal coverage. The compiled-output guardrail mirrors
# standarts/butun_standartlar.md (test_master_standards_sync); this pins which master
# standards the uploader can PLACE onto a real listbox option today, and which it
# cannot. Against the provisional 21-standard list (2026-10-06) and the alias map
# shipped in config/settings.yaml since then (Roman-numeral ASME Sections only).
# --------------------------------------------------------------------------- #
#: The map shipped in config/settings.yaml since 2026-10-06.
_SHIPPED_ALIASES = {
    "ASME I-XII": [r"^ASME\s+(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)$"],
}

#: Master-list standards the portal offers. Each MUST resolve to a real option; if the
#: portal drops one, this list is edited deliberately — it is not allowed to rot.
_MASTER_OFFERED = {
    "API 510": "exact", "API 570": "exact", "API 620": "exact", "API 650": "exact",
    "ASME B31.1": "exact", "ASME B31.3": "exact", "ASME I-XII": "exact",
    "ASTM E 572": "exact", "ASTM E 1476": "exact", "AWS D1.1": "exact",
    "ISO 3057": "exact", "ISO 10863": "exact", "ISO 16809": "exact",
    "ISO 17637": "exact", "ISO 19285": "exact",
    "ГОСТ 7512-82": "exact", "ГОСТ 18442-80": "exact", "ГОСТ 26790": "exact",
    "ГОСТ Р 51780": "exact", "ГОСТ Р 55724-2013": "exact", "ГОСТ Р 56512-2015": "exact",
}


@pytest.mark.parametrize("std,kind", sorted(_MASTER_OFFERED.items()))
def test_master_standard_resolves_to_a_portal_option(std, kind):
    option, got_kind = match_portal_standard(
        std, options=list(PORTAL_STANDARDS), aliases=_SHIPPED_ALIASES)
    assert option is not None, f"{std!r} no longer maps to any portal option"
    assert got_kind == kind


@pytest.mark.parametrize("std", [
    # On the 2026-08-12 list, gone from the portal's 2026-10-06 list.
    "API 5L", "API 579", "API 1104",
    "ASTM E 384", "ASTM E 1351", "ASTM E797/E797M", "EEMUA 153/158",
    "ISO 6507", "ISO 15549", "ISO 17636", "ISO 17638", "ISO 17640",
    "ISO 27895", "ISO 34352-1-4", "ГОСТ Р 55611", "ГОСТ Р ЕН 13018",
])
def test_master_standard_the_portal_lacks_falls_through(std):
    """Not every approved standard is a portal listbox option. These are ALLOWED
    into the compiled report (they mirror butun_standartlar.md) but the portal does
    not offer them, so the matcher returns 'none' and the report-level rule
    (portal.standard_policy) decides what happens."""
    option, kind = match_portal_standard(
        std, options=list(PORTAL_STANDARDS), aliases=_SHIPPED_ALIASES)
    assert (option, kind) == (None, "none")


def test_the_shipped_asme_alias_reaches_sections_but_not_b31():
    """ASME Sections I–XII (Roman) are the aggregate; B31.x are options of their own."""
    options = list(PORTAL_STANDARDS)
    assert match_portal_standard("ASME VIII", options, _SHIPPED_ALIASES) == (
        "ASME I-XII", "alias")
    assert match_portal_standard("ASME IX", options, _SHIPPED_ALIASES) == (
        "ASME I-XII", "alias")
    assert match_portal_standard("ASME B31.3", options, _SHIPPED_ALIASES) == (
        "ASME B31.3", "exact")
    assert match_portal_standard("ASME XIII", options, _SHIPPED_ALIASES) == (None, "none")


# --------------------------------------------------------------------------- #
# PORTAL_STANDARDS drift lock. The provisional 21 options typed by the operator from
# a screenshot of the live form (2026-10-06) — NOT yet probe-verified (TODO P0).
# PORTAL_STANDARDS is the --dry-run oracle and the --probe reconciliation baseline,
# so a silent edit to it changes which standards an operator is told will be filed.
# This pins the exact list AND its order; changing the live portal means editing this
# test on purpose.
# --------------------------------------------------------------------------- #
_LIVE_PORTAL_OPTIONS = (
    "API 510", "API 570", "API 620", "API 650", "ASME B31.1",
    "ASME B31.3", "ASME I-XII", "ASTM E 572", "ASTM E 1476",
    "AWS D1.1", "ISO 3057", "ISO 10863", "ISO 16809", "ISO 17637",
    "ISO 19285", "ГОСТ 7512-82", "ГОСТ 18442-80", "ГОСТ 26790",
    "ГОСТ Р 51780", "ГОСТ Р 55724-2013", "ГОСТ Р 56512-2015",
)


def test_portal_standards_is_the_exact_live_list():
    assert tuple(PORTAL_STANDARDS) == _LIVE_PORTAL_OPTIONS


def test_every_live_option_resolves_to_itself_exactly():
    # Each captured option, put back through the matcher against the live list,
    # must return itself — not a token/core near-miss onto a sibling.
    for option in _LIVE_PORTAL_OPTIONS:
        assert match_portal_standard(option, list(_LIVE_PORTAL_OPTIONS),
                                     _SHIPPED_ALIASES) == (option, "exact")


# --------------------------------------------------------------------------- #
# _resolve_targets — the strict client gate, on BOTH invocation paths.
#
# A hand-picked --report is not a smaller --all: it is the form an operator reaches
# for under time pressure, so naming a file explicitly must not be a way around the
# allowlist. The registry here mirrors the shipped settings.yaml shape but is
# self-contained, like _ASME_ALIASES above.
# --------------------------------------------------------------------------- #
_APPROVED = ["UBOC", "KHF", "AZF", "BS", "GEMZA", "NOV"]

_GATE_REGISTRY = {
    "UBOC":  {"code": "UBOC",  "name": "UBOC",               "voen": "1000000001",
              "aliases": ["uboc"]},
    "KHF":   {"code": "KHF",   "name": "Khazar Fabrication", "voen": "1000000002",
              "aliases": ["khazar fabrication"]},
    "KHE":   {"code": "KHE",   "name": "Khazar Engineering", "voen": "",
              "aliases": ["khazar engineering"]},
    "UP":    {"code": "UP",    "name": "Uniper / Prokon",    "voen": "",
              "aliases": ["uniper"]},
    "SDLN":  {"code": "SDLN",  "name": "SDLN",               "voen": "",
              "aliases": ["sdln"]},
    "SNM":   {"code": "SNM",   "name": "SIENMAR",            "voen": "",
              "aliases": ["sienmar"], "active": False},
}


class TestResolveTargetsClientGate:
    @pytest.fixture
    def gated(self, tmp_path, monkeypatch):
        """A settings-backed output/ tree; returns a writer for one sidecar."""
        import json
        from types import SimpleNamespace

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setattr(uploader, "_ROOT", tmp_path)
        monkeypatch.setattr(uploader, "_settings", lambda: SimpleNamespace(
            raw={"clients": _GATE_REGISTRY,
                 "excluded_clients": ["SNM"],
                 "approved_clients": _APPROVED}))

        def write(client_name, code="UT", month="MAY_2026", raw=None):
            path = out / f"compiled_monthly_report_{code}_x_{month}.json"
            path.write_text(
                raw if raw is not None
                else json.dumps({"client_name": client_name, "ndt_method": code}),
                encoding="utf-8")
            return path
        return write

    def _args(self, **kw):
        argv = []
        for flag, value in kw.items():
            argv += [f"--{flag}"] if value is True else [f"--{flag}", value]
        return build_parser().parse_args(argv)

    def test_approved_client_passes_the_single_report_path(self, gated):
        sidecar = gated("Khazar Fabrication")
        targets = uploader._resolve_targets(self._args(report=str(sidecar)))
        assert targets == [(sidecar, sidecar.with_suffix(".pdf"))]

    @pytest.mark.parametrize("client_name,code", [
        ("Khazar Engineering", "KHE"),
        ("SDLN", "SDLN"),
        ("Uniper / Prokon", "UP"),
        ("SIENMAR", "SNM"),
    ])
    def test_non_approved_client_is_refused_on_the_single_report_path(
            self, gated, client_name, code):
        """The hole this closes: --report used to skip every client check."""
        sidecar = gated(client_name)
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert code in str(exc.value) and "approved_clients" in str(exc.value)

    def test_unreadable_sidecar_is_refused_while_the_allowlist_is_populated(self, gated):
        """Fail CLOSED: a client that cannot be read is not one of the six."""
        sidecar = gated(None, raw="{ not json")
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert "unresolved" in str(exc.value)

    def test_sweep_keeps_only_approved_clients(self, gated):
        keep = gated("UBOC", month="MAY_2026")
        gated("Khazar Engineering", month="JUN_2026")
        gated("SDLN", month="JUL_2026")
        gated("SIENMAR", month="AUG_2026")
        targets = uploader._resolve_targets(self._args(all=True))
        assert [s for s, _pdf in targets] == [keep]

    def test_sweep_drops_a_sidecar_whose_client_cannot_be_read(self, gated):
        keep = gated("UBOC", month="MAY_2026")
        gated(None, month="JUN_2026", raw="[]")   # a non-dict JSON -> blank code
        targets = uploader._resolve_targets(self._args(all=True))
        assert [s for s, _pdf in targets] == [keep]

    def test_an_empty_allowlist_leaves_the_legacy_behaviour_alone(
            self, gated, monkeypatch):
        """The gate is opt-in: with no approved_clients, only retirement bites."""
        from types import SimpleNamespace
        monkeypatch.setattr(uploader, "_settings", lambda: SimpleNamespace(
            raw={"clients": _GATE_REGISTRY, "excluded_clients": ["SNM"]}))
        sidecar = gated("SDLN")
        assert uploader._resolve_targets(self._args(report=str(sidecar)))
        unreadable = gated(None, month="JUN_2026", raw="{ not json")
        assert uploader._resolve_targets(self._args(report=str(unreadable)))


# --------------------------------------------------------------------------- #
# _resolve_targets — the portal upload date gate (SKIPPED_PRE_DEC_2025).
#
# The portal takes appeals for December 2025 onward. Everything older in output/
# is back catalogue: an unfiltered `--all` swept 227 sidecars, most of them 2024 /
# early-2025 history. Enforced on BOTH invocation paths, like the client gate, and
# BEFORE it — a pre-cutoff report is ineligible whoever its client is.
# --------------------------------------------------------------------------- #
class TestResolveTargetsDateGate:
    @pytest.fixture
    def gated(self, tmp_path, monkeypatch):
        """An output/ tree whose clients all pass, so only the date gate can bite."""
        import json
        from types import SimpleNamespace

        out = tmp_path / "output"
        out.mkdir()
        monkeypatch.setattr(uploader, "_ROOT", tmp_path)
        monkeypatch.setattr(uploader, "_settings", lambda: SimpleNamespace(
            raw={"clients": _GATE_REGISTRY,
                 "excluded_clients": ["SNM"],
                 "approved_clients": _APPROVED}))

        def write(month="DEC_2025", period=None, client_name="UBOC", method="UT"):
            path = out / f"compiled_monthly_report_{method}_x_{month}.json"
            payload = {"client_name": client_name, "ndt_method": method}
            if period is not None:
                payload["reporting_period"] = period
            path.write_text(json.dumps(payload), encoding="utf-8")
            return path
        return write

    def _args(self, **kw):
        argv = []
        for flag, value in kw.items():
            argv += [f"--{flag}"] if value is True else [f"--{flag}", value]
        return build_parser().parse_args(argv)

    @pytest.mark.parametrize("month, period", [
        ("DEC_2024", "Dekabr 2024"),
        ("FEB_2024", "Fevral 2024"),
        ("APR_2025", "Aprel 2025"),
        ("AUG_2025", "Avqust 2025"),
        ("NOV_2025", "Noyabr 2025"),   # the last month on the wrong side
    ])
    def test_pre_cutoff_report_is_refused_on_the_single_report_path(
            self, gated, month, period):
        sidecar = gated(month=month, period=period)
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert "SKIPPED_PRE_DEC_2025" in str(exc.value)
        assert "prior to December 2025 portal upload cutoff" in str(exc.value)

    @pytest.mark.parametrize("month, period", [
        ("DEC_2025", "Dekabr 2025"),   # the cutoff month itself is eligible
        ("JAN_2026", "Yanvar 2026"),
        ("MAY_2026", "May 2026"),
    ])
    def test_cutoff_month_and_later_pass(self, gated, month, period):
        sidecar = gated(month=month, period=period)
        targets = uploader._resolve_targets(self._args(report=str(sidecar)))
        assert targets == [(sidecar, sidecar.with_suffix(".pdf"))]

    def test_sweep_keeps_only_reports_dated_december_2025_or_later(self, gated):
        keep_dec = gated(month="DEC_2025", period="Dekabr 2025")
        keep_feb = gated(month="FEB_2026", period="Fevral 2026")
        gated(month="FEB_2024", period="Fevral 2024")
        gated(month="DEC_2024", period="Dekabr 2024")
        gated(month="AUG_2025", period="Avqust 2025")
        targets = uploader._resolve_targets(self._args(all=True))
        assert sorted(s.name for s, _pdf in targets) == sorted(
            [keep_dec.name, keep_feb.name])

    def test_sweep_of_an_all_historical_tree_exits_naming_the_cutoff(self, gated):
        gated(month="FEB_2024", period="Fevral 2024")
        gated(month="APR_2025", period="Aprel 2025")
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(all=True))
        assert "SKIPPED_PRE_DEC_2025" in str(exc.value)

    def test_the_date_gate_runs_before_the_client_gate(self, gated):
        """A pre-cutoff report is ineligible whoever its client is — and says so."""
        sidecar = gated(month="FEB_2024", period="Fevral 2024",
                        client_name="Khazar Engineering")
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert "SKIPPED_PRE_DEC_2025" in str(exc.value)
        assert "approved_clients" not in str(exc.value)

    def test_the_filename_month_gates_a_sidecar_with_no_reporting_period(self, gated):
        """Legacy sidecars predate the field; the filename token still dates them."""
        sidecar = gated(month="AUG_2025", period=None)
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert "SKIPPED_PRE_DEC_2025" in str(exc.value)
        assert uploader._resolve_targets(
            self._args(report=str(gated(month="DEC_2025", period=None))))

    def test_reporting_period_wins_over_a_disagreeing_filename(self, gated):
        """The sidecar is what the payload is built from, so it is what is gated."""
        sidecar = gated(month="MAY_2026", period="Fevral 2024")
        with pytest.raises(SystemExit) as exc:
            uploader._resolve_targets(self._args(report=str(sidecar)))
        assert "SKIPPED_PRE_DEC_2025" in str(exc.value)


class TestSidecarPeriodStart:
    """The date the gate reads: sidecar first, filename token as the fallback."""

    def _write(self, tmp_path, name, payload):
        import json
        path = tmp_path / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                        encoding="utf-8")
        return path

    def test_reads_the_azerbaijani_reporting_period(self, tmp_path):
        p = self._write(tmp_path, "compiled_monthly_report_UT_x_MAY_2026.json",
                        {"reporting_period": "Dekabr 2025"})
        assert uploader._sidecar_period_start(p) == datetime.date(2025, 12, 1)

    def test_falls_back_to_the_filename_token(self, tmp_path):
        p = self._write(tmp_path, "compiled_monthly_report_UT_x_FEB_2024.json",
                        {"ndt_method": "UT"})
        assert uploader._sidecar_period_start(p) == datetime.date(2024, 2, 1)

    def test_unreadable_sidecar_still_dates_by_filename(self, tmp_path):
        p = self._write(tmp_path, "compiled_monthly_report_UT_x_APR_2025.json",
                        "{ not json")
        assert uploader._sidecar_period_start(p) == datetime.date(2025, 4, 1)

    @pytest.mark.parametrize("name", [
        "compiled_monthly_report_UT_x_SMARCH_2026.json",   # unknown month token
        "compiled_monthly_report_UT_x_FEB_26.json",        # two-digit year
        "report.json",                                     # no tokens at all
    ])
    def test_undatable_returns_none_and_is_not_skipped(self, tmp_path, name):
        """None means 'cannot gate' — the date gate refuses only PROVEN history."""
        p = self._write(tmp_path, name, {"ndt_method": "UT"})
        assert uploader._sidecar_period_start(p) is None

    def test_the_cutoff_is_the_first_of_december_2025(self):
        assert uploader.PORTAL_UPLOAD_CUTOFF == datetime.date(2025, 12, 1)
