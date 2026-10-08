"""The drop target: a dashed rectangle that accepts reports.

Qt does the hard part. ``setAcceptDrops(True)`` plus the three event handlers is
the entire native drag-and-drop contract, and the Windows shell hands us real
file URLs — the same ones Explorer would.

This widget knows nothing about ``input/``, recursion, or copying. It decides
whether a drag is plausible, paints itself accordingly, and emits the paths.
Everything else is ``services.ingest_service``, which is testable without a
display. The split matters: dragging is the one interaction that cannot be
unit-tested, so as little as possible should live on this side of it.

I/O contract
------------
DropZone().files_dropped(list[str])     paths the user dropped, unfiltered
DropZone().set_enabled_for_drops(bool)  refuse drops while a job is running
DropZone().set_message(str)             what it says when idle
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ...services.ingest_service import ACCEPTED_SUFFIXES


class DropZone(QFrame):
    """Drop .docx / .pdf files or folders here."""

    files_dropped = Signal(list)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)

        self._accepting = True
        self._idle_message = "Drop reports or folders here"

        self.icon = QLabel("⤓")
        self.icon.setObjectName("DropZoneIcon")
        self.icon.setAlignment(Qt.AlignCenter)

        self.title = QLabel(self._idle_message)
        self.title.setObjectName("DropZoneTitle")
        self.title.setAlignment(Qt.AlignCenter)

        self.hint = QLabel("Word documents and PDFs, nested folders included — "
                           "they are copied into input/ and sorted on the next run")
        self.hint.setObjectName("DropZoneHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self.icon)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)

    # ------------------------------------------------------------- painting --
    def _set_state(self, state: str) -> None:
        """Repaint via a QSS property selector rather than an inline stylesheet.

        The whole look lives in theme.py (see its docstring); a hex code here
        would be invisible to the theme toggle and wrong in one of the two modes.
        """
        self.setProperty("state", state)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_enabled_for_drops(self, accepting: bool) -> None:
        """Refuse drops while a job runs.

        Not cosmetic: the pipeline walks ``input/`` and moves files out of it
        (pre_processor.sort_input_files). Adding files underneath a live walk is
        a race, and the loser is a report that is neither sorted nor processed.
        """
        self._accepting = accepting
        self.setAcceptDrops(accepting)
        self.title.setText(self._idle_message if accepting
                           else "Ingestion paused while a job is running")
        self._set_state("idle" if accepting else "disabled")

    def set_message(self, message: str) -> None:
        """Report the outcome of the last drop, e.g. '350 files accepted.'"""
        self._idle_message = message
        if self._accepting:
            self.title.setText(message)

    # --------------------------------------------------------------- events --
    def _has_files(self, event) -> bool:
        """True when the drag carries at least one local file we might want.

        Folders always qualify: their contents are unknown until they are walked,
        and walking them on every mouse-move over the window would be absurd.
        Refusing the drag outright is the only honest "no" — accepting it and
        then silently ingesting nothing is worse.
        """
        data = event.mimeData()
        if not data.hasUrls():
            return False
        for url in data.urls():
            if not url.isLocalFile():
                continue
            path = url.toLocalFile()
            if path.endswith("/") or "." not in path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]:
                return True     # no extension: almost certainly a folder
            if any(path.casefold().endswith(s) for s in ACCEPTED_SUFFIXES):
                return True
        return False

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._accepting and self._has_files(event):
            event.acceptProposedAction()
            self._set_state("active")
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._set_state("idle" if self._accepting else "disabled")
        event.accept()

    def dropEvent(self, event: QDropEvent) -> None:
        self._set_state("idle")
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        if not paths:
            event.ignore()
            return
        event.acceptProposedAction()
        # Emitted raw. Deciding which of these are reports means walking folders,
        # and that is filesystem work that must not happen on the UI thread.
        self.files_dropped.emit(paths)
