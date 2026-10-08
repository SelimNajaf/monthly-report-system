"""Why each file was quarantined — captured from the console, remembered per file.

The pipeline prints its reason for every quarantine as it happens
(``  [quarantine] {name}: {reason} -> input/SKIPPED_REPORTS/`` — main.py:227,240;
pre_processor.py:569,571) and then keeps nothing: the reason is not stored beside the
file, so once the run's console scrolls away a file in ``SKIPPED_REPORTS`` is just a
name with no explanation of what fix it needs.

So the window watches the child's stdout, hands each ``[quarantine]`` line here, and
this persists ``name -> short tag`` (``OCR Needed`` / ``Undatable`` / …). The
Quarantine Explorer reads them back and shows a tag chip per card. A file with no
captured reason — quarantined in a run this build never saw — falls back to a neutral
"Needs review", so the tag is honest rather than guessed.

Best-effort throughout, like :mod:`cache_stats_service`: a tag that cannot be written
or read is not worth crashing anything over.

I/O contract
------------
parse_line(line) -> tuple[name, tag] | None
record(name, tag) -> None          # merges into the persisted map
load() -> dict[str, str]           # name -> tag, or {} if never written / unreadable
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

from . import app_paths

_REASONS_FILE = "quarantine_reasons.json"

#: The chip shown when no reason was captured for a file.
DEFAULT_TAG = "Needs review"

#: Substrings of the reason the pipeline prints -> the short tag the card shows. Order
#: matters: the first marker found in the reason wins. Keys mirror
#: quarantine_service.REASON_HINTS so the two stay in step.
_TAGS: tuple[tuple[str, str], ...] = (
    ("no readable text", "OCR Needed"),
    ("pdf readers disagree", "Reader conflict"),
    ("no detectable inspection date", "Undatable"),
    ("unsupported standard", "Unsupported standard"),
    ("ASR/ARS excluded", "Excluded"),
    ("excluded client", "Excluded"),
    ("unreadable", "Unreadable"),
)

#: ``  [quarantine] some name.docx: reason text -> input/...`` — the reason runs up to
#: the ``->`` arrow or a ``(name conflict …)`` note or end of line.
_LINE = re.compile(
    r"\[quarantine\]\s+(?P<name>.+?):\s+(?P<reason>.+?)"
    r"(?:\s+->|\s+\(name conflict|\s*$)")


def tag_for(reason: str) -> str:
    """Map a printed reason to a short tag, or the neutral default."""
    lowered = reason.casefold()
    for marker, tag in _TAGS:
        if marker.casefold() in lowered:
            return tag
    return DEFAULT_TAG


def parse_line(line: str) -> tuple[str, str] | None:
    """Pull ``(name, tag)`` from a ``[quarantine]`` console line, or None if it is not one."""
    match = _LINE.search(line)
    if not match:
        return None
    return match.group("name").strip(), tag_for(match.group("reason"))


def _path():
    return app_paths.state_dir() / _REASONS_FILE


def load() -> dict[str, str]:
    """The captured ``name -> tag`` map, or ``{}`` if never written / unreadable."""
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        tags = data.get("tags", {})
        return {str(k): str(v) for k, v in tags.items()} if isinstance(tags, dict) else {}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def record(name: str, tag: str) -> None:
    """Merge one ``name -> tag`` into the persisted map, atomically.

    Written temp-then-``os.replace`` like cache_stats_service.record — a torn write from
    a crash mid-save must never be read back as a real reason map.
    """
    try:
        tags = load()
        tags[name] = tag
        directory = app_paths.state_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = _path()
        temp = path.with_suffix(path.suffix + ".tmp")
        payload = {"tags": tags,
                   "recorded_at": datetime.now(timezone.utc).isoformat()}
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass  # a tag chip is not worth failing over
