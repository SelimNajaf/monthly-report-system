"""The window: wires pages to services and owns the run policy.

Policy lives here rather than in any page, so "one job at a time, and here is
what that disables" is stated once. The pages emit intent and render what they
are given; nothing below this file knows a QProcess exists.

Filesystem scans run on a QThreadPool. They are quick today — a hundred PDFs and
fifty-odd quarantined files — but they are unbounded in principle, and a
directory walk on the UI thread is exactly the stutter this app exists to avoid.
"""

from __future__ import annotations

from PySide6.QtCore import QFileSystemWatcher, QObject, QRunnable, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QMainWindow, QMessageBox,
                               QStackedWidget, QWidget)

from .. import __version__
from ..services import (app_paths, cache_service, cache_stats_service,
                        catalog as catalog_mod, ingest_service, job_runner,
                        ledger_service, metrics as metrics_mod,
                        metrics_history_service, quarantine_reasons_service,
                        quarantine_service, settings_service, settings_writer,
                        summary_exporter)
from ..services.progress import Stage, Track
from . import theme
from .pages import DashboardPage, QuarantinePage, SettingsPage, UploaderPage
from .widgets import Sidebar
from .widgets.preflight_dialog import PreflightDialog

_NAV = [("◆", "Dashboard"), ("☁", "Uploader / Registry"),
        ("⚠", "Quarantine"), ("⚙", "Settings")]

DASHBOARD, UPLOADER, QUARANTINE, SETTINGS = range(4)

#: How each run mode is named in the console notice that opens a run.
_MODE_NAMES = {job_runner.MODE_DRY: "dry-run",
               job_runner.MODE_FILL: "fill-only",
               job_runner.MODE_LIVE: "LIVE"}


def _filter_args(month: str, method: str, client: str) -> list[str]:
    """Turn dashboard filters into ``--month/--method/--client`` argv.

    An "All" selection is the empty sentinel (``catalog.ALL``) and is omitted, so
    the flag is present only when the user narrowed that dimension. The pipeline
    and the uploader both build their scope from this one function, which is what
    guarantees "Run Pipeline" and "Start Portal Upload" scope identically.
    """
    args: list[str] = []
    if month:
        args += ["--month", month]
    if method:
        args += ["--method", method]
    if client:
        args += ["--client", client]
    return args


def _upload_args(options, month: str, method: str, client: str) -> list[str]:
    """Turn the Uploader page's choices into ``uploader.py`` argv.

    The three modes are three different command lines, not one line with a flag
    flipped: ``--dry-run`` and ``--live`` are separate flags and the third mode
    passes neither, which is what makes it fill the real form and stop.

    Flags the chosen mode would render inert are omitted rather than passed and
    ignored. ``--limit`` outside Live is the clear case — ``_effective_limit``
    caps a run that cannot save at one report (uploader.py:1985-1990), so a
    ``--limit 3`` printed to the console would be a promise of three reports the
    backend has already decided against. Same for ``--slow`` with no browser to
    slow. The console line names what will happen, and this is what keeps that
    true.
    """
    mode = getattr(options, "mode", job_runner.MODE_DRY)

    if mode == job_runner.MODE_DRY:
        args = ["--dry-run", "--all"]
    elif mode == job_runner.MODE_LIVE:
        args = ["--live", "--all"]
    else:
        args = ["--all"]

    args += _filter_args(month, method, client)

    if mode == job_runner.MODE_LIVE:
        args += ["--limit", str(options.limit)]
    if mode != job_runner.MODE_DRY and options.slow:
        args += ["--slow", str(options.slow)]
    # --force is a ledger decision, not a browser one: it applies in every mode,
    # including the dry run, whose own ledger can strand a row just the same.
    if options.force:
        args.append("--force")

    return args


class _ScanSignals(QObject):
    done = Signal(object, object, object)   # catalog, metrics, quarantine listing
    failed = Signal(str)


class _ScanTask(QRunnable):
    """Walk input/ and output/ off the UI thread.

    The window keeps a reference to every live task. That is not belt-and-braces:
    ``QThreadPool.start`` takes ownership of the C++ runnable, but nothing owns
    the *Python* wrapper, so once ``refresh`` returns it is collectable — and it
    takes ``signals`` with it while the worker thread is still inside ``run``.
    The result is a "Signal source has been deleted" RuntimeError, a scan whose
    result never arrives, and a ``_scanning`` flag that never clears, which
    freezes the metrics for the rest of the session.
    """

    def __init__(self, settings, month: str, method: str, client: str) -> None:
        super().__init__()
        self.signals = _ScanSignals()
        self._settings = settings
        self._filters = (month, method, client)

    def run(self) -> None:
        try:
            names = catalog_mod.client_names_from(self._settings)
            catalog = catalog_mod.scan(self._settings.output_dir, names)
            counts = metrics_mod.collect(self._settings, catalog, *self._filters)
            files = quarantine_service.listing(self._settings)
            payload = (catalog, counts, files)
        except Exception as exc:   # a scan must never take the window with it
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        # Emitted outside the try: an exception raised by a *slot* is the slot's
        # problem, and must not be reported as a failed scan.
        self.signals.done.emit(*payload)


class _IngestSignals(QObject):
    progress = Signal(int, int, str)    # index, total, name
    done = Signal(object)               # IngestResult
    failed = Signal(str)


class _IngestTask(QRunnable):
    """Copy a dropped selection into ``input/`` off the UI thread.

    Both halves have to be off-thread, not just the copy: walking a dropped
    folder of a thousand files is itself slow enough to stutter the window, and
    the count is not known until the walk finishes.

    Same lifetime rule as :class:`_ScanTask` — the window holds a reference or
    the Python wrapper is collected while ``run`` is still using it.
    """

    def __init__(self, paths: list[str], input_dir) -> None:
        super().__init__()
        self.signals = _IngestSignals()
        self._paths = paths
        self._input_dir = input_dir
        self._cancelled = False

    def cancel(self) -> None:
        """Stop between files. Our own code is doing the copying — no kill needed."""
        self._cancelled = True

    def run(self) -> None:
        try:
            files = ingest_service.discover(self._paths, self._input_dir)
            result = ingest_service.ingest(
                files, self._input_dir,
                progress=self.signals.progress.emit,
                cancelled=lambda: self._cancelled)
        except Exception as exc:   # a drop must never take the window with it
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.signals.done.emit(result)   # outside the try: see _ScanTask.run


class _RecountSignals(QObject):
    done = Signal(object)   # Metrics


class _RecountTask(QRunnable):
    """Recount the filter-dependent metrics from a Catalog already in hand.

    Changing a dropdown does not change what is on disk — only which slice of it
    the cards should show. The old path re-walked ``output/`` and rebuilt all
    three combos for that (:meth:`MainWindow.refresh`), which is what made
    selection feel laggy and flickered an open popup. This reuses the cached
    Catalog and only recomputes the counts (``metrics.collect`` still reads the
    small ``input/`` tree, which is why it stays off the UI thread).

    Same lifetime rule as :class:`_ScanTask` — the window holds a reference or the
    Python wrapper is collected while ``run`` is still using it.
    """

    def __init__(self, settings, catalog, month: str, method: str, client: str) -> None:
        super().__init__()
        self.signals = _RecountSignals()
        self._settings = settings
        self._catalog = catalog
        self._filters = (month, method, client)

    def run(self) -> None:
        try:
            counts = metrics_mod.collect(self._settings, self._catalog, *self._filters)
        except Exception:
            return   # a recount is a repaint; on failure the cards keep their
                     # last honest value rather than showing an error
        self.signals.done.emit(counts)


class MainWindow(QMainWindow):
    """Monthly Report Studio."""

    def __init__(self, settings) -> None:
        super().__init__()
        self._settings = settings
        self._dark = theme.DEFAULT_DARK
        self._pool = QThreadPool.globalInstance()
        self._scanning = False
        self._rescan_pending = False
        self._tasks: set[_ScanTask] = set()
        self._recounts: set[_RecountTask] = set()
        self._ingest: _IngestTask | None = None
        self._catalog = None   # last scan's Catalog; reused for filter recounts
        self._metrics = None   # last scan's Metrics; reused for the summary export

        self.setWindowTitle("Monthly Report Studio")
        self.resize(1280, 840)
        self.setMinimumSize(1060, 700)

        self.dashboard = DashboardPage()
        self.uploader = UploaderPage()
        self.quarantine = QuarantinePage()
        self.settings_page = SettingsPage()

        self.stack = QStackedWidget()
        for page in (self.dashboard, self.uploader, self.quarantine, self.settings_page):
            self.stack.addWidget(page)

        self.sidebar = Sidebar(_NAV, version=__version__)
        self.sidebar.navigated.connect(self._navigate)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._runner = job_runner.JobRunner(self)
        self._connect()
        self._apply_theme()

        # Quarantine changes under our feet: the pipeline moves files there while
        # a run is live. Watching the directory beats asking the user to refresh.
        self._watcher = QFileSystemWatcher(self)
        folder = quarantine_service.quarantine_dir(settings)
        if folder.is_dir():
            self._watcher.addPath(str(folder))
        self._watcher.directoryChanged.connect(lambda _: self._debounced_refresh())

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(400)   # a run touches the folder in bursts
        self._debounce.timeout.connect(self.refresh)

        self.sidebar.select(DASHBOARD)
        self.refresh()
        self._refresh_health()
        # The last run's cache efficiency was persisted; show it now rather than an
        # empty card, so the metric is there before the operator runs anything.
        self.dashboard.set_cache_efficiency(cache_stats_service.load())
        self.dashboard.console.append_notice(
            f"Ready. Application root: {app_paths.app_root()}")

    # ----------------------------------------------------------------- wiring --
    def _connect(self) -> None:
        self.dashboard.run_requested.connect(self._run_pipeline)
        self.dashboard.upload_requested.connect(self._run_upload)
        self.dashboard.cancel_requested.connect(self._cancel)
        self.dashboard.filters_changed.connect(self._on_filters_changed)
        self.dashboard.files_dropped.connect(self._on_files_dropped)
        self.dashboard.export_requested.connect(self._export_summary)
        self.dashboard.validate_requested.connect(self._show_preflight)

        self.uploader.upload_requested.connect(self._run_upload)
        self.uploader.refresh_requested.connect(self._refresh_ledger)
        self.uploader.reset_requested.connect(self._reset_ledger_entry)
        self.uploader.validate_requested.connect(self._show_preflight)

        self.quarantine.open_requested.connect(self._open_quarantined)
        self.quarantine.reveal_requested.connect(
            lambda entry: quarantine_service.reveal_in_explorer(entry.path))
        self.quarantine.refresh_requested.connect(self.refresh)
        self.quarantine.batch_open_requested.connect(self._batch_open_quarantined)
        self.quarantine.batch_reveal_requested.connect(self._batch_reveal_quarantined)

        self.settings_page.theme_toggled.connect(self._on_theme_toggled)
        self.settings_page.refresh_requested.connect(self._refresh_health)
        self.settings_page.director_saved.connect(self._save_director)
        self.settings_page.purge_cache_requested.connect(self._purge_cache)

        self._runner.line.connect(self.dashboard.console.append_line)
        self._runner.line.connect(self._capture_quarantine_reason)
        self._runner.progress.connect(
            lambda track, percent: self.dashboard.set_progress(Track(track), percent))
        self._runner.busy.connect(
            lambda track, busy: self.dashboard.set_busy(Track(track), busy))
        self._runner.stage.connect(lambda stage: self.dashboard.set_stage(stage))
        self._runner.detail.connect(self._on_detail)
        self._runner.quarantined.connect(self._debounced_refresh)
        self._runner.finished.connect(self._on_finished)

    # -------------------------------------------------------------- run policy --
    def _run_pipeline(self) -> None:
        """Run the pipeline, scoped by the dashboard filters.

        The argv is built exactly like the uploader's (:meth:`_run_upload`): the
        same tokens, the same "omit when All" rule. main.py reads them off with
        argparse; an empty argv is the unattended full run it has always done.
        """
        if self._runner.running or self._ingesting:
            return

        args = _filter_args(*self.dashboard.filters())

        # Capture the "before" counts as the trend baseline, so once the run lands the
        # cards can show what it changed (metrics_history_service). Best-effort: a snapshot
        # that cannot be written just means no badge, never a failed run.
        if self._metrics is not None:
            metrics_history_service.snapshot(self._metrics)

        self.dashboard.console.clear_log()
        if args:
            self.dashboard.console.append_notice(
                f"Starting scoped pipeline: {' '.join(args)}")
        else:
            self.dashboard.console.append_notice(
                "Starting pipeline — processing every discovered group "
                "(month × method × client).")
        self.dashboard.reset_tracks()
        self._set_running(True)
        self._runner.start(job_runner.PIPELINE, args)

    def _cancel(self) -> None:
        """One button, two kinds of job.

        An ingest is our own code and stops with a flag; a pipeline is a child
        process tree and needs a kill. The user does not care which is running.
        """
        if self._ingesting and self._ingest is not None:
            self._ingest.cancel()
            self.dashboard.console.append_notice(
                "Stopping ingestion after the current file...", "warning")
            return
        self._runner.cancel(cleanup_dir=str(self._settings.input_dir))

    def _run_upload(self) -> None:
        """Assemble the uploader's argv from the filters and the run options.

        The filter values come from ``catalog``, which read them off real
        filenames, so they are the exact tokens ``uploader.py`` matches
        (uploader.py:434). The mode, limit, slow-motion and force come from the
        Uploader page.
        """
        if self._runner.running or self._ingesting:
            return

        options = self.uploader.options()
        args = _upload_args(options, *self.dashboard.filters())

        if options.mode == job_runner.MODE_LIVE and not self._confirm_live(options):
            return

        self.stack.setCurrentIndex(DASHBOARD)
        self.sidebar.select(DASHBOARD)
        self.dashboard.console.clear_log()
        self.dashboard.console.append_notice(
            f"Starting {_MODE_NAMES[options.mode]} upload: {' '.join(args)}",
            "warning" if options.mode == job_runner.MODE_LIVE else "accent")
        self.dashboard.reset_tracks()
        # Point the registry at the ledger THIS run writes: a dry run keeps its
        # own file, so leaving the live one on screen would show a table that
        # never updates and invite the conclusion that nothing happened.
        self.uploader.set_ledger_view(dry_run=options.mode == job_runner.MODE_DRY)
        self._set_running(True)
        self._runner.start(job_runner.UPLOAD, args)
        self._refresh_ledger()

    def _confirm_live(self, options) -> bool:
        """Ask before filing on a government portal. Default is No.

        The pre-flight has already established the run *could* work; this asks
        whether it *should*, and states the three things that decide it: where it
        is going, how much of it, and whether --force is on. Force earns its own
        line because it is the only option here that can create a duplicate
        record on a portal someone else has to go and withdraw.
        """
        portal = (self._settings.raw.get("portal") or {})
        url = portal.get("url") or "the E-Keyfiyyet portal"
        month, method, client = self.dashboard.filters()
        scope = " · ".join(p for p in (month.replace("_", " "), method, client) if p)

        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("Start a live upload?")
        box.setText("This saves real draft appeals on the portal.")
        box.setInformativeText(
            f"Portal:  {url}\n"
            f"Scope:   {scope or 'all pending reports'}\n"
            f"Reports: up to {options.limit}\n"
            f"Force:   {'ON — may create duplicate drafts' if options.force else 'off'}\n\n"
            f"Drafts are saved but never signed: “E-imza ilə təsdiqlə” is not "
            f"clicked. A browser will open and may ask you to log in with "
            f"e-İmza / Asan İmza.")
        box.setStandardButtons(QMessageBox.Cancel | QMessageBox.Yes)
        box.setDefaultButton(QMessageBox.Cancel)
        box.button(QMessageBox.Yes).setText("Start live upload")
        return box.exec() == QMessageBox.Yes

    def _set_running(self, running: bool) -> None:
        self.dashboard.set_running(running)
        self.uploader.set_running(running)

    def _on_detail(self, track: str, detail: str) -> None:
        self.dashboard.set_track_detail(Track(track), detail)
        stage = self.dashboard.stage_label.text().split(" — ")[0]
        self.dashboard.set_stage(stage, detail)

    def _on_finished(self, code: int, cancelled: bool) -> None:
        self._set_running(False)

        if cancelled:
            self.dashboard.set_stage("Cancelled")
            self.dashboard.console.append_notice("Cancelled by user.", "warning")
        elif code == 0:
            self.dashboard.set_stage("Done")
            self.dashboard.console.append_notice("Finished successfully.", "success")
        elif code == 1:
            # main.py returns 1 for "no datable reports" (main.py:131) — a
            # legitimate outcome, not a failure. The console already said which.
            self.dashboard.set_stage("Done")
            self.dashboard.console.append_notice(
                "Finished — nothing to process, or the run reported an issue "
                "above.", "warning")
        else:
            self.dashboard.set_stage("Failed")
            self.dashboard.console.append_notice(f"Failed with exit code {code}.", "danger")

        # Persist and show the run's parse-cache efficiency. Only a pipeline run reports
        # it; an upload leaves cache_stats None, so the last pipeline figure stands.
        stats = self._runner.cache_stats
        if stats is not None:
            self.dashboard.set_cache_efficiency(cache_stats_service.record(*stats))

        self.refresh()
        self._refresh_ledger()

    # ---------------------------------------------------------------- ingest --
    @property
    def _ingesting(self) -> bool:
        return self._ingest is not None

    def _on_files_dropped(self, paths: list) -> None:
        """Take a drop: walk it, copy it, and say what happened.

        Refused outright while a job runs. The pipeline is walking ``input/`` and
        moving files out of it at that moment (pre_processor.sort_input_files),
        and a file added underneath a live walk is one that is neither sorted nor
        processed — it just quietly is not in this month's report.
        """
        if self._runner.running:
            self.dashboard.console.append_notice(
                "Ingestion is paused while a job is running — wait for it to "
                "finish, then drop again.", "warning")
            return
        if self._ingesting:
            self.dashboard.console.append_notice(
                "Still ingesting the previous drop.", "warning")
            return

        self.dashboard.console.append_notice(
            f"Scanning {len(paths)} dropped item(s) for reports...")
        self.dashboard.set_stage(Stage.COPY.value)
        self.dashboard.set_busy(Track.INGEST, True)   # the walk reports nothing
        self._set_running(True)

        task = _IngestTask(list(paths), self._settings.input_dir)
        self._ingest = task                # see _ScanTask: the pool does not own this
        task.signals.progress.connect(self._on_ingest_progress)
        task.signals.done.connect(self._on_ingested)
        task.signals.failed.connect(self._on_ingest_failed)
        self._pool.start(task)

    def _on_ingest_progress(self, index: int, total: int, name: str) -> None:
        self.dashboard.set_progress(Track.INGEST, int(100 * index / max(total, 1)))
        self.dashboard.set_track_detail(Track.INGEST, f"Copying {index} of {total} — {name}")

    def _on_ingested(self, result) -> None:
        self._finish_ingest()
        summary = result.summary()

        level = "success" if result.copied and not result.failed else "warning"
        self.dashboard.console.append_notice(summary, level if result.total else "info")
        for name, reason in result.failed:
            self.dashboard.console.append_notice(f"  {name}: {reason}", "danger")
        if result.skipped:
            # No-clobber is only honest if the user can see it happened.
            self.dashboard.console.append_notice(
                f"  {len(result.skipped)} file(s) were already in input/ and were "
                f"left untouched — nothing was overwritten.", "info")

        self.dashboard.set_ingest_message(summary)
        self.dashboard.set_progress(Track.INGEST, 100 if result.copied else 0)
        self.dashboard.set_track_detail(Track.INGEST, summary)
        self.dashboard.set_stage("Ready" if result.copied else "Idle")
        self.refresh()

    def _on_ingest_failed(self, message: str) -> None:
        self._finish_ingest()
        self.dashboard.set_stage("Failed")
        self.dashboard.console.append_notice(f"Could not ingest that drop: {message}",
                                             "danger")

    def _finish_ingest(self) -> None:
        self._ingest = None
        self.dashboard.set_busy(Track.INGEST, False)
        self._set_running(False)

    # --------------------------------------------------------------- refresh --
    def _debounced_refresh(self) -> None:
        self._debounce.start()

    def refresh(self) -> None:
        """Rescan the filesystem off-thread and repaint the cards."""
        if self._scanning:
            # A scan is already walking the tree. Note that its answer will be
            # stale rather than starting a second walk, and re-run once it lands
            # — dropping the request would leave the cards showing the old
            # filter's numbers indefinitely.
            self._rescan_pending = True
            return

        self._scanning = True
        month, method, client = self.dashboard.filters()
        task = _ScanTask(self._settings, month, method, client)
        self._tasks.add(task)          # see _ScanTask: the pool does not own this
        task.signals.done.connect(self._on_scanned)
        task.signals.failed.connect(self._on_scan_failed)
        self._pool.start(task)

    def _on_scanned(self, catalog, counts, files) -> None:
        self._finish_scan()
        self._catalog = catalog   # reused by _on_filters_changed's recount
        self._metrics = counts     # reused by the summary export
        self.dashboard.set_metrics(counts, self._trend_deltas(counts))
        self.dashboard.populate_filters(catalog)
        self.dashboard.set_cache_status(cache_service.status(self._settings))
        self.dashboard.set_portal_readiness(self._portal_readiness())
        self.quarantine.set_files(files, quarantine_reasons_service.load())
        self.uploader.set_scope(*self.dashboard.filters())

    def _portal_readiness(self) -> list:
        """The pre-upload checklist, best-effort — a chip must never crash a scan."""
        try:
            return settings_service.portal_readiness(self._settings)
        except Exception:  # noqa: BLE001 — a readiness read is advisory, not load-bearing
            return []

    def _on_scan_failed(self, message: str) -> None:
        self._finish_scan()
        self.dashboard.console.append_notice(f"Could not scan directories: {message}",
                                             "danger")

    def _finish_scan(self) -> None:
        """Release the task and honour any request that arrived while it ran."""
        self._scanning = False
        self._tasks.clear()
        if self._rescan_pending:
            self._rescan_pending = False
            self.refresh()

    def _on_filters_changed(self, month: str, method: str, client: str) -> None:
        self.uploader.set_scope(month, method, client)
        # A filter change does not alter what exists on disk, so it must NOT
        # re-walk output/ or rebuild the dropdowns — doing so is what made
        # selection laggy and flickered the open popup. Recount the cards from
        # the catalog already in hand. Until the first scan lands there is no
        # catalog to reuse, so fall back to a full refresh that one time.
        if self._catalog is None:
            self.refresh()
            return
        task = _RecountTask(self._settings, self._catalog, month, method, client)
        self._recounts.add(task)   # see _ScanTask: the pool does not own this
        # Bind the task so a rapid second change can't clear a still-running one.
        task.signals.done.connect(lambda counts, t=task: self._on_recounted(counts, t))
        self._pool.start(task)

    def _capture_quarantine_reason(self, line: str) -> None:
        """Persist the issue tag for any file the pipeline reports quarantining.

        The reason is printed once, as the run streams, and kept nowhere else — captured
        here so the Quarantine Explorer can show it as a tag long after the console
        scrolls away. Best-effort: a line that is not a quarantine line is ignored.
        """
        parsed = quarantine_reasons_service.parse_line(line)
        if parsed is not None:
            quarantine_reasons_service.record(*parsed)

    def _on_recounted(self, counts, task) -> None:
        self._recounts.discard(task)
        self.dashboard.set_metrics(counts, self._trend_deltas(counts))

    def _trend_deltas(self, counts):
        """Per-card trend against the last run's baseline — whole-corpus only.

        Under an active filter the Generated count is a slice, and comparing a slice to
        the unfiltered baseline snapshot would show a nonsense delta. So the baseline is
        withheld when any filter narrows the view: the returned deltas then carry no
        previous value and the badges hide, rather than showing a misleading figure.
        """
        unfiltered = all(f == catalog_mod.ALL for f in self.dashboard.filters())
        baseline = metrics_history_service.load() if unfiltered else None
        return metrics_history_service.deltas(counts, baseline)

    def _refresh_ledger(self) -> None:
        path = ledger_service.ledger_path(app_paths.app_root(),
                                          dry_run=self.uploader.show_dry_run_ledger())
        self.uploader.set_view(ledger_service.read(path))

    def _reset_ledger_entry(self, key: str) -> None:
        """Clear one stalled ledger row after confirming, then re-read the ledger.

        Refused while a job runs — editing the ledger the uploader is checkpointing
        into would race its writes. The confirmation names what happens next
        (re-queued for upload), because a Reset that silently re-files on the next run
        is a surprise on a government portal.
        """
        if self._runner.running or self._ingesting:
            return

        answer = QMessageBox.question(
            self, "Reset this entry?",
            "This clears the stalled IN_PROGRESS record so the next upload re-sends "
            "this report.\n\n"
            "Only do this after checking the portal does not already have it — "
            "otherwise the run can create a duplicate draft.",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return

        path = ledger_service.ledger_path(app_paths.app_root(),
                                          dry_run=self.uploader.show_dry_run_ledger())
        try:
            cleared = ledger_service.reset_entry(path, key)
        except ledger_service.LedgerError as exc:
            QMessageBox.warning(self, "Could not reset entry", str(exc))
            return

        self.dashboard.console.append_notice(
            f"Reset {key.rsplit('/', 1)[-1]} — it will be re-uploaded on the next run."
            if cleared else f"{key.rsplit('/', 1)[-1]} was no longer in the ledger.",
            "warning" if cleared else "info")
        self._refresh_ledger()

    def _purge_cache(self) -> None:
        """Wipe the persistent parse cache after confirming, and report the count.

        Safe by construction (parse_cache memoizes work, not reports), but a full
        re-parse next run is worth a heads-up — so the dialog states the entry count
        and the consequence before deleting.
        """
        status = cache_service.status(self._settings)
        if not status.entries:
            QMessageBox.information(
                self, "Parse cache", "The parse cache is already empty — nothing to purge.")
            return

        answer = QMessageBox.question(
            self, "Purge the parse cache?",
            f"Delete {status.entries} cached parse(s) ({status.size_label})?\n\n"
            f"No report is lost — only the saved parse work. The next run will "
            f"re-parse every document under input/, which will be slower once.",
            QMessageBox.Cancel | QMessageBox.Yes, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return

        removed = cache_service.purge(self._settings)
        self.dashboard.console.append_notice(
            f"Purged parse cache — {removed} entr{'y' if removed == 1 else 'ies'} removed.",
            "warning")
        self.dashboard.set_cache_status(cache_service.status(self._settings))

    def _refresh_health(self) -> None:
        self.settings_page.set_checks(settings_service.health())
        self.settings_page.set_director(self._director())
        self.uploader.set_live_available(*self._live_precondition())
        self.settings_page.set_about(
            f"Monthly Report Studio v{__version__}\n"
            f"Frontend for the Monthly Report pipeline (main.py) and portal "
            f"uploader (uploader.py).\n\n"
            f"Application root: {app_paths.app_root()}\n"
            f"Settings file: {app_paths.settings_path()}\n"
            f"Mode: {'packaged executable' if app_paths.is_frozen() else 'source checkout'}\n\n"
            f"Uploads run in one of three modes, chosen on the Uploader page: a "
            f"dry run that launches no browser, a fill-only run that leaves the "
            f"completed form on screen without saving, and a live run that saves "
            f"a draft appeal. No mode ever signs one — “E-imza ilə təsdiqlə” is "
            f"not clicked by this application.")

    def _director(self) -> dict:
        """The signing director's configured values, or blanks if unreadable."""
        try:
            return settings_writer.read_director(app_paths.settings_path())
        except settings_writer.SettingsWriteError:
            # The health checklist above already reports an unreadable settings
            # file, in more detail than an empty form could.
            return {key: "" for key in settings_writer.DIRECTOR_KEYS}

    def _live_precondition(self) -> tuple[bool, str]:
        """Whether a live upload could work at all, and why not if it could not.

        Both halves are things ``uploader.py`` checks for itself and exits on —
        ``assert_director_configured`` (uploader.py:652-674) and the Playwright
        import. Asking here means the answer arrives as a greyed-out radio with a
        reason, instead of as a child process that dies two seconds after a
        click on a button labelled LIVE.
        """
        try:
            import playwright  # noqa: F401
        except ImportError:
            return False, ("Playwright is not installed, so no browser can be "
                           "driven. Dry-run uploads still work.")

        director = self._director()
        missing = [key for key in ("fin", "seriya_nomresi") if not director.get(key, "").strip()]
        if missing:
            return False, ("the signing director's "
                           + " and ".join("FİN" if k == "fin" else "Seriya nömrəsi"
                                          for k in missing)
                           + " is not set. Fill it in on the Settings tab — the "
                             "uploader refuses a live run without it.")

        return True, ""

    def _save_director(self, values: dict) -> None:
        """Write the credentials, then re-read everything that depended on them.

        Re-reading rather than trusting the write: ``self._settings`` was loaded
        at startup and is what ``_confirm_live`` reads the portal URL from, and
        the live precondition is computed from the file. Both have to be taken
        from disk again, or the app would be acting on the previous values while
        showing the new ones.
        """
        path = app_paths.settings_path()
        try:
            settings_writer.write_director(path, values)
        except settings_writer.SettingsWriteError as exc:
            self.settings_page.set_director_status(str(exc), ok=False)
            return

        try:
            self._settings = settings_service.load_settings()
        except settings_service.SettingsError as exc:
            self.settings_page.set_director_status(
                f"Saved, but the settings file no longer loads: {exc}", ok=False)
            return

        self.settings_page.set_director_status(
            f"Saved to {path.name}. A backup of the previous values is in "
            f"{path.name}.bak.", ok=True)
        self._refresh_health()

    def _open_quarantined(self, entry) -> None:
        try:
            quarantine_service.open_in_default_app(entry.path)
        except OSError as exc:
            QMessageBox.warning(self, "Could not open file", str(exc))

    def _batch_open_quarantined(self, files: list) -> None:
        """Open every ticked file in its default app. Confirms past a sane threshold."""
        if not self._confirm_batch(files, "open", "windows"):
            return
        failed = []
        for entry in files:
            try:
                quarantine_service.open_in_default_app(entry.path)
            except OSError:
                failed.append(entry.name)
        opened = len(files) - len(failed)
        self.dashboard.console.append_notice(
            f"Opened {opened} quarantined file(s)."
            + (f" {len(failed)} could not be opened: {', '.join(failed)}." if failed else ""),
            "warning" if failed else "success")

    def _batch_reveal_quarantined(self, files: list) -> None:
        """Reveal every ticked file in Explorer. Confirms past a sane threshold."""
        if not self._confirm_batch(files, "reveal", "Explorer windows"):
            return
        for entry in files:
            quarantine_service.reveal_in_explorer(entry.path)
        self.dashboard.console.append_notice(
            f"Revealed {len(files)} file(s) in Explorer.", "info")

    def _confirm_batch(self, files: list, verb: str, noun: str) -> bool:
        """Guard a batch that would spawn many windows at once. Small sets pass straight through."""
        if len(files) <= 10:
            return bool(files)
        return QMessageBox.question(
            self, f"{verb.capitalize()} {len(files)} files?",
            f"This will {verb} {len(files)} files at once, opening that many {noun}. "
            f"Continue?") == QMessageBox.Yes

    def _show_preflight(self) -> None:
        """Open the Pre-Flight Audit dialog with the current portal-readiness checks."""
        checks = self._portal_readiness()
        dialog = PreflightDialog(checks, theme.palette(self._dark), self)
        dialog.exec()

    def _export_summary(self) -> None:
        """Save a compiled monthly summary of the current scope as CSV or JSON."""
        if self._catalog is None:
            QMessageBox.information(self, "Nothing to export",
                                    "Run a scan first — there is no catalog to summarize yet.")
            return
        path, selected = QFileDialog.getSaveFileName(
            self, "Export Batch Summary", "monthly_summary.csv",
            "CSV (*.csv);;JSON (*.json)")
        if not path:
            return   # user cancelled the save dialog
        fmt = "json" if "json" in selected.lower() else None   # else inferred from suffix
        filters = self.dashboard.filters()
        metrics = self._metrics or metrics_mod.collect(self._settings, self._catalog, *filters)
        try:
            written = summary_exporter.export_summary(path, self._catalog, metrics, filters, fmt)
        except OSError as exc:
            QMessageBox.warning(self, "Could not export summary", str(exc))
            return
        self.dashboard.console.append_notice(f"Batch summary exported to {written}.", "success")

    # ----------------------------------------------------------------- theme --
    def _on_theme_toggled(self, dark: bool) -> None:
        self._dark = dark
        self._apply_theme()
        self._refresh_health()   # the checklist paints its own colours
        self._refresh_ledger()

    def _apply_theme(self) -> None:
        palette = theme.palette(self._dark)
        self.setStyleSheet(theme.stylesheet(palette))
        for page in (self.dashboard, self.uploader, self.quarantine, self.settings_page):
            page.set_palette(palette)

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        if index == UPLOADER:
            self._refresh_ledger()
        elif index == QUARANTINE:
            self.refresh()

    # ---------------------------------------------------------------- closing --
    def closeEvent(self, event) -> None:
        """Do not orphan a running pipeline.

        Closing the window would leave the child — and its ProcessPoolExecutor
        workers — running headless with nothing reading their output.
        """
        if self._runner.running:
            answer = QMessageBox.question(
                self, "A job is still running",
                "Stop it and close Monthly Report Studio?\n\n"
                "Reports already written to output/ are unaffected.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._runner.cancel(cleanup_dir=str(self._settings.input_dir))

        # An ingest is not worth a dialog — it is a file copy, it stops between
        # files, and every file already copied is intact. But it must be told to
        # stop, or waitForDone below blocks for the rest of the batch.
        if self._ingest is not None:
            self._ingest.cancel()

        # Let any in-flight scan finish before the window it reports to stops
        # existing. Without this, a directory walk still running at teardown
        # emits into a deleted receiver.
        self._rescan_pending = False
        self._pool.waitForDone(3000)
        event.accept()
