"""The sidecar's equipment_used key — the join, and its absence from the PDF.

build_report_json is the boundary where per-document instruments become the one
string the portal's equipment note is typed from, so the join rules (distinct,
first-seen order, always present) are pinned here rather than inferred from a
regenerated file on disk.
"""

import datetime as _dt
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.document_aggregator import MonthlyReport, ReportRow  # noqa: E402
from monthly_report.json_exporter import build_report_json, export_report_json  # noqa: E402


class _Settings:
    """Only what build_report_json touches: the clients registry behind client_voen."""
    raw = {"clients": {"KHF": {"code": "KHF", "voen": "1509876543"}}}


class _Translator:
    """The real translator maps rendered terms; here identity is enough — the point
    is that equipment_used must never be routed through it."""
    def term(self, text):
        return text


def _row(equipment, report_no="KF-MT-26-001", seq="1", standard="ASME B31.3"):
    return ReportRow(
        date=_dt.date(2026, 5, 21),
        date_str="21.05.2026",
        report_no=report_no,
        series_key=report_no,
        retest_rank=0,
        client="Khazar Fabrication",
        document_name=f"{report_no} (2165)",
        standard=standard,
        item_detail="Boru",
        result="Fit",
        equipment=equipment,
        seq=seq,
    )


def _report(*rows):
    return MonthlyReport(
        month="2026-05",
        document_number="MR-MT-KHF-26-05",
        title="",
        method="MT",
        client_code="KHF",
        client_name="Khazar Fabrication",
        rows=list(rows),
    )


def _build(*rows):
    return build_report_json(_report(*rows), _Settings(), _Translator())


def test_distinct_instruments_are_comma_joined():
    data = _build(_row("El/Magnet (S/N:B1261)", "KF-MT-26-001", "1"),
                  _row("PFINDER 280 magnet", "KF-MT-26-002", "2"))
    assert data["equipment_used"] == "El/Magnet (S/N:B1261), PFINDER 280 magnet"


def test_the_same_instrument_across_a_batch_is_named_once():
    """A month is usually one magnet over thirty reports. Repeating it thirty times
    would overflow the portal's note with one value."""
    data = _build(_row("El/Magnet (S/N:5803)", "KF-MT-26-001", "1"),
                  _row("El/Magnet (S/N:5803)", "KF-MT-26-002", "2"),
                  _row("El/Magnet (S/N:5803)", "KF-MT-26-003", "3"))
    assert data["equipment_used"] == "El/Magnet (S/N:5803)"


def test_join_order_is_first_seen_not_sorted():
    """The operator reads the note against the PDF's rows, which are date-ordered.
    A set() would reshuffle it on every run and look like a different submission."""
    data = _build(_row("Sonatest D70 (№ 1014948)", "KF-UT-26-001", "1"),
                  _row("EPOCH LT (№ 050010402)", "KF-UT-26-002", "2"))
    assert data["equipment_used"] == "Sonatest D70 (№ 1014948), EPOCH LT (№ 050010402)"


def test_a_method_without_equipment_still_carries_the_key_empty():
    """DP. The key is always present so the uploader's contract check stays fixed."""
    data = _build(_row("", "U-DP-26-011", "1"))
    assert data["equipment_used"] == ""


def test_documents_missing_the_field_do_not_punch_a_hole_in_the_join():
    """One unreadable Equipment block must not produce ", , " in a government field."""
    data = _build(_row("El/Magnet (S/N:5803)", "KF-MT-26-001", "1"),
                  _row("", "KF-MT-26-002", "2"),
                  _row("El/Magnet (S/N:B1261)", "KF-MT-26-003", "3"))
    assert data["equipment_used"] == "El/Magnet (S/N:5803), El/Magnet (S/N:B1261)"


def test_an_empty_report_carries_the_key_empty():
    assert _build()["equipment_used"] == ""


def test_equipment_never_reaches_the_items_table():
    """The PDF renders items_table's shape; equipment is a root-level digital payload
    and must not become a table column by the back door.

    ``method`` IS in the row set — it is the PDF's Üsul column, mirrored — while
    ``equipment_used`` stays root-level with no PDF counterpart.
    """
    data = _build(_row("El/Magnet (S/N:5803)"))
    assert set(data["items_table"][0]) == {"seq_no", "date", "report_no", "standard",
                                           "method", "item_name", "result"}


def test_empty_standard_survives_into_the_sidecar_unforced():
    """A report with no source standard keeps "" in items_table[].standard — the
    sidecar mirrors the mutated record, so nothing re-injects a method default."""
    data = _build(_row("", "SDLN-PMI-26-021", "1", standard=""))
    assert data["items_table"][0]["standard"] == ""


def test_the_key_survives_the_write_with_its_glyphs_intact(tmp_path):
    """№ and ə must not come back as \\u2116 — the portal field is typed from this."""
    path = export_report_json(_report(_row("EPOCH LT (№ 050010402)")),
                              _Settings(), _Translator(), tmp_path / "r.json")
    raw = path.read_text(encoding="utf-8")
    assert "№" in raw
    assert json.loads(raw)["equipment_used"] == "EPOCH LT (№ 050010402)"
