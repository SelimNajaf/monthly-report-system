"""A file whose NAME and in-body ``Report No`` carry different serials.

The filename is authoritative for a Report № (:func:`report_identity.resolve_report_no`),
so most name/body drift is harmless spelling — ``U-RT-26-004`` vs ``RT-U-26-004``.
This module is about the other kind: the ``-<YY>-<seq>`` serials themselves differ
(``U-RT-26-005 (Zığ).docx`` holds ``U-RT-26-004``). Measured on 2026-09-21 over the
whole corpus: 22 files.

Nothing here renames, edits or re-numbers a file. The source is fixed on the LAN.
The pipeline only:

* warns about every such file on every run (``main.py`` prints ``[report-no
  mismatch]`` and writes ``output/report_no_mismatch_<date>.md``);
* on ``filtering.block_mismatched_report_no: true`` keeps a **copy** out of the
  document — a file whose tables are identical to another file in the corpus that
  is named with the body's serial (``U-RT-26-005`` = ``U-RT-26-004``). The same
  inspection would otherwise print under two numbers. A mismatch that is not a copy
  (a stale header, a PDF named after another report) is only warned about.

I/O contract
------------
serial(report_no) -> (yy, seq) | None
mismatch_of(path, tables, meta) -> (name_no, body_no) | None
copy_siblings(path, tables, body_no, items) -> list[Path]
find_mismatches(cache) -> list[Mismatch]
block_enabled(settings) -> bool
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import docx_reader, extractor
from .report_identity import squash

#: Prefix of the ``report.skipped`` reason for a blocked copy.
BLOCK_REASON = "report-no mismatch"

# The last ``<YY>-<seq>`` pair of a report number: ``U-RT-26-005`` -> (26, 5).
_SERIAL = re.compile(r"(\d{2})\s*[-–—]+\s*(\d{1,4})(?!\d)")


def serial(report_no: str) -> tuple[str, int] | None:
    """The ``(yy, seq)`` serial of a report number, or ``None`` when unreadable."""
    found = _SERIAL.findall(report_no or "")
    return (found[-1][0], int(found[-1][1])) if found else None


def _name_no(path) -> str:
    return squash(docx_reader.parse_filename_metadata(path).get("report_no") or "").replace(" ", "")


def mismatch_of(path, tables, meta: dict | None = None) -> tuple[str, str] | None:
    """``(name_no, body_no)`` when both serials are readable and differ, else ``None``.

    Spelling (``U-RT`` / ``RT-U``), a retest marker (``R1``) and an unreadable body
    are not mismatches here.
    """
    if not isinstance(tables, list):
        return None
    if meta is None:
        meta = extractor.extract_meta(tables)
    name_no = _name_no(path)
    body_no = squash(meta.get("report_no", "")).replace(" ", "")
    a, b = serial(name_no), serial(body_no)
    if a is None or b is None or a == b:
        return None
    return name_no, body_no


def copy_siblings(path, tables, body_no: str, items) -> list[Path]:
    """Files in ``items`` with tables identical to ``tables``, named with ``body_no``'s serial.

    ``items`` is ``[(path, tables)]`` or a ``{path: tables}`` mapping — the parsed
    corpus. Non-empty means ``path`` is a copy of another report.
    """
    want = serial(body_no)
    pairs = items.items() if isinstance(items, dict) else items
    out = []
    for other, other_tables in pairs:
        if other == path or not isinstance(other_tables, list) or other_tables != tables:
            continue
        if serial(_name_no(other)) == want:
            out.append(Path(other))
    return sorted(out, key=str)


def weld_ids(tables, method: str) -> list[str]:
    """Weld ids as written, first-seen order; header text (``Date:``) dropped."""
    if not isinstance(tables, list):
        return []
    welds = (extractor.extract_rt_welds(tables) if method == "RT"
             else extractor.extract_welds(tables))
    out: list[str] = []
    for w in welds:
        v = (w.get("weld_no") or "").strip()
        if v and ":" not in v and v not in out:
            out.append(v)
    return out


@dataclass(frozen=True)
class Mismatch:
    path: Path
    name_no: str
    body_no: str
    date: str
    copy_of: tuple[Path, ...] = field(default=())

    @property
    def is_copy(self) -> bool:
        return bool(self.copy_of)


def find_mismatches(cache: dict) -> list[Mismatch]:
    """Every file in the parsed corpus whose name and body serials differ, by path."""
    out = []
    for path in sorted(cache, key=str):
        tables = cache[path]
        if not isinstance(tables, list):
            continue
        meta = extractor.extract_meta(tables)
        pair = mismatch_of(path, tables, meta)
        if pair is None:
            continue
        name_no, body_no = pair
        out.append(Mismatch(Path(path), name_no, body_no, meta.get("date", ""),
                            tuple(copy_siblings(path, tables, body_no, cache))))
    return out


def block_enabled(settings) -> bool:
    """Read ``filtering.block_mismatched_report_no`` — OFF when absent."""
    block = (getattr(settings, "raw", None) or {}).get("filtering") or {}
    return bool(block.get("block_mismatched_report_no", False))
