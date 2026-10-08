"""Where the application's data actually lives.

The pipeline resolves every path — ``input/``, ``output/``, fonts, translations —
against a project root that ``config.load_settings`` derives from the location of
``settings.yaml`` (config.py:59). ``main.py`` in turn derives that location from
its own ``__file__``.

That is fine when running from source and wrong once frozen: PyInstaller unpacks
a ``--onefile`` build into a temporary directory and deletes it on exit, so
``main.__file__`` points at ``%TEMP%\\_MEIxxxxx\\main.py``. Left alone, the
pipeline would read ``input/`` from that temp directory and write ``output/``
into it — and every generated report would vanish when the app closed.

So the root is decided here, once, and injected into the backend by
:mod:`monthly_report.gui.worker_entry` before any pipeline code runs.

I/O contract
------------
app_root() -> Path      # the directory holding config/, input/, output/
is_frozen() -> bool
"""

from __future__ import annotations

import sys
from pathlib import Path

# gui/services/app_paths.py -> gui/services -> gui -> monthly_report -> src -> <root>
_SOURCE_ROOT = Path(__file__).resolve().parents[4]


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def app_root() -> Path:
    """The project root: the directory that holds ``config/``, ``input/``, ``output/``.

    Frozen, that is the directory containing the ``.exe`` — data ships beside the
    executable, never inside it, because ``output/`` must survive the process.
    From source, it is the repository root.
    """
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _SOURCE_ROOT


def settings_path() -> Path:
    """Path to ``config/settings.yaml`` under :func:`app_root`."""
    return app_root() / "config" / "settings.yaml"


def state_dir() -> Path:
    """Directory for the dashboard's own persisted state — remembered between runs.

    Kept apart from ``config/`` (the operator's settings) and ``output/`` (reports):
    this is UI bookkeeping — last-run cache stats and the like — that ships beside
    the executable but is not the user's data. Not created here; the writer that
    needs it does the ``mkdir``.
    """
    return app_root() / ".state"


def launcher_path() -> Path:
    """Path to ``gui_launcher.py`` — only meaningful when running from source."""
    return _SOURCE_ROOT / "gui_launcher.py"
