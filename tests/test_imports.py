"""Structural smoke tests: every module imports cleanly, merger.py is gone."""

import importlib

import pytest

MODULES = [
    "monthly_report",
    "monthly_report.console",
    "monthly_report.text_norm",
    "monthly_report.naming",
    "monthly_report.report_identity",
    "monthly_report.method_registry",
    "monthly_report.retest_tracker",
    "monthly_report.document_aggregator",
    "monthly_report.pre_processor",
    "monthly_report.config",
    "monthly_report.cli",
    "monthly_report.json_exporter",
    "monthly_report.pdf_renderer",
    "monthly_report.docx_reader",
    "monthly_report.pdf_reader",
    "monthly_report.pdf_crosscheck",
    "monthly_report.extractor",
    "monthly_report.translator",
    "monthly_report.date_detector",
    "monthly_report.upload_ledger",
]


@pytest.mark.parametrize("name", MODULES)
def test_module_imports(name):
    importlib.import_module(name)


def test_merger_is_gone():
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("monthly_report.merger")


def test_month_tables_single_source():
    from monthly_report import json_exporter, naming, pdf_renderer
    assert pdf_renderer._AZ_MONTHS is naming.AZ_MONTHS
    assert json_exporter.reporting_period("2026-02") == "Fevral 2026"
    assert naming.reporting_period("garbage") == "—"


def test_default_output_shape(tmp_path):
    from monthly_report.naming import default_output

    class _S:
        output_dir = str(tmp_path)

    p = default_output(_S(), "2026-01", "UT", subdir="UT/UBOC", client="UBOC")
    assert p.name == "compiled_monthly_report_UT_UBOC_JAN_2026.pdf"
    assert p.parent.name == "UBOC" and p.parent.parent.name == "UT"
