"""Save a compiled monthly summary — the dashboard, as a file to hand over.

The dashboard already knows everything a monthly hand-off report needs: the metric
counts and, in the catalog, one row per generated report scoped to the operator's
filters. This turns that live view into a CSV (for a spreadsheet) or JSON (for
another system), so a month's output can be signed off without screenshotting the
window.

Read-only over the catalog — it summarizes what a run produced, it does not touch
input, output, or the cache.

I/O contract
------------
export_summary(path, catalog, metrics, filters, fmt=None) -> Path
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from . import catalog as catalog_mod


def _format_for(path: Path, fmt: str | None) -> str:
    """Pick the writer: explicit ``fmt`` wins, else the path's suffix, else CSV."""
    if fmt:
        return fmt.lower().lstrip(".")
    suffix = path.suffix.lower().lstrip(".")
    return suffix if suffix in ("csv", "json") else "csv"


def _rows(catalog, filters) -> list[dict]:
    """One dict per report in scope, in the catalog's order."""
    month, method, client = filters
    scoped = catalog.filter(month, method, client) if catalog else []
    # ADR-004: one row per DOCUMENT, and a document spans every method of its
    # client-month — so ``methods`` is a "/"-joined list where ``method`` used to be
    # a single token, and the ``folder`` column is gone with the method directory.
    return [
        {"methods": "/".join(art.methods), "client": art.client, "month": art.month,
         "pdf": art.pdf.name, "has_sidecar": art.has_sidecar}
        for art in scoped
    ]


def _metrics_pairs(metrics) -> list[tuple[str, object]]:
    return [
        ("documents", metrics.documents),
        ("pdfs", metrics.pdfs),
        ("sidecars", metrics.sidecars),
        ("quarantined", metrics.quarantined),
        ("archived_pdfs", metrics.archived_pdfs),
        ("sidecar_complete", metrics.sidecar_complete),
    ]


def export_summary(path, catalog, metrics, filters, fmt: str | None = None) -> Path:
    """Write a monthly summary of ``catalog`` (scoped by ``filters``) to ``path``.

    ``filters`` is the ``(month, method, client)`` tuple the dashboard reports; ``fmt``
    is ``"csv"``/``"json"`` or ``None`` to infer from the suffix. Returns the path
    written. UTF-8, ``ensure_ascii=False`` for JSON, so Azerbaijani names survive.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = _format_for(path, fmt)
    month, method, client = filters
    scope = {"month": month or catalog_mod.ALL, "method": method or catalog_mod.ALL,
             "client": client or catalog_mod.ALL}
    rows = _rows(catalog, filters)

    if fmt == "json":
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scope": scope,
            "metrics": dict(_metrics_pairs(metrics)),
            "report_count": len(rows),
            "reports": rows,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return path

    # CSV: a small metrics header, then the per-report table. newline="" per the
    # csv module's contract, so Excel does not see doubled line endings on Windows.
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["# Monthly Report Summary"])
        writer.writerow(["generated_at", datetime.now(timezone.utc).isoformat()])
        writer.writerow(["scope_month", scope["month"] or "ALL"])
        writer.writerow(["scope_method", scope["method"] or "ALL"])
        writer.writerow(["scope_client", scope["client"] or "ALL"])
        for name, value in _metrics_pairs(metrics):
            writer.writerow([name, value])
        writer.writerow([])
        writer.writerow(["methods", "client", "month", "pdf", "has_sidecar"])
        for row in rows:
            writer.writerow([row["methods"], row["client"], row["month"],
                             row["pdf"], row["has_sidecar"]])
    return path
