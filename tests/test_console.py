"""Tests for crash-proof console output, on both sides of the pipe.

The child side pins the original bug: printing a filename with Azerbaijani
glyphs to a cp125x Windows console raised UnicodeEncodeError and killed a
finished run.

The parent side pins the mirror of it. The GUI reads that same output back out
of a pipe, and a pipe splits wherever it likes — including between the two bytes
of an ``ə``. Getting the encoding right at both ends is what makes a report name
survive the whole journey to the console widget.
"""

import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from monthly_report.console import enable_utf8_console, safe_print

_AZ_NAME = "KF-MT-26-005 (Şəhər).docx"


class _Cp1251Stream(io.StringIO):
    """A stream that rejects non-cp1251 text, like a stock Windows console."""

    encoding = "cp1251"

    def write(self, text: str) -> int:
        text.encode(self.encoding)      # raises UnicodeEncodeError on Ş / ə
        return super().write(text)


class _NoReconfigure(io.StringIO):
    """A stream without reconfigure() — pytest capture, a wrapped stdout."""

    encoding = "cp1251"
    reconfigure = None                  # attribute exists but is not callable


def test_safe_print_survives_unencodable_name(monkeypatch):
    stream = _Cp1251Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    safe_print(f"  [quarantine] {_AZ_NAME}: unreadable")
    written = stream.getvalue()
    assert "quarantine" in written and "KF-MT-26-005" in written
    assert "?" in written          # the glyphs degraded rather than exploding


def test_safe_print_passes_ascii_through_untouched(monkeypatch):
    stream = _Cp1251Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    safe_print("  Groups discovered: 12")
    assert stream.getvalue() == "  Groups discovered: 12\n"


def test_safe_print_honours_file_kwarg():
    stream = _Cp1251Stream()
    safe_print(_AZ_NAME, file=stream)
    assert "?" in stream.getvalue()


def test_safe_print_handles_non_string_args(monkeypatch):
    stream = _Cp1251Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    safe_print("count", 12, ["a", _AZ_NAME])
    assert "12" in stream.getvalue()


def test_enable_utf8_console_reconfigures_when_possible(monkeypatch):
    calls = []

    class _Reconfigurable(io.StringIO):
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(sys, "stdout", _Reconfigurable())
    monkeypatch.setattr(sys, "stderr", _Reconfigurable())
    enable_utf8_console()
    assert calls == [{"encoding": "utf-8", "errors": "replace"}] * 2


def test_enable_utf8_console_never_raises(monkeypatch):
    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())
    enable_utf8_console()      # must be a silent no-op, not a crash


def test_enable_utf8_console_is_idempotent(monkeypatch):
    stream = io.StringIO()
    monkeypatch.setattr(sys, "stdout", stream)
    monkeypatch.setattr(sys, "stderr", stream)
    enable_utf8_console()
    enable_utf8_console()


# --------------------------------------------------------------------------- #
# The parent side: JobRunner reading that output back out of a QProcess pipe.
# --------------------------------------------------------------------------- #

class _FakeProcess:
    """Hands _drain the next queued chunk, the way a pipe would."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def readAllStandardOutput(self):
        return self._chunks.pop(0) if self._chunks else b""


def _drain_chunks(chunks):
    """Feed raw byte chunks through a real JobRunner and collect emitted lines."""
    from monthly_report.gui.services.job_runner import JobRunner

    runner = JobRunner()
    runner._process = _FakeProcess(chunks)
    lines = []
    runner.line.connect(lines.append)
    for _ in chunks:
        runner._drain()
    return runner, lines


def test_a_line_split_mid_character_is_not_corrupted():
    """The bug: 'ə' is two bytes and a read can land between them.

    Decoding each chunk on its own — as this did — turns one letter into two
    U+FFFD. The incremental decoder holds the first byte until the second lands.
    """
    payload = f"  [quarantine] {_AZ_NAME}: unreadable\n".encode("utf-8")
    split = payload.index("ə".encode("utf-8")) + 1      # between ə's two bytes

    _runner, lines = _drain_chunks([payload[:split], payload[split:]])

    assert lines == [f"  [quarantine] {_AZ_NAME}: unreadable"]
    assert "�" not in lines[0]


def test_a_line_split_mid_line_still_arrives_whole():
    """The other boundary: the tail after the last newline is buffered."""
    _runner, lines = _drain_chunks([b"Groups discove", b"red: 12\n"])
    assert lines == ["Groups discovered: 12"]


def test_genuinely_undecodable_bytes_degrade_rather_than_raise():
    """A signal handler that raises would take the rest of the output with it."""
    _runner, lines = _drain_chunks([b"bad \xff\xfe byte\n"])
    assert len(lines) == 1
    assert "�" in lines[0] and "byte" in lines[0]


def test_the_decoder_is_reset_between_jobs():
    """A run killed mid-character must not leak that byte into the next run's first line."""
    from monthly_report.gui.services.job_runner import JobRunner

    from monthly_report.gui.services import job_runner as module

    runner = JobRunner()
    runner._process = _FakeProcess([b"\xc9"])     # first half of an 'ə'
    runner._drain()

    # Reset the way start() does, then prove the held-back byte is gone.
    runner._buffer = ""
    runner._decoder = module._new_decoder()
    runner._process = _FakeProcess(["əli\n".encode("utf-8")])
    lines = []
    runner.line.connect(lines.append)
    runner._drain()

    assert lines == ["əli"]
