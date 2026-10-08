"""The official report-serial convention: ``MR-<CLIENT>-<YY>-<MM>``.

``naming.document_number`` is the single place a compiled report's serial is
minted (``document_aggregator`` calls it, ``json_exporter`` copies the result
into ``report_serial_no``, ``pdf_renderer`` only displays it). So the format is
pinned here, at the source: no ``MAG-`` prefix, no sequence number, a 2-digit
numeric month, and the client token folded in. ``document_number`` reads only
``settings.doc_number_pattern``, so a light stub carrying just that attribute
exercises the real formatter without loading a whole ``Settings``.

**ADR-004 removed ``{method}`` from the official pattern.** A compiled document
is one month of one client across EVERY NDT method, so no single method token
can name it — the method travels per row, in the PDF's Üsul column and the
sidecar's ``items_table[].method``. One client-month is one document, so the
serial is still unique without it. ``{method}`` stays SUPPORTED as a placeholder
for a custom pattern (covered below), it is just no longer in the official one.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from monthly_report.naming import document_number

_DEFAULT = SimpleNamespace(doc_number_pattern="MR-{client}-{yy}-{mm}")
#: A pattern that still asks for the method — supported, just not official.
_LEGACY = SimpleNamespace(doc_number_pattern="MR-{method}-{client}-{yy}-{mm}")


def test_serial_uses_the_official_month_numbered_format():
    serial = document_number(_DEFAULT, date(2026, 2, 1), client="UBOC")
    assert serial == "MR-UBOC-26-02"


def test_the_method_is_not_in_the_official_serial():
    """ADR-004. A document spans every method, so none of them names it."""
    serial = document_number(_DEFAULT, date(2026, 2, 1), method="MT", client="UBOC")
    assert serial == "MR-UBOC-26-02"          # the argument is simply unused
    for token in ("MT", "UT", "RT", "DP"):
        assert token not in serial


def test_serial_has_no_mag_prefix_and_no_sequence_number():
    serial = document_number(_DEFAULT, date(2026, 6, 1), client="KHE")
    assert not serial.startswith("MAG")
    assert serial == "MR-KHE-26-06"          # month numeric, no -NNN tail


def test_empty_client_falls_back_to_na_never_a_double_dash():
    serial = document_number(_DEFAULT, date(2026, 2, 1), client="")
    assert serial == "MR-NA-26-02"
    assert "--" not in serial


def test_a_custom_pattern_may_still_ask_for_the_method():
    """The placeholder is kept for back-compat with a hand-edited pattern."""
    serial = document_number(_LEGACY, date(2026, 2, 1), method="MT", client="UBOC")
    assert serial == "MR-MT-UBOC-26-02"


def test_broken_pattern_falls_back_to_the_official_shape():
    # A malformed custom pattern must not crash the run — the except-branch still
    # emits the official convention, which no longer carries the method.
    broken = SimpleNamespace(doc_number_pattern="{does_not_exist}")
    serial = document_number(broken, date(2026, 12, 1), method="UT", client="NOV")
    assert serial == "MR-NOV-26-12"
