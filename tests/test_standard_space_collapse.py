"""Pin ``filtering.collapse_standard_spaces`` and ``text_norm.collapse_spaces``.

The corpus prints ONE normative document under two spellings that differ by a
single extra blank — ``"Doc No: Q01906  criteria Table 3"`` against the one-blank
form. On a sheet that goes to the state that reads as two documents, and the
PDF's range collapsing refuses to merge across it because ``_can_merge`` compares
the standard as raw text.

The fix is one call at the single point where the row's Standart value is read,
NOT a widening of ``fold_typography``: that function maps one spelling of a
single CHARACTER onto another, and a run of blanks is not that. The tests below
pin both halves — the collapse itself, and the contract that fold_typography
still leaves inner whitespace alone, so ``split_standards`` keeps returning the
text it returns today.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))
sys.path.insert(0, str(_ROOT))

from monthly_report.document_aggregator import (  # noqa: E402
    collapse_standard_spaces_enabled)
from monthly_report.method_registry import _standard_key  # noqa: E402
from monthly_report.text_norm import collapse_spaces, fold_typography  # noqa: E402

#: The one real pair in the corpus, both spellings verbatim.
TWO = "Doc No: Q01906  criteria Table 3"
ONE = "Doc No: Q01906 criteria Table 3"


def _cfg(**filtering):
    class _C:
        raw = {"filtering": dict(filtering)}
    return _C()


# --------------------------------------------------------------------------
# collapse_spaces
# --------------------------------------------------------------------------

def test_the_corpus_pair_collapses_onto_one_spelling():
    assert collapse_spaces(TWO) == ONE
    assert collapse_spaces(ONE) == ONE


def test_every_run_of_whitespace_becomes_one_space_and_the_ends_are_stripped():
    assert collapse_spaces("  ASME   B31.3\t\n ") == "ASME B31.3"
    assert collapse_spaces("EEMUA 158") == "EEMUA 158"   # NBSP is whitespace
    assert collapse_spaces("") == ""
    assert collapse_spaces(None) == ""


def test_it_never_touches_a_letter_a_digit_or_a_separator():
    """It may only merge two spellings of one name, never two names."""
    for value in ("ISO 17636", "ISO 17638", "ASTM E797/E797M", "EEMUA 153/158",
                  "EEMUA 158,Edition 3,Section 7.5.4", "ISO-23278",
                  "API 1104 & ASME IX", "Sec 11, Q02412 Rev C"):
        assert collapse_spaces(value) == value


# --------------------------------------------------------------------------
# The contract that keeps it OUT of fold_typography
# --------------------------------------------------------------------------

def test_fold_typography_still_leaves_inner_whitespace_alone():
    """Widening it would change what split_standards RETURNS, not just compares.

    Its mappings are character-for-character, which is what makes it safe to run
    over a normative document's name. A run of blanks is not a second spelling of
    one character.
    """
    assert fold_typography(TWO) == TWO
    assert fold_typography(TWO) != fold_typography(ONE)


def test_the_two_spellings_already_key_the_same_so_no_gate_changes():
    """The allowlist gate was never fooled — the PDF was."""
    assert _standard_key(TWO) == _standard_key(ONE)


def test_the_uploader_matcher_answers_the_same_for_both_spellings():
    import uploader as up

    assert up._standard_key(TWO) == up._standard_key(ONE)
    assert up._standard_tokens(TWO) == up._standard_tokens(ONE)
    # Not in the portal at all, which is why this fix cannot change an upload.
    assert up.match_portal_standard(TWO) == up.match_portal_standard(ONE)
    assert up.match_portal_standard(TWO)[0] is None


# --------------------------------------------------------------------------
# The switch
# --------------------------------------------------------------------------

def test_the_switch_is_on_when_absent_and_still_turns_off():
    class _Bare:
        raw = {"clients": {}}

    assert collapse_standard_spaces_enabled(_Bare()) is True
    assert collapse_standard_spaces_enabled(_cfg()) is True
    assert collapse_standard_spaces_enabled(_cfg(collapse_standard_spaces=True)) is True
    assert collapse_standard_spaces_enabled(_cfg(collapse_standard_spaces=False)) is False


# --------------------------------------------------------------------------
# What it buys the PDF
# --------------------------------------------------------------------------

def test_two_neighbours_spelled_differently_now_draw_as_one_range():
    """18 adjacent pairs across 10 documents were split by the blank alone."""
    import datetime as _dt

    from monthly_report.document_aggregator import (MonthlyReport, ReportRow,
                                                    collapse_display_rows)

    def _row(no, seq, standard):
        d = _dt.date(2026, 1, 5)
        return ReportRow(date=d, date_str=d.strftime("%d.%m.%Y"), report_no=no,
                         series_key=no, retest_rank=0, client="AZF",
                         document_name=no, standard=standard, item_detail="Boru",
                         result="Fit", method="RT", seq=seq, sort_key=(int(seq), 0))

    def _report(*rows):
        return MonthlyReport(month="2026-01", document_number="MR-AZF-26-01",
                             title="T", method="RT", client_code="AZF",
                             client_name="AZFEN", rows=list(rows))

    split = _report(_row("AZF-RT-W1-26-255", "1", TWO),
                    _row("AZF-RT-W1-26-256", "2", ONE))
    assert len(collapse_display_rows(split)) == 2

    fixed = _report(_row("AZF-RT-W1-26-255", "1", collapse_spaces(TWO)),
                    _row("AZF-RT-W1-26-256", "2", collapse_spaces(ONE)))
    merged = collapse_display_rows(fixed)
    assert len(merged) == 1
    assert merged[0].report_label == "AZF-RT-W1-26-(255-256)"
