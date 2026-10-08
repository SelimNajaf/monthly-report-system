"""Turn backend stdout into progress events.

Neither ``main.py`` nor ``uploader.py`` exposes a progress callback, and adding
one would mean editing them. They do, however, already narrate themselves in a
stable format — so the dashboard reads the narration.

That makes stdout a contract. Every pattern below is anchored to the line that
produces it, and ``tests/test_gui_progress.py`` pins them against transcripts of
real runs: if a print statement is reworded, a test fails rather than a progress
bar silently freezing at 45%.

Pure functions over strings — no Qt, no disk, no clock. Feed stripped text
(see :func:`monthly_report.gui.services.ansi.strip`); the uploader's markers are
wrapped in colour codes and will not match otherwise.

I/O contract
------------
PipelineProgressParser().feed(line) -> ProgressEvent | None
UploadProgressParser().feed(line)   -> ProgressEvent | None
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Track(StrEnum):
    """Which progress bar an event belongs to.

    A run is two jobs wearing one coat. Getting documents *in* — copying,
    archiving, sorting — is bounded by disk, and its size is known up front. Turning them into reports is bounded by parsing and
    rendering, and its size is not known until the parse finishes. One bar had to
    average those together with invented weights (conversion was worth 20%
    whether there was one PDF or four hundred), which made it useless as an
    estimate of anything.

    Two bars, each 0-100 in its own units, say more and lie less.
    """

    INGEST = "ingest"     # bar A: ingestion & sorter
    COMPILE = "compile"   # bar B: compilation


#: Within the ingest track, conversion owns everything up to here and the sort
#: pass owns the tail. Sorting is a directory walk over files that are already
#: local — fast, and never the thing you are waiting for.
_CONVERT_CEILING = 90

#: Within the compile track: the parse is one opaque parallel block that reports
#: nothing until it returns, so it cannot fill a bar honestly; it claims a
#: quarter and shows busy while it runs. Rendering is per-group and observable.
_PARSE_CEILING = 25
_GROUP_CEILING = 30


class Stage(StrEnum):
    """Coarse phase of a run, shown next to the progress bar."""

    IDLE = "Idle"
    COPY = "Ingesting files"
    CONVERT = "Converting PDFs"
    SORT = "Sorting input"
    PARSE = "Parsing documents"
    GROUP = "Grouping reports"
    RENDER = "Rendering reports"
    UPLOAD = "Uploading"
    DONE = "Done"
    FAILED = "Failed"


#: Which bar each stage reports to. IDLE/DONE/FAILED are not listed: they are
#: whole-run states and carry whatever track produced them.
_TRACK_OF = {
    Stage.COPY: Track.INGEST,
    Stage.CONVERT: Track.INGEST,
    Stage.SORT: Track.INGEST,
    Stage.PARSE: Track.COMPILE,
    Stage.GROUP: Track.COMPILE,
    Stage.RENDER: Track.COMPILE,
    Stage.UPLOAD: Track.COMPILE,
}


@dataclass(frozen=True)
class ProgressEvent:
    """One observation drawn from a line of output.

    ``percent`` is ``None`` for work that reports no increments — the UI shows a
    busy/indeterminate bar rather than a bar frozen at a stale number. It is
    always relative to ``track``, never to the run as a whole.
    """

    stage: Stage
    percent: int | None = None
    detail: str = ""
    quarantined: bool = False
    fatal: bool = False
    track: Track = Track.COMPILE


# --------------------------------------------------------------------------- #
# Pipeline (main.py)
# --------------------------------------------------------------------------- #

#   [pdf] archiving 350 file(s) across 1 core(s)...       pre_processor.py
# Announces the batch. Nothing has moved yet, so this only names the work and pins
# the denominator. ADR-003 removed the conversion this stage used to perform; the
# verb changed with it, the shape of the line did not.
_CONVERT_START = re.compile(r"\[pdf\] archiving (\d+) file\(s\) across (\d+) core\(s\)")

#   [pdf] (12/350) archived KF-MT-26-005.pdf -> input/PDF_ARCHIVE/
#   [pdf] (13/350) failed BROKEN.pdf: PermissionError: ...
# One marker for both outcomes: a failed move still consumed a slot, and a bar that
# stalls on every locked file would be wrong about a batch that is progressing fine.
_CONVERTED = re.compile(r"\[pdf\] \((\d+)/(\d+)\)\s+(archived|failed)\s+(.*?)\s*$")

#   [pdf] cleaned up 3 partial conversion(s) from an interrupted run
# Dead since ADR-003 (there are no partial conversions to sweep), kept because a
# parser that forgets a line it used to understand chokes on an old log.
_CONVERT_SWEPT = re.compile(r"\[pdf\] cleaned up (\d+) partial conversion")

#   Sorted 4 loose file(s): ...  /  Sorted loose files: none              main.py:69,72
_SORTED = re.compile(r"^\s*Sorted (?:\d+ loose file|loose files)")

#   Parsing 120 report(s) across 8 core(s)...                            main.py:90
_PARSING = re.compile(r"^\s*Parsing (\d+) report\(s\) across (\d+) core\(s\)")

#   Parsed 118 file(s) in 4.2s (28 files/s)                              main.py:94
_PARSED = re.compile(r"^\s*Parsed (\d+) file\(s\)")

#   Parse cache: 116 hit(s), 2 parsed fresh (...)                        main.py:213
# Carries no progress of its own — captured only to feed the Cache Efficiency card.
_CACHE = re.compile(r"Parse cache:\s*(\d+) hit\(s\),\s*(\d+) parsed fresh")

#   Groups to compile: 12 (month x method x client)                      main.py:132
# Both wordings are matched: the live pipeline prints "to compile", while the
# recorded transcripts this parser is pinned against carry the older "discovered".
_GROUPS = re.compile(r"^\s*Groups (?:discovered|to compile):\s*(\d+)")

# [MT/KHF FEB 2026] -> compiled_monthly_report_MT_KHF_FEB_2026.pdf       main.py:171
_RENDERED = re.compile(r"^\[([^\]]+)\]\s*->\s*(.+\.pdf)\s*$")

# [MT/KHF FEB 2026] up to date -> compiled_monthly_report_MT_KHF_FEB_2026.pdf
# The incremental compile skip: no source file for this client changed, so the
# existing PDF + sidecar stand. It consumes a group exactly like a rendered one —
# missing it would leave the bar short on a run where nothing needed re-rendering,
# which is precisely the run the feature is built for.
_GROUP_CURRENT = re.compile(r"^\[([^\]]+)\]\s*up to date\s*->\s*(.+\.pdf)\s*$")

# [MT/KHF FEB 2026] no documents extracted — skipped.                    main.py:157
# Consumes a group exactly like a rendered one does; missing it would leave the
# bar short of 100% on any run with an empty group.
_GROUP_SKIPPED = re.compile(r"^\[([^\]]+)\]\s*no documents extracted")

#   [quarantine] name.docx: unreadable (...)                        main.py:102,115
_QUARANTINE = re.compile(r"^\s*\[quarantine\]\s*(.+?):\s*(.+?)\s*$")

#   DONE. Generated 12 report(s):                                        main.py:185
_DONE = re.compile(r"^\s*DONE\. Generated (\d+) report\(s\)")

#   No datable reports found. Nothing to do.                             main.py:130
_NOTHING = re.compile(r"^\s*No datable reports found")

#: Emitted by worker_entry when an exception escapes the backend.
_FATAL = re.compile(r"^\[FATAL\]\s*(.*)$")


class _MonotonicParser:
    """Shared guard: a progress bar must never run backwards.

    Clamped **per track**, which is the whole reason the tracks are worth having.
    The stages overlap in practice — a late quarantine line arrives after
    rendering has begun — and under one shared clamp an ingest event landing
    after compilation started would inherit compilation's high-water mark and
    read as complete. Each bar now keeps its own.
    """

    def __init__(self) -> None:
        self._percent = {Track.INGEST: 0, Track.COMPILE: 0}

    def _clamp(self, track: Track, value: float) -> int:
        percent = max(0, min(100, int(value)))
        self._percent[track] = max(self._percent[track], percent)
        return self._percent[track]

    def _at(self, track: Track) -> int:
        return self._percent[track]

    def reset(self) -> None:
        self._percent = {Track.INGEST: 0, Track.COMPILE: 0}


class PipelineProgressParser(_MonotonicParser):
    """Reads ``main.py``'s narration into :class:`ProgressEvent` values."""

    def __init__(self) -> None:
        super().__init__()
        self._groups_total = 0
        self._groups_done = 0
        self._convert_total = 0
        self._stage = Stage.IDLE
        #: (hits, misses) from the run's parse-cache line, or None until one lands.
        #: Read by the window when a run finishes to fill the Cache Efficiency card.
        self.cache_stats: tuple[int, int] | None = None

    def reset(self) -> None:
        super().reset()
        self._groups_total = 0
        self._groups_done = 0
        self._convert_total = 0
        self._stage = Stage.IDLE
        self.cache_stats = None

    def feed(self, line: str) -> ProgressEvent | None:
        """Interpret one line. Returns ``None`` for lines that say nothing new."""
        fatal = _FATAL.match(line)
        if fatal:
            # Paint the bar that was live. A failure during conversion says
            # nothing about compilation, which never started.
            track = _TRACK_OF.get(self._stage, Track.COMPILE)
            return ProgressEvent(Stage.FAILED, self._at(track), fatal.group(1),
                                 fatal=True, track=track)

        match = _CONVERT_START.search(line)
        if match:
            self._convert_total = int(match.group(1))
            return self._emit(Stage.CONVERT, 0,
                              f"{match.group(1)} PDF(s) across {match.group(2)} core(s)")

        match = _CONVERTED.search(line)
        if match:
            index, total = int(match.group(1)), int(match.group(2))
            outcome, name = match.group(3), match.group(4)
            share = _CONVERT_CEILING * index / max(total, 1)
            detail = f"PDF {index} of {total} — {name}"
            if outcome == "failed":
                detail = f"PDF {index} of {total} failed — {name}"
            return self._emit(Stage.CONVERT, share, detail)

        match = _CONVERT_SWEPT.search(line)
        if match:
            return self._emit(Stage.CONVERT, 0,
                              f"cleaned up {match.group(1)} partial conversion(s)")

        if _SORTED.match(line):
            return self._emit(Stage.SORT, 100, "input sorted")

        match = _PARSING.match(line)
        if match:
            detail = f"{match.group(1)} report(s) across {match.group(2)} core(s)"
            # ProcessPoolExecutor reports nothing until it returns — an honest
            # busy bar beats one that appears hung at a fixed number.
            return self._emit(Stage.PARSE, None, detail)

        match = _PARSED.match(line)
        if match:
            return self._emit(Stage.PARSE, _PARSE_CEILING, f"{match.group(1)} file(s) parsed")

        match = _CACHE.search(line)
        if match:
            self.cache_stats = (int(match.group(1)), int(match.group(2)))
            return None  # info only — no bar moves on this line

        match = _GROUPS.match(line)
        if match:
            self._groups_total = int(match.group(1))
            return self._emit(Stage.GROUP, _GROUP_CEILING, f"{self._groups_total} group(s)")

        match = _QUARANTINE.match(line)
        if match:
            # No percent of its own: quarantining is a side effect of whatever
            # stage is running, not a step through it.
            return self._emit(self._stage if self._stage is not Stage.IDLE else Stage.PARSE,
                              None, f"quarantined: {match.group(1)}", quarantined=True)

        match = _RENDERED.match(line)
        if match:
            return self._advance_group(match.group(2))

        match = _GROUP_CURRENT.match(line)
        if match:
            return self._advance_group(f"{match.group(2)} (up to date)")

        match = _GROUP_SKIPPED.match(line)
        if match:
            return self._advance_group(f"{match.group(1)}: no documents")

        match = _DONE.match(line)
        if match:
            self._clamp(Track.INGEST, 100)   # the run is over; bar A is not half-done
            return self._emit(Stage.DONE, 100, f"{match.group(1)} report(s) generated")

        if _NOTHING.match(line):
            # main.py returns 1 here (main.py:131). That is "nothing to do",
            # not a failure — the UI must not paint it red.
            self._clamp(Track.INGEST, 100)
            return self._emit(Stage.DONE, 100, "no datable reports found")

        return None

    def _emit(self, stage: Stage, share: float | None, detail: str,
              quarantined: bool = False) -> ProgressEvent:
        """Build an event on ``stage``'s track, remembering the stage we reached."""
        track = _TRACK_OF.get(stage, self._track_of_last_stage())
        self._stage = stage
        percent = None if share is None else self._clamp(track, share)
        return ProgressEvent(stage, percent, detail, quarantined=quarantined, track=track)

    def _track_of_last_stage(self) -> Track:
        """DONE/FAILED belong to whichever track was running when they arrived."""
        return _TRACK_OF.get(self._stage, Track.COMPILE)

    def _advance_group(self, detail: str) -> ProgressEvent:
        """Count one finished group, rendered or empty."""
        self._groups_done += 1
        if self._groups_total:
            span = 100 - _GROUP_CEILING
            share = _GROUP_CEILING + span * self._groups_done / self._groups_total
        else:
            share = self._at(Track.COMPILE)
        return self._emit(Stage.RENDER, share, detail)


# --------------------------------------------------------------------------- #
# Uploader (uploader.py)
# --------------------------------------------------------------------------- #

#   [3/12] SKIP output/KHF/....pdf (unchanged)        uploader.py:133,516,523,530
# The counter is printed for every outcome — UPLOAD, SKIP, BLOCKED, SKIP
# (invalid) — so one pattern covers the whole batch. Escape codes must already
# be stripped or the brackets will not match.
_UPLOAD_STEP = re.compile(r"^\s*\[(\d+)/(\d+)\]\s*(.*?)\s*$")

#   Ledger: 12 uploaded, 0 skipped ...  — the closing summary.
_UPLOAD_SUMMARY = re.compile(r"^\s*(\d+) uploaded,\s*(\d+) skipped")


class UploadProgressParser(_MonotonicParser):
    """Reads ``uploader.py``'s ``[n/total]`` batch counter.

    An upload ingests nothing, so it reports only on the compile track and bar A
    stays where the last pipeline run left it. Splitting an upload across two
    bars would mean inventing a phase that does not exist.
    """

    def feed(self, line: str) -> ProgressEvent | None:
        fatal = _FATAL.match(line)
        if fatal:
            return ProgressEvent(Stage.FAILED, self._at(Track.COMPILE), fatal.group(1),
                                 fatal=True, track=Track.COMPILE)

        match = _UPLOAD_STEP.match(line)
        if match:
            index, total = int(match.group(1)), int(match.group(2))
            percent = self._clamp(Track.COMPILE, 100 * index / max(total, 1))
            return ProgressEvent(Stage.UPLOAD, percent, match.group(3),
                                 track=Track.COMPILE)

        if _UPLOAD_SUMMARY.match(line):
            return ProgressEvent(Stage.DONE, self._clamp(Track.COMPILE, 100),
                                 line.strip(), track=Track.COMPILE)

        return None
