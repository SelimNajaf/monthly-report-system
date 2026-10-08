"""The Dashboard: metrics, controls, live progress and the terminal.

The one page an executive sees. It answers, top to bottom: how much work has this
system done, what would you like it to do, and what is it doing right now.

The page owns no process. It emits intent (``run_requested``) and renders what it
is told, so the window can decide policy — one job at a time, which buttons that
disables — in a single place.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QVBoxLayout, QWidget)

from ...services import catalog as catalog_mod
from ...services.metrics import Metrics
from ...services.progress import Track
from .. import theme
from ..widgets import ConsoleView, DropZone, MetricCard, PageHeader


class DashboardPage(QWidget):
    """Processing and ingestion."""

    run_requested = Signal()
    upload_requested = Signal()
    cancel_requested = Signal()
    filters_changed = Signal(str, str, str)   # month, method, client
    files_dropped = Signal(list)              # raw paths from a drag & drop
    export_requested = Signal()               # save a batch summary (CSV/JSON)
    validate_requested = Signal()             # open the pre-flight audit dialog

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._building = False

        # Build the widgets first, then assemble — the header's search box wires into the
        # console, so the console has to exist before the top bar is built.
        console_panel = self._build_console()
        drop = self._build_drop_zone()
        cards_column = self._build_cards()
        topbar = self._build_topbar()

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(16)
        root.addWidget(topbar)
        root.addWidget(self._build_filters())

        # The Stitch body: metric cards stacked in a narrow left column, the ingestion
        # dropzone over the live console filling the wide right column (a 4/8 split).
        right = QVBoxLayout()
        right.setSpacing(16)
        right.addWidget(drop)
        right.addWidget(console_panel, 1)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addLayout(cards_column, 4)
        body.addLayout(right, 8)
        root.addLayout(body, 1)

    # ------------------------------------------------------------- top bar --
    def _build_topbar(self) -> QWidget:
        """The shared page header: title, console search, cache/portal chips, status."""
        header = PageHeader(
            "Dashboard",
            "Document ingestion, conversion and report generation",
            search_placeholder="Search reports…", show_status=True)
        # The search filters the live console by substring — the one place the dashboard
        # shows a searchable body of text. Wired to the console built moments earlier.
        self.search = header.search
        self.search.textChanged.connect(self.console.set_filter)
        self.status = header.status

        # A compact read-out of the persistent parse cache, beside the run status. It
        # answers "why was that run instant?" without opening Settings. Populated by the
        # window after every scan (set_cache_status); starts blank so it never shows a
        # stale count before the first read.
        self.cache_chip = QLabel("")
        self.cache_chip.setObjectName("Chip")
        self.cache_chip.hide()

        # Portal readiness at a glance: are the VÖENs, director FIN/serial and the
        # standards all in order for a live upload? A quiet success when yes, an amber
        # count when not. The full breakdown is one click away in the Pre-Flight Audit
        # dialog. Populated alongside the health checks; hidden until first computed.
        self.portal_chip = QLabel("")
        self.portal_chip.setObjectName("Chip")
        self.portal_chip.hide()

        header.add_right(self.portal_chip)
        header.add_right(self.cache_chip)
        return header

    # ------------------------------------------------------------- filters --
    def _build_filters(self) -> QWidget:
        """The horizontal filters + CTA row, in its own panel below the header."""
        panel = QFrame()
        panel.setObjectName("Panel")

        filters_label = QLabel("FILTERS")
        filters_label.setObjectName("FieldLabel")

        self.month = QComboBox()
        self.method = QComboBox()
        self.client = QComboBox()
        for combo in (self.month, self.method, self.client):
            combo.setMinimumWidth(150)
            combo.setMaxVisibleItems(14)   # scroll rather than a list taller than the window
            combo.currentIndexChanged.connect(self._emit_filters)

        self.upload_button = QPushButton("☁   Start Portal Upload")
        self.upload_button.setMinimumHeight(40)
        self.upload_button.clicked.connect(self.upload_requested.emit)

        self.run_button = QPushButton("▶   Run Pipeline")
        self.run_button.setObjectName("PrimaryButton")
        self.run_button.setMinimumHeight(40)
        self.run_button.clicked.connect(self.run_requested.emit)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("DangerButton")
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_requested.emit)

        filters = QHBoxLayout()
        filters.setSpacing(10)
        filters.addWidget(filters_label)
        filters.addWidget(self.month)
        filters.addWidget(self.method)
        filters.addWidget(self.client)
        filters.addStretch(1)
        filters.addWidget(self.upload_button)
        filters.addWidget(self.run_button)
        filters.addWidget(self.cancel_button)

        # The filters scope everything the buttons do — the metrics, the pipeline, and
        # the upload — passed through as --month/--method/--client.
        hint = QLabel("Filters scope the metrics, Run Pipeline, and the portal upload. "
                      "Leave a filter on “All” to include every value.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)
        layout.addLayout(filters)
        layout.addWidget(hint)
        return panel

    # ----------------------------------------------------------------- cards --
    def _build_cards(self) -> QVBoxLayout:
        palette = theme.DARK
        self.card_documents = MetricCard("Total documents processed", "📄")
        # The two semantic cards carry a coloured left-accent border (accent_role) as
        # well as a tinted value — the Stitch motif: green Generated, amber Quarantined.
        self.card_generated = MetricCard("Generated PDFs / JSONs", "📊",
                                         palette.success, accent_role="success")
        self.card_quarantined = MetricCard("Quarantined files", "⚠",
                                           palette.warning, accent_role="warning")
        # A percentage, not a count — so it uses set_text, not the animated counter.
        # Reads "—" until a run (or a persisted last run) supplies real hit/miss numbers.
        self.card_cache = MetricCard("Cache efficiency", "⚡", palette.accent)
        self.card_cache.set_text("—", "no run recorded yet")
        self.cards = (self.card_documents, self.card_generated,
                      self.card_quarantined, self.card_cache)

        column = QVBoxLayout()
        column.setSpacing(16)
        for card in self.cards:
            column.addWidget(card)
        column.addStretch(1)
        return column

    # ------------------------------------------------------------ drop zone --
    def _build_drop_zone(self) -> QWidget:
        self.drop_zone = DropZone()
        self.drop_zone.files_dropped.connect(self.files_dropped.emit)
        return self.drop_zone

    # --------------------------------------------------------------- console --
    def _build_bar(self, caption: str) -> tuple[QVBoxLayout, QProgressBar, QLabel]:
        """One labelled track: caption on the left, live detail on the right."""
        name = QLabel(caption)
        name.setObjectName("FieldLabel")
        detail = QLabel("Idle")
        detail.setObjectName("Hint")
        detail.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(name)
        head.addStretch(1)
        head.addWidget(detail)

        bar = QProgressBar()
        bar.setTextVisible(False)
        bar.setFixedHeight(8)
        bar.setRange(0, 100)

        column = QVBoxLayout()
        column.setSpacing(4)
        column.addLayout(head)
        column.addWidget(bar)
        return column, bar, detail

    def _build_console(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("LIVE OUTPUT")
        title.setObjectName("SectionTitle")
        self.stage_label = QLabel("Ready")
        self.stage_label.setObjectName("Hint")

        # Log housekeeping, right of the stage read-out. Copy hands the whole
        # scrollback to the clipboard for a ticket; Clear wipes it. Both act on the
        # console below and say what they did through it, so the action is never silent.
        self.copy_button = QPushButton("Copy Logs")
        self.copy_button.setObjectName("ToolButton")
        self.copy_button.setToolTip("Copy the entire log to the clipboard as plain text.")
        self.copy_button.clicked.connect(self._copy_logs)

        self.clear_button = QPushButton("Clear Terminal")
        self.clear_button.setObjectName("ToolButton")
        self.clear_button.setToolTip("Clear the log view. Does not affect any output "
                                     "already written to disk.")
        self.clear_button.clicked.connect(self._clear_terminal)

        # Secondary actions, quieter than the run row: a dry pre-upload audit and a
        # summary export. Neither spawns a job, so both stay live during a run —
        # checking readiness or exporting what already exists is always safe.
        self.validate_button = QPushButton("Validate Portal Readiness")
        self.validate_button.setObjectName("ToolButton")
        self.validate_button.setToolTip("Dry-check VÖENs, director FIN/serial and NDT "
                                        "standards before a live upload.")
        self.validate_button.clicked.connect(self.validate_requested.emit)

        self.export_button = QPushButton("Export Batch Summary")
        self.export_button.setObjectName("ToolButton")
        self.export_button.setToolTip("Save a compiled summary of the current scope as "
                                      "CSV or JSON.")
        self.export_button.clicked.connect(self.export_requested.emit)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.stage_label)
        head.addSpacing(12)
        head.addWidget(self.validate_button)
        head.addWidget(self.export_button)
        head.addWidget(self.copy_button)
        head.addWidget(self.clear_button)

        # Two bars, because a run is two jobs: getting documents in (copy,
        # convert, sort) and turning them into reports (parse, render). They are
        # bounded by different things and one averaged bar could describe neither
        # honestly — see services.progress.Track.
        ingest, self.progress_ingest, self.detail_ingest = self._build_bar(
            "INGESTION & SORTER")
        compile_, self.progress_compile, self.detail_compile = self._build_bar(
            "COMPILATION")

        self._bars = {Track.INGEST: (self.progress_ingest, self.detail_ingest),
                      Track.COMPILE: (self.progress_compile, self.detail_compile)}

        self.console = ConsoleView()

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addLayout(ingest)
        layout.addLayout(compile_)
        layout.addWidget(self.console, 1)
        return panel

    # -------------------------------------------------------- log controls --
    def _clear_terminal(self) -> None:
        self.console.clear_log()

    def _copy_logs(self) -> None:
        if self.console.copy_to_clipboard():
            self.console.append_notice("Log copied to clipboard.", "success")
        else:
            self.console.append_notice("Nothing to copy — the log is empty.", "info")

    # ------------------------------------------------------------------ api --
    def set_cache_status(self, status) -> None:
        """Show the parse-cache chip. ``status`` is a cache_service.CacheStatus.

        Coloured by state so a disabled cache — every run re-parses everything — reads
        as a warning rather than a neutral fact, while an active cache is a quiet
        success. Hidden only if handed nothing.
        """
        self._cache_status = status
        if status is None:
            self.cache_chip.hide()
            return
        palette = self._palette_or_dark()
        colour = palette.success if status.enabled else palette.warning
        self.cache_chip.setText(status.summary)
        self.cache_chip.setStyleSheet(
            f"color: {colour}; border: 1px solid {colour}55; background: {colour}1A;")
        self.cache_chip.show()

    def set_portal_readiness(self, checks) -> None:
        """Show the portal-readiness chip. ``checks`` is a list of settings_service.Check.

        Green when every check passes, amber with a count when any fails — the same
        state-coloured pill vocabulary as the cache chip. Hidden only if handed nothing
        (readiness not yet computed).
        """
        self._readiness_checks = checks
        if not checks:
            self.portal_chip.hide()
            return
        failures = [c for c in checks if not c.ok]
        palette = self._palette_or_dark()
        if failures:
            colour = palette.warning
            text = f"Portal: {len(failures)} issue(s)"
        else:
            colour = palette.success
            text = "Portal ready"
        self.portal_chip.setText(text)
        self.portal_chip.setStyleSheet(
            f"color: {colour}; border: 1px solid {colour}55; background: {colour}1A;")
        self.portal_chip.show()

    def set_cache_efficiency(self, efficiency) -> None:
        """Fill the Cache Efficiency card from a cache_stats_service.CacheEfficiency.

        ``None`` leaves the card's "—" placeholder in place — the pipeline has not run
        since the store was cleared, so there is no honest rate to show.
        """
        if efficiency is None:
            self.card_cache.set_text("—", "no run recorded yet")
            return
        self.card_cache.set_text(efficiency.rate_label, efficiency.caption)

    def _palette_or_dark(self) -> theme.Palette:
        return getattr(self, "_palette", theme.DARK)

    def set_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        self.status.set_palette(palette)
        self.console.set_palette(palette)
        # Repaint the cache chip in the new theme's colours — its stylesheet is set
        # inline, so a theme switch would otherwise leave it in the old palette until
        # the next scan.
        if getattr(self, "_cache_status", None) is not None:
            self.set_cache_status(self._cache_status)
        if getattr(self, "_readiness_checks", None) is not None:
            self.set_portal_readiness(self._readiness_checks)
        for card in self.cards:
            card.apply_shadow(palette)
        self.card_generated._number.setStyleSheet(
            f"color: {palette.success}; background: transparent;")
        self.card_quarantined._number.setStyleSheet(
            f"color: {palette.warning}; background: transparent;")
        self.card_cache._number.setStyleSheet(
            f"color: {palette.accent}; background: transparent;")

    def set_metrics(self, metrics: Metrics, deltas=None) -> None:
        """Repaint the counted cards, and — when given a baseline — their trend badges.

        ``deltas`` is a ``dict[str, MetricDelta]`` from
        :mod:`services.metrics_history_service` keyed ``documents``/``generated``/
        ``quarantined``. ``None`` leaves the badges as they are (the window omits it for a
        filtered slice, where a delta against the whole-corpus baseline would mislead).
        """
        self.card_documents.set_value(
            metrics.documents,
            f"{metrics.archived_pdfs} PDF original(s) archived" if metrics.archived_pdfs
            else "source .docx under input/")

        caption = f"{metrics.sidecars} JSON sidecar(s)"
        if not metrics.sidecar_complete:
            # A gap means a run died between render_pdf and export_report_json
            # (main.py:163-167). Worth saying out loud rather than averaging away.
            caption = f"{metrics.sidecars} JSON — {metrics.pdfs - metrics.sidecars} missing"
        self.card_generated.set_value(metrics.pdfs, caption)

        self.card_quarantined.set_value(
            metrics.quarantined,
            "needs manual review" if metrics.quarantined else "nothing pending")

        if deltas is not None:
            # Generated rising is good (green); Quarantined falling is good.
            self.card_documents.set_trend(deltas["documents"], good_when="up")
            self.card_generated.set_trend(deltas["generated"], good_when="up")
            self.card_quarantined.set_trend(deltas["quarantined"], good_when="down")

    def populate_filters(self, catalog: catalog_mod.Catalog) -> None:
        """Rebuild the dropdowns, preserving the current selection where possible."""
        self._building = True   # suppress the churn of filters_changed per item
        try:
            self._fill(self.month, [(m, _pretty_month(m)) for m in catalog.months()],
                       "All months")
            self._fill(self.method, catalog.methods(), "All methods")
            self._fill(self.client, catalog.clients(), "All clients")
        finally:
            self._building = False
        self._emit_filters()

    def _fill(self, combo: QComboBox, pairs: list[tuple[str, str]], all_label: str) -> None:
        """Repopulate a combo — but only when its options actually changed.

        A scan runs on every filesystem change, and most of them leave the option
        set untouched (a run finishing does not invent new months). Rebuilding an
        unchanged combo would ``clear()`` and reselect it, which closes an open
        popup and can drop a click mid-selection — the exact "buggy dropdown" the
        user reported. So compare first and no-op when equal.
        """
        desired = [(all_label, catalog_mod.ALL)]
        desired += [(label, value) for value, label in pairs]
        current = [(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())]
        if current == desired:
            return

        previous = combo.currentData()
        combo.clear()
        for label, value in desired:
            combo.addItem(label, value)
        index = combo.findData(previous)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def filters(self) -> tuple[str, str, str]:
        return (self.month.currentData() or catalog_mod.ALL,
                self.method.currentData() or catalog_mod.ALL,
                self.client.currentData() or catalog_mod.ALL)

    def _emit_filters(self) -> None:
        if not self._building:
            self.filters_changed.emit(*self.filters())

    def set_running(self, running: bool) -> None:
        self.run_button.setEnabled(not running)
        self.upload_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        self.drop_zone.set_enabled_for_drops(not running)

    def set_busy(self, track: Track, busy: bool) -> None:
        """An indeterminate bar for work that cannot report increments.

        Qt's convention: range 0-0 means "busy". Used while read_many's process
        pool is running, which returns nothing until it is done.
        """
        bar, _detail = self._bars[track]
        bar.setRange(0, 0) if busy else bar.setRange(0, 100)

    def set_progress(self, track: Track, percent: int) -> None:
        bar, _detail = self._bars[track]
        if bar.maximum() == 0:
            bar.setRange(0, 100)
        bar.setValue(percent)

    def set_track_detail(self, track: Track, detail: str) -> None:
        _bar, label = self._bars[track]
        label.setText(detail or "Idle")

    def reset_tracks(self) -> None:
        """Clear both bars at the start of a job, so a run never inherits one."""
        for track in (Track.INGEST, Track.COMPILE):
            self.set_busy(track, False)
            self.set_progress(track, 0)
            self.set_track_detail(track, "")

    def set_stage(self, stage: str, detail: str = "") -> None:
        self.status.set_state(stage)
        self.stage_label.setText(f"{stage} — {detail}" if detail else stage)

    def set_ingest_message(self, message: str) -> None:
        self.drop_zone.set_message(message)


def _pretty_month(token: str) -> str:
    """``FEB_2026`` -> ``FEB 2026``. The underscore is the uploader's business."""
    return token.replace("_", " ")
