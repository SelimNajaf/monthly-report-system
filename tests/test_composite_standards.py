"""Composite ``ACC Standard`` cells at the offline gate (task 11-D).

A body standard cell can name TWO documents at once ("API 1104 & ASME IX"). Before
this, :func:`is_allowed_standard_lenient` matched the whole string and then its head,
so such a cell was rejected and every row citing it was dropped — even though both
halves are approved norms. The gate now splits, but only as a LAST resort and only
with every part approved.

Two properties are pinned here:

* **Whole-first.** The allowlist, not the splitter, is the authority. An approved
  literal that itself contains a separator ("Sec 11, Q02412 Rev C") must match as a
  whole; if the split ran first it would be torn into halves on no list.
* **No partial pass.** A cell half-naming an unapproved document is refused whole.
  The row was assessed against that document too, and compiling it would put an
  unapproved norm into a report that goes to the state.

Plus a drift test: :data:`method_registry._STANDARD_ITEM_SPLIT` is a deliberate copy
of the uploader's constant, and the two must stay byte-identical.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from monthly_report import method_registry                                  # noqa: E402
from monthly_report.config import load_settings                             # noqa: E402
from monthly_report.method_registry import (                                # noqa: E402
    is_allowed_standard,
    is_allowed_standard_lenient,
    split_standard_parts,
)


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


# --------------------------------------------------------------------------- #
# The splitter itself
# --------------------------------------------------------------------------- #
class TestSplitStandardParts:
    @pytest.mark.parametrize("raw,parts", [
        ("API 1104 & ASME IX",        ["API 1104", "ASME IX"]),
        ("API 1104 + ASME B31.8",     ["API 1104", "ASME B31.8"]),
        ("ASME VIII / ISO 17636",     ["ASME VIII", "ISO 17636"]),
        ("API 1104 and ASME IX",      ["API 1104", "ASME IX"]),
        ("API 1104; ASME IX",         ["API 1104", "ASME IX"]),
        ("Sec 11, Q02412 Rev C",      ["Sec 11", "Q02412 Rev C"]),
    ])
    def test_splits_on_every_separator(self, raw, parts):
        assert split_standard_parts(raw) == parts

    @pytest.mark.parametrize("raw", [
        "EEMUA 153/158",                       # unspaced slash INSIDE one name
        "ASTM E797/E797M",
        "EEMUA 158,Edition 3,Section 7.5.4",   # unspaced commas in an edition suffix
        "Doc No: Q01906  criteria Table 3",    # no separator at all
        "ISO 17636",
    ])
    def test_single_names_are_never_torn(self, raw):
        assert split_standard_parts(raw) == [raw.strip()]

    @pytest.mark.parametrize("raw", ["", "   ", None])
    def test_blank_yields_nothing(self, raw):
        assert split_standard_parts(raw) == []

    def test_punctuation_only_parts_are_dropped(self):
        """A bare '+' names no document; returning it would refuse a report over it."""
        assert split_standard_parts("API 1104 + + ASME IX") == ["API 1104", "ASME IX"]


# --------------------------------------------------------------------------- #
# The gate — measured cases from the live corpus
# --------------------------------------------------------------------------- #
class TestLenientComposite:
    @pytest.mark.parametrize("std", [
        "API 1104 & ASME IX",        # 84 rows in the corpus, both halves approved
        "API 1104 & ASME B31.3",     # 3 rows
        "ASME VIII / ISO 17636",
        "ISO 17636 & ISO 17637",
    ])
    def test_composite_passes_when_every_part_is_approved(self, std, settings):
        assert is_allowed_standard_lenient(std, settings)
        # The whole string is NOT on the allowlist — the split is what carries it.
        assert not is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", [
        "GIS-42-103 / 341.4",            # 70 rows — BOTH halves unapproved
        "EP-GIS-18-016 /   API5C6",      # 108 rows — both unapproved
        "API 1104 and DNV-OS-F101",      # ONE half approved: still refused
        "ISO 17636 & EEMUA 197",
        "API 1104 + ASME B31.8",         # B31.8 is not on the list (B31.1/B31.3 are)
    ])
    def test_no_partial_pass(self, std, settings):
        assert not is_allowed_standard_lenient(std, settings)

    def test_whole_string_is_tried_before_the_split(self, settings):
        """``Sec 11, Q02412 Rev C`` passes as a WHOLE literal.

        The splitter tears it into ``["Sec 11", "Q02412 Rev C"]``. The second half
        survives on the head rule (``Q02412`` is an approved literal), but ``Sec 11``
        names no document and is on no list — so the split alone would DROP this row.
        Only the whole-string attempt saves it. Proved here rather than asserted: the
        parts are checked individually.
        """
        assert is_allowed_standard_lenient("Sec 11, Q02412 Rev C", settings)
        parts = split_standard_parts("Sec 11, Q02412 Rev C")
        assert len(parts) == 2
        assert not is_allowed_standard_lenient("Sec 11", settings)
        assert not all(is_allowed_standard_lenient(p, settings) for p in parts)

    def test_split_does_not_rescue_it_when_the_literal_is_removed(self):
        """Without its allowlist row, the same value is refused — whole-first is load-bearing."""
        without = SimpleNamespace(raw={"allowed_standards": ["API 1104", "ASME B31.3"]})
        assert not is_allowed_standard_lenient("Sec 11, Q02412 Rev C", without)
        assert is_allowed_standard_lenient("API 1104 & ASME B31.3", without)

    @pytest.mark.parametrize("std", [
        "EEMUA 158,Edition 3,Section 7.5.4",   # head rule, unchanged by task 11-D
        "ISO 17636 Table 5",
        "ISOP 10675-1",
        "", "   ", None,
    ])
    def test_pre_existing_behaviour_is_unchanged(self, std, settings):
        assert is_allowed_standard_lenient(std, settings)

    def test_strict_predicate_is_not_widened(self, settings):
        """``is_allowed_standard`` must stay strict — the pre_processor quarantine
        brake reads the FILENAME standard through it and was not part of task 11-D."""
        assert not is_allowed_standard("API 1104 & ASME IX", settings)
        assert not is_allowed_standard("ASME VIII / ISO 17636", settings)


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #
def test_split_regex_matches_the_uploader_copy():
    """The two copies of ``_STANDARD_ITEM_SPLIT`` must never diverge.

    The same cell is split on both sides of the pipeline — here to decide whether a
    row compiles, in the uploader to decide which portal options the appeal names. A
    difference means a row that compiles cannot be filed, or the reverse. They are
    copies rather than one import because the uploader's matching path is frozen.
    """
    import uploader
    assert method_registry._STANDARD_ITEM_SPLIT == uploader._STANDARD_ITEM_SPLIT
