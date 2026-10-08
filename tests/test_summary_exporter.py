"""The monthly summary export: the dashboard's live view, as a CSV or JSON file.

No Qt and no real pipeline — a fabricated ``Catalog`` of ``Artifact`` rows and a
``Metrics`` are enough to pin the two writers, the format inference, and the scope
filtering the export inherits from the catalog.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from monthly_report.gui.services import summary_exporter
from monthly_report.gui.services.catalog import ALL, Artifact, Catalog
from monthly_report.gui.services.metrics import Metrics


def _catalog() -> Catalog:
    return Catalog(artifacts=(
        # ADR-004: one document per client-month, so a row lists every method it
        # holds and there is no method folder to export.
        Artifact(pdf=Path("r_KHF_FEB_2026.pdf"), client="KHF",
                 month="FEB_2026", methods=("DP", "MT")),
        Artifact(pdf=Path("r_AZF_FEB_2026.pdf"), client="AZF",
                 month="FEB_2026", methods=("RT",)),
    ))


_METRICS = Metrics(documents=5, pdfs=2, sidecars=1, quarantined=1, archived_pdfs=3)


class TestJson:
    def test_json_round_trips_reports_and_metrics(self, tmp_path):
        out = tmp_path / "summary.json"
        summary_exporter.export_summary(out, _catalog(), _METRICS,
                                        (ALL, ALL, ALL), "json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["report_count"] == 2
        assert data["metrics"]["pdfs"] == 2
        assert {r["client"] for r in data["reports"]} == {"KHF", "AZF"}

    def test_format_inferred_from_suffix(self, tmp_path):
        out = tmp_path / "summary.json"
        summary_exporter.export_summary(out, _catalog(), _METRICS, (ALL, ALL, ALL))
        json.loads(out.read_text(encoding="utf-8"))  # parses = it wrote JSON


class TestCsv:
    def test_csv_has_a_row_per_report_plus_a_metrics_header(self, tmp_path):
        out = tmp_path / "summary.csv"
        summary_exporter.export_summary(out, _catalog(), _METRICS, (ALL, ALL, ALL))
        text = out.read_text(encoding="utf-8")
        assert "# Monthly Report Summary" in text
        assert "r_KHF_FEB_2026.pdf" in text
        assert "r_AZF_FEB_2026.pdf" in text


class TestScope:
    def test_filters_narrow_the_exported_rows(self, tmp_path):
        out = tmp_path / "summary.json"
        summary_exporter.export_summary(out, _catalog(), _METRICS,
                                        (ALL, "MT", ALL), "json")
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["report_count"] == 1
        assert data["reports"][0]["methods"] == "DP/MT"
