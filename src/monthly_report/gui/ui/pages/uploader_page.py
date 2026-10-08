"""Uploader / State Registry: what has been sent to the portal, and what has not.

The ledger is the interesting half. ``uploader.py`` checkpoints twice around
every submit — ``IN_PROGRESS`` before, ``UPLOADED`` after (upload_ledger.py:28) —
so a leftover ``IN_PROGRESS`` is not noise, it is the record of a process that
died mid-submit and a report whose fate nobody knows. This table is where a human
sees that.

The other half is the run mode. The uploader has three, not two, and the
difference between them is the difference between a rehearsal and a filing:

* **Dry run** launches no browser and keeps its own ledger, so simulating a batch
  can never mask a real pending upload.
* **Fill only** drives the real form and then stops, leaving it on screen to be
  read. This is what a first run should be.
* **Live** clicks "Yadda saxla" and saves a draft appeal on a government portal.
  It is never the default, it is unselectable until the pre-flight checks pass,
  and it asks before it starts.

No mode signs anything: "E-imza ilə təsdiqlə" is not clicked by any of them.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox,
                               QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSlider, QSpinBox, QStackedWidget,
                               QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...services import job_runner, ledger_service
from .. import theme
from ..widgets import Badge, PageHeader

_COLUMNS = ("Report", "Status", "Serial", "Updated", "Content hash")

#: Radio order, and the button label each mode gives the run button. The label
#: matters: the button is the last thing read before a real form gets filled, so
#: it says what this click will actually do rather than a generic "Upload".
_MODES = (
    (job_runner.MODE_DRY, "Dry run",
     "Simulates every step. No browser, separate ledger.",
     "☁   Start Portal Upload (Dry Run)"),
    (job_runner.MODE_FILL, "Fill only",
     "Real browser, form filled and left on screen. Nothing is saved.",
     "☁   Start Portal Upload (Fill Only)"),
    (job_runner.MODE_LIVE, "Live — saves a draft",
     "Clicks “Yadda saxla”. Writes a real draft appeal to the portal.",
     "☁   Start Portal Upload (LIVE)"),
)


class UploaderPage(QWidget):
    """Portal upload controls and the durable upload ledger."""

    upload_requested = Signal()
    refresh_requested = Signal()
    reset_requested = Signal(str)   # the ledger key of a stalled entry to clear
    validate_requested = Signal()   # open the pre-flight audit dialog

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = theme.DARK
        # The rows behind the table, kept so the filter can re-hide after a repaint
        # and the Reset button can find the selected row's status and key.
        self._rows: tuple = ()
        # Live starts refused and is armed by the window's pre-flight, so a
        # build whose health check never runs cannot offer a live upload.
        self._live_ok = False
        self._live_reason = "checking…"

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 22, 26, 22)
        root.setSpacing(16)

        root.addWidget(self._build_header())
        root.addWidget(self._build_controls())
        root.addWidget(self._build_registry(), 1)

        self.set_live_available(self._live_ok, self._live_reason)

    def _build_header(self) -> QWidget:
        # The ledger filter lives in the shared header's search box — one box covering
        # Client, Method and State, as the registry note explains.
        header = PageHeader(
            "Uploader / State Registry",
            "Transaction-safe portal submission, recorded per report",
            search_placeholder="Filter by client, method or state…",
            show_status=True)
        self.filter_box = header.search
        self.filter_box.setToolTip("Matches client, method or state "
                                   "(UPLOADED / IN_PROGRESS / SKIPPED)")
        header.search_changed.connect(lambda _: self._apply_filter())

        self.summary = QLabel("")
        self.summary.setObjectName("Hint")

        # A dry readiness check, right where a live upload is chosen — VÖENs, director
        # and standards — so the operator can confirm the portal will accept the batch
        # before selecting a live run.
        self.validate_button = QPushButton("Validate Portal Readiness")
        self.validate_button.setObjectName("ToolButton")
        self.validate_button.clicked.connect(self.validate_requested.emit)

        header.add_right(self.summary)
        header.add_right(self.validate_button)
        return header

    def _build_controls(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        self.scope = QLabel("Scope: all reports")
        self.scope.setObjectName("FlatLabel")
        scope_hint = QLabel("Set the Month, NDT Method and Client filters on the "
                            "Dashboard to narrow what gets uploaded.")
        scope_hint.setObjectName("Hint")
        scope_hint.setWordWrap(True)

        self.upload_button = QPushButton(_MODES[0][3])
        self.upload_button.setObjectName("PrimaryButton")
        self.upload_button.setMinimumHeight(48)
        self.upload_button.clicked.connect(self.upload_requested.emit)

        left = QVBoxLayout()
        left.setSpacing(3)
        left.addWidget(self.scope)
        left.addWidget(scope_hint)

        top = QHBoxLayout()
        top.setSpacing(18)
        top.addLayout(left, 1)
        top.addWidget(self.upload_button, 0, Qt.AlignVCenter)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.addLayout(top)
        layout.addWidget(self._rule())
        layout.addWidget(self._build_mode())
        layout.addLayout(self._build_options())
        return panel

    def _rule(self) -> QWidget:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setObjectName("Rule")
        line.setFixedHeight(1)
        return line

    def _build_mode(self) -> QWidget:
        """The three run modes, as a horizontal segmented pill strip.

        Segments rather than a checkbox because the choice is not "on or off" — the
        middle mode is the useful one and a two-state control cannot reach it. The
        checked segment is cobalt; the selected mode's explanation shows below.
        """
        box = QWidget()
        self._mode_buttons: dict[str, QPushButton] = {}
        self._mode_hints = {mode: hint for mode, _label, hint, _button in _MODES}
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)

        title = QLabel("RUN MODE")
        title.setObjectName("SectionTitle")

        segments = QHBoxLayout()
        segments.setContentsMargins(0, 0, 0, 0)
        segments.setSpacing(8)
        for row, (mode, label, _hint, _button) in enumerate(_MODES):
            segment = QPushButton(label)
            segment.setObjectName("Segment")
            segment.setCheckable(True)
            segment.setChecked(mode == job_runner.MODE_DRY)
            self._mode_group.addButton(segment, row)
            self._mode_buttons[mode] = segment
            segments.addWidget(segment)
        segments.addStretch(1)

        # The selected mode's explanation, updated by _sync_options — one line rather
        # than three stacked hints, so the strip stays a strip.
        self.mode_detail = QLabel("")
        self.mode_detail.setObjectName("Hint")
        self.mode_detail.setWordWrap(True)

        # Shown when a pre-flight check refuses Live, carrying the reason it is greyed.
        self.live_reason = QLabel("")
        self.live_reason.setObjectName("Hint")
        self.live_reason.setWordWrap(True)
        self.live_reason.hide()

        self._mode_group.idToggled.connect(self._on_mode_changed)

        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(title)
        layout.addLayout(segments)
        layout.addWidget(self.mode_detail)
        layout.addWidget(self.live_reason)
        return box

    def _build_options(self) -> QHBoxLayout:
        """Limit, slow-motion and force.

        Limit and slow-motion are disabled in the modes where the backend
        ignores them — ``_effective_limit`` caps a run that cannot save at one
        report (uploader.py:1985-1990), and ``--slow`` has nothing to slow when
        there is no browser. A knob that silently does nothing is worse than one
        that is visibly unavailable and says why.
        """
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(1, 20)
        self.limit_spin.setValue(1)
        self.limit_spin.setFixedWidth(70)
        self.limit_spin.setToolTip("Reports to process in one run.")

        self.slow_slider = QSlider(Qt.Horizontal)
        self.slow_slider.setRange(0, 5000)
        self.slow_slider.setSingleStep(500)
        self.slow_slider.setPageStep(1000)
        self.slow_slider.setTickInterval(500)
        self.slow_slider.setTickPosition(QSlider.TicksBelow)
        self.slow_slider.setMinimumWidth(180)
        self.slow_slider.setToolTip("Pause before every browser action, so the "
                                    "form can be watched as it fills.")
        self.slow_value = QLabel("0 ms")
        self.slow_value.setObjectName("Hint")
        self.slow_value.setFixedWidth(64)
        self.slow_slider.valueChanged.connect(
            lambda ms: self.slow_value.setText(f"{ms} ms"))

        self.force_check = QCheckBox("Force")
        self.force_check.setToolTip(
            "Re-upload reports the ledger flags as interrupted mid-submit. Only "
            "after checking the portal — this can create a duplicate draft.")

        self.limit_label = QLabel("Limit")
        self.limit_label.setObjectName("FieldLabel")
        self.slow_label = QLabel("Slow motion")
        self.slow_label.setObjectName("FieldLabel")

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self.limit_label)
        layout.addWidget(self.limit_spin)
        layout.addSpacing(14)
        layout.addWidget(self.slow_label)
        layout.addWidget(self.slow_slider, 1)
        layout.addWidget(self.slow_value)
        layout.addSpacing(14)
        layout.addWidget(self.force_check)

        self._sync_options()
        return layout

    def _on_mode_changed(self, _id: int, checked: bool) -> None:
        if not checked:
            return              # the button being un-checked; the other one reports
        self._sync_options()

    def _sync_options(self) -> None:
        """Match the controls, and the button's promise, to the selected mode."""
        mode = self.mode()
        live = mode == job_runner.MODE_LIVE
        browser = mode != job_runner.MODE_DRY

        self.limit_spin.setEnabled(live)
        self.limit_label.setEnabled(live)
        self.limit_spin.setToolTip(
            "Reports to process in one run." if live else
            "Only Live can chain reports: a run that cannot save stops after one "
            "so the filled form stays readable (uploader.py:_effective_limit).")

        for widget in (self.slow_slider, self.slow_label, self.slow_value):
            widget.setEnabled(browser)
        self.slow_slider.setToolTip(
            "Pause before every browser action, so the form can be watched as it "
            "fills." if browser else "No browser is launched in a dry run.")

        self.mode_detail.setText(self._mode_hints.get(mode, ""))

        for candidate, _label, _hint, button_text in _MODES:
            if candidate == mode:
                self.upload_button.setText(button_text)
                break

    def _build_registry(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")

        title = QLabel("UPLOAD LEDGER")
        title.setObjectName("SectionTitle")

        self.dry_toggle = QCheckBox("Show dry-run ledger")
        self.dry_toggle.setChecked(True)
        self.dry_toggle.toggled.connect(lambda _: self.refresh_requested.emit())

        # Clears a stalled IN_PROGRESS row so the next run re-sends it. Disabled until
        # such a row is selected — the only state where re-queuing is the right move
        # (an UPLOADED row is done; resetting it would re-file a duplicate).
        self.reset_button = QPushButton("Reset Selected Entry")
        self.reset_button.setObjectName("DangerButton")
        self.reset_button.setEnabled(False)
        self.reset_button.setToolTip("Select a stalled IN_PROGRESS row to re-queue it "
                                     "for the next upload.")
        self.reset_button.clicked.connect(self._emit_reset)

        refresh = QPushButton("↻  Refresh")
        refresh.clicked.connect(self.refresh_requested.emit)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.reset_button)
        head.addWidget(self.dry_toggle)
        head.addWidget(refresh)

        self.banner = QLabel("")
        self.banner.setObjectName("Banner")
        self.banner.setWordWrap(True)
        self.banner.hide()

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.itemSelectionChanged.connect(self._on_row_selection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, len(_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeToContents)

        self.empty = QLabel("No uploads recorded yet.\n\n"
                            "Run a dry-run upload to populate the ledger.")
        self.empty.setObjectName("EmptyState")
        self.empty.setAlignment(Qt.AlignCenter)

        self.stack = QStackedWidget()
        self.stack.addWidget(self.table)
        self.stack.addWidget(self.empty)

        self.path_label = QLabel("")
        self.path_label.setObjectName("Hint")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 14, 18, 16)
        layout.setSpacing(10)
        layout.addLayout(head)
        layout.addWidget(self.banner)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.path_label)
        return panel

    # ------------------------------------------------------------------ api --
    def set_palette(self, palette: theme.Palette) -> None:
        self._palette = palette
        # The live-refusal notice is coloured inline, so a theme switch has to
        # repaint it or it keeps the old theme's warning colour.
        self.set_live_available(self._live_ok, self._live_reason)

    def show_dry_run_ledger(self) -> bool:
        return self.dry_toggle.isChecked()

    def mode(self) -> str:
        for mode, radio in self._mode_buttons.items():
            if radio.isChecked():
                return mode
        return job_runner.MODE_DRY

    def options(self) -> job_runner.UploadOptions:
        """What was chosen, as data. Turning it into flags is the window's job."""
        return job_runner.UploadOptions(
            mode=self.mode(),
            limit=self.limit_spin.value(),
            slow=self.slow_slider.value(),
            force=self.force_check.isChecked())

    def set_live_available(self, ok: bool, reason: str = "") -> None:
        """Arm or refuse Live mode, with the refusal's reason kept visible.

        A greyed-out control with no explanation is a dead end. Refusing also
        reverts a Live selection made while it was still armed — the credentials
        can go blank under a running app (the file is editable in Settings), and
        the button must not keep promising a run the uploader would abort.
        """
        self._live_ok, self._live_reason = ok, reason
        live = self._mode_buttons[job_runner.MODE_LIVE]
        live.setEnabled(ok)
        live.setToolTip("" if ok else reason)

        if not ok and live.isChecked():
            self._mode_buttons[job_runner.MODE_DRY].setChecked(True)

        self.live_reason.setText("" if ok else f"Live is unavailable: {reason}")
        self.live_reason.setStyleSheet(
            "" if ok else f"color: {self._palette.warning}; background: transparent;")
        self.live_reason.setVisible(not ok)
        self._sync_options()

    def set_ledger_view(self, dry_run: bool) -> None:
        """Show the ledger the next run will actually write.

        Signals blocked because the window refreshes the ledger itself right
        after starting a job; letting the toggle also request one would read the
        file twice for one change.
        """
        blocked = self.dry_toggle.blockSignals(True)
        self.dry_toggle.setChecked(dry_run)
        self.dry_toggle.blockSignals(blocked)

    def set_scope(self, month: str, method: str, client: str) -> None:
        parts = [p for p in (month.replace("_", " "), method, client) if p]
        self.scope.setText(f"Scope: {' · '.join(parts)}" if parts
                           else "Scope: all reports")

    def set_running(self, running: bool) -> None:
        """Freeze the whole choice while a job runs, not just the button.

        The argv was assembled at start. Leaving the controls live would let the
        panel describe a run that is not the one happening.
        """
        self.upload_button.setEnabled(not running)
        self.force_check.setEnabled(not running)
        for radio in self._mode_buttons.values():
            radio.setEnabled(not running)
        if running:
            self.limit_spin.setEnabled(False)
            self.slow_slider.setEnabled(False)
            self.reset_button.setEnabled(False)   # never edit the ledger mid-run
        else:
            self.set_live_available(self._live_ok, self._live_reason)
            self._on_row_selection()

    def set_view(self, view: ledger_service.LedgerView) -> None:
        """Render a ledger, an empty state, or an error — never a crash."""
        self.path_label.setText(str(view.path))

        if view.error:
            # A ledger that exists but does not parse is refused rather than
            # treated as empty (upload_ledger.py:140-164). Say why.
            self._show_banner(f"Ledger could not be read: {view.error}", "danger")
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText("The ledger file is unreadable.\n\n"
                               "It is not being treated as empty — that would "
                               "risk re-uploading every report.")
            self.summary.setText("")
            return

        if not view.rows:
            self._hide_banner()
            self.stack.setCurrentWidget(self.empty)
            self.empty.setText("No uploads recorded yet.\n\n"
                               "Run a dry-run upload to populate the ledger."
                               if not view.exists else
                               "The ledger is empty.\n\n"
                               "Run a dry-run upload to populate it.")
            self.summary.setText("0 entries")
            return

        self._fill(view)
        self.stack.setCurrentWidget(self.table)
        self.summary.setText(f"{len(view.rows)} entries · {view.uploaded} uploaded")

        if view.stalled:
            self._show_banner(
                f"{view.stalled} report(s) left IN_PROGRESS — a run stopped "
                f"mid-submit. The portal may or may not have them; re-run with "
                f"--force once verified, or select one and Reset it.", "warning")
        else:
            self._hide_banner()

    def _fill(self, view: ledger_service.LedgerView) -> None:
        self._rows = tuple(view.rows)
        self.table.setRowCount(len(view.rows))
        for row_index, row in enumerate(view.rows):
            name = QTableWidgetItem(row.name)
            name.setToolTip(row.key)          # the full path is too wide to show
            # Carry the ledger key on the row so Reset can find it without re-reading.
            name.setData(Qt.UserRole, row.key)
            # The status still lives as a (hidden-behind-the-badge) item so the header
            # search can match on state text; the Badge widget is what the eye reads.
            status_item = QTableWidgetItem(row.status)
            hash_item = QTableWidgetItem(row.short_hash)
            hash_item.setToolTip(row.content_hash)

            for column, item in enumerate((name, status_item,
                                           QTableWidgetItem(row.serial),
                                           QTableWidgetItem(row.updated_at),
                                           hash_item)):
                self.table.setItem(row_index, column, item)
            self.table.setCellWidget(row_index, 1, self._status_badge(row))

        self._apply_filter()
        self._on_row_selection()

    def _status_badge(self, row) -> Badge:
        """Emerald UPLOADED, pulsing amber IN_PROGRESS, slate for anything else."""
        badge = Badge()
        if row.is_stalled:
            badge.set_status(row.status, self._palette.warning, pulsing=True)
        elif row.status.upper() == "UPLOADED":
            badge.set_status(row.status, self._palette.success)
        else:
            badge.set_status(row.status, self._palette.text_muted)
        return badge

    # -------------------------------------------------------------- filter --
    def _apply_filter(self) -> None:
        """Hide rows that do not contain the filter text (case-insensitive).

        Matches against the report name and the status cell — the report filename
        carries the client and method tokens, and the status is the run state — so one
        box covers Client, Method and State without three controls.
        """
        needle = self.filter_box.text().strip().casefold() if hasattr(self, "filter_box") else ""
        for row_index in range(self.table.rowCount()):
            if not needle:
                self.table.setRowHidden(row_index, False)
                continue
            name = self.table.item(row_index, 0)
            status = self.table.item(row_index, 1)
            haystack = " ".join(i.text() for i in (name, status) if i).casefold()
            self.table.setRowHidden(row_index, needle not in haystack)

    # --------------------------------------------------------------- reset --
    def _selected_row(self):
        """The ledger Row for the current selection, or None."""
        indexes = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not indexes:
            return None
        row_index = indexes[0].row()
        return self._rows[row_index] if 0 <= row_index < len(self._rows) else None

    def _on_row_selection(self) -> None:
        """Arm Reset only for a stalled IN_PROGRESS row — the one safe case."""
        row = self._selected_row()
        self.reset_button.setEnabled(bool(row and row.is_stalled))

    def _emit_reset(self) -> None:
        row = self._selected_row()
        if row and row.is_stalled:
            self.reset_requested.emit(row.key)

    def _show_banner(self, text: str, kind: str) -> None:
        colour = getattr(self._palette, kind)
        self.banner.setText(text)
        self.banner.setStyleSheet(
            f"background: {colour}22; color: {colour}; border: 1px solid {colour}66;")
        self.banner.show()

    def _hide_banner(self) -> None:
        self.banner.hide()
