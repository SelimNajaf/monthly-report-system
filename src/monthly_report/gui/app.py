"""Composition root — build the application, or explain why it cannot start.

The settings load happens here, before the window exists, because
``config.load_settings`` is fail-fast (config.py:73-78) and the failure it raises
most often — a missing DejaVu TTF — makes every page meaningless. A dialog that
names the file and its expected location is more use than an empty dashboard.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from .services import app_paths, settings_service
from .ui import theme


def _startup_failure(message: str) -> int:
    """Report a fatal startup problem in a dialog rather than a traceback."""
    QMessageBox.critical(
        None, "Monthly Report Studio — cannot start",
        f"{message}\n\n"
        f"Application root: {app_paths.app_root()}\n"
        f"Expected settings: {app_paths.settings_path()}\n\n"
        f"The config/, assets/, translations/ and images/ folders must sit "
        f"beside the application.")
    return 2


def run_app() -> int:
    """Open the dashboard. Returns the Qt exit code."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)

    app = QApplication(sys.argv)
    app.setApplicationName("Monthly Report Studio")
    app.setOrganizationName("Mag-Pi")
    app.setStyle("Fusion")   # a consistent base under the stylesheet, on every Windows

    family = theme.install_fonts()
    if family:
        font = app.font()
        font.setFamilies([font.family(), family])   # DejaVu backs the AZ glyphs
        app.setFont(font)

    try:
        settings = settings_service.load_settings()
    except settings_service.SettingsError as exc:
        return _startup_failure(str(exc))

    # Imported after the settings check: a window that cannot be populated is
    # not worth constructing.
    from .ui.main_window import MainWindow

    window = MainWindow(settings)
    window.show()
    return app.exec()
