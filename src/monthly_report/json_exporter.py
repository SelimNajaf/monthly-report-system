"""Parallel JSON metadata exporter — a machine-readable sidecar for each PDF.

This is the data-decoupling stage. Whenever the pipeline saves a compiled monthly
report PDF it also emits a matching ``.json`` next to it, carrying the SAME rendered
(translated) values shown in the PDF. Downstream consumers — the E-Keyfiyyet portal
uploader (``uploader.py``) — read this JSON instead of ever re-parsing a PDF, so the
raw data payload is cleanly separated from the visual rendering layer.

Contract notes (see the JSON data-contract rules):
  * The exporter reuses the SAME ``report`` object and the SAME ``translator`` the
    PDF renderer used, so ``item_name`` / ``result`` are byte-identical to the PDF
    cells and ``reporting_period`` matches the PDF header — no drift, one source of
    truth.
  * ``client_voen`` is ALWAYS a string (an opaque Tax ID, never a number): quoting
    preserves leading zeros and avoids float precision loss on long IDs.
  * ``equipment_used`` is the one deliberate EXCEPTION to the mirror rule above: it
    has no PDF counterpart. The compiled report's table is fixed at its 7 columns,
    but the portal's appeal form asks which instrument was used, so the value is
    carried here — a digital-only payload — instead of being rendered.

I/O contract
------------
export_report_json(report, settings, translator, json_path) -> Path
"""

from __future__ import annotations

import json
from pathlib import Path

# The shared naming module is the single source for the Azerbaijani month table,
# so the JSON's reporting_period is guaranteed identical to the PDF header's
# "Hesabat dövrü" line.
from .document_aggregator import pulled_from, pulled_parent_style
from .method_registry import client_voen
from .naming import reporting_period
from .text_norm import unique_ordered


def build_report_json(report, settings, translator) -> dict:
    """Assemble the JSON metadata payload for one compiled monthly report.

    Every displayed value comes straight from the already-built ``report`` and is
    translated with the same ``translator`` the PDF used, so the JSON is an exact
    machine-readable mirror of the rendered PDF.
    """
    # presentation.pulled_parent_style: marked — a cross-month parent's row says
    # which month it belongs to. Only that row gains the key; on plain the
    # sidecar is byte-identical to before. The row stays in items_table and in
    # total_records: it is on the page. ``hidden`` writes exactly what ``marked``
    # writes — hiding is a PDF decision, the sidecar keeps every report.
    mark_pulled = pulled_parent_style(settings) in ("marked", "hidden")
    return {
        "client_name": report.client_name,
        "client_voen": client_voen(report.client_code, settings),
        "reporting_period": reporting_period(report.month),
        # Under ADR-004 one document spans every method of a client-month, so this
        # is a "/"-joined token list ("DP/MPI/RT/UTM"). Kept as a STRING because
        # uploader.load_report_json requires the key and every existing sidecar has
        # it as one; a single-method document is byte-identical to before. The list
        # form sits beside it for consumers that want to iterate.
        "ndt_method": report.method,
        "ndt_methods": [t for t in str(report.method or "").split("/") if t],
        "report_serial_no": report.document_number,
        "total_records": len(report.rows),
        # Distinct source report numbers behind this batch (rows can exceed reports
        # when retests merge). Lets the uploader's volume gate read the same
        # reports count the compiler filtered on, without re-parsing anything.
        "source_report_count": len(report.source_reports),
        # Every distinct instrument in the batch, comma-joined. Untranslated: an
        # instrument model is a proper noun ("EPOCH LT"), not a term. Always
        # present — "" for a method with no equipment field (DP) — so the sidecar
        # schema stays fixed.
        "equipment_used": ", ".join(unique_ordered(r.equipment for r in report.rows)),
        "items_table": [
            {
                "seq_no": r.seq,
                "date": r.date_str,
                "report_no": r.report_no,
                "standard": r.standard,
                # The PDF's Üsul column, mirrored. Read off the row rather than
                # re-derived so the sidecar and the rendered table can never name
                # a different method for the same document.
                "method": getattr(r, "method", "") or report.method,
                "item_name": translator.term(r.item_detail),
                "result": translator.term(r.result),
                **({"pulled_from": pulled_from(r)}
                   if mark_pulled and r.is_pulled_parent else {}),
            }
            for r in report.rows
        ],
    }


def export_report_json(report, settings, translator, json_path: str | Path) -> Path:
    """Write the JSON sidecar next to its PDF and return the written path.

    Creates the parent directory if needed and writes UTF-8 with
    ``ensure_ascii=False`` so Azerbaijani glyphs (``ə ğ ı ö ş ç ü``) and the string
    VÖEN survive verbatim.
    """
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    data = build_report_json(report, settings, translator)
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return json_path
