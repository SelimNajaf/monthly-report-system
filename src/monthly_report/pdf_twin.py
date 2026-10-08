"""PDF twin lookup — the archived original's filename(s) for a parsed report.

Every PDF dropped into ``input/`` is converted to ``.docx`` and the original is
moved to ``input/PDF_ARCHIVE/`` (see :func:`pre_processor.convert_input_pdfs`).
That archived name is the only place a *signed* fact about the report survives
outside the document body, and for the cut ``Date:`` cells it is what KB-1b reads
the month and year from — see :mod:`date_detector`.

Why an index instead of a per-file glob: the archive holds thousands of PDFs and
the date is needed once per report at four separate stages (discovery, the client
volume snapshot, the aggregator, the retest tracker). One pass, cached, keeps those
four stages cheap AND — the part that matters — keeps them in agreement. A stage
that resolved twins differently would put the same report in a different month than
discovery did, which is exactly the drift ``discover_groups.last_client_stats``
exists to prevent.

Matching is by :func:`report_identity.report_key_of` — the leading report-number
token — because that is what the ``.docx`` and its PDF share; everything after it
(job number, pipe size, weld id, date) differs between the two by design::

    UT-SDLN-25-009.docx
    UT-SDLN-25-009(F1815)24"x 15.9_W-1_11.09.2025.pdf   -> both UT-SDLN-25-009

A key with several archived PDFs returns all of them; the caller decides what to do
with a disagreement (KB-1b refuses to repair from one).

ASR/ARS originals are left OUT of the index. Those documents are excluded from every
report in this pipeline on sight (:func:`report_identity.is_excluded`, quarantined by
the pre-processor), so admitting one here as dating evidence for a DIFFERENT report
contradicts the rule that removed it — and in practice it did exactly that: the
retest ``UT-SDLN-25-024(F1752)...W-103ASR_22.09.2025.pdf`` sits under the same report
key as the original ``...W-103_20.09.2025.pdf``, and the pair read as two disagreeing
dates that refused an otherwise clean repair.

I/O contract
------------
names_for(path, settings) -> tuple[str, ...]   # archived PDF names for this report
index(input_dir) -> dict[str, tuple[str, ...]]
reset_cache() -> None                          # tests, and after the archive moves
"""

from __future__ import annotations

from pathlib import Path

from .naming import PDF_ARCHIVE_DIR
from .report_identity import is_excluded, report_key_of

#: ``(archive path, mtime) -> index``. The mtime of the archive DIRECTORY changes
#: whenever a PDF is added or removed from it, so a run that archives new originals
#: mid-pass (conversion runs before discovery) rebuilds rather than serving a stale
#: index. Cheap either way: one ``stat`` per call.
_CACHE: dict[tuple[str, int], dict[str, tuple[str, ...]]] = {}


def reset_cache() -> None:
    """Drop the memoised index. For tests, and for a caller that moved the archive."""
    _CACHE.clear()


def index(input_dir) -> dict[str, tuple[str, ...]]:
    """``report key -> archived PDF filenames``, memoised per archive state."""
    archive = Path(input_dir) / PDF_ARCHIVE_DIR
    try:
        stamp = archive.stat().st_mtime_ns
    except OSError:
        return {}                       # no archive yet: no twins, not an error
    key = (str(archive), stamp)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    built: dict[str, list[str]] = {}
    try:
        names = sorted(p.name for p in archive.rglob("*.pdf")
                       if not p.name.startswith("~$")
                       and not is_excluded(p.name, ""))
    except OSError:
        return {}
    for name in names:
        built.setdefault(report_key_of(name), []).append(name)
    table = {k: tuple(v) for k, v in built.items()}
    _CACHE.clear()                      # only the current archive state is worth keeping
    _CACHE[key] = table
    return table


def names_for(path, settings) -> tuple[str, ...]:
    """The archived PDF filenames twinned with ``path``'s report, possibly empty."""
    return index(settings.input_dir).get(report_key_of(Path(path).name), ())
