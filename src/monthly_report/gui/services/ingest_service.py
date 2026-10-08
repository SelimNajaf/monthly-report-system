"""Take a dropped selection and put it in ``input/``.

The dashboard could show the work but not receive it: every month began in
Windows Explorer, copying a few hundred reports by hand. This is the other half
of that gesture.

Pure filesystem work over plain paths — no Qt, no widgets, no window. The drop
zone decides *that* files arrived; this decides *which* ones are reports and what
happens to them, and it is unit-tested without a display.

Two rules, both inherited rather than invented:

* **Never overwrite.** ``pre_processor.move_to`` returns False rather than clobber
  a same-named file (pre_processor.py:69). A drop follows the same rule: an
  existing name is skipped and counted, which also makes re-dropping the same
  folder harmless.
* **Never leave a partial file.** Copy to ``<name>.part``, then rename. A cancelled
  or crashed ingest leaves nothing that ``rglob("*.docx")`` will pick up and treat
  as a real report — the same reasoning as ``pre_processor.PART_SUFFIX``.

I/O contract
------------
discover(paths, input_dir) -> list[Path]
ingest(files, input_dir, progress=None, cancelled=None) -> IngestResult
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

#: What the pipeline can actually process. ``.docx`` is read directly;
#: ``.pdf`` is converted by pre_processor.convert_input_pdfs on the next run.
#: Anything else dropped is ignored rather than copied somewhere it will confuse
#: a later scan.
ACCEPTED_SUFFIXES = frozenset({".docx", ".pdf"})

#: Suffix for a copy in flight — see the module docstring.
PART_SUFFIX = ".part"


@dataclass
class IngestResult:
    """What a drop actually did."""

    copied: list[str] = field(default_factory=list)
    #: (name, reason) — overwhelmingly "already in input/".
    skipped: list[tuple[str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    cancelled: bool = False

    @property
    def total(self) -> int:
        return len(self.copied) + len(self.skipped) + len(self.failed)

    def summary(self) -> str:
        """The line the dashboard card shows."""
        if not self.total:
            return "Nothing to ingest — no .docx or .pdf found in that drop."

        parts = [f"{len(self.copied)} file(s) accepted"]
        if self.skipped:
            parts.append(f"{len(self.skipped)} already present")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        head = ", ".join(parts)
        if self.cancelled:
            return f"{head}. Ingestion cancelled."
        return f"{head}. Ready to process." if self.copied else f"{head}."


def _is_report(path: Path) -> bool:
    """A file the pipeline will read, ignoring Word's lock artifacts.

    ``~$`` files are the 162-byte owner stubs Word writes beside an open
    document. Every scan in the pipeline skips them (pre_processor.py:145,
    main.py:88); copying one in would just create work for those filters.
    """
    return (path.suffix.casefold() in ACCEPTED_SUFFIXES
            and not path.name.startswith("~$"))


def _is_within(path: Path, folder: Path) -> bool:
    """True when ``path`` is inside ``folder``. Never raises on an odd path."""
    try:
        path.resolve().relative_to(folder.resolve())
        return True
    except (ValueError, OSError):
        return False


def discover(paths: Iterable[str | Path], input_dir: str | Path) -> list[Path]:
    """Every report inside a dropped selection, recursively, sorted.

    A drop hands us a flat list of top-level items: some are files, some are
    folders holding hundreds more at arbitrary depth. Both are expanded here so
    the caller — and the progress bar — knows the real size of the job before it
    starts.

    Files already under ``input_dir`` are excluded. Dragging out of the input
    folder and back into the window is an easy accident, and without this guard
    it would mean copying a file onto itself.
    """
    input_dir = Path(input_dir)
    found: set[Path] = set()

    for entry in paths:
        entry = Path(entry)
        try:
            if entry.is_dir():
                candidates: Iterable[Path] = (p for p in entry.rglob("*") if p.is_file())
            elif entry.is_file():
                candidates = [entry]
            else:
                continue      # a URL, a device, something that vanished
        except OSError:
            continue          # unreadable folder; a drop must not raise

        for path in candidates:
            if _is_report(path) and not _is_within(path, input_dir):
                found.add(path)

    return sorted(found)


def ingest(files: Iterable[str | Path], input_dir: str | Path,
           progress: Callable[[int, int, str], None] | None = None,
           cancelled: Callable[[], bool] | None = None) -> IngestResult:
    """Copy ``files`` into the root of ``input_dir``. Never raises.

    Everything lands flat in the root, whatever nesting it was dropped from:
    ``pre_processor.sort_input_files`` is the thing that decides where a report
    belongs, it reads the method registry to do it, and it runs on the next
    pipeline run anyway. Preserving the source tree here would just create
    folders that stage 0 has to undo.

    ``progress(index, total, name)`` is called per file, and ``cancelled()`` is
    polled between files — this is our own code doing the copying, so stopping it
    needs a flag, not a kill.
    """
    input_dir = Path(input_dir)
    files = [Path(f) for f in files]
    result = IngestResult()
    total = len(files)
    if not total:
        return result

    try:
        input_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result.failed = [(f.name, f"{type(exc).__name__}: {exc}") for f in files]
        return result

    for index, source in enumerate(files, 1):
        if cancelled is not None and cancelled():
            result.cancelled = True
            break
        if progress is not None:
            progress(index, total, source.name)

        destination = input_dir / source.name
        if destination.exists():
            # No-clobber, matching pre_processor.move_to. A different file with a
            # colliding name is NOT ingested — the count is what makes that
            # visible rather than silent.
            result.skipped.append((source.name, "already in input/"))
            continue

        part = destination.with_name(destination.name + PART_SUFFIX)
        try:
            shutil.copy2(source, part)
            os.replace(part, destination)
        except OSError as exc:
            try:
                part.unlink()
            except OSError:
                pass
            result.failed.append((source.name, f"{type(exc).__name__}: {exc}"))
            continue
        result.copied.append(source.name)

    return result


def sweep_part_files(input_dir: str | Path) -> int:
    """Delete copy leftovers from an ingest that died mid-file."""
    removed = 0
    for part in Path(input_dir).rglob(f"*{PART_SUFFIX}"):
        try:
            part.unlink()
            removed += 1
        except OSError:
            pass
    return removed
