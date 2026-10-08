"""A modal read-out of portal readiness: pass/fail, with the reason on each row.

The header chip says *whether* a live upload is ready; this says *why not*. It is the
same ``settings_service.Check`` list the chip is coloured from, rendered as a checklist
an operator can read down before committing to a portal run — the dry pre-flight that
saves a failed upload halfway through a batch.

The first ``QDialog`` in the app: a top-level window does not inherit the main window's
stylesheet, so it styles itself from the same ``theme`` sheet and object-name vocabulary
(``#Panel``, ``#PageTitle``, ``#Hint``, ``PrimaryButton``) as every page.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from .. import theme


class PreflightDialog(QDialog):
    """Renders a list of ``settings_service.Check`` as a readiness checklist."""

    def __init__(self, checks, palette: theme.Palette,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self.setWindowTitle("Pre-Flight Audit — Portal Readiness")
        self.setMinimumWidth(460)
        # Top-level window: inherit nothing, style from the shared sheet.
        self.setStyleSheet(theme.stylesheet(palette))

        failures = [c for c in checks if not c.ok]

        title = QLabel("Portal Readiness")
        title.setObjectName("PageTitle")
        summary = QLabel("All checks passed — ready for a live upload." if not failures
                         else f"{len(failures)} issue(s) to resolve before a live upload.")
        summary.setObjectName("PageSubtitle")

        panel = QFrame()
        panel.setObjectName("Panel")
        grid = QGridLayout(panel)
        grid.setContentsMargins(18, 16, 18, 16)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        for row, check in enumerate(checks):
            mark = QLabel("✓" if check.ok else "✕")
            colour = palette.success if check.ok else palette.warning
            mark.setStyleSheet(f"color: {colour}; background: transparent; "
                               f"font-weight: 700; font-size: 14px;")

            label = QLabel(check.label)
            label.setObjectName("FlatLabel")

            detail = QLabel(check.detail)
            detail.setObjectName("Hint")
            detail.setWordWrap(True)
            if not check.ok:
                detail.setStyleSheet(f"color: {colour}; background: transparent; "
                                     f"font-size: 11px;")

            grid.addWidget(mark, row * 2, 0, Qt.AlignTop)
            grid.addWidget(label, row * 2, 1, Qt.AlignTop)
            grid.addWidget(detail, row * 2 + 1, 1, Qt.AlignTop)

        close = QPushButton("Close")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(summary)
        layout.addWidget(panel)
        layout.addLayout(buttons)
