"""What the pipeline has actually produced — the source of truth for the filters.

The dropdowns could have been built from ``settings.yaml``, but the config does
not hold what the uploader needs. Two mismatches make that route wrong:

* Months are not configured at all. ``main.py`` discovers them from each
  document's inspection date and overwrites ``settings.target_month`` per group,
  so the YAML value says nothing about what exists.
* ``uploader.py`` matches ``--month FEB_2026`` and ``--client KHF`` against
  *filenames*.

So this reads the filenames instead. The values it yields are the exact tokens
the uploader matches, which means a selection can never be spelled wrong, and a
dropdown can never offer a combination that produces nothing.

**Method is the exception, and ADR-004 is why.** A compiled document is one month
of one client across EVERY NDT method, so the filename carries no method token and
the output tree has no method folder. The methods a document actually contains are
read out of its JSON sidecar (``items_table[].method``, falling back to the root
``ndt_method``), and the method dropdown filters on membership: "documents that
CONTAIN UT", not "the UT document".

I/O contract
------------
scan(output_dir, client_names) -> Catalog
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from monthly_report.naming import MONTH_ABBR

#: Sentinel for "no filter". Empty so it is falsy at every call site.
ALL = ""

_ABBRS = frozenset(MONTH_ABBR.values())
_PREFIX = "compiled_monthly_report_"
_YEAR = re.compile(r"^\d{4}$")


@dataclass(frozen=True)
class Artifact:
    """One generated report: the PDF and its JSON sidecar."""

    pdf: Path
    client: str                    # e.g. "KHF" — what --client matches
    month: str                     # e.g. "FEB_2026" — what --month matches
    methods: tuple[str, ...] = ()  # every NDT token inside, from the sidecar

    @property
    def sidecar(self) -> Path:
        """The JSON twin. ``json_exporter`` writes it beside the PDF, same stem."""
        return self.pdf.with_suffix(".json")

    @property
    def has_sidecar(self) -> bool:
        return self.sidecar.is_file()


def _parse_stem(stem: str) -> tuple[str, str] | None:
    """Split ``compiled_monthly_report_KHF_FEB_2026`` into ``(client, month)``.

    Mirrors ``naming.default_output``, which joins only the tokens it is given —
    so they are counted from the RIGHT, where the month abbreviation and year are
    always the last two parts. Guessing from the left would misread a report
    generated without a client.

    ADR-004 removed the method token from the filename, and this function changed
    with it: the CLIENT is now the single lead token. It used to read a lone lead
    token as the method and return an empty client, which quietly turned
    ``main._purge_excluded_client_outputs`` — the sweep that retires a retired
    client's compiled output — into a no-op the moment the filename lost its
    method. A legacy two-token name (``..._MT_KHF_FEB_2026``) still resolves to
    its client, so old output already in the tree keeps being swept.
    """
    if not stem.startswith(_PREFIX):
        return None

    parts = stem[len(_PREFIX):].split("_")
    if len(parts) < 2 or not _YEAR.match(parts[-1]) or parts[-2] not in _ABBRS:
        return None

    month = f"{parts[-2]}_{parts[-1]}"
    lead = parts[:-2]
    if not lead:
        return ALL, month
    # One token: the client (ADR-004). Two: a pre-ADR-004 <METHOD>_<CLIENT>
    # name, whose client is the LAST lead token.
    return lead[-1], month


@dataclass(frozen=True)
class Catalog:
    """An immutable snapshot of ``output/``."""

    artifacts: tuple[Artifact, ...] = ()
    client_names: dict[str, str] | None = None

    def months(self) -> list[str]:
        """Newest first — the month a user wants is almost always the last one."""
        seen = {a.month for a in self.artifacts}
        return sorted(seen, key=_month_sort_key, reverse=True)

    def methods(self) -> list[tuple[str, str]]:
        """``(value, label)`` pairs — every NDT token present anywhere in output/.

        No folder half any more: ADR-004 removed the method directory level, so a
        token names no folder to be disambiguated against.
        """
        tokens = {t for art in self.artifacts for t in art.methods if t}
        return [(token, token) for token in sorted(tokens)]

    def clients(self) -> list[tuple[str, str]]:
        """``(code, label)`` pairs, labelled with the client's name from settings."""
        names = self.client_names or {}
        codes = sorted({a.client for a in self.artifacts if a.client})
        return [(code, f"{code} — {names[code]}" if code in names else code)
                for code in codes]

    def filter(self, month: str = ALL, method: str = ALL,
               client: str = ALL) -> list[Artifact]:
        """Artifacts matching every non-empty criterion."""
        # Method is a MEMBERSHIP test: one document carries several (ADR-004).
        return [a for a in self.artifacts
                if (not month or a.month == month)
                and (not method or method in a.methods)
                and (not client or a.client == client)]


def _month_sort_key(month: str) -> tuple[int, int]:
    """``FEB_2026`` -> ``(2026, 2)``. Chronological, not alphabetical."""
    abbr, _, year = month.partition("_")
    index = next((n for n, a in MONTH_ABBR.items() if a == abbr), 0)
    return (int(year) if year.isdigit() else 0, index)


def _sidecar_methods(sidecar: Path) -> tuple[str, ...]:
    """The NDT tokens a compiled document contains, read from its JSON twin.

    ``items_table[].method`` is the authority — it is the same value the PDF's
    Üsul column draws. The root ``ndt_method`` (``"DP/MPI/RT/UTM"``) is the
    fallback, and it also covers a pre-ADR-004 sidecar, where it is one token.

    A missing, unreadable or malformed sidecar yields ``()`` rather than raising:
    ``output/`` is a user directory and the dashboard must still open.
    """
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict):
        return ()
    tokens = {str(r.get("method", "")).strip()
              for r in data.get("items_table", []) or []
              if isinstance(r, dict)}
    tokens.discard("")
    if not tokens:
        tokens = {t.strip()
                  for t in str(data.get("ndt_method", "") or "").split("/")}
        tokens.discard("")
    return tuple(sorted(tokens))


def scan(output_dir: Path, client_names: dict[str, str] | None = None) -> Catalog:
    """Walk ``output/`` and read every generated report's filename.

    Unparseable names are skipped rather than raising: ``output/`` is a user
    directory, and a stray PDF someone dropped there must not stop the dashboard
    from opening.
    """
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return Catalog(client_names=client_names)

    artifacts = []
    for pdf in sorted(output_dir.rglob("compiled_monthly_report_*.pdf")):
        parsed = _parse_stem(pdf.stem)
        if parsed is None:
            continue
        client, month = parsed
        artifacts.append(Artifact(
            pdf=pdf, client=client, month=month,
            methods=_sidecar_methods(pdf.with_suffix(".json"))))

    return Catalog(artifacts=tuple(artifacts), client_names=client_names)


def client_names_from(settings) -> dict[str, str]:
    """``{"KHF": "Khazar Fabrication", ...}`` from the raw settings.

    ``Settings`` exposes the client registry only as ``raw`` (config.py:39), the
    same way ``method_registry`` reads it.
    """
    clients = (settings.raw or {}).get("clients", {}) or {}
    names = {}
    for key, entry in clients.items():
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code", key))
        name = entry.get("name")
        if name:
            names[code] = str(name)
    return names
