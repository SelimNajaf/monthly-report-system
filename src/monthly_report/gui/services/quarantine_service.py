"""The quarantine folder, and getting a file from it into Word.

Quarantine is the pipeline's human-in-the-loop queue. Nothing is deleted: a file
that cannot be processed is moved aside with a reason (main.py:101,112;
pre_processor.py:317,322) so a person can fix it. Most commonly that means a
scanned image needing OCR — which someone has to open in Word to repair.

This tab is the whole loop's last mile.

I/O contract
------------
quarantine_dir(settings) -> Path
listing(settings) -> list[QuarantinedFile]
open_in_default_app(path) -> None   # raises OSError with a readable message
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from monthly_report.naming import QUARANTINE_DIR

#: Reasons the pipeline quarantines a file, keyed by the marker it prints. Shown
#: as a hint in the list so the user knows what fix is needed before opening it.
REASON_HINTS = {
    "no readable text": "Scanned image — re-convert with an OCR-enabled tool.",
    "pdf readers disagree": "Two PDF readers gave different answers — open the PDF, read the Accept/Reject column, and settle it (see output/pdf_crosscheck_*.md).",
    "unreadable": "File is corrupt or locked — check it opens in Word.",
    "no detectable inspection date": "Add or correct the inspection date field.",
    "ASR/ARS excluded": "Excluded by design — no action needed.",
    "excluded client": "Retired account — excluded by design, no action needed.",
    "unsupported standard": "Standard not on the approved allowed_standards list.",
}


@dataclass(frozen=True)
class QuarantinedFile:
    """One file awaiting human attention."""

    path: Path
    size: int
    modified: datetime

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def size_label(self) -> str:
        kb = self.size / 1024
        return f"{kb:.0f} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"

    @property
    def modified_label(self) -> str:
        return self.modified.strftime("%d.%m.%Y %H:%M")


def quarantine_dir(settings) -> Path:
    """``input/SKIPPED_REPORTS``.

    The folder name is a module constant, not a setting (naming.py:23), so it is
    imported rather than retyped — a literal here would silently diverge the day
    it changes.
    """
    return Path(settings.input_dir) / QUARANTINE_DIR


def listing(settings) -> list[QuarantinedFile]:
    """Every quarantined file, newest first.

    Newest first because the file a user wants is the one the run they just
    watched put there.
    """
    folder = quarantine_dir(settings)
    if not folder.is_dir():
        return []

    files = []
    for path in folder.iterdir():
        if not path.is_file() or path.name.startswith("~$"):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue  # vanished mid-scan; a listing must not raise
        files.append(QuarantinedFile(path=path, size=stat.st_size,
                                     modified=datetime.fromtimestamp(stat.st_mtime)))

    return sorted(files, key=lambda f: f.modified, reverse=True)


def hint_for(name: str, reasons: dict[str, str] | None = None) -> str:
    """A remedial hint for a quarantined file, if its reason is known."""
    reason = (reasons or {}).get(name, "")
    for marker, hint in REASON_HINTS.items():
        if marker in reason:
            return hint
    return ""


def open_in_default_app(path: Path) -> None:
    """Open a file with whatever Windows has registered for it — Word, for .docx.

    ``os.startfile`` is Windows-only and the right call here: it hands the file to
    the shell exactly as a double-click would, so the user's real Word install
    (with their templates and OCR add-ins) opens it, rather than some path this
    app guessed at.
    """
    path = Path(path)
    if not path.is_file():
        raise OSError(f"File no longer exists: {path}")

    if sys.platform == "win32":
        os.startfile(path)  # noqa: S606  (intentional shell association)
    elif sys.platform == "darwin":
        # macOS: hand the file to Launch Services, the double-click equivalent.
        subprocess.Popen(["open", str(path)])
    else:
        # Linux/other. Not a supported target, but a developer on another OS
        # should not be met with an AttributeError.
        subprocess.Popen(["xdg-open", str(path)])


def reveal_in_explorer(path: Path) -> None:
    """Open the containing folder with the file selected."""
    path = Path(path)
    if sys.platform == "win32" and path.exists():
        subprocess.Popen(["explorer", "/select,", str(path)])
    elif sys.platform == "darwin" and path.exists():
        # macOS: -R reveals the file selected in Finder (like explorer /select,).
        subprocess.Popen(["open", "-R", str(path)])
    elif path.exists():
        # Linux/other: no portable "select" flag, so open the parent folder.
        subprocess.Popen(["xdg-open", str(path.parent)])
