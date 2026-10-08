"""Child-process entry point — the seam between the GUI and the backend.

The dashboard never runs the pipeline in its own process. It re-launches itself
with ``--worker <kind>``, and that child lands here. Nothing in this module
imports Qt: the child is a plain CLI run whose stdout happens to be a pipe.

Why a child process rather than a thread:

* ``docx_reader.read_many`` drives a ``ProcessPoolExecutor`` (docx_reader.py:184).
  Running it inside the GUI process means the GUI itself is the spawn parent.
* ``sys.stdout`` is process-global, so an in-process ``redirect_stdout`` could
  not isolate one job's output from another's.
* A process can actually be killed. A thread cannot.

The one thing this module does to the backend is rebind ``_ROOT`` — a module
global that both entry points read *inside* their functions, never at import
time, so assigning it here takes effect on the very next call. That is dependency
injection from the composition root, not a modification: the files on disk are
untouched, and in a source checkout the value assigned is the one they would have
computed themselves.

I/O contract
------------
run_worker(argv: list[str]) -> int   # argv is everything after ``--worker``
"""

from __future__ import annotations

import sys
import traceback

from .services import app_paths

#: Prefix for failures that escape the backend entirely. The GUI matches on this
#: to colour the line red and mark the job failed rather than merely finished.
FATAL_PREFIX = "[FATAL]"


def _prepare_import_path() -> None:
    """Make ``main`` / ``uploader`` importable when running from source.

    Frozen builds bundle both as hidden imports, so this is a no-op there.
    """
    if app_paths.is_frozen():
        return
    root = str(app_paths.app_root())
    if root not in sys.path:
        sys.path.insert(0, root)


def _run_pipeline(args: list[str]) -> int:
    """Run ``main.main(args)`` — optionally scoped by ``--month/--method/--client``.

    ``args`` is whatever the GUI assembled from the dashboard dropdowns (empty for
    an unattended full run). ``main`` parses it with argparse, exactly as a
    terminal invocation would.
    """
    import main

    # Read at call time (main.py), so this must land before main() is invoked.
    main._ROOT = app_paths.app_root()
    return main.main(args)


def _run_upload(args: list[str]) -> int:
    """Run ``uploader.main(argv)`` with the flags the GUI assembled."""
    import uploader

    # Used by _ledger_path/_resolve_targets/_ledger_key (uploader.py:349,403,415,448).
    uploader._ROOT = app_paths.app_root()
    return uploader.main(args)


def run_worker(argv: list[str]) -> int:
    """Dispatch to a backend entry point and return its exit code.

    Every failure path is funnelled into a single ``[FATAL]`` line. A child that
    dies silently is undiagnosable from the GUI — the console widget would just
    stop. ``uploader`` in particular raises bare ``SystemExit("message")`` in six
    places (e.g. uploader.py:427, 615), which would otherwise print nothing
    useful to a pipe.
    """
    if not argv:
        print(f"{FATAL_PREFIX} worker requires a job kind: pipeline | upload")
        return 2

    kind, rest = argv[0], argv[1:]
    _prepare_import_path()

    try:
        if kind == "pipeline":
            return _run_pipeline(rest)
        if kind == "upload":
            return _run_upload(rest)
        print(f"{FATAL_PREFIX} unknown job kind: {kind!r}")
        return 2
    except SystemExit as exc:
        # argparse exits 0/2; the uploader raises SystemExit("human message").
        code = exc.code
        if isinstance(code, int):
            return code
        if code:
            print(f"{FATAL_PREFIX} {code}")
        return 1
    except KeyboardInterrupt:
        print(f"{FATAL_PREFIX} cancelled")
        return 130
    except Exception as exc:
        # Verbose inside: the traceback goes to the console widget, where it is
        # visible and copyable, instead of dying with the process.
        traceback.print_exc()
        print(f"{FATAL_PREFIX} {type(exc).__name__}: {exc}")
        return 1
