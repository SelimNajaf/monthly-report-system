"""Pin the scoped-run path: CLI flags -> Scope -> narrowed stages.

``main.py`` used to take no arguments and compile every group. It now accepts
``--month/--method/--client`` (the same tokens the uploader and the GUI use) and
threads them into two stages: PDF conversion (method-only gate) and group
discovery (all three). The tests here cover the translation at the boundary
(``JUN_2025`` -> ``2025-06``), the two gates, and — the one that matters most —
that a default/empty scope leaves both stages behaving exactly as before.
"""

from __future__ import annotations

import datetime as dt
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from monthly_report import pre_processor as pp

# Minimal registry so the real detect_method classifies the test filenames.
_RAW = {"ndt_methods": {
    "UT": {"folder": "UT", "patterns": ["-UT-"]},
    "MPI": {"folder": "MPI", "patterns": ["-MT-"]},
}}


def _settings(tmp_path: Path, raw=None):
    return SimpleNamespace(input_dir=tmp_path, raw=raw if raw is not None else {},
                           dayfirst=True)


# --------------------------------------------------------------------------- #
# Month normalization
# --------------------------------------------------------------------------- #
class TestNormalizeMonth:
    @pytest.mark.parametrize("token", ["JUN_2025", "JUN 2025", "jun_2025",
                                       "2025-06", "2025-6"])
    def test_all_forms_canonicalize(self, token):
        assert main._normalize_month(token) == "2025-06"

    @pytest.mark.parametrize("token", ["", "JUNE_2025", "XYZ_2025", "2025",
                                       "2025-13", "13_2025", "garbage"])
    def test_bad_tokens_raise(self, token):
        with pytest.raises(ValueError):
            main._normalize_month(token)


class TestBuildScope:
    def test_flags_map_and_uppercase(self):
        args = main.build_parser().parse_args(
            ["--month", "JUN_2025", "--method", "ut", "--client", "uboc"])
        scope = main._build_scope(args)
        assert scope.month == "2025-06"
        assert scope.method == "UT"
        assert scope.client == "UBOC"
        assert not scope.is_empty

    def test_no_flags_is_empty_scope(self):
        scope = main._build_scope(main.build_parser().parse_args([]))
        assert scope == pp.Scope()
        assert scope.is_empty

    def test_bad_month_exits_2(self):
        args = main.build_parser().parse_args(["--month", "NOPE"])
        with pytest.raises(SystemExit) as exc:
            main._build_scope(args)
        assert exc.value.code == 2


class TestNoCleanFlag:
    """Housekeeping is on by default; --no-clean is the escape hatch."""

    def test_default_runs_housekeeping(self):
        assert main.build_parser().parse_args([]).no_clean is False

    def test_flag_disables_housekeeping(self):
        assert main.build_parser().parse_args(["--no-clean"]).no_clean is True

    def test_is_independent_of_scope(self):
        """Cleanup is global — the flag must not leak into the filter."""
        args = main.build_parser().parse_args(["--no-clean", "--method", "UT"])
        assert args.no_clean is True
        assert main._build_scope(args) == pp.Scope(method="UT")


# --------------------------------------------------------------------------- #
# Scope.matches — the predicate both gates lean on
# --------------------------------------------------------------------------- #
class TestScopeMatches:
    """``matches`` answers on ``(month, client)`` — ADR-004 dropped the method.

    No discovered group is method-specific any more: one client-month is one
    document holding every method. ``Scope.method`` survives because it still
    narrows PDF archiving / ``pdf_sources`` and becomes a ROW filter in the
    aggregator — but it can no longer select or reject a whole group, and the
    tests below pin exactly that.
    """

    def test_empty_matches_everything(self):
        assert pp.Scope().matches("2025-06", "UBOC")

    def test_each_dimension_is_anded(self):
        scope = pp.Scope(month="2025-06", client="UBOC")
        assert scope.matches("2025-06", "UBOC")
        assert not scope.matches("2025-07", "UBOC")  # wrong month
        assert not scope.matches("2025-06", "AZF")   # wrong client

    def test_month_alone_leaves_the_client_free(self):
        scope = pp.Scope(month="2025-06")
        assert scope.matches("2025-06", "UBOC")
        assert scope.matches("2025-06", "AZF")

    def test_client_is_case_insensitive(self):
        assert pp.Scope(client="UBOC").matches("2025-06", "uboc")

    def test_a_method_scope_never_rejects_a_group(self):
        """It filters rows downstream, not groups here."""
        scope = pp.Scope(method="UT")
        assert scope.matches("2025-06", "UBOC")
        assert scope.matches("2025-06", "KHF")


# --------------------------------------------------------------------------- #
# Conversion gate — method only, leave-untouched
# --------------------------------------------------------------------------- #
class TestArchiveMethodGate:
    """Scoping survived ADR-003 unchanged — only what the stage does changed."""

    def _seed(self, tmp_path):
        (tmp_path / "U-UT-26-010.pdf").write_bytes(b"%PDF UT")
        (tmp_path / "KF-MT-26-005.pdf").write_bytes(b"%PDF MT")

    def test_out_of_scope_pdf_is_left_entirely_untouched(self, tmp_path):
        self._seed(tmp_path)

        result = pp.archive_input_pdfs(_settings(tmp_path, _RAW), method="UT")

        assert result["archived"] == ["U-UT-26-010.pdf"]
        assert (tmp_path / pp.PDF_ARCHIVE_DIR / "U-UT-26-010.pdf").exists()
        # MT left exactly where it was — not archived, not recorded. A later
        # unscoped run must still find it.
        assert (tmp_path / "KF-MT-26-005.pdf").exists()
        assert not (tmp_path / pp.PDF_ARCHIVE_DIR / "KF-MT-26-005.pdf").exists()
        assert "KF-MT-26-005.pdf" not in result["archived"]
        assert all(n != "KF-MT-26-005.pdf" for n, _ in result["skipped"])

    def test_no_method_archives_everything(self, tmp_path):
        self._seed(tmp_path)
        result = pp.archive_input_pdfs(_settings(tmp_path, _RAW))
        assert sorted(result["archived"]) == ["KF-MT-26-005.pdf", "U-UT-26-010.pdf"]

    def test_indeterminate_method_is_never_skipped(self, tmp_path):
        """A filename with no registered token -> NDT -> archive under any scope."""
        (tmp_path / "MYSTERY-26-001.pdf").write_bytes(b"%PDF ??")
        result = pp.archive_input_pdfs(_settings(tmp_path, _RAW), method="UT")
        assert result["archived"] == ["MYSTERY-26-001.pdf"]

    def test_pdf_sources_honours_the_same_scope(self, tmp_path):
        self._seed(tmp_path)
        pp.archive_input_pdfs(_settings(tmp_path, _RAW))
        settings = _settings(tmp_path, _RAW)
        assert [p.name for p in pp.pdf_sources(settings, method="UT")] ==             ["U-UT-26-010.pdf"]
        assert sorted(p.name for p in pp.pdf_sources(settings)) ==             ["KF-MT-26-005.pdf", "U-UT-26-010.pdf"]


# --------------------------------------------------------------------------- #
# Group-discovery gate — all three dimensions, authoritative
# --------------------------------------------------------------------------- #
class TestDiscoverGroupsScope:
    """Filter the returned groups using the real parsed month/method/client.

    The per-file resolution helpers are stubbed to deterministic values keyed by
    filename, so the test exercises the scope filtering in isolation from the
    docx extractor.
    """

    _SPECS = {
        "a.docx": ("2025-06-01", "UT", "UBOC"),
        "b.docx": ("2025-06-02", "MT", "KHF"),
        "c.docx": ("2025-07-03", "UT", "UBOC"),
    }

    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        # cache value is the filename; extract_meta turns it into the spec.
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
        monkeypatch.setattr(pp, "detect_method",
                            lambda rn, settings: by_name[rn][1])
        monkeypatch.setattr(pp, "resolve_client_by_field",
                            lambda meta, rn, settings: (by_name[rn][2], ""))
        return _settings(tmp_path), cache

    def _month_clients(self, groups):
        return {(m, cl) for m, cl, _n, _methods in groups}

    def test_no_scope_returns_every_group(self, wired):
        settings, cache = wired
        groups, _q = pp.discover_groups(settings, cache)
        assert self._month_clients(groups) == {
            ("2025-06", "UBOC"), ("2025-06", "KHF"), ("2025-07", "UBOC")}

    def test_the_methods_a_group_holds_are_reported_not_keyed(self, wired):
        """ADR-004: the tokens ride along for the log, never in the key."""
        settings, cache = wired
        groups, _q = pp.discover_groups(settings, cache)
        methods = {(m, cl): ms for m, cl, _n, ms in groups}
        assert methods[("2025-06", "UBOC")] == ("UT",)
        assert methods[("2025-06", "KHF")] == ("MT",)

    def test_none_scope_equals_empty_scope(self, wired):
        settings, cache = wired
        assert pp.discover_groups(settings, dict(cache)) == \
            pp.discover_groups(settings, dict(cache), pp.Scope())

    def test_month_scope(self, wired):
        settings, cache = wired
        groups, _q = pp.discover_groups(settings, cache, pp.Scope(month="2025-06"))
        assert self._month_clients(groups) == {
            ("2025-06", "UBOC"), ("2025-06", "KHF")}

    def test_method_scope_selects_no_group_of_its_own(self, wired):
        """--method narrows rows downstream; every group is still discovered.

        Before ADR-004 this returned the two UT groups. A group is no longer a
        method's, so the filter has nothing to reject here — it reaches the
        aggregator instead, where it drops non-UT ROWS.
        """
        settings, cache = wired
        groups, _q = pp.discover_groups(settings, cache, pp.Scope(method="UT"))
        assert self._month_clients(groups) == {
            ("2025-06", "UBOC"), ("2025-06", "KHF"), ("2025-07", "UBOC")}

    def test_full_scope_pins_one_group(self, wired):
        settings, cache = wired
        groups, _q = pp.discover_groups(
            settings, cache, pp.Scope(month="2025-06", method="UT", client="UBOC"))
        assert self._month_clients(groups) == {("2025-06", "UBOC")}
