"""The allowed-standards guardrail — approved norms compile, foreign ones quarantine.

Two layers:

* :func:`is_allowed_standard` in isolation, run against the REAL
  ``config/settings.yaml`` (so the shipped allowlist itself is under test, like
  ``test_client_exclusion`` does for ``excluded_clients``).
* ``discover_groups`` end-to-end: a document citing a disallowed standard is moved
  to ``input/SKIPPED_REPORTS/`` and dropped from the cache; allowed and
  blank-standard documents still form groups.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import pre_processor as pp                     # noqa: E402
from monthly_report.config import load_settings                   # noqa: E402
from monthly_report.method_registry import (                      # noqa: E402
    is_allowed_standard,
    is_allowed_standard_lenient,
)


@pytest.fixture(scope="module")
def settings():
    return load_settings(str(_ROOT / "config" / "settings.yaml"))


# --------------------------------------------------------------------------- #
# is_allowed_standard — the predicate, against the shipped config
# --------------------------------------------------------------------------- #
class TestIsAllowedStandard:
    @pytest.mark.parametrize("std", [
        "API 1104", "ASME B31.1", "ASME B31.3", "AWS D1.1", "API 5L",
        "EEMUA 153/158", "EEMUA 158", "ISO 17636", "ISO 17638", "ISO 17640",
    ])
    def test_curated_literals_are_allowed(self, std, settings):
        assert is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", [
        "ISO-17636", "iso 17636", "iso  17636", "ISO_17636", "  ISO 17636  ",
    ])
    def test_literal_match_is_separator_blind_and_case_insensitive(self, std, settings):
        assert is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["ASME V", "ASME VIII", "ASME IX", "ASME XII",
                                     "ASME-VIII", "asme viii", "ASME  IX"])
    def test_asme_roman_regex_matches(self, std, settings):
        assert is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["ASME", "ASME XIII", "ASME 8", "ASME VIIII",
                                     "ASME B31.1X"])
    def test_asme_regex_rejects_out_of_range_and_partials(self, std, settings):
        assert not is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["ISO 11666", "ISO 23278", "ISO 10675-1",
                                     "ISO 3452-1", "ASTM E1476", "AWS A4.2M"])
    def test_in_use_method_defaults_are_allowed(self, std, settings):
        """The `ndt_methods[*].default_standard` values must survive the guardrail,
        or a report that resolves to a method default would be quarantined."""
        assert is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["DNV-OS-F101", "ISO 9712", "EEMUA 197",
                                     "AWS D1.2", "SNT-TC-1A", "ASTM A388"])
    def test_foreign_standards_are_rejected(self, std, settings):
        assert not is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", ["", "   ", None])
    def test_blank_is_allowed(self, std, settings):
        """A standard we cannot read is not disproved — the fallback owns it."""
        assert is_allowed_standard(std, settings)

    def test_empty_list_disables_the_guardrail(self):
        allow_all = SimpleNamespace(raw={"allowed_standards": []})
        assert is_allowed_standard("DNV-OS-F101", allow_all)

    def test_missing_key_disables_the_guardrail(self):
        assert is_allowed_standard("DNV-OS-F101", SimpleNamespace(raw={}))


# --------------------------------------------------------------------------- #
# AZFEN client document-references (task 11-C)
# --------------------------------------------------------------------------- #
class TestAzfenDocumentReferences:
    """The seven AZF client doc-refs are allowed — and nothing else moved with them.

    These are not norms; they are the client's internal document numbers, printed
    in the source exactly as listed. They live in ``allowed_standards`` only, never
    in ``standarts/butun_standartlar.md``, so these tests are the single place that
    pins them.
    """

    _AZF = [
        "Doc No: Q01906 criteria Table 3",
        "Doc No: Q00255 criteria Table 5",
        "Q02412",
        "Q02401 Table 1",
        "Q02007 rev. AN. Table 8",
        "Q00255 rev. Z. Table 5",
        "Sec 11, Q02412 Rev C",
    ]

    @pytest.mark.parametrize("std", _AZF)
    def test_azf_doc_refs_are_allowed(self, std, settings):
        assert is_allowed_standard(std, settings)

    @pytest.mark.parametrize("std", [
        "Doc No: Q01906  criteria Table 3",     # double space, as some templates emit
        "doc no: q01906 criteria table 3",      # case
        "Doc No: Q01906-criteria-Table 3",      # hyphens for spaces
    ])
    def test_double_space_and_separator_variants_key_the_same(self, std, settings):
        """``_standard_key`` collapses runs of space/hyphen/underscore to one space,
        so the noisy spellings never need their own allowlist rows."""
        assert is_allowed_standard(std, settings)

    def test_comma_form_needs_the_whole_string(self, settings):
        """``Sec 11, Q02412 Rev C`` passes as a WHOLE literal, not by its head.

        ``_standard_head`` would cut it at the comma to ``Sec 11``, which is not an
        allowed value — proof that the literal itself is carrying this row.
        """
        assert is_allowed_standard("Sec 11, Q02412 Rev C", settings)
        assert not is_allowed_standard("Sec 11", settings)

    @pytest.mark.parametrize("std", [
        "GIS-42-103 / 341.4",
        "EP-GIS-18-016 / API5C6",
        "EP‐GIS‐18‐016 API5C6",     # Word-dashed (U+2010) spelling
        "GIS-42-103",
        "EP-GIS-18-016",
        "API5C6",
        "341.4",
    ])
    def test_sdln_doc_refs_stay_dropped(self, std, settings):
        """SDLN cites its own client doc-refs too — those were NOT approved.

        Pinned in both predicates: adding the AZF literals must not widen the gate
        for another client's numbers, and the lenient variant (used by the compile
        path) must not let them through a head/split retry either.
        """
        assert not is_allowed_standard(std, settings)
        assert not is_allowed_standard_lenient(std, settings)


# --------------------------------------------------------------------------- #
# discover_groups — the guardrail actually quarantines
# --------------------------------------------------------------------------- #
class TestGuardrailQuarantine:
    """Only the disallowed-FILENAME-standard file is moved; the rest compile.

    The per-file resolution helpers are stubbed to deterministic values keyed by
    filename (mirroring ``test_main_scope.TestDiscoverGroupsScope``); the filename
    standard is injected via the filename-metadata stub. The body extractor is
    stubbed to return a DISALLOWED value for every file, to prove the guardrail
    reads the filename only and never gates on the noisy body cell. Real files are
    written to disk so the quarantine ``os.replace`` has something to move.
    """

    # name -> (date, method, client, filename_standard)
    _SPECS = {
        "allowed.docx":    ("2025-06-01", "UT", "UBOC", "ISO 17636"),
        "disallowed.docx": ("2025-06-02", "UT", "UBOC", "DNV-OS-F101"),
        # filename standard blank — its body would say a disallowed standard, but
        # the guardrail must ignore the body and let it pass to the fallback.
        "blank.docx":      ("2025-06-03", "UT", "UBOC", ""),
    }

    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        for name in self._SPECS:
            (tmp_path / name).write_text("stub", encoding="utf-8")
        cache = {tmp_path / name: name for name in self._SPECS}
        by_name = self._SPECS

        monkeypatch.setattr(pp.extractor, "extract_meta",
                            lambda blocks: {"date": by_name[blocks][0], "name": blocks})
        monkeypatch.setattr(pp, "resolve_report_no", lambda meta, path: (path.name, None))
        monkeypatch.setattr(pp, "is_excluded", lambda name, rn: False)
        # Both entry points are stubbed. discover_groups reads the ``_ex`` variant
        # (it reports the KB-1 truncated-year repair); corpus_client_stats, called
        # from the same run, still reads the plain one. Patching the shared module
        # attribute covers every importer. Both take the report number the repair
        # needs (and the PDF-twin names KB-1b reads), and ignore both — this
        # fixture supplies whole ISO dates.
        monkeypatch.setattr(pp.date_detector, "parse_inspection_date",
                            lambda s, dayfirst=False, report_no="", twin_names=():
                            dt.date.fromisoformat(s))
        monkeypatch.setattr(pp.date_detector, "parse_inspection_date_ex",
                            lambda s, dayfirst=False, report_no="", twin_names=():
                            (dt.date.fromisoformat(s), None))
        monkeypatch.setattr(pp, "detect_method", lambda rn, settings: by_name[rn][1])
        monkeypatch.setattr(pp, "resolve_client_by_field",
                            lambda meta, rn, settings: (by_name[rn][2], ""))
        # Standard comes from the filename metadata. The body extractor returns a
        # DISALLOWED value for every file — the guardrail must never consult it.
        monkeypatch.setattr(pp.docx_reader, "parse_filename_metadata",
                            lambda path: {"standard": by_name[path.name][3] or None})
        monkeypatch.setattr(pp.extractor, "extract_standard",
                            lambda blocks: "DNV-OS-F101")

        settings = SimpleNamespace(input_dir=tmp_path, dayfirst=True,
                                   raw={"allowed_standards": ["ISO 17636"]})
        return settings, cache, tmp_path

    def test_disallowed_is_quarantined_allowed_and_blank_compile(self, wired):
        settings, cache, tmp_path = wired
        groups, quarantined = pp.discover_groups(settings, cache)

        # The foreign-standard file moved to SKIPPED_REPORTS and left the cache.
        skipped = tmp_path / pp.QUARANTINE_DIR / "disallowed.docx"
        assert skipped.exists()
        assert not (tmp_path / "disallowed.docx").exists()
        assert (tmp_path / "disallowed.docx") not in cache

        names = {n for n, _ in quarantined}
        reasons = {n: r for n, r in quarantined}
        assert names == {"disallowed.docx"}
        assert "unsupported standard" in reasons["disallowed.docx"]

        # Allowed and blank-standard files still form their group (one UT/UBOC group,
        # two files) and stay on disk.
        assert (tmp_path / "allowed.docx").exists()
        assert (tmp_path / "blank.docx").exists()
        assert {(m, cl) for m, cl, _n, _ms in groups} == {("2025-06", "UBOC")}
        count = {(m, cl): n for m, cl, n, _ms in groups}
        assert count[("2025-06", "UBOC")] == 2
