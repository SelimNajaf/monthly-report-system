"""One module per sidebar destination."""

from .dashboard_page import DashboardPage
from .quarantine_page import QuarantinePage
from .settings_page import SettingsPage
from .uploader_page import UploaderPage

__all__ = ["DashboardPage", "QuarantinePage", "SettingsPage", "UploaderPage"]
