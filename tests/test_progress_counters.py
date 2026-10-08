"""Pin the live ``[Stage N: Name] [i/total]`` counters.

An operator watching a thousand-report run has one question — is this moving? —
and the counters are the only answer the pipeline gives. Three properties make
them worth trusting, and each is pinned below:

* the counter reaches its total, and never skips a number on the way (a gap reads
  as lost work, and the branches most likely to be forgotten are the ones that
  skip rather than produce);
* it is monotonic even when the work is not, because the index is assigned in the
  parent as results land, never by a worker;
* it is **additive**. The GUI drives its progress bars by parsing main.py's
  narration (``gui/services/progress.py``), so a counter line that accidentally
  matched one of those patterns would move a bar twice or count a group twice.
  :class:`TestTheGuiParserIgnoresTheCounters` is the guard.

The default everywhere is silence: ``progress_every=0``. Every pre-existing call
site passes nothing and must behave exactly as it did before.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

import main
from monthly_report import docx_reader, parse_cache
from monthly_report import pre_processor as pp
from monthly_report.console import progress_printer
from monthly_report.gui.services.progress import PipelineProgressParser

#: Matches any counter line: [Stage 0: Sorter] [105/1053] some message
_COUNTER = re.compile(r"^\[(?P<stage>[^\]]+)\] \[(?P<index>\d+)/(?P<total>\d+)\](?P<tail>.*)$")

_RAW = {"ndt_methods": {
    "UT": {"folder": "UT", "patterns": ["-UT-"]},
    "MPI": {"folder": "MPI", "patterns": ["-MT-"]},
}}


def _settings(tmp_path: Path, raw=None):
    return SimpleNamespace(input_dir=tmp_path, raw=raw if raw is not None else _RAW,
                           dayfirst=True)


def _counters(out: str, stage: str | None = None) -> list[tuple[int, int]]:
    """Every ``(index, total)`` pair printed, in order, optionally one stage only."""
    pairs = []
    for line in out.splitlines():
        match = _COUNTER.match(line)
        if match and (stage is None or match.group("stage") == stage):
            pairs.append((int(match.group("index")), int(match.group("total"))))
    return pairs


# --------------------------------------------------------------------------- #
# The emitter itself
# --------------------------------------------------------------------------- #
class TestProgressPrinter:
    def test_the_line_carries_stage_index_total_and_message(self, capsys):
        progress_printer("Stage 3: Rendering", 14)(5, "Compiled output/UT/x.pdf")
        assert capsys.readouterr().out == (
            "[Stage 3: Rendering] [5/14] Compiled output/UT/x.pdf\n")

    def test_a_message_is_optional(self, capsys):
        progress_printer("Stage 0: Sorter", 3)(2)
        assert capsys.readouterr().out == "[Stage 0: Sorter] [2/3]\n"

    def test_every_item_prints_by_default(self, capsys):
        emit = progress_printer("S", 4)
        for i in range(1, 5):
            emit(i)
        assert _counters(capsys.readouterr().out) == [(1, 4), (2, 4), (3, 4), (4, 4)]

    def test_throttling_still_prints_the_first_and_the_last(self, capsys):
        """The two items an operator actually needs: it started, and it finished."""
        emit = progress_printer("S", 10, every=4)
        for i in range(1, 11):
            emit(i)
        indexes = [i for i, _total in _counters(capsys.readouterr().out)]
        assert indexes == [1, 4, 8, 10]

    @pytest.mark.parametrize("every", [0, -1])
    def test_a_non_positive_rate_is_silence(self, capsys, every):
        emit = progress_printer("S", 3, every=every)
        for i in range(1, 4):
            emit(i, "work")
        assert capsys.readouterr().out == ""

    def test_an_empty_stage_prints_nothing_rather_than_dividing_by_zero(self, capsys):
        progress_printer("S", 0)          # built, never called — no work to count
        assert capsys.readouterr().out == ""

    def test_output_is_flushed(self, capsys):
        """Buffered counters are useless: the point is seeing them mid-run."""
        flushed: list[bool] = []

        class _Stream:
            def write(self, _text): return None
            def flush(self): flushed.append(True)

        import contextlib
        with contextlib.redirect_stdout(_Stream()):
            progress_printer("S", 1)(1, "x")
        assert flushed == [True]


# --------------------------------------------------------------------------- #
# STAGE 0 — the sorter
# --------------------------------------------------------------------------- #
class TestSorterCounter:
    def _tree(self, tmp_path: Path) -> None:
        (tmp_path / "KF-UT-26-001.docx").write_text("x", encoding="utf-8")
        (tmp_path / "KF-MT-26-002.docx").write_text("x", encoding="utf-8")
        (tmp_path / "MYSTERY-26-003.docx").write_text("x", encoding="utf-8")

    def test_silent_by_default(self, tmp_path, capsys):
        self._tree(tmp_path)
        pp.sort_input_files(_settings(tmp_path))
        assert _counters(capsys.readouterr().out) == []

    def test_every_candidate_is_counted_once_up_to_the_total(self, tmp_path, capsys):
        self._tree(tmp_path)
        pp.sort_input_files(_settings(tmp_path), progress_every=1)
        assert _counters(capsys.readouterr().out, "Stage 0: Sorter") == [
            (1, 3), (2, 3), (3, 3)]

    def test_a_file_left_in_place_still_advances_the_counter(self, tmp_path, capsys):
        """The unmatched file is the one a naive counter would silently drop."""
        self._tree(tmp_path)
        pp.sort_input_files(_settings(tmp_path), progress_every=1)
        out = capsys.readouterr().out
        assert "no method matched, left in place: MYSTERY-26-003.docx" in out

    def test_word_lock_files_are_not_in_the_denominator(self, tmp_path, capsys):
        """~$ artifacts are not reports; counting them would inflate the total."""
        self._tree(tmp_path)
        (tmp_path / "~$KF-UT-26-001.docx").write_text("lock", encoding="utf-8")
        pp.sort_input_files(_settings(tmp_path), progress_every=1)
        totals = {total for _i, total in _counters(capsys.readouterr().out)}
        assert totals == {3}

    def test_the_sorting_message_names_the_destination(self, tmp_path, capsys):
        self._tree(tmp_path)
        pp.sort_input_files(_settings(tmp_path), progress_every=1)
        assert ("Sorting report into method folder: KF-UT-26-001.docx -> input/UT/"
                in capsys.readouterr().out)


# --------------------------------------------------------------------------- #
# STAGE 1 — the two passes, each with its own honest denominator
# --------------------------------------------------------------------------- #
class TestParseCounters:
    def _docs(self, tmp_path: Path, n: int) -> list[Path]:
        paths = []
        for i in range(n):
            p = tmp_path / f"r{i}.docx"
            p.write_text(f"doc {i}", encoding="utf-8")
            paths.append(p)
        return paths

    def test_read_many_is_silent_by_default(self, tmp_path, capsys, monkeypatch):
        paths = self._docs(tmp_path, 3)
        monkeypatch.setattr(docx_reader, "_read_one",
                            lambda s: (s, [[["cell"]]], True, []))
        docx_reader.read_many(paths, max_workers=1)
        assert _counters(capsys.readouterr().out) == []

    def test_read_many_counts_every_result(self, tmp_path, capsys, monkeypatch):
        paths = self._docs(tmp_path, 3)
        monkeypatch.setattr(docx_reader, "_read_one",
                            lambda s: (s, [[["cell"]]], True, []))
        docx_reader.read_many(paths, max_workers=1, progress_every=1)
        assert _counters(capsys.readouterr().out, "Stage 1: Parsing") == [
            (1, 3), (2, 3), (3, 3)]

    def test_an_unreadable_file_still_advances_the_counter(self, tmp_path, capsys,
                                                           monkeypatch):
        """A failed parse consumed a slot; a bar that stalls on it is lying."""
        paths = self._docs(tmp_path, 2)
        monkeypatch.setattr(
            docx_reader, "_read_one",
            lambda s: (s, "PackageNotFoundError: broken", False, [])
            if s.endswith("r1.docx") else (s, [[["cell"]]], True, []))
        docx_reader.read_many(paths, max_workers=1, progress_every=1)
        out = capsys.readouterr().out
        assert _counters(out, "Stage 1: Parsing") == [(1, 2), (2, 2)]
        assert "Parse failed: r1.docx" in out

    def test_the_hash_pass_counts_the_whole_corpus(self, tmp_path, capsys, monkeypatch):
        paths = self._docs(tmp_path, 4)
        monkeypatch.setattr(docx_reader, "_read_one",
                            lambda s: (s, [[["cell"]]], True, []))
        parse_cache.read_many_cached(paths, tmp_path / ".cache", max_workers=1,
                                     progress_every=1)
        out = capsys.readouterr().out
        assert (4, 4) in _counters(out, "Stage 1: Parsing")
        assert "Processing parse_cache..." in out

    def test_the_two_passes_keep_separate_denominators(self, tmp_path, capsys,
                                                       monkeypatch):
        """Four files, one of them a cache miss: 4 hashed, 1 parsed.

        A single shared denominator would show a counter that sprints through the
        hits and then appears to stall on the one file doing real work.
        """
        cache_dir = tmp_path / ".cache"
        paths = self._docs(tmp_path, 4)
        monkeypatch.setattr(docx_reader, "_read_one",
                            lambda s: (s, [[["cell"]]], True, []))
        # Warm the store for three of the four, then count a second run.
        parse_cache.read_many_cached(paths[:3], cache_dir, max_workers=1)
        capsys.readouterr()

        parse_cache.read_many_cached(paths, cache_dir, max_workers=1, progress_every=1)

        totals = {total for _i, total in _counters(capsys.readouterr().out,
                                                   "Stage 1: Parsing")}
        assert totals == {4, 1}

    def test_read_many_cached_is_silent_by_default(self, tmp_path, capsys, monkeypatch):
        paths = self._docs(tmp_path, 2)
        monkeypatch.setattr(docx_reader, "_read_one",
                            lambda s: (s, [[["cell"]]], True, []))
        parse_cache.read_many_cached(paths, tmp_path / ".cache", max_workers=1)
        assert _counters(capsys.readouterr().out) == []


# --------------------------------------------------------------------------- #
# STAGE 2 — group discovery
# --------------------------------------------------------------------------- #
class TestGroupingCounter:
    _SPECS = {
        "a.docx": ("2025-06-01", "UT", "UBOC"),
        "b.docx": ("2025-06-02", "MT", "KHF"),
    }

    @pytest.fixture
    def wired(self, tmp_path, monkeypatch):
        cache = {tmp_path / name: name for name in self._SPECS}
        by_name = self._SPECS
        monkeypatch.setattr(pp.extractor, "extract_meta",
                            lambda blocks: {"date": by_name[blocks][0], "name": blocks})
        monkeypatch.setattr(pp, "resolve_report_no", lambda meta, path: (path.name, None))
        monkeypatch.setattr(pp, "is_excluded", lambda name, rn: False)
        # Both entry points are stubbed. discover_groups reads the ``_ex`` variant
        # (it reports the KB-1 truncated-year repair); corpus_client_stats, called
        # from the same run, still reads the plain one. Patching the shared module
        # attribute covers every importer. Both take the report number the repair
        # needs (and the PDF-twin names KB-1b reads), and ignore both — this
        # fixture supplies whole ISO dates.
        monkeypatch.setattr(pp.date_detector, "parse_inspection_date",
                            lambda s, dayfirst=False, report_no="", twin_names=():
                            dt.date.fromisoformat(s))
        monkeypatch.setattr(pp.date_detector, "parse_inspection_date_ex",
                            lambda s, dayfirst=False, report_no="", twin_names=():
                            (dt.date.fromisoformat(s), None))
        monkeypatch.setattr(pp, "detect_method", lambda rn, settings: by_name[rn][1])
        monkeypatch.setattr(pp, "resolve_client_by_field",
                            lambda meta, rn, settings: (by_name[rn][2], ""))
        return _settings(tmp_path, raw={}), cache

    def test_silent_by_default(self, wired, capsys):
        settings, cache = wired
        pp.discover_groups(settings, cache)
        assert _counters(capsys.readouterr().out) == []

    def test_every_cached_file_is_counted(self, wired, capsys):
        settings, cache = wired
        pp.discover_groups(settings, cache, progress_every=1)
        assert _counters(capsys.readouterr().out, "Stage 2: Grouping") == [
            (1, 2), (2, 2)]

    def test_the_denominator_survives_files_dropped_mid_loop(self, wired, capsys,
                                                             monkeypatch):
        """Quarantine pops entries out of the cache while it is being walked."""
        settings, cache = wired
        monkeypatch.setattr(pp, "is_excluded", lambda name, rn: rn == "a.docx")
        monkeypatch.setattr(pp, "quarantine", lambda input_dir, path: True)
        pp.discover_groups(settings, cache, progress_every=1)
        assert _counters(capsys.readouterr().out, "Stage 2: Grouping") == [
            (1, 2), (2, 2)]


# --------------------------------------------------------------------------- #
# STAGE -1 — the pre-existing counter keeps its machine-readable token
# --------------------------------------------------------------------------- #
class TestConvertCounterKeepsItsContract:
    """The stage label is a prefix, never a replacement.

    ``[pdf] (n/N)`` is what the GUI matches and what two other tests assert. The
    label was added in front of it precisely so a human can see which stage is
    talking without the machine losing what it reads.
    """

    def test_the_label_precedes_the_untouched_token(self, tmp_path, capsys):
        (tmp_path / "KF-MT-26-005.pdf").write_bytes(b"%PDF-1.4 stub")
        pp.archive_input_pdfs(SimpleNamespace(input_dir=tmp_path, raw={}))

        out = capsys.readouterr().out
        # ADR-003 changed the verb (this stage archives now) and nothing else: the
        # label is still a prefix and the (n/N) token is still what the GUI reads.
        assert "[Stage -1: PDF Convert] [pdf] (1/1) archived" in out
        assert "[Stage -1: PDF Convert] [pdf] archiving 1 file(s)" in out


# --------------------------------------------------------------------------- #
# The reason all of the above had to be additive
# --------------------------------------------------------------------------- #
class TestTheGuiParserIgnoresTheCounters:
    """No *new* counter line may move a GUI progress bar.

    The dashboard counts groups by matching main.py's per-group narration. If a
    counter line also matched, a rendered group would be counted twice and the bar
    would reach 100% at the halfway point.

    STAGE -1 is the deliberate exception and is asserted separately below: its
    counter predates this work, the GUI has always read it, and the stage label
    was added as a prefix precisely so it keeps being read.
    """

    @pytest.mark.parametrize("line", [
        "[Stage 0: Sorter] [105/1053] Sorting report into method folder: a.docx -> input/UT/",
        "[Stage 0: Sorter] [106/1053] already sorted, left in place: b.docx",
        "[Stage 1: Parsing] [500/1053] Processing parse_cache...",
        "[Stage 1: Parsing] [3/12] Parsed report: KF-UT-26-011.docx",
        "[Stage 2: Grouping] [640/1053] Classifying report: KF-DP-26-002.docx",
        "[Stage 3: Rendering] [5/14] Compiled output/UT/UBOC/compiled_monthly_report_UT_UBOC_JUN_2026.pdf",
        "[Stage 3: Rendering] [6/14] Reused output/MPI/KHF/compiled_monthly_report_MT_KHF_JUN_2026.pdf",
        "[Stage 3: Rendering] [7/14] Skipped (low volume) MT/AZF JUN 2026",
        "[Stage 3: Rendering] [8/14] Skipped (no documents extracted) UT/GEMZA JUN 2026",
        # Not counters, but held to the same additive rule: two markers added for the
        # multi-run determinism check. Both sit alongside narration the GUI already
        # counts, so either one matching would double-count a group.
        "[Incremental Skip] output/UT/UBOC/compiled_monthly_report_UT_UBOC_JUN_2026.pdf"
        " already up to date.",
        "    [unapproved standard] KF-MT-26-042 (2335) (ASME B31.3).docx: unapproved "
        "standard 'EP-GIS-42-103' not listed in butun_standartlar.md — row omitted",
    ])
    def test_a_counter_line_produces_no_event(self, line):
        assert PipelineProgressParser().feed(line) is None

    def test_the_pdf_counter_still_moves_the_ingest_bar(self):
        """The one line that was reworded must still be understood."""
        parser = PipelineProgressParser()
        parser.feed("  [Stage -1: PDF Convert] [pdf] archiving 4 file(s) across 4 core(s)...")
        event = parser.feed(
            "  [Stage -1: PDF Convert] [pdf] (2/4) archived b.pdf -> input/PDF_ARCHIVE/")
        assert event is not None and event.percent == 45

    def test_a_render_line_is_still_counted_exactly_once(self):
        """Feed the real pair — narration then counter — and count the events."""
        parser = PipelineProgressParser()
        parser.feed("  Groups to compile: 2 (month x method x client)")
        events = [
            parser.feed("[UT/UBOC JUN 2026] -> compiled_monthly_report_UT_UBOC_JUN_2026.pdf"),
            parser.feed("[Stage 3: Rendering] [1/2] Compiled "
                        "output/UT/UBOC/compiled_monthly_report_UT_UBOC_JUN_2026.pdf"),
        ]
        assert [e is not None for e in events] == [True, False]


# --------------------------------------------------------------------------- #
# The config knob
# --------------------------------------------------------------------------- #
class TestRenderedPathIsReadable:
    """A counter line names the deliverable the way the operator refers to it."""

    def test_a_path_inside_the_project_is_shown_relative(self):
        inside = Path(main._ROOT) / "output" / "UT" / "UBOC" / "report.pdf"
        assert main._display_path(inside) == "output/UT/UBOC/report.pdf"

    def test_a_path_outside_the_project_keeps_its_full_form(self, tmp_path):
        """A configured absolute output_dir: the whole path IS the information."""
        outside = tmp_path / "elsewhere" / "report.pdf"
        assert main._display_path(outside) == outside.as_posix()


class TestProgressEverySetting:
    def test_the_default_is_every_item(self):
        assert main._progress_every({}) == 1

    def test_an_explicit_rate_is_honoured(self):
        assert main._progress_every({"progress_every": 25}) == 25

    def test_zero_switches_the_counters_off(self):
        assert main._progress_every({"progress_every": 0}) == 0

    @pytest.mark.parametrize("junk", ["often", None, [1]])
    def test_a_junk_value_falls_back_rather_than_stopping_the_run(self, junk):
        """How often a counter prints is cosmetic; it must never abort a compile."""
        assert main._progress_every({"progress_every": junk}) == 1
