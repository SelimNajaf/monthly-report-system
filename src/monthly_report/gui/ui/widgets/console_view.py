"""The live terminal — a rolling, colour-coded view of the child's stdout.

Two colouring paths, because the two backends behave differently:

* ``uploader.py`` emits ANSI unconditionally (uploader.py:89-103). Those codes
  already encode the right semantics, so they are parsed and honoured.
* ``main.py`` emits none — ``pre_processor.warn`` checks ``isatty()``
  (pre_processor.py:39), which is false under a pipe. Its lines are matched
  against the markers it prints instead.

The block limit is not a nicety. A run over a large ``input/`` prints thousands
of lines, and an unbounded text widget grows until the machine notices.
"""

from __future__ import annotations

import re
from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit, QWidget

from ...services import ansi
from .. import theme

#: Keep the last N lines. Enough to scroll back through a full run; bounded
#: enough that a runaway loop cannot exhaust memory.
MAX_LINES = 5000

#: Semantic rules for the pipeline's uncoloured output, most specific first.
#: Each maps a pattern to a Palette attribute name.
_RULES: tuple[tuple[re.Pattern, str, bool], ...] = (
    (re.compile(r"^\[FATAL\]|Traceback|Error|error:", re.I), "danger", True),
    (re.compile(r"\[quarantine\]|Quarantine Warning|quarantined|failed", re.I), "warning", False),
    (re.compile(r"^\s*DONE\.|-> .*\.pdf$|Generated \d+ report"), "success", True),
    (re.compile(r"^\s*\[pdf\]|^\s*Parsing |^\s*Parsed |^\s*Sorted "
                r"|Groups (?:discovered|to compile)|^\s*\[LAN Sync\]"), "info", False),
    (re.compile(r"^\s*={10,}|MONTHLY REPORT ORCHESTRATOR"), "text_muted", False),
    (re.compile(r"^\[.+\]\s"), "accent", True),        # [MT/KHF FEB 2026] group headers
    (re.compile(r"^\s{4}\w+\s+:"), "text_muted", False),  # indented "doc# : ..." detail
)


class ConsoleView(QPlainTextEdit):
    """Read-only, rolling, colour-coded log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Console")
        self.setReadOnly(True)
        self.setMaximumBlockCount(MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._palette = theme.DARK
        self._carry = ansi.DEFAULT_STYLE
        # The header search filters the log by substring. To filter a rolling widget we
        # need the source lines, not just what is painted — so keep a bounded record of
        # every entry (backend line or dashboard notice) and re-render the matching subset
        # on demand. Capped at MAX_LINES for the same reason the widget is.
        self._history: deque[tuple[str, tuple]] = deque(maxlen=MAX_LINES)
        self._filter = ""

    def set_palette(self, palette: theme.Palette) -> None:
        """Adopt a theme. Existing text keeps its old colours — recolouring the
        scrollback would mean re-parsing every line for no benefit."""
        self._palette = palette

    def set_filter(self, text: str) -> None:
        """Show only lines containing ``text`` (case-insensitive); empty shows all.

        Re-renders from the kept history rather than the painted widget, so clearing the
        filter restores every line — including ones a filter had hidden while they streamed
        in. New output keeps arriving under the active filter (see append_line).
        """
        new_filter = (text or "").strip().lower()
        if new_filter == self._filter:
            return
        self._filter = new_filter
        self._rerender()

    def _matches(self, text: str) -> bool:
        return not self._filter or self._filter in text.lower()

    def _rerender(self) -> None:
        """Rebuild the document from history under the current filter."""
        self.clear()
        self._carry = ansi.DEFAULT_STYLE
        for kind, payload in self._history:
            if kind == "line":
                (line,) = payload
                if self._matches(line):
                    self._render_line(line)
            else:  # notice
                text, notice_kind = payload
                if self._matches(text):
                    self._render_notice(text, notice_kind)

    def clear_log(self) -> None:
        self.clear()
        self._carry = ansi.DEFAULT_STYLE
        self._history.clear()

    def copy_to_clipboard(self) -> bool:
        """Put the whole scrollback on the clipboard as plain text. False if empty.

        Plain text, not the coloured rich text: the operator is pasting a log into a
        ticket or a chat, where the ANSI-derived colours would be noise. Returns whether
        anything was copied so the caller can say so.
        """
        text = self.toPlainText()
        if not text:
            return False
        QGuiApplication.clipboard().setText(text)
        return True

    # ------------------------------------------------------------------------ #
    def append_line(self, line: str) -> None:
        """Record one line and, if it passes the active filter, paint it."""
        self._history.append(("line", (line,)))
        if self._matches(line):
            self._render_line(line)

    def _render_line(self, line: str) -> None:
        """Paint one line, styled.

        Autoscroll only when the view is already at the bottom, so reading back
        through a finished stage is not yanked away by new output.
        """
        at_bottom = self._at_bottom()
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)

        if self.blockCount() > 1 or self.toPlainText():
            cursor.insertBlock()

        spans = ansi.parse(line, self._carry)
        if len(spans) == 1 and spans[0].style == ansi.DEFAULT_STYLE:
            # No escape codes: this is main.py. Colour it by what it says.
            self._insert(cursor, spans[0].text, *self._rule_for(spans[0].text))
        else:
            for span in spans:
                colour = self._palette.console_colour(span.style.fg)
                self._insert(cursor, span.text, colour, span.style.bold, span.style.dim)
            self._carry = spans[-1].style if spans else ansi.DEFAULT_STYLE

        if at_bottom:
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    def append_notice(self, text: str, kind: str = "accent") -> None:
        """Record a dashboard notice and, if it passes the active filter, paint it."""
        self._history.append(("notice", (text, kind)))
        if self._matches(text):
            self._render_notice(text, kind)

    def _render_notice(self, text: str, kind: str = "accent") -> None:
        """A line from the dashboard itself, not the backend. Marked so nobody
        mistakes it for pipeline output."""
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.End)
        if self.toPlainText():
            cursor.insertBlock()
        self._insert(cursor, f"— {text}", getattr(self._palette, kind), True, False)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

    # ------------------------------------------------------------------------ #
    def _rule_for(self, text: str) -> tuple[str, bool, bool]:
        for pattern, attribute, bold in _RULES:
            if pattern.search(text):
                return getattr(self._palette, attribute), bold, False
        return self._palette.console_text, False, False

    def _insert(self, cursor: QTextCursor, text: str, colour: str,
                bold: bool = False, dim: bool = False) -> None:
        if not text:
            return
        fmt = QTextCharFormat()
        colour_value = QColor(colour)
        if dim:
            colour_value.setAlpha(150)
        fmt.setForeground(colour_value)
        if bold:
            fmt.setFontWeight(700)
        cursor.insertText(text, fmt)

    def _at_bottom(self) -> bool:
        bar = self.verticalScrollBar()
        return bar.value() >= bar.maximum() - 4
