"""Typographic folding and composite-standard splitting in the portal matcher.

Two seams, both added 2026-09-09 (TAPŞIRIQ 09), both guarding the SAME invariant from
opposite sides: an appeal must name every normative document the inspection was judged
by, and must never name one it was not.

  * ``_normalize_typography`` folds look-alike punctuation so one document spelled two
    ways compares equal. It may only ever merge two spellings of ONE name — the tests
    below pin that it never merges two different names.
  * ``_STANDARD_ITEM_SPLIT`` cuts a cell naming several documents into its parts, so
    each is matched on its own. Splitting does not soften the gate: one unoffered part
    still refuses the whole report.

The corpus values exercised here are REAL — "API 1104 & ASME IX" (85 source cells),
"API 1104 + ASME B31.8" (4) and "API 1104 & ASME B31.3" (3) were counted off the
parse cache on 2026-09-09; "SET TO 80% FSH+2dB TR" is the acceptance-criterion text
that motivates the whitespace-flank rule on "+".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from uploader import (  # noqa: E402
    PORTAL_STANDARDS,
    _baseline_options,
    _normalize_typography,
    _standard_core,
    _standard_key,
    _standard_tokens,
    match_portal_standard,
    split_standards,
    unmatched_standards,
)
import uploader  # noqa: E402

#: A pinned alias map, so these tests do not read config/settings.yaml. Test data for
#: the split + alias machinery on real corpus cells, NOT the shipped map: its B31 entry
#: is hypothetical. The shipped map (operator, 2026-10-06) maps Roman-numeral Sections
#: only, because ASME B31.1 / B31.3 are portal options of their own.
_PINNED_ALIASES = {
    "ASME I-XII": [
        r"^ASME\s+(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)$",
        r"^ASME\s+B31(\.\d+)?$",
    ],
}

#: The map shipped in config/settings.yaml since 2026-10-06.
_SHIPPED_ALIASES = {
    "ASME I-XII": [r"^ASME\s+(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)$"],
}


@pytest.fixture(autouse=True)
def _pinned_aliases(monkeypatch):
    monkeypatch.setattr(uploader, "_standard_aliases", lambda: dict(_PINNED_ALIASES))


# --------------------------------------------------------------------------- folding


@pytest.mark.parametrize("written, plain", [
    ("ГОСТ 7512‐82", "ГОСТ 7512-82"),   # U+2010 hyphen
    ("ГОСТ 7512‑82", "ГОСТ 7512-82"),   # U+2011 nb hyphen
    ("ГОСТ 7512‒82", "ГОСТ 7512-82"),   # U+2012 figure dash
    ("ГОСТ 7512–82", "ГОСТ 7512-82"),   # U+2013 en dash
    ("ГОСТ 7512—82", "ГОСТ 7512-82"),   # U+2014 em dash
    ("ISO 17636", "ISO 17636"),                                                 # nbsp
    ("ISO 34352–1–4", "ISO 34352-1-4"),                                    # en dashes
])
def test_dashes_and_spaces_fold_to_their_ascii_originals(written, plain):
    """Word's autocorrect must not invent a second normative document."""
    assert _standard_key(written) == _standard_key(plain)


def test_curly_quotes_fold_to_straight_ones():
    assert _normalize_typography("AWS ‘D1.1’") == "AWS 'D1.1'"
    assert _normalize_typography("AWS “D1.1”") == 'AWS "D1.1"'


def test_nfkc_flattens_a_pasted_unicode_roman_numeral():
    """"ASME Ⅸ" (U+2168) is the same Section as "ASME IX" typed as two letters."""
    assert _normalize_typography("ASME Ⅸ") == "ASME IX"
    assert match_portal_standard("ASME Ⅸ", _baseline_options())[0] == "ASME I-XII"


def test_folding_is_idempotent_and_survives_blank_input():
    assert _normalize_typography("") == ""
    assert _normalize_typography(None) == ""
    once = _normalize_typography("ГОСТ Р 55611–2013")
    assert _normalize_typography(once) == once


# ------------------------------------------- folding must not merge two real standards


@pytest.mark.parametrize("left, right", [
    ("ISO 17636", "ISO 17638"),          # one digit apart — the whole risk in one pair
    ("ISO 17637", "ISO 17638"),
    ("ASTM E 384", "ASTM E 1351"),
    ("API 579", "API 5L"),
    ("API 1104", "API 510"),
    ("ГОСТ Р 55611", "ГОСТ Р 51780"),
    ("EEMUA 153/158", "EEMUA 157/158"),
])
def test_typography_folds_only_appearance(left, right):
    """The fold touches punctuation only; letters and digits distinguish documents."""
    assert _standard_key(left) != _standard_key(right)
    assert _standard_tokens(left) != _standard_tokens(right)


def test_every_portal_option_keeps_a_distinct_key_after_folding():
    """The fold may not collapse two options the portal offers separately."""
    keys = [_standard_key(o) for o in PORTAL_STANDARDS]
    assert len(set(keys)) == len(keys)


def test_every_portal_option_still_matches_itself_exactly():
    options = _baseline_options()
    for option in PORTAL_STANDARDS:
        assert match_portal_standard(option, options, _SHIPPED_ALIASES) == (
            option, "exact")


def test_the_fold_reaches_tokens_and_core_not_only_the_key():
    """All three comparison primitives normalize, or a rule could disagree with a rule."""
    assert _standard_tokens("ISO 17636") == _standard_tokens("ISO 17636")
    assert _standard_core("EEMUA–158,Edition 3") == _standard_core("EEMUA-158,Edition 3")


# ------------------------------------------------------------------------- composites


@pytest.mark.parametrize("cell, parts", [
    ("API 1104 & ASME IX", ["API 1104", "ASME IX"]),
    ("API 1104 + ASME B31.8", ["API 1104", "ASME B31.8"]),
    ("API 1104 & ASME B31.3", ["API 1104", "ASME B31.3"]),
    ("ASME VIII / ISO 17636", ["ASME VIII", "ISO 17636"]),
    ("ASME VIII and ISO 17636", ["ASME VIII", "ISO 17636"]),
    ("ASME VIII; ISO 17636", ["ASME VIII", "ISO 17636"]),
])
def test_a_cell_naming_several_documents_splits_into_all_of_them(cell, parts):
    assert split_standards(cell) == parts


@pytest.mark.parametrize("cell", [
    "EEMUA 153/158",                        # slash inside one name
    "ASTM E797/E797M",                      # slash inside one name
    "EEMUA 158,Edition 3,Section 7.5.4",    # commas inside an edition suffix
    "ISO 34352-1-4",                        # the portal's own range spelling
    "SET TO 80% FSH+2dB TR",                # unspaced plus in an acceptance criterion
    "API 1104 Block",                       # a calibration block, not a second standard
])
def test_a_single_name_is_never_cut_in_half(cell):
    assert split_standards(cell) == [cell]


def test_plus_splits_only_when_whitespace_flanks_it():
    """"A + B" is two documents; "FSH+2dB" is one acceptance level."""
    assert split_standards("API 1104 + ASME B31.8") == ["API 1104", "ASME B31.8"]
    assert split_standards("API 1104+ASME B31.8") == ["API 1104+ASME B31.8"]


def test_a_composite_folds_before_it_splits():
    """An en-dashed, nbsp-spaced cell splits exactly like its ASCII twin."""
    assert (split_standards("API 1104 & ASME IX")
            == split_standards("API 1104 & ASME IX"))


# ---------------------------------------------------- the all-or-nothing gate on parts


@pytest.mark.usefixtures("portal_2026_08_12")
def test_a_composite_passes_only_when_every_part_is_offered():
    options = _baseline_options()
    parts = split_standards("API 1104 & ASME IX")
    assert [match_portal_standard(p, options)[0] for p in parts] == [
        "API 1104", "ASME I-XII"]
    assert unmatched_standards(parts, options) == []


@pytest.mark.usefixtures("portal_2026_08_12")
def test_one_unoffered_part_refuses_the_whole_cell():
    """No partial filing: the offered half does not carry the unoffered half through."""
    options = _baseline_options()
    parts = split_standards("API 1104 & AWS D1.1")
    assert match_portal_standard("API 1104", options)[0] == "API 1104"
    assert match_portal_standard("AWS D1.1", options)[0] is None
    assert unmatched_standards(parts, options) == ["AWS D1.1"]


@pytest.mark.usefixtures("portal_2026_08_12")
def test_splitting_the_plus_stopped_a_silent_half_filing():
    """Regression for the reason "+" was added.

    Unsplit, "API 1104 + ASME B31.8" matched WHOLE against "API 1104" on the core rule
    (tokens up to the first digit-carrying one), so the appeal named one of the two
    documents and dropped the other without a word. Split, both are named.
    """
    options = _baseline_options()
    assert match_portal_standard("API 1104 + ASME B31.8", options) == ("API 1104", "core")
    named = [match_portal_standard(p, options)[0]
             for p in split_standards("API 1104 + ASME B31.8")]
    assert named == ["API 1104", "ASME I-XII"]


def test_blank_and_separator_only_cells_claim_nothing():
    for cell in ("", None, "   ", " & ", " + "):
        assert split_standards(cell) == []
        assert unmatched_standards(split_standards(cell)) == []


# ------------------------------------------- the compile-time allowlist gate folds too

def _settings():
    from monthly_report.config import load_settings
    return load_settings(_ROOT / "config" / "settings.yaml")


@pytest.mark.parametrize("written", [
    "ГОСТ 7512‐82",   # U+2010
    "ГОСТ 7512‑82",   # U+2011
    "ГОСТ 7512–82",   # U+2013
    "ГОСТ 7512—82",   # U+2014
    "ISO 17636",       # nbsp
])
def test_the_quarantine_gate_accepts_a_word_dashed_spelling(written):
    r"""`method_registry.is_allowed_standard` keys on the same fold as the portal.

    Before 2026-09-09 it normalized ASCII ``[\s_-]`` only, so a source that wrote the
    standard with Word's en dash was quarantined however carefully the ASCII spelling
    was added to ``allowed_standards`` — and the reason was invisible in the report.
    """
    from monthly_report.method_registry import is_allowed_standard
    assert is_allowed_standard(written, _settings())


def test_the_gate_still_rejects_a_foreign_code_in_either_spelling():
    """The fold must not turn the guardrail off. EP-GIS-18-016 is not a standard."""
    from monthly_report.method_registry import (is_allowed_standard,
                                                is_allowed_standard_lenient)
    settings = _settings()
    for spelling in ("EP‐GIS‐18‐016 API5C6", "EP-GIS-18-016 API5C6"):
        assert not is_allowed_standard(spelling, settings)
        assert not is_allowed_standard_lenient(spelling, settings)


def test_both_gates_share_one_fold_implementation():
    """One definition, so the offline gate and the portal gate cannot drift apart."""
    import uploader
    from monthly_report.text_norm import fold_typography
    assert uploader._normalize_typography is fold_typography
