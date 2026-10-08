#!/usr/bin/env python
"""Launcher for Monthly Report Studio — the desktop dashboard.

Two modes, one file:

    python gui_launcher.py                     # open the dashboard
    python gui_launcher.py --worker pipeline   # run main.main() headless
    python gui_launcher.py --worker upload --dry-run --all

The worker mode is not a debugging aid, it is how the dashboard runs anything:
the GUI re-launches this exact executable as a child process and reads its
stdout. Keeping both modes in one entry point is what makes a single-file
``.exe`` possible — frozen, ``sys.executable`` *is* this program, so the child
command is simply ``MonthlyReportStudio.exe --worker pipeline``.

The dispatch happens before Qt is imported, so the worker child never pays for
loading a GUI toolkit it will not use.
"""

from __future__ import annotations

import multiprocessing
import sys
from pathlib import Path

# Make the src/ package importable when run as a plain script — same bootstrap
# main.py uses (main.py:27-28). Frozen builds already have it bundled.
if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))


def main(argv: list[str] | None = None) -> int:
    """Route to the worker or the dashboard."""
    argv = list(sys.argv[1:] if argv is None else argv)

    if argv[:1] == ["--worker"]:
        from monthly_report.gui.worker_entry import run_worker

        return run_worker(argv[1:])

    from monthly_report.gui.app import run_app

    return run_app()


if __name__ == "__main__":
    # MUST be the first thing to run. docx_reader.read_many drives a
    # ProcessPoolExecutor (docx_reader.py:184) and Windows spawns rather than
    # forks, so each worker re-executes this program. Without freeze_support the
    # frozen build would open a new dashboard window per CPU core instead of
    # parsing documents.
    multiprocessing.freeze_support()
    raise SystemExit(main())
