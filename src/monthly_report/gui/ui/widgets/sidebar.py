"""Left-hand navigation.

Emits an index and knows nothing about what the pages contain — the window wires
it to a QStackedWidget. That keeps adding a fifth page a one-line change here.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QButtonGroup, QLabel, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)


class Sidebar(QWidget):
    """Brand, nav buttons, footer. ``navigated(index)`` on selection."""

    navigated = Signal(int)

    def __init__(self, items: list[tuple[str, str]], version: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(216)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        brand = QLabel("Monthly Report Studio")
        brand.setObjectName("SidebarBrand")
        brand.setWordWrap(True)
        tagline = QLabel("NDT reporting automation")
        tagline.setObjectName("SidebarTagline")
        layout.addWidget(brand)
        layout.addWidget(tagline)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (icon, label) in enumerate(items):
            button = QPushButton(f"  {icon}   {label}")
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setCursor(button.cursor())
            self._group.addButton(button, index)
            layout.addWidget(button)

        layout.addStretch(1)
        footer = QLabel(f"v{version}" if version else "")
        footer.setObjectName("SidebarFooter")
        layout.addWidget(footer)

        self._group.idClicked.connect(self.navigated.emit)

    def select(self, index: int) -> None:
        button = self._group.button(index)
        if button is not None:
            button.setChecked(True)
            self.navigated.emit(index)
