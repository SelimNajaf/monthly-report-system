"""Tests for Azerbaijani-safe case-folding.

The bug this pins: the dotted capital U+0130 casefolds to ``i`` + U+0307
(combining dot above), which does not contain the reject token ``"imtina"`` --
so a rejected weld rolled up as accepted.

Fixtures are built from explicit code points rather than typed glyphs: an
editor or encoding round-trip would happily normalise a literal into the very
form these tests exist to distinguish.
"""

import unicodedata

from monthly_report.text_norm import fold

_DOTTED_CAPITAL = "İ"            # composed: LATIN CAPITAL LETTER I WITH DOT ABOVE
_COMBINING_DOT = "̇"             # COMBINING DOT ABOVE
_DOTLESS_LOWER = "ı"             # LATIN SMALL LETTER DOTLESS I

_COMPOSED = _DOTTED_CAPITAL + "mtina"          # "İmtina"
_DECOMPOSED = "I" + _COMBINING_DOT + "mtina"   # same word, NFD spelling
_YARASIZ = "yaras" + _DOTLESS_LOWER + "z"      # "yarasız"


def test_fixtures_are_the_two_distinct_spellings():
    assert _COMPOSED != _DECOMPOSED
    assert unicodedata.normalize("NFD", _COMPOSED) == _DECOMPOSED
    # The bug itself: plain casefold leaves a combining dot behind.
    assert "imtina" not in _COMPOSED.casefold()


def test_composed_dotted_capital_folds_to_plain_i():
    assert fold(_COMPOSED) == "imtina"


def test_decomposed_dotted_capital_folds_the_same():
    assert fold(_DECOMPOSED) == "imtina"
    assert fold(_COMPOSED) == fold(_DECOMPOSED)


def test_no_combining_dot_survives():
    assert _COMBINING_DOT not in fold(_COMPOSED)
    assert _COMBINING_DOT not in fold(_DECOMPOSED)


def test_reject_tokens_are_matchable_after_folding():
    assert "imtina" in fold("Nəticə: " + _COMPOSED)   # "Nəticə: İmtina"
    assert "reject" in fold("REJECTED")
    assert _YARASIZ in fold(_YARASIZ.capitalize())


def test_ascii_is_unchanged_apart_from_case():
    assert fold("Accept/Reject") == "accept/reject"
    assert fold("REJECT") == "reject"
    # The Turkic I -> ı rule is deliberately NOT applied: ASCII I folds to i, so
    # the existing ASCII tokens keep matching.
    assert fold("INFO") == "info"
    assert fold("YARASIZ") == "yarasiz"


def test_dotless_i_survives():
    assert fold(_YARASIZ) == _YARASIZ


def test_empty_and_none():
    assert fold("") == ""
    assert fold(None) == ""


def test_idempotent():
    for text in (_COMPOSED, _DECOMPOSED, _YARASIZ, "Accept/Reject", ""):
        assert fold(fold(text)) == fold(text)
