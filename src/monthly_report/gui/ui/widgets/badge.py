"""A coloured status pill for a table cell — solid, or pulsing for live states.

The upload ledger needs a per-row status badge: emerald ``UPLOADED``, slate
``SKIPPED``, and a **pulsing** amber ``IN_PROGRESS`` — a stalled row is a report whose
fate nobody knows, and the pulse says "this one still needs a human" at a glance. It
reuses the ``#Chip`` shape from the stylesheet and colours itself inline, the same way
the dashboard's cache/portal chips do; the pulse mirrors :class:`StatusPill`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QLabel, QWidget


class Badge(QLabel):
    """A rounded status chip. Optionally pulses to flag a live/unresolved state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Chip")
        self.setAlignment(Qt.AlignCenter)
        self._colour = "#8C98AD"
        self._bright = True
        self._pulse = QTimer(self)
        self._pulse.setInterval(620)
        self._pulse.timeout.connect(self._toggle)

    def set_status(self, text: str, colour: str, pulsing: bool = False) -> None:
        """Show ``text`` in ``colour``; pulse the fill if ``pulsing``."""
        self._colour = colour
        self.setText(text)
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
        # Two alpha suffixes over the base colour: a translucent fill and a hairline
        # border, brightened/dimmed on each pulse tick.
        fill = "26" if self._bright else "14"      # ~15% / ~8%
        self.setStyleSheet(
            f"color: {self._colour}; background: {self._colour}{fill}; "
            f"border: 1px solid {self._colour}66;")
