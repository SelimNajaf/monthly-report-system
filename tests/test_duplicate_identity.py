"""Transposed Report № merge — evidence rules, winner order and the OFF default.

``duplicate_identity.merge_duplicates`` collapses two compiled rows that are the
same report under two spellings (``DP-SDLN-26-060`` / ``SDLN-DP-26-060``). The
whole module is evidence-driven: the number is never enough, the **weld
identifiers** decide. These tests pin the four things that can go wrong:

* the switch is OFF unless the operator turns it on (it renumbers ``Sıra №``);
* two live documents with DISJOINT weld sets are two real inspections and must
  survive — a wrong merge deletes an inspection from a state document;
* an undecidable pair keeps BOTH rows and is named in ``report.skipped`` under the
  ``DUPLICATE_IDENTITY_UNDECIDED`` prefix;
* the surviving row is the live ``.docx``, never the archived PDF read of it.

Everything here is in-memory: records and ``(path, tables)`` pairs are built by
hand, no file is written, read, moved or renamed.
"""

from __future__ import annotations

import datetime as _dt
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import duplicate_identity                          # noqa: E402
from monthly_report.document_aggregator import ReportRow               # noqa: E402
from monthly_report.duplicate_identity import (                        # noqa: E402
    DISTINCT, DUPLICATE_IDENTITY_CHILD_UNMATCHED, DUPLICATE_IDENTITY_MERGED,
    DUPLICATE_IDENTITY_UNDECIDED, SAME,
    UNDECIDED, canon_key, merge_duplicates)

_INPUT = Path("C:/corpus/input") if sys.platform == "win32" else Path("/corpus/input")


def _settings(enabled: bool | None = True):
    """A Settings stand-in: only ``raw`` and ``input_dir`` are read."""
    filtering: dict = {}
    if enabled is not None:
        filtering["merge_duplicate_identities"] = enabled
    return SimpleNamespace(raw={"filtering": filtering}, input_dir=_INPUT)


def _row(report_no: str, *, client: str = "SDLN", method: str = "DP",
         rank: int = 0) -> ReportRow:
    return ReportRow(
        date=_dt.date(2026, 5, 15),
        date_str="15.05.2026",
        report_no=report_no,
        series_key=report_no,
        retest_rank=rank,
        client=client,
        document_name=report_no,
        standard="EEMUA 158",
        item_detail="Spool",
        result="Fit",
        method=method,
    )


def _tables(*weld_ids: str):
    """A metadata table plus a weld block ``extract_welds`` can read."""
    meta = [["Report No:", "n/a"], ["Date:", "15.05.2026"], ["Client:", "SDLN"]]
    welds = [["Weld No", "Result"]] + [[wid, "Accept"] for wid in weld_ids]
    return [meta, welds]


def _live(name: str):
    return _INPUT / name


def _archived(name: str):
    return _INPUT / "PDF_ARCHIVE" / name


# --------------------------------------------------------------------------- #
# 1 — the switch
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("enabled", [False, None])   # explicit false, and absent
def test_off_by_default_leaves_every_row_alone(enabled):
    """A mergeable pair is NOT merged while the flag is off — and produces no notes.

    The switch changes report.rows and therefore every Sıra № in the compiled
    document, so it stays off until the operator throws it.
    """
    records = [_row("DP-SDLN-26-060"), _row("SDLN-DP-26-060")]
    items = [(_live("DP-SDLN-26-060.docx"), _tables("W1", "W2")),
             (_archived("SDLN-DP-26-060.pdf"), _tables("W1", "W2"))]

    out, notes = merge_duplicates(records, items, _settings(enabled))

    assert out == records
    assert notes == []


# --------------------------------------------------------------------------- #
# 2 — the key
# --------------------------------------------------------------------------- #
def test_canon_key_is_order_blind_but_not_value_blind():
    assert canon_key("DP-SDLN-26-060") == canon_key("SDLN-DP-26-060")
    assert canon_key("KF-MT-25-081") != canon_key("KF-MT-25-082")


# --------------------------------------------------------------------------- #
# 3 — case A: two live documents, disjoint welds = two real inspections
# --------------------------------------------------------------------------- #
def test_two_live_documents_with_disjoint_welds_stay_distinct():
    """The case the whole module is ordered around: never merge two inspections."""
    records = [_row("DP-SDLN-26-061"), _row("SDLN-DP-26-061")]
    items = [(_live("DP-SDLN-26-061.docx"), _tables("W1", "W2")),
             (_live("SDLN-DP-26-061.docx"), _tables("W7", "W8"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert len(out) == 2                       # both inspections survive
    assert notes == []                         # DISTINCT is not the operator's problem
    assert merge_duplicates.last_stats[DISTINCT] == 1


# --------------------------------------------------------------------------- #
# 4 — case B: two live documents, identical welds = one report seen twice
# --------------------------------------------------------------------------- #
def test_two_live_documents_with_identical_welds_merge_deterministically():
    records = [_row("DP-SDLN-26-062"), _row("SDLN-DP-26-062")]
    items = [(_live("DP-SDLN-26-062.docx"), _tables("W1", "W2")),
             (_live("SDLN-DP-26-062.docx"), _tables("W1", "W2"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == ["DP-SDLN-26-062"]   # str(path) tiebreak
    assert notes == [("SDLN-DP-26-062.docx",
                      f"{DUPLICATE_IDENTITY_MERGED} SDLN-DP-26-062 -> DP-SDLN-26-062 "
                      f"(DP-SDLN-26-062.docx): iki canlı sənəd, tikiş dəstləri eyni")]
    assert merge_duplicates.last_stats[SAME] == 1


# --------------------------------------------------------------------------- #
# 5 — case C: two live documents, weld evidence incomplete
# --------------------------------------------------------------------------- #
def test_incomplete_weld_evidence_keeps_both_rows_and_names_the_pair():
    records = [_row("DP-SDLN-26-063"), _row("SDLN-DP-26-063")]
    items = [(_live("DP-SDLN-26-063.docx"), _tables("W1")),
             (_live("SDLN-DP-26-063.docx"), _tables())]      # no weld block

    out, notes = merge_duplicates(records, items, _settings())

    assert len(out) == 2
    assert len(notes) == 1
    file_name, reason = notes[0]
    assert file_name == "DP-SDLN-26-063.docx"
    assert reason.startswith(DUPLICATE_IDENTITY_UNDECIDED)
    assert "DP-SDLN-26-063 / SDLN-DP-26-063" in reason
    assert merge_duplicates.last_stats[UNDECIDED] == 1


# --------------------------------------------------------------------------- #
# 6 — case D: live document + archived PDF of the same job
# --------------------------------------------------------------------------- #
def test_archived_pdf_copy_merges_and_the_live_document_wins():
    """R1 winner order: live beats settled, and .docx beats the PDF read of it."""
    records = [_row("SDLN-DP-26-064"), _row("DP-SDLN-26-064")]
    items = [(_archived("SDLN-DP-26-064.pdf"), _tables("W1")),    # weaker, subset
             (_live("DP-SDLN-26-064.docx"), _tables("W1", "W2"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == ["DP-SDLN-26-064"]
    assert len(notes) == 1
    assert notes[0][0] == "SDLN-DP-26-064.pdf"
    assert notes[0][1].startswith(
        f"{DUPLICATE_IDENTITY_MERGED} SDLN-DP-26-064 -> DP-SDLN-26-064 ")
    assert merge_duplicates.last_stats[SAME] == 1


def test_settled_copy_of_a_different_job_is_undecided():
    """Same segments, different filename tail -> the job numbers disagree."""
    records = [_row("DP-SDLN-26-065"), _row("SDLN-DP-26-065")]
    items = [(_live("DP-SDLN-26-065 (2106).docx"), _tables("W1")),
             (_archived("SDLN-DP-26-065 (9999).pdf"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert len(out) == 2
    assert notes and "iş nömrəsi fərqli" in notes[0][1]
    assert merge_duplicates.last_stats[UNDECIDED] == 1


# --------------------------------------------------------------------------- #
# 7 — case E/F: no source file to weigh
# --------------------------------------------------------------------------- #
def test_pair_with_no_source_file_is_undecided_not_merged():
    records = [_row("DP-SDLN-26-066"), _row("SDLN-DP-26-066")]

    out, notes = merge_duplicates(records, [], _settings())

    assert len(out) == 2
    assert notes and "mənbə faylı tapılmadı" in notes[0][1]
    assert merge_duplicates.last_stats[UNDECIDED] == 1


# --------------------------------------------------------------------------- #
# 8 — what is never a candidate
# --------------------------------------------------------------------------- #
def test_retests_and_unrelated_numbers_are_never_touched():
    """A retest shares its parent's segments by design — it is not a duplicate."""
    records = [_row("DP-SDLN-26-067"),
               _row("DP-SDLN-26-067R1", rank=1),
               _row("DP-SDLN-26-068")]
    items = [(_live("DP-SDLN-26-067.docx"), _tables("W1")),
             (_live("DP-SDLN-26-067R1.docx"), _tables("W1")),
             (_live("DP-SDLN-26-068.docx"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == [r.report_no for r in records]
    assert notes == []
    assert merge_duplicates.last_stats.total() == 0


# --------------------------------------------------------------------------- #
# 9 — the archive tree is settled, wherever it sits
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("folder", ["PDF_ARCHIVE", "_PRUNED", "SKIPPED_REPORTS"])
def test_every_settled_tree_loses_to_the_live_document(folder):
    records = [_row("DP-SDLN-26-069"), _row("SDLN-DP-26-069")]
    items = [(_live("DP-SDLN-26-069.docx"), _tables("W1")),
             (_INPUT / folder / "SDLN-DP-26-069.docx", _tables("W1"))]

    out, _notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == ["DP-SDLN-26-069"]
    assert merge_duplicates.last_stats[SAME] == 1


# --------------------------------------------------------------------------- #
# 10 — chain merge: a SAME pair's retests inherit the parent's verdict
# --------------------------------------------------------------------------- #
def test_same_parent_pair_merges_same_suffix_retests_without_classifying_them():
    """The R1 pair is merged on the PARENT's verdict. Its own welds are disjoint —
    classified alone it would be DISTINCT — which proves classify() is not asked."""
    records = [_row("DP-SDLN-26-070"), _row("SDLN-DP-26-070"),
               _row("DP-SDLN-26-070R1", rank=1), _row("SDLN-DP-26-070R1", rank=1)]
    items = [(_live("DP-SDLN-26-070.docx"), _tables("W1", "W2")),
             (_archived("SDLN-DP-26-070.pdf"), _tables("W1")),
             (_archived("SDLN-DP-26-070R1.pdf"), _tables("W9")),
             (_live("DP-SDLN-26-070R1.docx"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == ["DP-SDLN-26-070", "DP-SDLN-26-070R1"]
    # Every dropped row is named, parent and inherited retest alike.
    assert [n[1].split(":")[0] for n in notes] == [
        f"{DUPLICATE_IDENTITY_MERGED} SDLN-DP-26-070 -> DP-SDLN-26-070 (DP-SDLN-26-070.docx)",
        f"{DUPLICATE_IDENTITY_MERGED} SDLN-DP-26-070R1 -> DP-SDLN-26-070R1 "
        f"(DP-SDLN-26-070R1.docx)"]
    assert merge_duplicates.last_stats[SAME] == 1          # parents only
    assert merge_duplicates.last_child_stats["inherited"] == 1


def test_retest_suffix_on_one_spelling_only_is_kept_and_noted():
    records = [_row("DP-SDLN-26-071"), _row("SDLN-DP-26-071"),
               _row("DP-SDLN-26-071R1", rank=1), _row("SDLN-DP-26-071R1", rank=1),
               _row("SDLN-DP-26-071R2", rank=2)]
    items = [(_live("DP-SDLN-26-071.docx"), _tables("W1")),
             (_archived("SDLN-DP-26-071.pdf"), _tables("W1")),
             (_live("DP-SDLN-26-071R1.docx"), _tables("W1")),
             (_archived("SDLN-DP-26-071R1.pdf"), _tables("W1")),
             (_archived("SDLN-DP-26-071R2.pdf"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert [r.report_no for r in out] == ["DP-SDLN-26-071", "DP-SDLN-26-071R1",
                                          "SDLN-DP-26-071R2"]
    merged = [n for n in notes if n[1].startswith(DUPLICATE_IDENTITY_MERGED)]
    notes = [n for n in notes if n not in merged]
    assert len(notes) == 1
    file_name, reason = notes[0]
    assert file_name == "SDLN-DP-26-071R2.pdf"
    assert reason.startswith(DUPLICATE_IDENTITY_CHILD_UNMATCHED)
    assert "SDLN-DP-26-071R2" in reason
    assert [n[0] for n in merged] == ["SDLN-DP-26-071.pdf", "SDLN-DP-26-071R1.pdf"]
    assert merge_duplicates.last_child_stats == {"inherited": 1, "unmatched": 1}


@pytest.mark.parametrize("parent_welds, verdict", [
    ((("W1",), ("W7",)), DISTINCT),     # two live documents, disjoint welds
    ((("W1",), ()), UNDECIDED),         # two live documents, incomplete evidence
])
def test_retests_of_a_pair_that_is_not_same_are_never_touched(parent_welds, verdict):
    wa, wb = parent_welds
    records = [_row("DP-SDLN-26-072"), _row("SDLN-DP-26-072"),
               _row("DP-SDLN-26-072R1", rank=1), _row("SDLN-DP-26-072R1", rank=1)]
    items = [(_live("DP-SDLN-26-072.docx"), _tables(*wa)),
             (_live("SDLN-DP-26-072.docx"), _tables(*wb)),
             (_live("DP-SDLN-26-072R1.docx"), _tables("W1")),
             (_live("SDLN-DP-26-072R1.docx"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings())

    assert len(out) == 4
    assert not any(DUPLICATE_IDENTITY_CHILD_UNMATCHED in n[1] for n in notes)
    assert merge_duplicates.last_stats[verdict] == 1
    assert merge_duplicates.last_child_stats.total() == 0


def test_chain_merge_is_off_with_the_switch():
    records = [_row("DP-SDLN-26-073"), _row("SDLN-DP-26-073"),
               _row("DP-SDLN-26-073R1", rank=1), _row("SDLN-DP-26-073R1", rank=1)]
    items = [(_live("DP-SDLN-26-073.docx"), _tables("W1")),
             (_archived("SDLN-DP-26-073.pdf"), _tables("W1")),
             (_live("DP-SDLN-26-073R1.docx"), _tables("W1")),
             (_archived("SDLN-DP-26-073R1.pdf"), _tables("W1"))]

    out, notes = merge_duplicates(records, items, _settings(False))

    assert out == records
    assert notes == []
    assert merge_duplicates.last_child_stats.total() == 0


# --------------------------------------------------------------------------- #
# 11 — R3-A: a merge never drops a row silently, and the note changes no row
# --------------------------------------------------------------------------- #
def test_merged_note_names_both_spellings_and_the_rows_are_unchanged():
    records = [_row("SDLN-DP-26-074"), _row("DP-SDLN-26-074"), _row("DP-SDLN-26-075")]
    items = [(_archived("SDLN-DP-26-074.pdf"), _tables("W1")),
             (_live("DP-SDLN-26-074.docx"), _tables("W1", "W2")),
             (_live("DP-SDLN-26-075.docx"), _tables("W3"))]

    out, notes = merge_duplicates(records, items, _settings())

    # Rows: exactly the pre-note result — the loser gone, everything else as is.
    assert out == [records[1], records[2]]
    assert [n[0] for n in notes] == ["SDLN-DP-26-074.pdf"]
    reason = notes[0][1]
    assert reason.startswith(DUPLICATE_IDENTITY_MERGED)
    assert "SDLN-DP-26-074" in reason and "DP-SDLN-26-074" in reason


def test_distinct_and_undecided_pairs_get_no_merged_note():
    records = [_row("DP-SDLN-26-076"), _row("SDLN-DP-26-076")]
    items = [(_live("DP-SDLN-26-076.docx"), _tables("W1")),
             (_live("SDLN-DP-26-076.docx"), _tables("W7"))]
    out, notes = merge_duplicates(records, items, _settings())
    assert len(out) == 2 and notes == []
