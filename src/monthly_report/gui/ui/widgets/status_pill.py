"""A coloured dot and a word: what the app is doing, at a glance.

The console carries the detail. This carries the answer to the only question a
manager standing behind the chair actually asks.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from .. import theme


class StatusPill(QWidget):
    """Status indicator. The dot pulses while a job is live."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme.DARK
        self._colour = self._palette.text_muted
        self._bright = True

        self._dot = QLabel("●")
        self._dot.setAlignment(Qt.AlignCenter)
        self._label = QLabel("Idle")
        self._label.setObjectName("FlatLabel")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        layout.addWidget(self._dot)
        layout.addWidget(self._label)

        # A pulse says "still working" during the parse stage, which reports no
        # increments and would otherwise look identical to a hang.
        self._pulse = QTimer(self)
        self._pulse.setInterval(620)
        self._pulse.timeout.connect(self._toggle)
        self._repaint()

    def set_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        self.set_state(self._label.text())

    def set_state(self, state: str) -> None:
        """Colour the pill for a stage name from ``services.progress.Stage``."""
        lowered = state.casefold()
        if lowered in ("idle", ""):
            colour, pulsing = self._palette.text_muted, False
        elif lowered in ("done", "finished"):
            colour, pulsing = self._palette.success, False
        elif lowered in ("failed", "error"):
            colour, pulsing = self._palette.danger, False
        elif lowered == "cancelled":
            colour, pulsing = self._palette.warning, False
        else:
            colour, pulsing = self._palette.accent, True

        self._colour = colour
        self._label.setText(state or "Idle")
        self._label.setStyleSheet(
            f"color: {colour}; background: transparent; font-weight: 600;")

        if pulsing and not self._pulse.isActive():
            self._pulse.start()
        elif not pulsing and self._pulse.isActive():
            self._pulse.stop()
            self._bright = True
        self._repaint()

    def _toggle(self) -> None:
        self._bright = not self._bright
        self._repaint()

    def _repaint(self) -> None:
        opacity = "" if self._bright else "opacity: 0.3;"
        self._dot.setStyleSheet(
            f"color: {self._colour}; background: transparent; font-size: 13px; {opacity}")
