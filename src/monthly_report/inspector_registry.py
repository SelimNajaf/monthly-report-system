"""Config-driven inspector assignment — who signs a compiled monthly report.

NO inspector name is hardcoded. The client -> inspector routing lives in
settings.yaml's ``inspector_matrix`` block, so reassigning an inspector is a pure
config change. Two routing forms:

* ``clients``     -> a flat client-code -> name map (UBOC -> Azadxan Əhmədov).
* ``date_routing`` -> a client whose inspector changed hands on a date. SDLN's
  older reports belong to one inspector and everything from the boundary onward
  to another. Checked FIRST, so a client listed in both is routed by date.

The date compared is the REPORT'S month, supplied by the caller — not any single
row's inspection date. A compiled month can carry retest parents imported from
earlier months, and one of those must not decide the whole report's signature.

I/O contract
------------
resolve_inspector(client_code, report_date, settings) -> str   ("" when unmapped)
as_date(value) -> datetime.date | None                         (config date parser)
"""

from __future__ import annotations

import datetime as _dt


def as_date(value) -> _dt.date | None:
    """A ``date`` from a date, a datetime, or an ISO string — else ``None``.

    Config is hand-edited YAML, so ``boundary`` arrives as whatever the editor
    typed: PyYAML parses an unquoted 2026-03-01 into a ``date`` and a quoted one
    into a ``str``. Both are accepted; anything unparseable returns ``None`` and
    the caller declines to route rather than guessing a side of the boundary.
    """
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    try:
        return _dt.date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        return None


def resolve_inspector(client_code: str, report_date, settings) -> str:
    """Return the configured İnspektor for a client, or ``""`` when unmapped.

    ``report_date`` identifies WHEN the report is for — the caller passes the
    first day of the target month. It only matters for clients under
    ``date_routing``; flat ``clients`` entries ignore it.

    Returns ``""`` rather than raising or substituting a default: an unmapped
    client keeps whatever name was read from its source documents, so adding a
    client to the registry never blanks its signature block. A ``date_routing``
    client with an unusable date or boundary returns ``""`` for the same reason —
    a signature is not the place to guess.
    """
    matrix = settings.raw.get("inspector_matrix") or {}
    code = (client_code or "").strip().casefold()
    if not code:
        return ""

    routing = matrix.get("date_routing") or {}
    for key, spec in routing.items():
        if str(key).strip().casefold() != code:
            continue
        spec = spec or {}
        boundary = as_date(spec.get("boundary"))
        when = as_date(report_date)
        if boundary is None or when is None:
            return ""
        side = "before" if when < boundary else "on_or_after"
        return str(spec.get(side, "")).strip()

    clients = matrix.get("clients") or {}
    for key, name in clients.items():
        if str(key).strip().casefold() == code:
            return str(name).strip()
    return ""
