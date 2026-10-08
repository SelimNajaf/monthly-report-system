"""Azerbaijani-safe text normalisation for case-insensitive token matching.

Python's ``str.casefold`` follows the default Unicode rules, which mangle the
Azerbaijani dotted capital ``İ`` (U+0130): it folds to ``i`` **plus** U+0307
COMBINING DOT ABOVE, so ``"İmtina".casefold()`` does not contain ``"imtina"``
and a rejected weld silently reads as accepted. :func:`fold` resolves the dot so
the two forms compare equal.

Also home to :func:`unique_ordered`, the shared "collapse a column of cell values
into a distinct, first-seen-order list" helper. It lives here rather than in
``uploader.py`` (where it began) because both sides of the sidecar contract need
it — the exporter to build ``equipment_used``, the uploader to build the
inspection object and the standards list — and ``monthly_report`` must not import
the root-level uploader: the dependency runs the other way.

I/O contract
------------
fold(text) -> str             # casefolded, dot-resolved, safe for substring matching
fold_typography(text) -> str  # look-alike punctuation -> ASCII, NFKC applied
collapse_spaces(text) -> str  # runs of whitespace -> one space, ends stripped
unique_ordered(values) -> list[str]   # distinct, first-seen order, blanks dropped
"""

from __future__ import annotations

import unicodedata

# U+0307 COMBINING DOT ABOVE — what casefold() leaves behind on İ.
_COMBINING_DOT_ABOVE = "̇"

#: Look-alike characters an office suite substitutes for their ASCII originals.
#: Word autocorrects a typed "-" into an en dash and a typed quote into a curly one,
#: so the same normative document reaches us spelled two ways depending on which
#: office wrote the report — `EP‐GIS‐18‐016` in the SDLN UT corpus carries U+2010
#: hyphens, not ASCII ones, which is why an ASCII spelling added to the allowlist
#: would silently fail to match it.
_TYPOGRAPHIC_FOLD = {
    # Dashes: U+2010 hyphen, U+2011 non-breaking hyphen, U+2012 figure dash,
    # U+2013 en dash, U+2014 em dash, U+2015 horizontal bar, U+2212 minus sign,
    # U+FF0D fullwidth hyphen-minus. Every one of them means "-" in "ГОСТ 7512-82".
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-",
    "\u2014": "-", "\u2015": "-", "\u2212": "-", "\uff0d": "-",
    # Quotes and primes: curly single/double, modifier apostrophe, prime/double prime.
    "\u2018": "'", "\u2019": "'", "\u02bc": "'", "\u2032": "'",
    "\u201c": '"', "\u201d": '"', "\u2033": '"',
    # Spaces (and the zero-width one) NFKC does not flatten in every build.
    "\u00a0": " ", "\u2007": " ", "\u202f": " ", "\u200b": "",
}


def fold_typography(text: str) -> str:
    """Fold look-alike punctuation to ASCII and apply NFKC. Appearance only.

    Two documents named the same way must compare equal however the source office
    typed them, so an en dash reads as a hyphen and a curly apostrophe as a straight
    one. NFKC additionally flattens fullwidth forms and Unicode Roman numerals, so a
    pasted ``"ASME Ⅸ"`` (U+2168) becomes ``"ASME IX"``.

    NOT a substitution seam, and that is the whole reason it is safe to run over a
    standard's name. Every mapping is between two spellings of ONE character; none
    touches a letter or a digit, which is what actually distinguishes one normative
    document from another — ``ISO 17636`` and ``ISO 17638`` differ in a digit. So the
    fold can only ever merge two spellings of one name, never two names. Applied to
    the candidate and to the allowlist/portal entry alike, so it cannot pull a
    matching pair apart either.

    Distinct from :func:`fold`, which resolves the Azerbaijani dotted İ for CASE
    matching. This one is about punctuation, and the two compose in either order.
    """
    s = str(text or "")
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    if any(c in _TYPOGRAPHIC_FOLD for c in s):
        s = "".join(_TYPOGRAPHIC_FOLD.get(c, c) for c in s)
    return s


def collapse_spaces(text: str) -> str:
    """Collapse every run of whitespace to ONE space and strip the ends.

    Deliberately NOT part of :func:`fold_typography`. That function's contract is
    character-for-character — every entry of ``_TYPOGRAPHIC_FOLD`` maps one
    spelling of a single character onto another, which is what makes it safe to
    run over a normative document's name. A run of blanks is not a second
    spelling of one character, and folding it there would quietly change what
    ``split_standard_parts`` and ``uploader.split_standards`` RETURN, i.e. the
    text that reaches the portal form and the logs.

    Measured on 2026-09-18: the corpus holds 23 distinct standard values, and
    exactly one pair of them differs by nothing but this —
    ``"Doc No: Q01906  criteria Table 3"`` (two blanks, 89 rows / 17 documents)
    against the one-blank spelling (186 rows / 15 documents). The same normative
    document, printed two ways in one official table.
    """
    return " ".join(str(text or "").split())


def fold(text: str) -> str:
    """Case-fold ``text`` so dotted ``İ`` matches a plain lowercase ``i``.

    Normalising to NFC first means both spellings of the character are covered:
    the composed ``İ`` (U+0130) and the decomposed ``I`` + U+0307 that Word
    exports emit. Both compose to U+0130, casefold to ``i`` + U+0307, and lose
    the dot here — so ``fold("İmtina") == "imtina"`` either way.

    Only the dot is resolved. The full Turkic rule (``I`` -> ``ı``) is
    deliberately NOT applied: it would fold ASCII tokens like ``Accept/Reject``
    and ``ASR`` into dotless-ı forms and break the matching that already works.
    """
    folded = unicodedata.normalize("NFC", text or "").casefold()
    return folded.replace(_COMBINING_DOT_ABOVE, "")


def unique_ordered(values) -> list[str]:
    """De-duplicate while preserving first-seen order, dropping blanks.

    Order matters: the operator reviewing the draft reads these fields against the
    PDF's table, and a set() would shuffle them differently on every run.
    """
    seen: list[str] = []
    for raw in values:
        text = str(raw or "").strip()
        if text and text not in seen:
            seen.append(text)
    return seen
