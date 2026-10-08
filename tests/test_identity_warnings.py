"""Filename identity noise is reported, never repaired (ADR-003 follow-up).

A PDF export carries tails a curated ``.docx`` never had. Because the filename is
authoritative for a Report №, those tails ship into the monthly document. The rule
under test is that the pipeline says so out loud and changes nothing: there is no
shape that separates ``U-UT-25-003rej`` (a real number) from ``UT-U-25-003 rej``
(a noisy name), so any stripping rule would corrupt one to tidy the other.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from monthly_report.gui.services.progress import PipelineProgressParser, Stage
from monthly_report.report_identity import identity_noise


class TestNoisyNames:
    """Names whose leading token is not the whole Report № the file will ship."""

    @pytest.mark.parametrize("name, reason", [
        ("KF-FC-25-07.docx.pdf", "ikiqat uzantı"),
        ("U-DP-25-005.docx.pdf", "ikiqat uzantı"),
        ("MPI-SDLN-26-353___F1945___18.06.26.pdf", "ardıcıl alt-xətt"),
        ("UT-SDLN-26-042_____F1929____03.06.26.pdf", "ardıcıl alt-xətt"),
        ("UT-U-25-003 rej (Dashgil 2).pdf", "naməlum şəkilçi"),
        ("UP-RT-26-043..docx", "naməlum şəkilçi"),
    ])
    def test_reason(self, name, reason):
        assert identity_noise(name) == reason


class TestCleanNames:
    """Shapes that are NOT noise — flagging them would train the operator to ignore."""

    @pytest.mark.parametrize("name", [
        "KF-FC-25-07.pdf",
        "MPI-SDLN-26-353.pdf",
        # A retest marker is part of the report number, not a tail.
        "KF-MT-25-019 R1 (1866)  (ASME B31.3).docx",
        "U-UT-26-010 RS1.docx",
        # Parenthesised job/standard groups are stripped before the number is read.
        "U-UT-26-001  (Platform)_en_en.docx",
        # 'rej' glued to the number IS the number — this report exists in the corpus.
        "U-UT-25-003rej.docx",
    ])
    def test_clean(self, name):
        assert identity_noise(name) is None


class TestStdoutContract:
    """The new console line must not be mistaken for any line the GUI already parses.

    ``_RENDERED`` anchors on a line STARTING with ``[``; the identity line is indented
    for exactly that reason. This test is the reason the indent may not be removed.
    """

    LINE = ("  [identity] KF-FC-25-07.docx.pdf: ikiqat uzantı "
            "(Report № -> KF-FC-25-07.docx)")
    SUMMARY = "  Identity warnings: 4 noisy PDF name(s) audited -> identity_warnings_2026-09-08.md"

    @pytest.mark.parametrize("line", [LINE, SUMMARY])
    def test_parser_ignores(self, line):
        assert PipelineProgressParser().feed(line) is None

    def test_quarantine_line_still_parses(self):
        """Guard against a regex loosened to accommodate the new line."""
        event = PipelineProgressParser().feed("  [quarantine] x.pdf: unreadable")
        assert event is not None and event.stage is not Stage.IDLE
