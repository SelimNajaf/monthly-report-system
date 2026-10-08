"""Quarantine Explorer — the human-in-the-loop queue.

The pipeline never deletes a file it cannot process. It moves it to
``input/SKIPPED_REPORTS/`` with a reason and carries on (main.py:100-120), which
is the right call for a batch job and useless to a person unless something
eventually shows them the pile. This is that something.

"Open File" hands the document to the Windows shell, so it opens in the user's
real Word — with their templates and OCR add-ins — rather than a path this app
guessed at. Most quarantined files are scanned images needing exactly that.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from ...services.quarantine_service import QuarantinedFile
from .. import theme
from ..widgets import PageHeader

#: Issue tag -> Palette attribute for its chip colour. Actionable problems are amber,
#: a hard-unreadable file red, an excluded-by-design file muted.
#: The card widget draws what the eye reads; the item carries no display text (a delegate
#: would paint it *under* the transparent card and bleed through). The searchable
#: "name size date" string lives here instead, for _apply_filter to match against.
_SEARCH_ROLE = Qt.UserRole + 1

_TAG_COLOURS = {
    "OCR Needed": "warning",
    "Undatable": "warning",
    "Unreadable": "danger",
    "Unsupported standard": "info",
    "Excluded": "text_muted",
    "Needs review": "text_muted",
}


class QuarantinePage(QWidget):
    """Lists quarantined files and opens them for repair."""

    open_requested = Signal(object)     # QuarantinedFile
    reveal_requested = Signal(object)
    refresh_requested = Signal()
    batch_open_requested = Signal(object)     # list[QuarantinedFile]
    batch_reveal_requested = Signal(object)   # list[QuarantinedFile]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme.DARK

        self._reasons: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)
        root.addWidget(self._build_header())
        root.addWidget(self._build_body(), 1)

    def _build_header(self) -> QWidget:
        # The queue's name filter lives in the shared header's search box.
        header = PageHeader(
            "Quarantine Explorer",
            "Files the pipeline set aside for manual review — nothing is ever deleted",
            search_placeholder="Filter quarantined files by name…")
        self.filter_box = header.search
        header.search_changed.connect(lambda _: self._apply_filter())

        self.count = QLabel("")
        self.count.setObjectName("Hint")
        header.add_right(self.count)
        return header

    def _build_body(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        # Batch selection: a tick per row plus a "Select all" master. Independent of the
        # single-row selection that drives Open/Show — a user ticks a set to act on many
        # at once without losing the one row they have highlighted.
        self.select_all = QCheckBox("Select all")
        self.select_all.setTristate(True)
        self.select_all.clicked.connect(self._toggle_select_all)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(12)
        filter_row.addStretch(1)
        filter_row.addWidget(self.select_all)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setAlternatingRowColors(True)
        self.list.itemSelectionChanged.connect(self._on_selection)
        self.list.itemDoubleClicked.connect(lambda _: self._emit_open())
        self.list.itemChanged.connect(lambda _: self._on_check_changed())

        self.empty = QLabel("Nothing in quarantine.\n\n"
                            "Every document the pipeline found was readable, "
                            "datable and processed.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.list)
        self.stack.addWidget(self.empty)

        self.open_button = QPushButton("📝   Open File in Word")
        self.open_button.setObjectName("PrimaryButton")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._emit_open)

        self.reveal_button = QPushButton("📂  Show in Explorer")
        self.reveal_button.setEnabled(False)
        self.reveal_button.clicked.connect(self._emit_reveal)

        refresh = QPushButton("↻  Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)

        # Batch actions over the ticked set. All non-destructive — quarantine never
        # deletes, so these only open, reveal or copy paths for many files at once.
        self.batch_open_button = QPushButton("Open selected")
        self.batch_open_button.setObjectName("ToolButton")
        self.batch_open_button.setEnabled(False)
        self.batch_open_button.clicked.connect(self._emit_batch_open)

        self.batch_reveal_button = QPushButton("Show selected in Explorer")
        self.batch_reveal_button.setObjectName("ToolButton")
        self.batch_reveal_button.setEnabled(False)
        self.batch_reveal_button.clicked.connect(self._emit_batch_reveal)

        self.copy_paths_button = QPushButton("Copy paths")
        self.copy_paths_button.setObjectName("ToolButton")
        self.copy_paths_button.setEnabled(False)
        self.copy_paths_button.clicked.connect(self._copy_paths)

        self.hint = QLabel("Select a file to open it for review.")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.reveal_button)
        buttons.addWidget(refresh)
        buttons.addStretch(1)

        batch = QHBoxLayout()
        batch.setSpacing(10)
        batch.addWidget(self.batch_open_button)
        batch.addWidget(self.batch_reveal_button)
        batch.addWidget(self.copy_paths_button)
        batch.addStretch(1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(filter_row)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.hint)
        layout.addLayout(buttons)
        layout.addLayout(batch)
        return panel

    # ------------------------------------------------------------------ api --
    def set_palette(self, palette: theme.Palette) -> None:
        self._palette = palette

    def set_files(self, files: list[QuarantinedFile],
                  reasons: dict[str, str] | None = None) -> None:
        """Rebuild the list, keeping the selected file selected if it survives.

        ``reasons`` maps a filename to a captured issue tag
        (:mod:`services.quarantine_reasons_service`); a file with none gets the neutral
        "Needs review" chip. The item's searchable string lives in ``_SEARCH_ROLE`` for the
        filter, while a card widget renders the name, meta and issue tag.
        """
        self._reasons = reasons or {}
        previous = self._selected_path()
        # Building sets check states, which would each fire itemChanged and thrash the
        # batch-button refresh — mute the list until the rebuild is done.
        self.list.blockSignals(True)
        self.list.clear()

        for entry in files:
            # No display text on the item — the card widget below is the only thing drawn.
            # The searchable string goes in _SEARCH_ROLE for _apply_filter to match.
            item = QListWidgetItem()
            item.setData(Qt.UserRole, entry)
            item.setData(_SEARCH_ROLE, f"{entry.name}  {entry.size_label}  "
                                       f"{entry.modified_label}")
            item.setToolTip(str(entry.path))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list.addItem(item)
            card = self._build_card(entry)
            # sizeHint from an unpolished card underestimates; floor it so the two-line
            # text and the chip are never vertically clipped by the row.
            hint = card.sizeHint()
            item.setSizeHint(QSize(hint.width(), max(hint.height(), 56)))
            self.list.setItemWidget(item, card)
            if previous is not None and entry.path == previous:
                item.setSelected(True)

        self.list.blockSignals(False)
        self.count.setText(f"{len(files)} file(s) awaiting review" if files
                           else "queue clear")
        self.stack.setCurrentWidget(self.list if files else self.empty)
        self._apply_filter()
        self._on_selection()
        self._on_check_changed()

    def _build_card(self, entry: QuarantinedFile) -> QWidget:
        """A row card: filename, size · date, and a coloured issue-tag chip."""
        name = QLabel(entry.name)
        name.setObjectName("FlatLabel")
        meta = QLabel(f"{entry.size_label}  ·  {entry.modified_label}")
        meta.setObjectName("Hint")
        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(3)
        text.addWidget(name)
        text.addWidget(meta)

        tag = self._reasons.get(entry.name, "Needs review")
        chip = QLabel(tag)
        chip.setObjectName("Chip")
        colour = getattr(self._palette, _TAG_COLOURS.get(tag, "text_muted"))
        chip.setStyleSheet(
            f"color: {colour}; background: {colour}1A; border: 1px solid {colour}55;")

        card = QWidget()
        # Opaque-background attribute so the card owns its rectangle rather than letting
        # anything paint through it; the fill stays transparent so alternating row colours
        # still read beneath it.
        card.setObjectName("QuarantineCard")
        card.setAttribute(Qt.WA_StyledBackground, True)
        row = QHBoxLayout(card)
        row.setContentsMargins(6, 6, 10, 6)
        row.setSpacing(10)
        row.addLayout(text, 1)
        row.addWidget(chip, 0, Qt.AlignVCenter)
        return card

    def _apply_filter(self) -> None:
        """Hide list items whose label does not contain the filter text.

        Case-insensitive substring over the item's whole label (name, size, date), so
        a partial filename or a date fragment both narrow the queue.
        """
        needle = self.filter_box.text().strip().casefold() if hasattr(self, "filter_box") else ""
        for index in range(self.list.count()):
            item = self.list.item(index)
            haystack = (item.data(_SEARCH_ROLE) or "").casefold()
            item.setHidden(bool(needle) and needle not in haystack)
        # A file hidden by the filter drops out of the batch set — keep the buttons and
        # the master tick honest about what is actually actionable.
        if hasattr(self, "select_all"):
            self._on_check_changed()

    # -------------------------------------------------------------- internal --
    def _selected(self) -> QuarantinedFile | None:
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _selected_path(self):
        entry = self._selected()
        return entry.path if entry else None

    def _on_selection(self) -> None:
        entry = self._selected()
        self.open_button.setEnabled(entry is not None)
        self.reveal_button.setEnabled(entry is not None)
        self.hint.setText(
            f"Opens {entry.name} in whatever application Windows associates with it."
            if entry else "Select a file to open it for review.")

    def _emit_open(self) -> None:
        entry = self._selected()
        if entry is not None:
            self.open_requested.emit(entry)

    def _emit_reveal(self) -> None:
        entry = self._selected()
        if entry is not None:
            self.reveal_requested.emit(entry)

    # ------------------------------------------------------------ batch ops --
    def _checked(self) -> list[QuarantinedFile]:
        """Every ticked file, in list order. Hidden (filtered-out) rows are excluded."""
        out = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked and not item.isHidden():
                out.append(item.data(Qt.UserRole))
        return out

    def _toggle_select_all(self) -> None:
        """Master tick: check or clear every visible row.

        Tristate only reports Partially checked; a click always drives to all-or-none,
        so from a partial state the first click selects everything.
        """
        target = Qt.Unchecked if self.select_all.checkState() == Qt.Unchecked else Qt.Checked
        self.list.blockSignals(True)
        for index in range(self.list.count()):
            item = self.list.item(index)
            if not item.isHidden():
                item.setCheckState(target)
        self.list.blockSignals(False)
        self._on_check_changed()

    def _on_check_changed(self) -> None:
        """Refresh batch-button enablement and the master tick's tristate."""
        checked = self._checked()
        visible = [self.list.item(i) for i in range(self.list.count())
                   if not self.list.item(i).isHidden()]
        any_checked = bool(checked)
        for button in (self.batch_open_button, self.batch_reveal_button,
                       self.copy_paths_button):
            button.setEnabled(any_checked)

        self.select_all.blockSignals(True)
        if not visible or not any_checked:
            self.select_all.setCheckState(Qt.Unchecked)
        elif len(checked) == len(visible):
            self.select_all.setCheckState(Qt.Checked)
        else:
            self.select_all.setCheckState(Qt.PartiallyChecked)
        self.select_all.blockSignals(False)

    def _emit_batch_open(self) -> None:
        files = self._checked()
        if files:
            self.batch_open_requested.emit(files)

    def _emit_batch_reveal(self) -> None:
        files = self._checked()
        if files:
            self.batch_reveal_requested.emit(files)

    def _copy_paths(self) -> None:
        """Put the ticked files' full paths on the clipboard, one per line."""
        files = self._checked()
        if not files:
            return
        QGuiApplication.clipboard().setText("\n".join(str(f.path) for f in files))
        self.hint.setText(f"Copied {len(files)} path(s) to the clipboard.")
