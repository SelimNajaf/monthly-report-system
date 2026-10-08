"""Settings: the pre-flight checklist, the signing director, and resolved paths.

``settings.yaml`` is the pipeline's contract and stays hand-edited — every key in
it is documented in place by a comment explaining why it holds the value it does,
and that is not a conversation a dialog can have.

One block is the exception. ``portal.director`` is not configuration in the same
sense: it is a specific person's identity-document values, they are required
before any live upload can run at all (uploader.py:652-674), and the person who
knows them is the one sitting in front of this window rather than the one with
the repository open. So those five fields are editable here, and nothing else is.
The write is a targeted one — see services/settings_writer.

The rest of the page is a health check. ``config.load_settings`` is fail-fast and
raises ``FileNotFoundError`` when a DejaVu TTF is absent (config.py:73-78). From a
terminal that is a clear message. From a GUI it would be a crash on the first
click of Run — so the questions get asked here, before the button is armed.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QFormLayout, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from ...services.settings_service import Check
from ...services.settings_writer import DIRECTOR_KEYS
from .. import theme
from ..widgets import PageHeader

#: The five boxes, in the order the portal shows them. The last two are marked
#: required because they are the two ``assert_director_configured`` refuses a
#: live run without; the name parts are filled by the portal's own lookup from
#: them and are kept so the operator can check that lookup against the document.
_DIRECTOR_FIELDS = (
    ("ad", "First name (ad)", "Given name, exactly as on the identity document"),
    ("soyadi", "Last name (soyadı)", "Surname"),
    ("atasinin_adi", "Patronymic (atasının adı)", "Middle name"),
    ("fin", "FİN *", "Required for a live upload"),
    ("seriya_nomresi", "Seriya nömrəsi *", "Required for a live upload"),
)


class SettingsPage(QWidget):
    """Environment health, resolved paths, and the theme switch."""

    theme_toggled = Signal(bool)        # True = dark
    refresh_requested = Signal()
    director_saved = Signal(dict)       # {key: value} for the five director keys
    purge_cache_requested = Signal()    # wipe the persistent parse cache

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme.palette(theme.DEFAULT_DARK)
        self._director: dict[str, str] = {key: "" for key in DIRECTOR_KEYS}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(16)
        outer.addWidget(self._build_header())

        body = QWidget()
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(16)
        self._body.addWidget(self._build_health())
        self._body.addWidget(self._build_director())
        self._body.addWidget(self._build_maintenance())
        self._body.addWidget(self._build_appearance())
        self._body.addWidget(self._build_about())
        self._body.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        outer.addWidget(scroll, 1)

    def _build_header(self) -> QWidget:
        header = PageHeader("Settings", "Environment health and resolved paths")
        recheck = QPushButton("↻  Re-check")
        recheck.clicked.connect(self.refresh_requested.emit)
        header.add_right(recheck)
        return header

    def _build_health(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("PRE-FLIGHT CHECKS")
        title.setObjectName("SectionTitle")

        # Two columns of diagnostic cards (see set_checks); both stretch evenly.
        self._grid = QGridLayout()
        self._grid.setColumnStretch(0, 1)
        self._grid.setColumnStretch(1, 1)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(12)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addLayout(self._grid)
        return panel

    def _build_director(self) -> QWidget:
        """The one editable block, and the only writer in the application."""
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("SIGNING DIRECTOR")
        title.setObjectName("SectionTitle")

        blurb = QLabel(
            "Written to the portal.director block in settings.yaml. FİN and "
            "Seriya nömrəsi are required before a live upload can run; the "
            "portal fills the three name boxes itself by looking those two up, "
            "so the names here are what you check its answer against.")
        blurb.setObjectName("Hint")
        blurb.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(8)

        self._fields: dict[str, QLineEdit] = {}
        for key, label, hint in _DIRECTOR_FIELDS:
            edit = QLineEdit()
            edit.setPlaceholderText(hint)
            edit.setMaxLength(120)
            # Not masked. These get read character by character off a physical
            # ID card while typing, and a masked field makes that harder without
            # making anything safer — the same values sit in plain text in a
            # file this user owns.
            edit.textEdited.connect(self._on_director_edited)
            self._fields[key] = edit

            caption = QLabel(label)
            caption.setObjectName("FieldLabel")
            form.addRow(caption, edit)

        self.director_status = QLabel("")
        self.director_status.setObjectName("Hint")
        self.director_status.setWordWrap(True)
        self.director_status.hide()

        self.director_save = QPushButton("Save credentials")
        self.director_save.setEnabled(False)
        self.director_save.clicked.connect(self._emit_director)

        self.director_revert = QPushButton("Revert")
        self.director_revert.setEnabled(False)
        self.director_revert.clicked.connect(lambda: self.set_director(self._director))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.director_revert)
        buttons.addWidget(self.director_save)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(blurb)
        layout.addLayout(form)
        layout.addWidget(self.director_status)
        layout.addLayout(buttons)
        return panel

    def _on_director_edited(self, _text: str) -> None:
        """Arm Save only when something actually differs from what is on disk."""
        dirty = any(edit.text().strip() != self._director.get(key, "")
                    for key, edit in self._fields.items())
        self.director_save.setEnabled(dirty)
        self.director_revert.setEnabled(dirty)
        if dirty:
            self.director_status.hide()

    def _emit_director(self) -> None:
        self.director_saved.emit(
            {key: edit.text().strip() for key, edit in self._fields.items()})

    def _build_maintenance(self) -> QWidget:
        """The parse-cache purge — the one housekeeping action worth a button.

        The cache is safe to delete: it memoizes parse *work*, never the reports, so a
        purge only costs the next run a full re-parse (parse_cache.py:1-16). Exposed
        here for the recovery case — a bad batch that poisoned entries, or a want to
        force a clean re-parse — behind a confirmation the window shows.
        """
        # A danger left-accent marks this panel as the one destructive control on the
        # page (reuses the metric-card accent selector).
        panel = QFrame()
        panel.setObjectName("Card")
        panel.setProperty("accent", "danger")

        title = QLabel("MAINTENANCE")
        title.setObjectName("SectionTitle")

        blurb = QLabel(
            "The parse cache memoizes the .docx parse across runs so a monthly run "
            "re-parses only new or changed files. Purging it is safe — no report is "
            "lost, only the saved work — and the next run simply re-parses everything.")
        blurb.setObjectName("Hint")
        blurb.setWordWrap(True)

        self.purge_cache_button = QPushButton("Purge Parse Cache")
        self.purge_cache_button.setObjectName("DangerButton")
        self.purge_cache_button.clicked.connect(self.purge_cache_requested.emit)

        row = QHBoxLayout()
        row.addWidget(self.purge_cache_button)
        row.addStretch(1)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(blurb)
        layout.addLayout(row)
        return panel

    def _build_appearance(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("APPEARANCE")
        title.setObjectName("SectionTitle")

        self.dark_toggle = QCheckBox("Dark theme")
        self.dark_toggle.setChecked(theme.DEFAULT_DARK)
        self.dark_toggle.toggled.connect(self.theme_toggled.emit)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.dark_toggle)
        return panel

    def _build_about(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("ABOUT")
        title.setObjectName("SectionTitle")

        self.about = QLabel("")
        self.about.setObjectName("Hint")
        self.about.setWordWrap(True)
        self.about.setTextInteractionFlags(Qt.TextSelectableByMouse)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)
        layout.addWidget(title)
        layout.addWidget(self.about)
        return panel

    # ------------------------------------------------------------------ api --
    def set_palette(self, palette: theme.Palette) -> None:
        self._palette = palette

    def set_about(self, text: str) -> None:
        self.about.setText(text)

    def set_director(self, values: dict) -> None:
        """Load the values from disk into the form, and make that the clean state.

        Called after every successful save as well as on refresh, so what the
        form calls "unchanged" is always what the file actually contains — not
        what the user last typed.
        """
        self._director = {key: str(values.get(key, "") or "") for key in DIRECTOR_KEYS}
        for key, edit in self._fields.items():
            blocked = edit.blockSignals(True)
            edit.setText(self._director[key])
            edit.blockSignals(blocked)
        self.director_save.setEnabled(False)
        self.director_revert.setEnabled(False)

    def set_director_status(self, message: str, ok: bool) -> None:
        """Report the outcome of a save beside the fields that caused it."""
        colour = self._palette.success if ok else self._palette.danger
        self.director_status.setText(message)
        self.director_status.setStyleSheet(
            f"color: {colour}; background: transparent;")
        self.director_status.show()

    def set_checks(self, checks: list[Check]) -> None:
        """Redraw the checklist as a grid of diagnostic cards, two per row.

        Each check is a card with a success/danger left-accent, an emerald ✓ or red ✕,
        the check label and — stated plainly on failure — its remedy.
        """
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for index, check in enumerate(checks):
            self._grid.addWidget(self._check_card(check), index // 2, index % 2,
                                 Qt.AlignTop)

    def _check_card(self, check: Check) -> QWidget:
        colour = self._palette.success if check.ok else self._palette.danger

        mark = QLabel("✓" if check.ok else "✕")
        mark.setStyleSheet(f"color: {colour}; background: transparent; "
                           f"font-weight: 700; font-size: 18px;")
        label = QLabel(check.label)
        label.setObjectName("FlatLabel")
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(mark, 0, Qt.AlignTop)
        head.addWidget(label, 1, Qt.AlignVCenter)

        detail = QLabel(check.detail)
        detail.setObjectName("Hint")
        detail.setWordWrap(True)
        if not check.ok:
            detail.setStyleSheet(f"color: {colour}; background: transparent; "
                                 f"font-size: 11px;")

        card = QFrame()
        card.setObjectName("Card")
        card.setProperty("accent", "success" if check.ok else "danger")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(detail)
        return card
