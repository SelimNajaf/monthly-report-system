"""Runs a backend job as a child process and streams its output.

This is why the dashboard never freezes. ``QProcess`` is asynchronous: it never
blocks, it emits a signal when bytes arrive, and Qt delivers that signal on the
UI thread. There is no worker thread to marshal across, no lock, no
``redirect_stdout``, and no way for a slow pipeline to wedge the event loop —
because the UI thread never waits for it in the first place.

A thread would have been worse on every axis that matters here:

* ``docx_reader.read_many`` drives a ``ProcessPoolExecutor`` (docx_reader.py:184).
  In-process, the GUI becomes the spawn parent of every worker.
* ``sys.stdout`` is process-global. Redirecting it to capture output would race
  with anything else that prints.
* Threads cannot be killed. Cancel would be a lie.

I/O contract
------------
JobRunner().start(kind, args) -> None
    .line(str)  .progress(int)  .stage(str)  .busy(bool)  .finished(int, bool)
"""

from __future__ import annotations

import codecs
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

from . import ansi, app_paths
from .progress import (PipelineProgressParser, ProgressEvent, Stage, Track,
                       UploadProgressParser)

#: Job kinds, matching worker_entry.run_worker's dispatch.
PIPELINE = "pipeline"
UPLOAD = "upload"

#: The uploader's three run modes. Three, not two: ``--dry-run`` and ``--live``
#: are not opposite ends of one switch. With neither flag the uploader opens a
#: real browser, fills the real form, and stops without saving — the mode that
#: exists so a human can read a filled appeal before anything is committed
#: (uploader.py:1985-1990). A Live checkbox would have made it unreachable.
MODE_DRY = "dry"       # no browser at all; writes the dry-run ledger
MODE_FILL = "fill"     # real browser, form filled, nothing saved
MODE_LIVE = "live"     # clicks "Yadda saxla" and saves a draft appeal


@dataclass(frozen=True)
class UploadOptions:
    """What the operator chose on the Uploader page, before it becomes argv.

    Lives here rather than in the window so the page can return one and the
    window can read one without either importing the other. Turning it into
    flags is :func:`ui.main_window._upload_args`'s job, and it is deliberately
    not this class's: which flags the backend ignores in which mode is knowledge
    about ``uploader.py``, not about a radio button.
    """

    mode: str = MODE_DRY
    limit: int = 1
    slow: int = 0
    force: bool = False


def _new_decoder():
    """A UTF-8 decoder that survives a chunk boundary landing mid-character.

    ``replace`` rather than ``strict`` for the same reason the child's streams
    use it (console.py:31-40): a console is a place to read what happened, and
    one undecodable byte must not be able to raise inside a signal handler and
    take the output with it.
    """
    return codecs.getincrementaldecoder("utf-8")("replace")


class JobRunner(QObject):
    """Owns one child process at a time and narrates it to the UI.

    Signals:
        line(str)                  one line of output, escape codes intact
        progress(str, int)         track name, 0-100
        busy(str, bool)            track name; True while it reports no increments
        stage(str)                 human-readable phase
        detail(str, str)           track name, what the current step is doing
        quarantined()              a file was quarantined; refresh that tab
        started()
        finished(int, bool)        exit code, and whether the user cancelled

    The track travels as ``Track``'s string value rather than the enum: Qt's
    signal marshalling only knows the types it was told about, and a plain str
    keeps the UI free to look it up without registering a metatype.
    """

    line = Signal(str)
    progress = Signal(str, int)
    busy = Signal(str, bool)
    stage = Signal(str)
    detail = Signal(str, str)
    quarantined = Signal()
    started = Signal()
    finished = Signal(int, bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._parser = None
        self._buffer = ""
        self._decoder = _new_decoder()
        self._cancelled = False
        self._failed = False

    # ------------------------------------------------------------- lifecycle --
    @property
    def running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.NotRunning

    @property
    def cache_stats(self) -> tuple[int, int] | None:
        """The last pipeline run's ``(hits, misses)``, or None.

        Read after ``finished`` to fill the Cache Efficiency card: the parse-cache
        counts only exist in the worker child's stdout, and the parser is the one
        thing that saw them. Survives until the next ``start`` replaces the parser.
        """
        return getattr(self._parser, "cache_stats", None)

    def start(self, kind: str, args: list[str] | None = None) -> None:
        """Launch ``kind`` with ``args``. One job at a time, enforced here."""
        if self.running:
            raise RuntimeError("a job is already running")

        self._parser = PipelineProgressParser() if kind == PIPELINE else UploadProgressParser()
        self._buffer = ""
        self._decoder = _new_decoder()
        self._cancelled = False
        self._failed = False

        process = QProcess(self)
        # Merged, so a traceback on stderr lands in the console in the right
        # place rather than arriving separately, out of order, or not at all.
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.setWorkingDirectory(str(app_paths.app_root()))
        process.setProcessEnvironment(self._environment())
        process.readyReadStandardOutput.connect(self._drain)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)

        program, arguments = self._command(kind, args or [])
        self._process = process
        self.stage.emit(Stage.IDLE.value)
        for track in Track:
            self.progress.emit(track.value, 0)
        process.start(program, arguments)
        self.started.emit()

    def cancel(self, cleanup_dir: str | None = None) -> None:
        """Kill the job, the workers it spawned, and the mess they left.

        ``QProcess.kill`` reaches the child only. ``ProcessPoolExecutor`` workers
        are grandchildren and outlive it — on Windows they would keep a CPU core
        pinned and hold file handles open long after the UI said "Cancelled".
        ``taskkill /T`` takes the tree, which now covers the PDF conversion pool
        as well as the parser: same mechanism, one process deeper.

        ``cleanup_dir`` is swept for ``.part`` files afterwards. A worker killed
        mid-conversion cannot tidy up after itself, and the process that knew
        what it was writing is the one we just killed — so the sweep belongs
        here, on the outside.
        """
        if not self.running or self._process is None:
            return

        self._cancelled = True
        pid = int(self._process.processId())
        if sys.platform == "win32" and pid:
            try:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                               capture_output=True, timeout=10, check=False)
            except (OSError, subprocess.SubprocessError):
                pass  # fall through to kill() — best effort, never raise from Cancel
        self._process.kill()

        if cleanup_dir:
            # After the kill, so a worker cannot rename a .part into place
            # behind us. Anything it still holds open survives to be swept by
            # convert_input_pdfs on the next run.
            self._process.waitForFinished(3000)
            swept = self._sweep(cleanup_dir)
            if swept:
                self.line.emit(f"[cleanup] removed {swept} partial file(s) "
                               f"left by the cancelled run")

    @staticmethod
    def _sweep(directory: str) -> int:
        """Delete conversion/ingest leftovers. Never raises — this is cleanup."""
        removed = 0
        try:
            for part in Path(directory).rglob("*.part"):
                try:
                    part.unlink()
                    removed += 1
                except OSError:
                    pass   # still locked by a dying worker; next run gets it
        except OSError:
            pass
        return removed

    # --------------------------------------------------------------- command --
    def _command(self, kind: str, args: list[str]) -> tuple[str, list[str]]:
        """Build the child command line.

        Frozen, ``sys.executable`` is the dashboard itself, so the child is the
        same binary with ``--worker``; ``gui_launcher`` dispatches before Qt is
        imported. From source it is the interpreter plus the launcher script.
        """
        worker = ["--worker", kind, *args]
        if app_paths.is_frozen():
            return sys.executable, worker
        return sys.executable, ["-u", str(app_paths.launcher_path()), *worker]

    def _environment(self) -> QProcessEnvironment:
        """Inherit the parent environment, then force line-buffered UTF-8.

        Inheriting is not laziness, it is required. A PyInstaller onefile build
        passes ``_MEIPASS2`` to its children so they reuse the parent's already
        extracted bundle. Building this environment from scratch would drop that
        variable, and every child — including each ProcessPoolExecutor worker —
        would re-unpack several hundred megabytes of PyMuPDF and OpenCV to a new
        temp directory before doing any work.
        """
        env = QProcessEnvironment.systemEnvironment()
        # Without this, output arrives in one lump when the process exits, and
        # the "live" console is a lie.
        env.insert("PYTHONUNBUFFERED", "1")
        # Report names carry Azerbaijani glyphs; the pipe has no code page.
        env.insert("PYTHONIOENCODING", "utf-8")
        return env

    # ----------------------------------------------------------------- output --
    def _drain(self) -> None:
        """Read whatever arrived and emit whole lines.

        Pipes split wherever they please, including mid-character. Two separate
        boundaries have to survive that, and they need different machinery:

        * mid-*character* — ``ə`` is two bytes and a read can land between them.
          The incremental decoder holds the first byte back until the second
          arrives. Decoding each chunk on its own instead, as this used to, turns
          one Azerbaijani letter into two U+FFFD, and does it more often the
          busier the pipe gets.
        * mid-*line* — the tail after the last newline is buffered until the rest
          of it shows up.
        """
        if self._process is None:
            return

        chunk = self._decoder.decode(bytes(self._process.readAllStandardOutput()))
        self._buffer += chunk.replace("\r\n", "\n").replace("\r", "\n")

        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            self._handle(line)

    def _handle(self, line: str) -> None:
        """Emit one line and whatever progress it implies."""
        self.line.emit(line)

        # The parsers match on plain text; the uploader's markers are wrapped in
        # colour codes (uploader.py:135) and would never match raw.
        event = self._parser.feed(ansi.strip(line)) if self._parser else None
        if event is not None:
            self._apply(event)

    def _apply(self, event: ProgressEvent) -> None:
        track = event.track.value
        self.stage.emit(event.stage.value)
        if event.detail:
            self.detail.emit(track, event.detail)
        if event.quarantined:
            self.quarantined.emit()
        if event.fatal:
            self._failed = True

        self.busy.emit(track, event.percent is None)
        if event.percent is not None:
            self.progress.emit(track, event.percent)

    # ----------------------------------------------------------------- events --
    def _on_error(self, error: QProcess.ProcessError) -> None:
        """A process that never started emits no output and no exit code."""
        if error == QProcess.FailedToStart:
            self.line.emit(f"[FATAL] could not start worker process: "
                           f"{self._process.errorString() if self._process else error}")
            self._failed = True

    def _on_finished(self, exit_code: int, status: QProcess.ExitStatus) -> None:
        # Close the decoder first: a process killed mid-character leaves a byte
        # held back, and this is what turns it into the U+FFFD it deserves
        # instead of swallowing it.
        self._buffer += self._decoder.decode(b"", final=True)

        # Flush a final line with no trailing newline — the uploader's summary
        # often arrives that way.
        if self._buffer:
            self._handle(self._buffer)
            self._buffer = ""

        code = exit_code
        if self._cancelled:
            self.stage.emit("Cancelled")
        elif status == QProcess.CrashExit and not self._cancelled:
            self.line.emit("[FATAL] worker process crashed")
            self._failed = True
            code = code or 1
        elif self._failed:
            self.stage.emit(Stage.FAILED.value)
            code = code or 1

        # Never leave a bar spinning: an indeterminate bar on a dead process is
        # the exact "is it working or is it hung?" question this app answers.
        for track in Track:
            self.busy.emit(track.value, False)
        if self._process is not None:
            self._process.deleteLater()
            self._process = None
        self.finished.emit(code, self._cancelled)
