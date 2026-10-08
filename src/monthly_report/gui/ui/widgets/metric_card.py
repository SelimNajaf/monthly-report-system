"""A headline number on a raised card.

The counter animates from its previous value rather than snapping. That is not
decoration: when a run finishes and three cards change at once, a number that
travels tells the viewer *which* numbers moved and by how much — a snap just
leaves a different screen.
"""

from __future__ import annotations

from PySide6.QtCore import (QEasingCurve, Property, QPropertyAnimation, Qt)
from PySide6.QtWidgets import (QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QSizePolicy, QVBoxLayout, QWidget)
from PySide6.QtGui import QColor

from .. import theme


class MetricCard(QWidget):
    """One executive metric: an icon, a title, a big number and a caption.

    A card can carry a semantic left-accent border (Stitch's motif: green for the
    Generated card, amber for Quarantined) and a small trend badge beside the number
    (``↑ 12%`` / ``↓ 4%``) fed by :mod:`services.metrics_history_service`.
    """

    def __init__(self, title: str, icon: str = "", accent: str = "",
                 accent_role: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        # A dynamic property the QSS keys the 4px left border off:
        # ``#Card[accent="success"]``. Set even when empty so the selector attribute
        # always exists (a repaint after setProperty then needs no unpolish here — the
        # value is fixed for the card's life).
        self.setProperty("accent", accent_role)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(124)

        self._value = 0
        self._displayed = 0

        header = QHBoxLayout()
        self._title = QLabel(title.upper())
        self._title.setObjectName("CardTitle")
        header.addWidget(self._title)
        header.addStretch(1)
        self._icon = QLabel(icon)
        self._icon.setObjectName("CardIcon")
        header.addWidget(self._icon)

        self._number = QLabel("0")
        self._number.setObjectName("CardValue")
        if accent:
            # Only the value is tinted. Tinting the whole card would turn a
            # dashboard into a traffic light.
            self._number.setStyleSheet(f"color: {accent}; background: transparent;")

        # The trend badge sits inline, right of the number and baseline-aligned to it,
        # exactly as the Stitch mock places the ``↑ 12%``. Hidden until set_trend feeds
        # it a delta that has a baseline to compare against.
        self._trend = QLabel("")
        self._trend.setObjectName("CardTrend")
        self._trend.hide()
        value_row = QHBoxLayout()
        value_row.setContentsMargins(0, 0, 0, 0)
        value_row.setSpacing(8)
        value_row.addWidget(self._number)
        value_row.addWidget(self._trend, 0, Qt.AlignBottom)
        value_row.addStretch(1)

        self._caption = QLabel("")
        self._caption.setObjectName("CardCaption")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(2)
        layout.addLayout(header)
        layout.addLayout(value_row)
        layout.addWidget(self._caption)

        self._animation = QPropertyAnimation(self, b"displayed", self)
        self._animation.setDuration(650)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    # -- animated counter ---------------------------------------------------- #
    def _get_displayed(self) -> int:
        return self._displayed

    def _set_displayed(self, value: int) -> None:
        self._displayed = int(value)
        self._number.setText(f"{self._displayed:,}".replace(",", " "))

    # Qt drives this by name from QPropertyAnimation(b"displayed").
    displayed = Property(int, _get_displayed, _set_displayed)

    def set_value(self, value: int, caption: str = "") -> None:
        """Count to ``value``. Skips the animation when nothing changed."""
        self._caption.setText(caption)
        if value == self._value:
            return
        self._animation.stop()
        self._animation.setStartValue(self._displayed)
        self._animation.setEndValue(int(value))
        self._animation.start()
        self._value = int(value)

    def set_text(self, value: str, caption: str = "") -> None:
        """Show a pre-formatted string instead of an animated integer.

        For metrics that are not whole counts — a percentage like ``94.2%`` or a
        placeholder ``—``. The counter animation is int-only, so a card that has to
        read ``94.2%`` sets its headline directly and skips the tween.
        """
        self._animation.stop()
        self._number.setText(value)
        self._caption.setText(caption)

    def set_caption(self, caption: str) -> None:
        self._caption.setText(caption)

    def set_trend(self, delta, good_when: str = "up") -> None:
        """Show a ``↑ 12%`` / ``↓ 4%`` badge from a metrics_history_service.MetricDelta.

        Colour follows meaning, not direction: ``good_when`` says which way is good for
        this card (Generated rising is good; Quarantined falling is good), so a good move
        is green and a bad one amber. A delta with no baseline — the first run — carries
        an empty label and hides the badge, so the card never shows a fabricated 0%.
        """
        self._trend_delta = delta
        self._trend_good_when = good_when
        label = getattr(delta, "label", "")
        direction = delta.direction
        # No baseline (empty label) or a flat move (baseline present, but unchanged / rounds
        # to 0%) both hide the badge — the card never shows a fabricated "↓ 0%".
        if not label or direction == "flat":
            self._trend.hide()
            return
        arrow = "↑" if direction == "up" else "↓"
        palette = self._palette_or_dark()
        good = (direction == good_when)
        colour = palette.success if good else palette.warning
        self._trend.setText(f"{arrow} {label}")
        self._trend.setStyleSheet(f"color: {colour}; background: transparent;")
        self._trend.show()

    def _palette_or_dark(self) -> theme.Palette:
        return getattr(self, "_palette", theme.DARK)

    def apply_shadow(self, palette: theme.Palette) -> None:
        """Lift the card off the background.

        Re-applied on every theme change: a shadow tuned for a near-black window
        is a smudge on a near-white one, so the alpha comes from the palette.
        """
        self._palette = palette
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(24)
        effect.setOffset(0, 4)
        effect.setColor(QColor(0, 0, 0, palette.shadow))
        self.setGraphicsEffect(effect)
        # Re-tint a live trend badge in the new theme — its colour is set inline, so a
        # theme switch would otherwise strand it in the old palette until the next run.
        if getattr(self, "_trend_delta", None) is not None and self._trend.isVisible():
            self.set_trend(self._trend_delta, self._trend_good_when)
