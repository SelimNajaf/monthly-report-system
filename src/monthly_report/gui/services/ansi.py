"""ANSI SGR tokenizer — turns escape codes into styled spans.

``uploader.py`` colours its output unconditionally (uploader.py:89-103): it has
no ``isatty()`` guard, so it emits escape codes even into a pipe. Rendered raw in
a text widget those show up as literal ``[1;36m`` noise.

Rather than strip them, this reads them. The uploader already encodes exactly the
semantics the console wants — green for UPLOAD, red for BLOCKED, grey for SKIP —
so parsing SGR gives the dashboard a correctly colour-coded log for free.

``main.py`` is the mirror image: ``pre_processor.warn`` checks ``isatty()``
(pre_processor.py:39), which is false under a pipe, so pipeline output arrives
clean and passes through here untouched as a single unstyled span.

No Qt, no I/O — pure text in, styled spans out.

I/O contract
------------
parse(text: str) -> list[Span]   # Span = (text, Style)
strip(text: str) -> str
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

#: CSI sequences. Only SGR ("m") carries style; the rest (cursor moves, erases)
#: are matched purely so they can be dropped instead of rendered as mojibake.
_CSI = re.compile(r"\x1b\[([0-9;]*)([A-Za-z])")

#: SGR colour code -> semantic name. The UI maps names to theme colours, so the
#: palette stays in one place and dark/light themes can differ.
_FOREGROUND = {
    30: "black", 31: "red", 32: "green", 33: "yellow",
    34: "blue", 35: "magenta", 36: "cyan", 37: "white",
    90: "grey", 91: "red", 92: "green", 93: "yellow",
    94: "blue", 95: "magenta", 96: "cyan", 97: "white",
}


@dataclass(frozen=True)
class Style:
    """Rendering attributes for one run of text."""

    fg: str | None = None
    bold: bool = False
    dim: bool = False
    underline: bool = False


DEFAULT_STYLE = Style()


@dataclass(frozen=True)
class Span:
    """A run of text sharing one style."""

    text: str
    style: Style = DEFAULT_STYLE


def _apply(style: Style, params: str) -> Style:
    """Fold one SGR parameter list into the running style."""
    # A bare "\033[m" means "\033[0m" — reset.
    codes = [int(p) if p else 0 for p in params.split(";")] if params else [0]

    for code in codes:
        if code == 0:
            style = DEFAULT_STYLE
        elif code == 1:
            style = replace(style, bold=True)
        elif code == 2:
            style = replace(style, dim=True)
        elif code == 4:
            style = replace(style, underline=True)
        elif code in (22, 21):
            style = replace(style, bold=False, dim=False)
        elif code == 24:
            style = replace(style, underline=False)
        elif code == 39:
            style = replace(style, fg=None)
        elif code in _FOREGROUND:
            style = replace(style, fg=_FOREGROUND[code])
        # Unknown codes (backgrounds, 256-colour) are ignored rather than
        # rejected: an unstyled span beats a crash or a leaked escape code.
    return style


def parse(text: str, style: Style = DEFAULT_STYLE) -> list[Span]:
    """Split ``text`` into styled spans, consuming every escape sequence.

    ``style`` seeds the run, so a caller streaming line by line can carry an
    unterminated colour across lines. Adjacent spans sharing a style are merged,
    which keeps the widget's block count down on long logs.
    """
    spans: list[Span] = []
    cursor = 0

    def push(chunk: str, chunk_style: Style) -> None:
        if not chunk:
            return
        if spans and spans[-1].style == chunk_style:
            spans[-1] = Span(spans[-1].text + chunk, chunk_style)
        else:
            spans.append(Span(chunk, chunk_style))

    for match in _CSI.finditer(text):
        push(text[cursor:match.start()], style)
        if match.group(2) == "m":
            style = _apply(style, match.group(1))
        cursor = match.end()

    push(text[cursor:], style)
    return spans


def strip(text: str) -> str:
    """``text`` with every escape sequence removed.

    The progress parsers run on stripped text: matching ``[3/12]`` against a
    string where the brackets are wrapped in colour codes would silently never
    fire.
    """
    return _CSI.sub("", text)
