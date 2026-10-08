"""Console output that never crashes on Azerbaijani text.

Windows consoles default to a cp125x code page. Every stage of this pipeline
prints filenames, and the filenames carry Azerbaijani glyphs (``Ş ə ı ğ ç ö ü
İ``) as a matter of course, so a plain ``print`` raises ``UnicodeEncodeError``
and kills a run whose real work already finished.

Two layers, deliberately:

* :func:`enable_utf8_console` is the fix — it reconfigures the streams so the
  glyphs encode.
* :func:`safe_print` is the guarantee — it degrades to replacement characters if
  a stream could not be reconfigured (pytest capture, a detached or already
  wrapped stdout).

Neither ever raises: output is cosmetic, and cosmetics must not abort a run.

:func:`progress_printer` sits on top of both and is the pipeline's one way of
saying "item i of N" out loud.

I/O contract
------------
enable_utf8_console() -> None        # call once, first thing in an entry point
safe_print(*args, **kwargs) -> None  # drop-in for print()
progress_printer(stage, total, every=1) -> (index, message) -> None
"""

from __future__ import annotations

import sys
from typing import Callable


def enable_utf8_console() -> None:
    """Switch ``sys.stdout``/``sys.stderr`` to UTF-8, replacing what won't encode.

    Idempotent — both entry points call it and a second call is a no-op. Streams
    that do not implement ``reconfigure`` (pytest's capture, a wrapped or
    detached stream) are left alone; :func:`safe_print` covers those.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass   # not reconfigurable — safe_print is the fallback


def _degrade(value: object, encoding: str) -> str:
    """Round-trip ``value`` through ``encoding``, replacing unencodable glyphs."""
    text = value if isinstance(value, str) else str(value)
    try:
        return text.encode(encoding, "replace").decode(encoding, "replace")
    except LookupError:
        return text.encode("ascii", "replace").decode("ascii", "replace")


def safe_print(*args: object, **kwargs) -> None:
    """``print`` that survives a console which cannot encode the text.

    On ``UnicodeEncodeError`` each argument is re-encoded through the stream's
    own encoding with ``errors="replace"``, so an un-encodable name prints as
    ``KF-MT-26-005 (?ki? h?ll).docx`` rather than aborting the run.

    Flushes by default. A pipeline stage that narrates its progress is only
    useful if the operator sees the line while the stage is still running, and a
    redirected or piped stdout is block-buffered — without this, an hour-long run
    delivers its counters in 8 KB bursts. Callers may still pass ``flush=False``.
    """
    kwargs.setdefault("flush", True)
    try:
        print(*args, **kwargs)
    except UnicodeEncodeError:
        stream = kwargs.get("file") or sys.stdout
        encoding = getattr(stream, "encoding", None) or "ascii"
        print(*(_degrade(a, encoding) for a in args), **kwargs)


def progress_printer(stage: str, total: int,
                     every: int = 1) -> Callable[[int, str], None]:
    """Return ``emit(index, message)`` printing ``[stage] [i/total] message``.

    One shared shape for every stage, so an operator watching a long run reads
    the same three fields everywhere and can tell a slow stage from a hung one.

    ``every`` throttles the middle of a long walk: the first and last items
    always print, and so does every ``every``-th between them. A corpus of a
    thousand reports would otherwise emit a thousand lines per stage into a
    console that also has to stay readable. ``every <= 0`` returns a no-op, so a
    caller switches counters off by changing the number, not by branching.

    The emitted lines are deliberately *additive* — they never replace an
    existing narration line, because the GUI parses that narration
    (``gui/services/progress.py``) and each pattern there is pinned by a test.
    """
    if every <= 0:
        return lambda _index, _message="": None

    def emit(index: int, message: str = "") -> None:
        if not (index == 1 or index >= total or index % every == 0):
            return
        tail = f" {message}" if message else ""
        safe_print(f"[{stage}] [{index}/{total}]{tail}")

    return emit
