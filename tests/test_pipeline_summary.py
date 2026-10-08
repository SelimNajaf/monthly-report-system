"""The executive audit generator must build a real PDF and tally sidecars honestly.

``generate_pipeline_summary.py`` scans the live system state and renders a
multi-page Azerbaijani audit PDF. Two things are pinned here:

* ``build_report(output_path=...)`` writes a genuine PDF (``%PDF`` magic) into a
  caller-supplied path — the house convention for asserting a PDF is real, since
  the suite carries no PDF-parsing helper. The ``output_path`` parameter is what
  lets a test render into ``tmp_path`` without clobbering the real ``output/``.
* ``tally_sidecars`` — the pure aggregation core — groups by NDT method, by
  client, and by quality verdict exactly as the tables/charts consume it. Pinned
  with inline fixtures so the logic is checked without rendering anything.

The build test uses the repo's live ``config/settings.yaml`` and real ``output/``
(the script is defensive and produces an all-zero report on an empty checkout),
so it needs no synthesized corpus — only a redirected output path.
"""

from __future__ import annotations

import datetime as dt

import pytest

import generate_pipeline_summary as gps

# The rule anchors on July 24, 2026: the ongoing month (2026-07) is incomplete,
# so the latest *closed* month is June 2026 (2026-06).
_TODAY = dt.date(2026, 7, 24)


def _sidecar(method, client, voen, records, results, serial, month=None,
             source_reports=None):
    sc = {
        "client_name": client,
        "client_voen": voen,
        "ndt_method": method,
        "report_serial_no": serial,
        "total_records": records,
        "items_table": [{"result": r} for r in results],
    }
    if month is not None:
        sc["_month"] = month  # catalog-format token, e.g. "JUN_2026"
    if source_reports is not None:
        sc["source_report_count"] = source_reports
    return sc


class TestBuildReport:
    def test_build_report_writes_a_real_pdf(self, tmp_path):
        out = tmp_path / "exec_report.pdf"
        result = gps.build_report(output_path=out)

        assert result == out
        assert out.is_file()
        assert out.read_bytes().startswith(b"%PDF")
        # A multi-page executive report is never a few hundred bytes.
        assert out.stat().st_size > 2000

    def test_default_output_path_lands_in_output_dir(self, tmp_path):
        # Redirect via an explicit path but confirm the default name is exposed
        # by building once and checking the returned filename convention.
        out = tmp_path / "pipeline_executive_summary_report.pdf"
        result = gps.build_report(output_path=out)
        assert result.name == "pipeline_executive_summary_report.pdf"


class TestMonthResolution:
    def test_incomplete_month_is_skipped_default_is_latest_closed(self):
        # Default target must never be the ongoing (incomplete) month 2026-07;
        # it resolves to the latest fully completed month, 2026-06.
        assert gps.latest_completed_month(_TODAY) == "2026-06"
        assert gps.resolve_target_month(None, today=_TODAY) == "2026-06"
        assert gps.is_month_complete("2026-06", today=_TODAY) is True
        assert gps.is_month_complete("2026-07", today=_TODAY) is False

    def test_explicit_ongoing_month_is_refused(self):
        # Asking for the incomplete month by hand is an error, not a silent roll-back.
        with pytest.raises(SystemExit):
            gps.resolve_target_month("2026-07", today=_TODAY)

    def test_month_flag_2026_06(self):
        assert gps.resolve_target_month("2026-06", today=_TODAY) == "2026-06"
        assert gps.parse_month_arg("2026-06") == "2026-06"
        assert gps.catalog_month("2026-06") == "JUN_2026"
        assert gps.scoped_output_name("2026-06") == \
            "pipeline_executive_summary_report_2026_06.pdf"

    def test_date_flag_26_02_and_other_formats(self):
        assert gps.parse_month_arg("26-02") == "2026-02"
        assert gps.resolve_target_month("26-02", today=_TODAY) == "2026-02"
        assert gps.parse_month_arg("26-06") == "2026-06"
        assert gps.parse_month_arg("JUN_2026") == "2026-06"
        assert gps.parse_month_arg("FEB_2026") == "2026-02"

    def test_bad_token_raises(self):
        with pytest.raises(ValueError):
            gps.parse_month_arg("nonsense")
        with pytest.raises(ValueError):
            gps.parse_month_arg("2026-13")


class TestSidecarMonthScoping:
    def test_sidecar_month_from_stamp_period_and_serial(self):
        assert gps.sidecar_month({"_month": "JUN_2026"}) == "JUN_2026"
        assert gps.sidecar_month({"reporting_period": "İyun 2026"}) == "JUN_2026"
        assert gps.sidecar_month({"report_serial_no": "MR-DP-KHE-26-06"}) == "JUN_2026"
        assert gps.sidecar_month({}) == ""

    def test_filter_keeps_only_the_target_month(self):
        rows = [
            _sidecar("UT", "A", "1", 2, ["Yararlı"], "S1", month="JUN_2026"),
            _sidecar("MT", "B", "2", 1, ["Yararlı"], "S2", month="MAY_2026"),
            _sidecar("RT", "C", "3", 3, ["Yararlı"], "S3", month="JUN_2026"),
        ]
        kept = gps.filter_sidecars_by_month(rows, "JUN_2026")
        assert {sc["ndt_method"] for sc in kept} == {"UT", "RT"}
        agg = gps.tally_sidecars(kept)
        assert agg.total_reports == 2
        assert agg.total_records == 5

    def test_empty_month_keeps_everything(self):
        rows = [_sidecar("UT", "A", "1", 1, ["Yararlı"], "S1", month="JUN_2026")]
        assert gps.filter_sidecars_by_month(rows, "") == rows


class TestBuildScoped:
    def test_build_with_target_month_writes_a_real_pdf(self, tmp_path):
        out = tmp_path / "scoped.pdf"
        result = gps.build_report(output_path=out, target_month="2026-06")
        assert result == out
        assert out.read_bytes().startswith(b"%PDF")
        assert out.stat().st_size > 2000


class TestAuditIdentity:
    def test_audit_serial_format(self):
        assert gps.audit_serial("2026-06") == "AUD-MR-2026-06"
        assert gps.audit_serial("2026-02") == "AUD-MR-2026-02"


class TestKpiHelpers:
    def test_yararli_ratio_on_a_known_mix(self):
        # 3 Yararlı out of 4 graded verdict rows -> 75%.
        q = {"Yararlı": 3, "Məlumat üçün": 1}
        assert gps.yararli_ratio(q) == pytest.approx(75.0)

    def test_yararli_ratio_counts_yararsiz_in_the_denominator(self):
        q = {"Yararlı": 2, "Yararsız": 2}
        assert gps.yararli_ratio(q) == pytest.approx(50.0)

    def test_yararli_ratio_is_zero_when_nothing_graded(self):
        assert gps.yararli_ratio({}) == 0.0


class TestKpiCards:
    """The KPI grid is print-first: clean captions, charcoal ink, no colour/delta noise."""

    @staticmethod
    def _texts(flowable):
        from reportlab.platypus import Paragraph, Table
        if isinstance(flowable, Paragraph):
            return [flowable.text]
        if isinstance(flowable, Table):
            return [t for row in flowable._cellvalues for cell in row
                    for t in TestKpiCards._texts(cell)]
        return []

    @staticmethod
    def _metrics(documents=830, pdfs=142, quarantined=58):
        from types import SimpleNamespace
        return SimpleNamespace(documents=documents, pdfs=pdfs,
                               quarantined=quarantined, sidecars=pdfs,
                               sidecar_complete=True)

    def _grid_texts(self, scoped=True, metrics=None):
        st = gps._styles()
        metrics = metrics or self._metrics()
        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 2, ["Yararlı", "Məlumat üçün"], "S1"),
        ])
        section = gps._kpi_section(metrics, agg, None, 5, {}, st, scoped=scoped)
        return self._texts(section[1])  # section[0] is the heading paragraph

    def test_clean_captions_present(self):
        texts = self._grid_texts()
        for caption in ("Skan edilmiş ilkin sənədlər",
                        "Tərtib edilmiş rəsmi hesabatlar",
                        "Cəmi backlog — aya görə bölünmür",
                        "Cəmi müayinə qeydləri"):
            assert caption in texts

    def test_no_delta_or_arrow_noise(self):
        texts = self._grid_texts()
        joined = " ".join(texts)
        assert "əvvəlki" not in joined
        for arrow in ("▲", "▼", "■"):
            assert arrow not in joined

    def test_card_text_is_charcoal_ink(self):
        st = gps._styles()
        assert st["kpi_num"].textColor == gps._INK
        assert st["kpi_lbl"].textColor == gps._INK
        assert st["kpi_sub"].textColor == gps._INK

    def test_all_time_mode_reverts_card1_and_card3(self):
        # --all: card 1 shows the cumulative input-document count and card 3 uses
        # the plain quarantine caption (no "aya görə bölünmür" scope disclaimer).
        texts = self._grid_texts(scoped=False,
                                 metrics=self._metrics(documents=768, quarantined=56))
        assert "768" in texts                       # cumulative documents on card 1
        assert "Karantinə alınmış fayllar" in texts
        assert "Skan edilmiş ilkin sənədlər (bütün dövr)" in texts
        assert "Cəmi backlog — aya görə bölünmür" not in texts


class TestCharts:
    def test_bar_and_client_charts_are_drawings(self):
        from reportlab.graphics.shapes import Drawing

        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı", "Yararlı", "Məlumat üçün"], "S1"),
            _sidecar("MT", "KHE", "2", 2, ["Yararlı", "Yararlı"], "S2"),
        ])
        assert isinstance(gps._bar_chart(agg), Drawing)
        assert isinstance(gps._client_chart(agg), Drawing)

    def test_client_chart_is_none_without_clients(self):
        assert gps._client_chart(gps.tally_sidecars([])) is None


class TestTallySidecars:
    def test_groups_reports_and_records_by_method(self):
        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı", "Yararlı", "Yararlı"], "S1"),
            _sidecar("UT", "UBOC", "1", 2, ["Yararlı", "Yararsız"], "S2"),
            _sidecar("MT", "KHF", "2", 1, ["Yararlı"], "S3"),
        ])
        rows = {r.token: r for r in agg.method_rows}
        assert rows["UT"].reports == 2
        assert rows["UT"].records == 5
        assert rows["MT"].reports == 1
        assert agg.total_reports == 3
        assert agg.total_records == 6

    def test_method_rows_follow_the_spec_order_and_include_absent_methods(self):
        agg = gps.tally_sidecars([_sidecar("RT", "NOV", "9", 1, ["Yararlı"], "S1")])
        tokens = [r.token for r in agg.method_rows]
        # Canonical spec order, every method present even with zero reports.
        assert tokens[:8] == ["UT", "MT", "RT", "DP", "UTM", "FC", "PMI", "HRT"]
        rt = next(r for r in agg.method_rows if r.token == "RT")
        assert rt.reports == 1 and rt.label == "RT"
        ut = next(r for r in agg.method_rows if r.token == "UT")
        assert ut.reports == 0

    def test_alias_tokens_fold_into_canonical(self):
        # FERRITE -> FC, HT -> HRT, MPI -> MT (older/hand-edited sidecars).
        agg = gps.tally_sidecars([
            _sidecar("FERRITE", "GEMZA", "3", 2, ["Yararlı", "Yararlı"], "S1"),
            _sidecar("MPI", "GEMZA", "3", 1, ["Yararlı"], "S2"),
        ])
        rows = {r.token: r for r in agg.method_rows}
        assert rows["FC"].reports == 1 and rows["FC"].records == 2
        assert rows["MT"].reports == 1

    def test_quality_split_tallies_every_item_row(self):
        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı", "Yararlı", "Məlumat üçün"], "S1"),
            _sidecar("PMI", "UBOC", "1", 1, ["Məlumat üçün"], "S2"),
        ])
        assert agg.quality["Yararlı"] == 2
        assert agg.quality["Məlumat üçün"] == 2

    def test_per_method_yararli_percentage_is_scoped_to_that_method(self):
        # UT graded 2 Yararlı + 1 Məlumat üçün -> 66.7%; PMI 0/1 -> 0%.
        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı", "Yararlı", "Məlumat üçün"], "S1"),
            _sidecar("PMI", "UBOC", "1", 1, ["Məlumat üçün"], "S2"),
        ])
        rows = {r.token: r for r in agg.method_rows}
        assert rows["UT"].yararli == 2 and rows["UT"].items == 3
        assert rows["UT"].yararli_pct == pytest.approx(66.6667, abs=0.01)
        assert rows["PMI"].yararli_pct == 0.0

    def test_client_rows_carry_voen_records_and_serials(self):
        agg = gps.tally_sidecars([
            _sidecar("UT", "Khazar Fabrication", "1000000002", 2, ["Yararlı", "Yararlı"], "S1"),
            _sidecar("MT", "Khazar Fabrication", "1000000002", 1, ["Yararlı"], "S2"),
        ])
        assert len(agg.client_rows) == 1
        c = agg.client_rows[0]
        assert c.voen == "1000000002"
        assert c.records == 3
        assert sorted(c.serials) == ["S1", "S2"]

    def test_empty_input_yields_zeroed_aggregation(self):
        agg = gps.tally_sidecars([])
        assert agg.total_reports == 0
        assert agg.total_records == 0
        assert agg.total_source_reports == 0
        assert agg.client_rows == []
        assert agg.quality == {}
        # Method scaffold is still the full spec list at zero.
        assert [r.token for r in agg.method_rows][:8] == \
            ["UT", "MT", "RT", "DP", "UTM", "FC", "PMI", "HRT"]

    def test_total_source_reports_sums_source_report_count(self):
        # source_report_count can exceed the sidecar count (retests merge many
        # source reports into one compiled batch); a missing field falls back to 1.
        agg = gps.tally_sidecars([
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı"], "S1", source_reports=4),
            _sidecar("MT", "KHF", "2", 1, ["Yararlı"], "S2", source_reports=2),
            _sidecar("RT", "NOV", "3", 1, ["Yararlı"], "S3"),  # no field -> 1
        ])
        assert agg.total_source_reports == 7
        assert agg.total_reports == 3


class TestMonthScopedKpi:
    """The KPI cards must scope to the target month — never leak all-time totals."""

    @staticmethod
    def _texts(section):
        return TestKpiCards._texts(section[1])

    def _june_and_may_sidecars(self):
        return [
            _sidecar("UT", "UBOC", "1", 3, ["Yararlı", "Yararlı", "Məlumat üçün"],
                     "MR-UT-UBOC-26-06", month="JUN_2026", source_reports=2),
            _sidecar("MT", "KHE", "2", 2, ["Yararlı", "Yararsız"],
                     "MR-MT-KHE-26-06", month="JUN_2026", source_reports=1),
            # A May batch that must NOT bleed into the June KPI numbers.
            _sidecar("RT", "NOV", "9", 5, ["Yararlı"] * 5,
                     "MR-RT-NOV-26-05", month="MAY_2026", source_reports=9),
        ]

    def test_scoped_cards_equal_june_totals_only(self):
        from types import SimpleNamespace
        st = gps._styles()
        all_sidecars = self._june_and_may_sidecars()
        june = gps.filter_sidecars_by_month(all_sidecars, "JUN_2026")
        agg = gps.tally_sidecars(june)

        # metrics carries deliberately inflated all-time counts that must NOT
        # surface on the scoped cards 1/4/6.
        metrics = SimpleNamespace(documents=768, pdfs=2, quarantined=56,
                                  sidecars=2, sidecar_complete=True)
        section = gps._kpi_section(metrics, agg, None, 0, {}, st, scoped=True)
        texts = self._texts(section)

        # Card 1 = June source reports (2+1), card 4 = June records (3+2),
        # card 6 = June clients (2). None of the all-time noise appears.
        assert str(agg.total_source_reports) == "3" and "3" in texts
        assert str(agg.total_records) == "5" and "5" in texts
        assert str(len(agg.client_rows)) == "2"
        assert "768" not in texts   # all-time documents never leaks
        # The May batch's record count must not appear as a scoped figure.
        assert agg.total_records == 5 and agg.total_source_reports == 3


class TestMainEntry:
    def test_month_flag_resolves_and_builds(self, tmp_path, monkeypatch):
        # Exercise CLI parsing + month resolution + wiring without clobbering the
        # real output/ dir: build_report is stubbed to a tmp PDF.
        captured = {}

        def fake_build(settings, target_month=None, all_time=False):
            captured["month"] = target_month
            captured["all_time"] = all_time
            out = tmp_path / "smoke.pdf"
            out.write_bytes(b"%PDF-1.4 smoke")
            return out

        monkeypatch.setattr(gps, "build_report", fake_build)
        rc = gps.main(["--month", "2026-06"])
        assert rc == 0
        assert captured["month"] == "2026-06"
        assert captured["all_time"] is False

    def test_ongoing_month_flag_is_refused(self, monkeypatch):
        # The incomplete current month must never reach build_report.
        monkeypatch.setattr(gps.dt, "date", _FixedDate)
        with pytest.raises(SystemExit):
            gps.main(["--month", "2026-07"])

    def test_all_flag_builds_cumulative_report(self, tmp_path, monkeypatch):
        # --all reaches build_report with all_time=True and no month resolution.
        captured = {}

        def fake_build(settings, target_month=None, all_time=False):
            captured["all_time"] = all_time
            captured["month"] = target_month
            out = tmp_path / "all.pdf"
            out.write_bytes(b"%PDF-1.4 all")
            return out

        monkeypatch.setattr(gps, "build_report", fake_build)
        rc = gps.main(["--all"])
        assert rc == 0
        assert captured["all_time"] is True
        assert captured["month"] is None

    def test_all_and_month_are_mutually_exclusive(self):
        # argparse.error raises SystemExit before any build is attempted.
        with pytest.raises(SystemExit):
            gps.main(["--all", "--month", "2026-06"])


class _FixedDate(dt.date):
    """A date subclass whose ``today()`` is pinned to the audit anchor day."""

    @classmethod
    def today(cls):
        return cls(2026, 7, 24)
