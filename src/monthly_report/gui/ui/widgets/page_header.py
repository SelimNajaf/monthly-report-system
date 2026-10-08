"""The shared top-header shell — one component, on every page.

Every page opens with the same bar: a title and subtitle on the left, and on the
right an optional search box, a slot for page-specific chips/buttons, and an optional
live-status pill. Extracting it here is what makes the four pages *identical* rather
than merely similar — the Stitch "Executive Slate & Cobalt" header is defined once.

A page that wants to filter something wires :attr:`search_changed` to its own filter
(the dashboard to its console, the uploader to its ledger, the quarantine list to its
cards); the header itself knows nothing about what it searches.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QSizePolicy, QVBoxLayout, QWidget)

from .status_pill import StatusPill


class PageHeader(QFrame):
    """Title, subtitle, optional search, a right-hand slot, and an optional status pill."""

    search_changed = Signal(str)

    def __init__(self, title: str, subtitle: str, *,
                 search_placeholder: str | None = None,
                 show_status: bool = False,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")

        self._title = QLabel(title)
        self._title.setObjectName("PageTitle")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("PageSubtitle")

        text = QVBoxLayout()
        text.setSpacing(1)
        text.addWidget(self._title)
        text.addWidget(self._subtitle)

        self.search: QLineEdit | None = None
        if search_placeholder is not None:
            self.search = QLineEdit()
            self.search.setObjectName("SearchBox")
            self.search.setPlaceholderText(search_placeholder)
            self.search.setClearButtonEnabled(True)
            # Grow with the header row instead of pinning to a minimum — a long placeholder
            # (the uploader's client/method/state filter) was clipping at 240px.
            self.search.setMinimumWidth(360)
            self.search.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.search.textChanged.connect(self.search_changed)

        self.status: StatusPill | None = StatusPill() if show_status else None

        row = QHBoxLayout(self)
        row.setContentsMargins(18, 14, 18, 14)
        row.setSpacing(12)
        row.addLayout(text)
        row.addStretch(1)
        if self.search is not None:
            # Stretch factor so the field shares the row's slack with the spacer and grows,
            # rather than the spacer eating it all and pinning the box to its minimum.
            row.addWidget(self.search, 1)
        # Everything add_right() adds lands here, before the status pill.
        self._slot_index = row.count()
        if self.status is not None:
            row.addWidget(self.status)
        self._row = row

    def add_right(self, widget: QWidget) -> None:
        """Insert a page-specific widget (chip, summary, button) before the status pill."""
        self._row.insertWidget(self._slot_index, widget)
        self._slot_index += 1

    def set_title(self, title: str) -> None:
        self._title.setText(title)

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(subtitle)
