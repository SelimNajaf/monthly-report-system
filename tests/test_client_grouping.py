"""ADR-004: one compiled document per (month × client), every NDT method inside it.

The grouping key lost its method half. A client's UT, MT, RT, DP and UTM reports for
one month used to compile to five separate deliverables, five serials and five portal
appeals; they now compile to ONE, and each row names its own method in the Üsul column
that was added for exactly this purpose (September 03, 2026).

What these tests pin is the set of things that quietly break when a key loses a
dimension — every one of them was found by tracing the old key rather than by a test
failing:

* the **cross-month retest pull** is method-scoped inside ``retest_tracker`` and was
  SKIPPED ENTIRELY when the aggregator was handed ``method=None``. That would have
  silently undone B1's traceability, so the aggregator now loops the methods its rows
  actually carry;
* ``_fill_missing_standards`` borrows a blank standard from "the batch", and the batch
  used to be one method. Widened to the whole document it would let a DP row inherit an
  MT row's ``EEMUA 158`` — the substitution the zero-substitution rule forbids, printed
  on a government sheet;
* the **row order** must keep same-method rows adjacent, or ``collapse_display_rows``
  (which only merges neighbours) shatters every range;
* the portal has ONE "Nəticə:" box for a document that may mix informational methods
  (UTM/HrT/PMI) with real ones.

Rendering is not exercised here — ``pdf_renderer`` was not changed by ADR-004 and has
its own tests. What is under test is which groups exist, which rows they carry, in what
order, and what the sidecar and the uploader make of them.
"""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import pre_processor                                 # noqa: E402
from monthly_report.config import load_settings                          # noqa: E402
from monthly_report.document_aggregator import (                         # noqa: E402
    ReportRow, _fill_missing_standards, build_monthly_report)
from monthly_report.json_exporter import build_report_json               # noqa: E402
from monthly_report.naming import default_output                         # noqa: E402


class _Translator:
    """Identity translation — keeps the assertions about VALUES, not wording."""

    untranslated: set = set()

    def term(self, text):
        return text


def _tables(report_no: str, client: str, date_str: str, standard: str,
            item: str = "Pipe"):
    """A metadata block ``extract_meta`` / ``extract_standard`` can read."""
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", client],
        ["ACC Standard:", standard],
        ["Item Inspection:", item],
    ]]


#: filename -> tables, so a cache can be built without python-docx or a parse.
_SPECS: dict[str, list] = {}


def _corpus(tmp_path: Path, specs, *, floor: int = 0):
    """Write a fake corpus and return ``(settings, cache)``.

    ``specs`` is ``(filename, report_no, client, date, standard)``. The volume floor
    defaults OFF so these tests measure grouping, not filtration — the corpus gate
    has its own coverage in ``test_pipeline_determinism``.
    """
    _SPECS.clear()
    cache: dict[Path, list] = {}
    for fname, report_no, client, date_str, standard in specs:
        path = tmp_path / fname
        path.write_text(fname, encoding="utf-8")
        tables = _tables(report_no, client, date_str, standard)
        _SPECS[fname] = tables
        cache[path] = tables
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.output_dir = str(tmp_path / "_out")
    cfg.target_month = "2026-05"
    cfg.raw["filtering"] = {"min_total_client_volume": floor}
    return cfg, cache


#: One UBOC month carrying three methods — the shape the whole ADR is about.
#: Report numbers use the corpus's real token positions so ``detect_method``
#: resolves them for real: -UT- -> UT, -MT- -> MT, -DP- -> DP (the TOKEN,
#: not the folder — method_folder maps MT -> MPI, and ADR-004 retired that
#: folder level entirely).
_MIXED = [
    ("U-UT-26-001.docx", "U-UT-26-001", "UBOC", "05.05.2026", "EEMUA 158"),
    ("U-UT-26-002.docx", "U-UT-26-002", "UBOC", "06.05.2026", "EEMUA 158"),
    ("U-MT-26-010.docx", "U-MT-26-010", "UBOC", "07.05.2026", "ASME VIII"),
    ("U-MT-26-011.docx", "U-MT-26-011", "UBOC", "08.05.2026", "ASME VIII"),
    ("U-DP-26-020.docx", "U-DP-26-020", "UBOC", "09.05.2026", "ISO 3452-1"),
]


# --------------------------------------------------------------------------- #
# Discovery — the key itself
# --------------------------------------------------------------------------- #
class TestTheGroupKeyIsMonthAndClient:
    def test_three_methods_of_one_client_month_form_ONE_group(self, tmp_path):
        cfg, cache = _corpus(tmp_path, _MIXED)

        groups, _q = pre_processor.discover_groups(cfg, cache)

        assert [(m, c, n) for m, c, n, _ms in groups] == [("2026-05", "UBOC", 5)]

    def test_the_methods_ride_along_as_a_report_never_as_a_key(self, tmp_path):
        """Position 4 of the tuple, sorted — for the log and the row filter only."""
        cfg, cache = _corpus(tmp_path, _MIXED)

        (group,), _q = pre_processor.discover_groups(cfg, cache)

        assert group[3] == ("DP", "MT", "UT")

    def test_two_clients_in_one_month_still_split(self, tmp_path):
        """The client half of the key is untouched — one PDF per client, always."""
        cfg, cache = _corpus(tmp_path, _MIXED + [
            ("KF-MT-26-030.docx", "KF-MT-26-030", "KHAZAR FABRICATION",
             "10.05.2026", "ASME VIII")])

        groups, _q = pre_processor.discover_groups(cfg, cache)

        assert sorted(c for _m, c, _n, _ms in groups) == ["KHF", "UBOC"]

    def test_two_months_of_one_client_still_split(self, tmp_path):
        cfg, cache = _corpus(tmp_path, _MIXED + [
            ("U-UT-26-090.docx", "U-UT-26-090", "UBOC", "03.06.2026", "EEMUA 158")])

        groups, _q = pre_processor.discover_groups(cfg, cache)

        assert sorted(m for m, _c, _n, _ms in groups) == ["2026-05", "2026-06"]

    def test_last_members_is_keyed_the_same_way(self, tmp_path):
        """main.py's incremental skip reads this side channel — same key or it lies."""
        cfg, cache = _corpus(tmp_path, _MIXED)

        pre_processor.discover_groups(cfg, cache)

        assert list(pre_processor.discover_groups.last_members) == [("2026-05", "UBOC")]


# --------------------------------------------------------------------------- #
# Aggregation — one document, many methods
# --------------------------------------------------------------------------- #
@pytest.fixture
def mixed_report(tmp_path):
    cfg, cache = _corpus(tmp_path, _MIXED)
    report = build_monthly_report(cfg, _Translator(), client_code="UBOC", cache=cache)
    return cfg, report


class TestOneDocumentCarriesEveryMethod:
    def test_every_method_of_the_client_month_is_in_the_document(self, mixed_report):
        _cfg, report = mixed_report

        assert len(report.rows) == 5
        assert {r.method for r in report.rows} == {"UT", "MT", "DP"}

    def test_each_row_names_its_own_method(self, mixed_report):
        """The Üsul column's value, resolved per document rather than per group."""
        _cfg, report = mixed_report
        by_no = {r.report_no: r.method for r in report.rows}

        assert by_no["U-UT-26-001"] == "UT"
        assert by_no["U-MT-26-010"] == "MT"
        assert by_no["U-DP-26-020"] == "DP"

    def test_the_report_level_method_is_the_joined_set(self, mixed_report):
        """Not records[0]'s method — that would name a mixed document after a row."""
        _cfg, report = mixed_report

        assert report.method == "DP/MT/UT"

    def test_rows_are_ordered_in_method_blocks(self, mixed_report):
        """collapse_display_rows only merges NEIGHBOURS with an equal method, so a
        pure date order would shatter every range it could otherwise draw."""
        _cfg, report = mixed_report

        assert [r.method for r in report.rows] == ["DP", "MT", "MT", "UT", "UT"]

    def test_inside_a_method_block_the_order_is_still_the_date(self, mixed_report):
        _cfg, report = mixed_report
        mpi = [r for r in report.rows if r.method == "MT"]

        assert [r.report_no for r in mpi] == ["U-MT-26-010", "U-MT-26-011"]

    def test_the_sequence_numbers_run_1_to_n_across_the_whole_document(self,
                                                                       mixed_report):
        _cfg, report = mixed_report

        assert [r.seq for r in report.rows] == ["1", "2", "3", "4", "5"]

    def test_a_method_scope_still_narrows_the_rows(self, tmp_path):
        """--method survives as a ROW filter — a diagnostic view, not a deliverable."""
        cfg, cache = _corpus(tmp_path, _MIXED)

        report = build_monthly_report(cfg, _Translator(), "UT",
                                      client_code="UBOC", cache=cache)

        assert {r.method for r in report.rows} == {"UT"}
        assert len(report.rows) == 2


# --------------------------------------------------------------------------- #
# The serial, the path and the sidecar
# --------------------------------------------------------------------------- #
class TestTheDeliverableIdentity:
    def test_the_serial_carries_no_method(self, mixed_report):
        _cfg, report = mixed_report

        assert report.document_number == "MR-UBOC-26-05"

    def test_the_output_path_has_no_method_folder_and_no_method_token(self, tmp_path):
        cfg, _cache = _corpus(tmp_path, _MIXED)

        path = default_output(cfg, "2026-05", subdir="UBOC", client="UBOC")

        assert path.name == "compiled_monthly_report_UBOC_MAY_2026.pdf"
        assert path.parent.name == "UBOC"

    def test_the_sidecar_names_every_method_two_ways(self, mixed_report):
        """``ndt_method`` stays a STRING (uploader.load_report_json requires the key
        and every existing sidecar has one); the list sits beside it."""
        cfg, report = mixed_report

        data = build_report_json(report, cfg, _Translator())

        assert data["ndt_method"] == "DP/MT/UT"
        assert data["ndt_methods"] == ["DP", "MT", "UT"]

    def test_the_sidecar_rows_still_carry_their_own_method(self, mixed_report):
        cfg, report = mixed_report

        data = build_report_json(report, cfg, _Translator())

        assert [r["method"] for r in data["items_table"]] == [
            "DP", "MT", "MT", "UT", "UT"]

    def test_a_single_method_document_is_unchanged_by_the_list_field(self, tmp_path):
        """Every pre-ADR-004 shape still round-trips: one token, one-item list."""
        cfg, cache = _corpus(tmp_path, _MIXED[:2])
        report = build_monthly_report(cfg, _Translator(), client_code="UBOC",
                                      cache=cache)

        data = build_report_json(report, cfg, _Translator())

        assert data["ndt_method"] == "UT"
        assert data["ndt_methods"] == ["UT"]


# --------------------------------------------------------------------------- #
# Zero substitution — the standards borrow must not cross a method boundary
# --------------------------------------------------------------------------- #
def _row(report_no, method, standard):
    d = _dt.date(2026, 5, 5)
    return ReportRow(date=d, date_str="05.05.2026", report_no=report_no,
                     series_key=report_no, retest_rank=0, client="UBOC",
                     document_name=report_no, standard=standard, item_detail="Pipe",
                     result="Fit", method=method)


class TestTheStandardsBorrowStaysInsideItsMethod:
    """``_fill_missing_standards`` batches by method, and that is load-bearing.

    A blank Standart cell borrows the batch's most common one. The batch was one
    method until ADR-004; across a merged document a DP row could inherit an MT row's
    ``EEMUA 158`` — a standard that inspection was never performed against, printed on
    an official sheet. That is exactly what the zero-substitution rule forbids.
    """

    def test_a_blank_cell_borrows_from_its_own_method(self):
        rows = [_row("U-MT-26-010", "MT", "ASME VIII"),
                _row("U-MT-26-011", "MT", "ASME VIII"),
                _row("U-MT-26-012", "MT", "")]

        _fill_missing_standards(rows)

        assert rows[2].standard == "ASME VIII"

    def test_a_blank_cell_never_borrows_across_a_method(self):
        rows = [_row("U-MT-26-010", "MT", "EEMUA 158"),
                _row("U-MT-26-011", "MT", "EEMUA 158"),
                _row("U-DP-26-020", "DP", "")]

        _fill_missing_standards(rows)

        assert rows[2].standard == ""       # stays blank, never inherits EEMUA 158

    def test_each_method_borrows_its_own_most_common_value(self):
        rows = [_row("U-MT-26-010", "MT", "EEMUA 158"),
                _row("U-MT-26-011", "MT", ""),
                _row("U-DP-26-020", "DP", "ISO 3452-1"),
                _row("U-DP-26-021", "DP", "")]

        _fill_missing_standards(rows)

        assert rows[1].standard == "EEMUA 158"
        assert rows[3].standard == "ISO 3452-1"

    def test_a_method_that_is_blank_throughout_stays_blank(self):
        """PMI / ferrite: no source standard is not a standard to be invented."""
        rows = [_row("U-MT-26-010", "MT", "EEMUA 158"),
                _row("U-PMI-26-030", "PMI", ""),
                _row("U-PMI-26-031", "PMI", "")]

        _fill_missing_standards(rows)

        assert [r.standard for r in rows[1:]] == ["", ""]


# --------------------------------------------------------------------------- #
# Cross-month retest parents — the pull that method=None used to switch off
# --------------------------------------------------------------------------- #
class TestCrossMonthParentsSurviveTheMergedGroup:
    """``retest_tracker`` filters on ONE method token and stamps it onto the rows it
    builds, and the aggregator only called it when ``method is not None``. Merging the
    group would therefore have disabled the whole pull — losing B1's traceability
    without a single test going red. The aggregator now loops the methods its rows
    carry.
    """

    _RETEST = [
        # April originals, in an earlier month than the compiled one.
        ("U-UT-26-001.docx", "U-UT-26-001", "UBOC", "05.04.2026", "EEMUA 158"),
        ("U-MT-26-010.docx", "U-MT-26-010", "UBOC", "06.04.2026", "ASME VIII"),
        # May retests of both — their parents must be pulled in.
        ("U-UT-26-001R1.docx", "U-UT-26-001R1", "UBOC", "05.05.2026", "EEMUA 158"),
        ("U-MT-26-010R1.docx", "U-MT-26-010R1", "UBOC", "06.05.2026", "ASME VIII"),
    ]

    def test_a_parent_is_pulled_for_every_method_in_the_document(self, tmp_path):
        cfg, cache = _corpus(tmp_path, self._RETEST)

        report = build_monthly_report(cfg, _Translator(), client_code="UBOC",
                                      cache=cache)

        assert report.pulled_parents == 2
        pulled = {r.report_no for r in report.rows if r.is_pulled_parent}
        assert pulled == {"U-UT-26-001", "U-MT-26-010"}

    def test_each_pulled_parent_keeps_its_own_method(self, tmp_path):
        cfg, cache = _corpus(tmp_path, self._RETEST)

        report = build_monthly_report(cfg, _Translator(), client_code="UBOC",
                                      cache=cache)
        by_no = {r.report_no: r.method for r in report.rows}

        assert by_no["U-UT-26-001"] == "UT"
        assert by_no["U-MT-26-010"] == "MT"

    def test_the_retest_is_lettered_off_its_own_pulled_parent(self, tmp_path):
        """``4`` -> ``4a`` still anchors, across a document that mixes methods."""
        cfg, cache = _corpus(tmp_path, self._RETEST)

        report = build_monthly_report(cfg, _Translator(), client_code="UBOC",
                                      cache=cache)
        seq = {r.report_no: r.seq for r in report.rows}

        assert seq["U-MT-26-010R1"] == seq["U-MT-26-010"] + "a"
        assert seq["U-UT-26-001R1"] == seq["U-UT-26-001"] + "a"

    def test_a_scoped_method_run_pulls_only_that_methods_parent(self, tmp_path):
        cfg, cache = _corpus(tmp_path, self._RETEST)

        report = build_monthly_report(cfg, _Translator(), "UT",
                                      client_code="UBOC", cache=cache)

        assert {r.report_no for r in report.rows if r.is_pulled_parent} == {
            "U-UT-26-001"}


# --------------------------------------------------------------------------- #
# The uploader's side of a multi-method document
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def uploader_mod():
    return pytest.importorskip("uploader")


class TestThePortalVerdictOfAMixedDocument:
    """One Nəticə box, several methods. "Məlumat üçün" only when EVERY method is
    informational — one real inspection makes the filing "Yararlı", because the
    weaker claim would be the wrong one to make about a document that contains
    pass/fail work."""

    def test_a_single_token_behaves_exactly_as_before(self, uploader_mod):
        assert uploader_mod.portal_result("UT") == uploader_mod.RESULT_FIT
        assert uploader_mod.portal_result("UTM") == uploader_mod.RESULT_INFORMATIONAL

    def test_one_real_method_makes_the_whole_filing_yararli(self, uploader_mod):
        assert uploader_mod.portal_result("DP/UTM") == uploader_mod.RESULT_FIT
        assert uploader_mod.portal_result("DP/MPI/UT/UTM") == uploader_mod.RESULT_FIT

    def test_an_all_informational_document_files_as_informational(self, uploader_mod):
        assert uploader_mod.portal_result("UTM/PMI") == \
            uploader_mod.RESULT_INFORMATIONAL

    def test_a_blank_method_is_still_yararli(self, uploader_mod):
        assert uploader_mod.portal_result("") == uploader_mod.RESULT_FIT


def _sidecar_file(tmp_path, **payload):
    path = tmp_path / "compiled_monthly_report_UBOC_MAY_2026.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class TestTheUploaderMethodFilterReadsTheSidecar:
    """``--method`` was a filename substring test; the filename carries no method
    token any more, and one document holds several."""

    def test_a_method_inside_the_document_matches(self, tmp_path, uploader_mod):
        path = _sidecar_file(tmp_path, ndt_method="DP/MT",
                             items_table=[{"method": "DP"}, {"method": "MT"}])

        assert uploader_mod._sidecar_has_method(path, "MT")
        assert uploader_mod._sidecar_has_method(path, "dp")     # case-insensitive

    def test_a_method_the_document_does_not_hold_is_filtered_out(self, tmp_path,
                                                                 uploader_mod):
        path = _sidecar_file(tmp_path, ndt_method="DP/MT",
                             items_table=[{"method": "DP"}, {"method": "MT"}])

        assert not uploader_mod._sidecar_has_method(path, "RT")

    def test_a_pre_adr004_sidecar_falls_back_to_its_root_token(self, tmp_path,
                                                               uploader_mod):
        path = _sidecar_file(tmp_path, ndt_method="MT", items_table=[{}])

        assert uploader_mod._sidecar_has_method(path, "MT")
        assert not uploader_mod._sidecar_has_method(path, "UT")

    def test_no_filter_keeps_everything(self, tmp_path, uploader_mod):
        path = _sidecar_file(tmp_path, ndt_method="MT", items_table=[])

        assert uploader_mod._sidecar_has_method(path, "")

    def test_an_unreadable_sidecar_is_narrowed_out_not_crashed_on(self, tmp_path,
                                                                  uploader_mod):
        path = tmp_path / "compiled_monthly_report_UBOC_MAY_2026.json"
        path.write_text("{not json", encoding="utf-8")

        assert not uploader_mod._sidecar_has_method(path, "UT")


class TestTheBlockedStandardReport:
    """Reporting only — the gate is untouched. One unlisted standard still refuses
    the WHOLE document and files nothing; this names what that cost."""

    _DATA = {
        "items_table": [
            {"method": "UT", "standard": "EP-GIS-18-016", "report_no": "U-UT-26-001"},
            {"method": "UT", "standard": "EP-GIS-18-016", "report_no": "U-UT-26-002"},
            {"method": "MT", "standard": "ASME VIII", "report_no": "U-MT-26-010"},
        ]
    }

    def test_it_names_the_standard_its_methods_and_its_row_count(self, uploader_mod):
        detail = uploader_mod._blocked_standard_detail(self._DATA, ["EP-GIS-18-016"])

        assert detail == [("EP-GIS-18-016", "UT", 2)]

    def test_nothing_unmatched_reports_nothing(self, uploader_mod):
        assert uploader_mod._blocked_standard_detail(self._DATA, []) == []

    def test_a_row_with_no_method_is_counted_not_dropped(self, uploader_mod):
        data = {"items_table": [{"standard": "EP-GIS-18-016", "report_no": "X"}]}

        assert uploader_mod._blocked_standard_detail(data, ["EP-GIS-18-016"]) == [
            ("EP-GIS-18-016", "?", 1)]


# --------------------------------------------------------------------------- #
# The console contract — the GUI parses these lines
# --------------------------------------------------------------------------- #
class TestTheScopeWarningIsInvisibleToTheProgressParser:
    """``--method`` compiles a PARTIAL document, so the run says so out loud — and
    the line must be claimed by none of the group patterns, or the GUI's compile
    progress bar counts a group that never rendered."""

    def test_the_partial_document_warning_produces_no_event(self):
        from monthly_report.gui.services.progress import PipelineProgressParser

        parser = PipelineProgressParser()
        line = ("  [scope] --method UT: compiled documents will carry UT rows ONLY "
                "— partial, not a deliverable.")

        assert parser.feed(line) is None


class TestTheGroupBannerStillCounts:
    def test_the_reworded_banner_is_still_read_as_a_group_total(self):
        """The parenthetical changed with the key; the regex ends at the digits."""
        from monthly_report.gui.services.progress import PipelineProgressParser

        parser = PipelineProgressParser()
        parser.feed("  Groups to compile: 12 (month x client)")

        assert parser.feed("[UBOC MAY 2026] -> compiled_monthly_report_UBOC_MAY_2026.pdf") \
            is not None
