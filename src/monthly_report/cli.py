"""Command-line entrypoint — orchestrates the full automated pipeline.

    read config -> scan input/ .docx -> detect date & filter by month ->
    extract (header-driven) -> retest-number & merge -> render Azerbaijani PDF ->
    report skipped files and untranslated gaps

Usage
-----
    monthly-report --month 2026-01
    python -m monthly_report.cli --month 2026-01

``--month`` overrides ``target_month`` in config/settings.yaml.
"""

from __future__ import annotations

import argparse
import datetime as _dt
from pathlib import Path

from . import config, document_aggregator, pdf_renderer
from .console import enable_utf8_console, safe_print
from .naming import default_output
from .translator import Translator, load_dictionary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monthly-report",
        description="Generate the Azerbaijani monthly inspection report PDF.",
    )
    parser.add_argument("--month", metavar="YYYY-MM",
                        help="Target inspection month (overrides config/settings.yaml).")
    parser.add_argument("--config", default="config/settings.yaml",
                        help="Path to settings.yaml (default: config/settings.yaml).")
    parser.add_argument("--out", metavar="PATH",
                        help="Output PDF path (default: output/compiled_monthly_report_<MON>_<YYYY>.pdf).")
    return parser


def main(argv: list[str] | None = None) -> int:
    enable_utf8_console()   # report names carry Azerbaijani glyphs — see console.py
    args = build_parser().parse_args(argv)
    settings = config.load_settings(args.config)
    if args.month:
        settings.target_month = args.month

    translator = Translator(load_dictionary(settings.translations_path), settings)
    report = document_aggregator.build_monthly_report(settings, translator)

    if not report.rows:
        safe_print(f"[!] No reports matched month {settings.target_month}. Nothing to render.")
        for name, reason in report.skipped:
            safe_print(f"    skipped {name}: {reason}")
        return 1

    out_path = Path(args.out) if args.out else default_output(settings, settings.target_month)
    pdf_renderer.render_pdf(report, settings, translator, out_path)

    # --- run summary ---
    safe_print("=" * 66)
    safe_print(f"  Monthly report generated: {out_path}")
    safe_print(f"  Document number : {report.document_number}")
    safe_print(f"  Month           : {settings.target_month}")
    safe_print(f"  Reports merged  : {len(report.source_reports)}  {report.source_reports}")
    safe_print(f"  Weld rows       : {len(report.rows)}")
    safe_print(f"  Retests matched : {report.retest_pairs} (parent/child sub-numbered)")
    safe_print(f"  Signatories     : {report.signatures}")
    if report.skipped:
        safe_print(f"  Skipped files   : {len(report.skipped)}")
        for name, reason in report.skipped:
            safe_print(f"      - {name}: {reason}")
    if report.untranslated:
        safe_print(f"  Untranslated    : {len(report.untranslated)} segment(s) flagged {settings.untranslated_marker}")
        for seg in report.untranslated:
            safe_print(f"      - {seg}")
    safe_print("=" * 66)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
