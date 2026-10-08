"""The three numbers on the executive cards.

Counted from the filesystem, never from a database the pipeline does not have.
That keeps the dashboard honest: it reports what is on disk right now, including
work done from the terminal before the GUI existed.

I/O contract
------------
collect(settings, catalog, month, method, client) -> Metrics
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from monthly_report.naming import PDF_ARCHIVE_DIR, PRUNED_DIR, QUARANTINE_DIR

from . import catalog as catalog_mod

#: Word's lock files for an open document. Counting them would inflate the
#: "processed" figure every time someone has a report open — the same reason
#: main.py:88 filters them out of the parse set.
_LOCK_PREFIX = "~$"

#: Directories under input/ that hold finished, rejected or retired work, not
#: input. Mirrors pre_processor.SETTLED_DIRS — kept as a literal set so this
#: service stays a pure filesystem scan with no pipeline import.
_EXCLUDED = {QUARANTINE_DIR.casefold(), PDF_ARCHIVE_DIR.casefold(),
             PRUNED_DIR.casefold()}


@dataclass(frozen=True)
class Metrics:
    """A snapshot of the pipeline's footprint on disk."""

    documents: int = 0        # source .docx awaiting or feeding the pipeline
    pdfs: int = 0             # generated reports
    sidecars: int = 0         # their JSON twins
    quarantined: int = 0      # files needing human attention
    archived_pdfs: int = 0    # originals already converted

    @property
    def sidecar_complete(self) -> bool:
        """Every PDF has its JSON. A mismatch means a run died between the two
        writes (main.py:163-167) and is worth surfacing."""
        return self.pdfs == self.sidecars


def _count_source_docs(input_dir: Path) -> int:
    """Every .docx under input/ that the pipeline would actually read.

    Mirrors main.py:87-89 exactly — same recursion, same exclusions — so the card
    matches the count the pipeline prints when it runs.
    """
    if not input_dir.is_dir():
        return 0

    total = 0
    for path in input_dir.rglob("*.docx"):
        if path.name.startswith(_LOCK_PREFIX):
            continue
        try:
            top = path.relative_to(input_dir).parts[0]
        except (ValueError, IndexError):
            continue
        if top.casefold() in _EXCLUDED:
            continue
        total += 1
    return total


def _count_dir(path: Path, pattern: str = "*") -> int:
    if not path.is_dir():
        return 0
    return sum(1 for item in path.glob(pattern) if item.is_file())


def collect(settings, catalog: catalog_mod.Catalog,
            month: str = catalog_mod.ALL,
            method: str = catalog_mod.ALL,
            client: str = catalog_mod.ALL) -> Metrics:
    """Count everything, honouring the dashboard's filter.

    The generated-report counts respect the dropdowns; the input-side counts do
    not. That asymmetry is deliberate — ``input/`` is not organised by month, and
    a "Quarantined" card that changed when you picked a month would be lying:
    those 58 files need attention regardless of what is selected.
    """
    input_dir = Path(settings.input_dir)
    selected = catalog.filter(month=month, method=method, client=client)

    return Metrics(
        documents=_count_source_docs(input_dir),
        pdfs=len(selected),
        sidecars=sum(1 for art in selected if art.has_sidecar),
        quarantined=_count_dir(input_dir / QUARANTINE_DIR),
        archived_pdfs=_count_dir(input_dir / PDF_ARCHIVE_DIR, "*.pdf"),
    )
