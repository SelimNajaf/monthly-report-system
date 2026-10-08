"""Pin the stdout contract the dashboard's progress bar depends on.

``main.py`` and ``uploader.py`` expose no progress callback, so the GUI reads
their printed narration. That makes their output an interface — and an interface
with no test is one that gets reworded in a tidy-up commit, leaving a progress
bar frozen at 45% with nothing to point at.

Every transcript below is copied from real output. No Qt, no display, no disk:
these run anywhere ``pytest`` does.
"""

from __future__ import annotations

import json

import pytest

from monthly_report.gui.services import ansi, catalog
from monthly_report.gui.services.catalog import ALL, Artifact, Catalog, _parse_stem
from monthly_report.gui.services.progress import (PipelineProgressParser, Stage,
                                                  Track, UploadProgressParser)

# --------------------------------------------------------------------------- #
# A transcript of a real `python main.py` run (via the GUI worker seam), copied
# from output captured on 2026-07-16 and trimmed to the lines that matter. The
# [pdf] markers are the parallel-conversion format — pre_processor prints one
# header, then one line per completed file.
# --------------------------------------------------------------------------- #
PIPELINE_TRANSCRIPT = """\
======================================================================
  MONTHLY REPORT ORCHESTRATOR
  Input root: C:\\Users\\Admin\\Desktop\\Monthly-Report-Auto\\input
  [pdf] archiving 3 file(s) across 1 core(s)...
  [pdf] (1/3) archived KF-DP-26-002.pdf -> input/PDF_ARCHIVE/
  [pdf] (2/3) archived KF-MT-26-005.pdf -> input/PDF_ARCHIVE/
  [pdf] (3/3) failed AZF-RT-W1-26-255.pdf: PermissionError: [WinError 32]
  PDFs: 3 found — 2 archived -> input/PDF_ARCHIVE/, 0 skipped (already archived)
  Sorted 2 loose file(s): 2 -> input/RT/
  Parsing 120 report(s) across 8 core(s)...
  Parsed 118 file(s) in 4.2s (28 files/s)
  [quarantine] scan-only.docx: no readable text (scanned image) -> input/SKIPPED_REPORTS/
  Groups discovered: 4 (month x method x client)
======================================================================

[MT/KHF FEB 2026] -> compiled_monthly_report_MT_KHF_FEB_2026.pdf
    json sidecar : compiled_monthly_report_MT_KHF_FEB_2026.json

[DP/KHE FEB 2026] no documents extracted — skipped.

[RT/AZF FEB 2026] -> compiled_monthly_report_RT_AZF_FEB_2026.pdf

[UT/UBOC MAR 2026] -> compiled_monthly_report_UT_UBOC_MAR_2026.pdf

======================================================================
  DONE. Generated 3 report(s):
    - output/MPI/KHF/compiled_monthly_report_MT_KHF_FEB_2026.pdf
======================================================================
"""


def _run(parser, transcript: str):
    """Feed a transcript line by line, collecting the events it produces."""
    return [event for line in transcript.splitlines()
            if (event := parser.feed(ansi.strip(line))) is not None]


class TestPipelineProgress:
    def test_both_tracks_reach_100_on_a_complete_run(self):
        events = _run(PipelineProgressParser(), PIPELINE_TRANSCRIPT)
        assert events[-1].stage is Stage.DONE
        assert events[-1].percent == 100
        # The ingest track must also finish full — a run that leaves bar A short
        # of 100 reads as "still working" when it is done. DONE tops it off.
        last_ingest = [e for e in events if e.track is Track.INGEST and e.percent is not None]
        assert last_ingest[-1].percent == 100

    def test_each_track_never_goes_backwards(self):
        """Clamped per track: an ingest event after compilation began must not
        inherit compilation's high-water mark, and vice versa."""
        for track in (Track.INGEST, Track.COMPILE):
            percents = [e.percent for e in _run(PipelineProgressParser(), PIPELINE_TRANSCRIPT)
                        if e.track is track and e.percent is not None]
            assert percents == sorted(percents), track

    def test_conversion_and_sort_are_the_ingest_track(self):
        for line in ("  [pdf] archiving 4 file(s) across 4 core(s)...",
                     "  [pdf] (1/4) archived a.pdf -> input/PDF_ARCHIVE/",
                     "  Sorted 2 loose file(s): 2 -> input/RT/"):
            assert PipelineProgressParser().feed(line).track is Track.INGEST

    def test_parse_group_render_are_the_compile_track(self):
        parser = PipelineProgressParser()
        assert parser.feed("  Parsing 120 report(s) across 8 core(s)...").track is Track.COMPILE
        assert parser.feed("  Parsed 118 file(s) in 4.2s").track is Track.COMPILE
        assert parser.feed("  Groups discovered: 2 (month x method x client)").track is Track.COMPILE
        rendered = parser.feed("[MT/KHF FEB 2026] -> compiled_monthly_report_MT_KHF_FEB_2026.pdf")
        assert rendered.track is Track.COMPILE

    def test_stages_appear_in_pipeline_order(self):
        seen = []
        for event in _run(PipelineProgressParser(), PIPELINE_TRANSCRIPT):
            if not seen or seen[-1] is not event.stage:
                seen.append(event.stage)
        assert Stage.CONVERT in seen
        assert seen.index(Stage.CONVERT) < seen.index(Stage.PARSE)
        assert seen.index(Stage.PARSE) < seen.index(Stage.RENDER)
        assert seen[-1] is Stage.DONE

    def test_pdf_conversion_is_proportional_within_the_ingest_track(self):
        parser = PipelineProgressParser()
        parser.feed("  [pdf] archiving 4 file(s) across 4 core(s)...")
        first = parser.feed("  [pdf] (1/4) archived a.pdf -> input/PDF_ARCHIVE/")
        last = parser.feed("  [pdf] (4/4) archived d.pdf -> input/PDF_ARCHIVE/")
        assert first.stage is Stage.CONVERT
        assert first.track is Track.INGEST
        assert "a.pdf" in first.detail
        assert first.percent == 22     # 90 * 1/4, rounded down
        assert last.percent == 90      # the conversion ceiling on the ingest bar

    def test_a_failed_conversion_still_advances_the_bar(self):
        """A bad PDF consumed a slot; the bar must not stall on it."""
        parser = PipelineProgressParser()
        parser.feed("  [pdf] archiving 2 file(s) across 2 core(s)...")
        parser.feed("  [pdf] (1/2) archived a.pdf -> input/PDF_ARCHIVE/")
        event = parser.feed("  [pdf] (2/2) failed b.pdf: RuntimeError: boom")
        assert event.percent == 90
        assert "failed" in event.detail

    def test_parsing_is_indeterminate(self):
        """ProcessPoolExecutor reports nothing until it returns; say so honestly."""
        parser = PipelineProgressParser()
        event = parser.feed("  Parsing 120 report(s) across 8 core(s)...")
        assert event.stage is Stage.PARSE
        assert event.percent is None
        assert "8 core(s)" in event.detail

    def test_empty_group_still_advances_the_bar(self):
        """main.py:157 skips a group with no rows. Missing it strands the bar short."""
        parser = PipelineProgressParser()
        parser.feed("  Groups discovered: 2 (month x method x client)")
        parser.feed("[MT/KHF FEB 2026] no documents extracted — skipped.")
        final = parser.feed("[RT/AZF FEB 2026] -> compiled_monthly_report_RT_AZF_FEB_2026.pdf")
        assert final.percent == 100

    def test_an_up_to_date_group_still_advances_the_bar(self):
        """The incremental compile skip reuses a PDF instead of rendering it.

        On the run the feature exists for — nothing changed — EVERY group takes this
        path, so missing the line would leave the bar frozen at the group ceiling for
        the whole run.
        """
        parser = PipelineProgressParser()
        parser.feed("  Groups to compile: 2 (month x method x client)")
        first = parser.feed("[MT/KHF FEB 2026] up to date -> "
                            "compiled_monthly_report_MT_KHF_FEB_2026.pdf")
        final = parser.feed("[RT/AZF FEB 2026] up to date -> "
                            "compiled_monthly_report_RT_AZF_FEB_2026.pdf")
        assert first.stage is Stage.RENDER
        assert "up to date" in first.detail
        assert final.percent == 100

    def test_the_live_group_total_is_read(self):
        """main.py prints 'Groups to compile:'; the older transcripts say 'discovered'."""
        for line in ("  Groups discovered: 4 (month x method x client)",
                     "  Groups to compile: 4 (month x method x client)"):
            parser = PipelineProgressParser()
            assert parser.feed(line).detail == "4 group(s)"

    def test_quarantine_line_flags_a_refresh(self):
        parser = PipelineProgressParser()
        event = parser.feed("  [quarantine] scan.docx: no readable text (scanned image)")
        assert event.quarantined is True
        assert "scan.docx" in event.detail

    def test_no_datable_reports_is_done_not_failed(self):
        """main.py returns 1 here (main.py:131). Exit 1, but nothing went wrong."""
        parser = PipelineProgressParser()
        event = parser.feed("  No datable reports found. Nothing to do.")
        assert event.stage is Stage.DONE
        assert event.fatal is False
        assert event.percent == 100

    def test_fatal_line_marks_failure(self):
        event = PipelineProgressParser().feed("[FATAL] FileNotFoundError: font missing")
        assert event.fatal is True
        assert event.stage is Stage.FAILED

    def test_fatal_paints_the_track_that_was_running(self):
        """A crash during conversion says nothing about compilation."""
        parser = PipelineProgressParser()
        parser.feed("  [pdf] archiving 2 file(s) across 2 core(s)...")
        event = parser.feed("[FATAL] MemoryError")
        assert event.track is Track.INGEST

        parser = PipelineProgressParser()
        parser.feed("  Parsing 10 report(s) across 4 core(s)...")
        event = parser.feed("[FATAL] MemoryError")
        assert event.track is Track.COMPILE

    def test_prose_produces_no_events(self):
        parser = PipelineProgressParser()
        assert parser.feed("======================================================") is None
        assert parser.feed("  MONTHLY REPORT ORCHESTRATOR") is None
        assert parser.feed("") is None


# --------------------------------------------------------------------------- #
# The uploader colours its output unconditionally (uploader.py:89-103).
# --------------------------------------------------------------------------- #
UPLOAD_TRANSCRIPT = (
    "  \033[1m\033[36m[1/3]\033[0m \033[1m\033[32mUPLOAD\033[0m output/MPI/KHF/a.pdf\n"
    "  \033[1m\033[36m[2/3]\033[0m \033[90mSKIP\033[0m output/RT/AZF/b.pdf \033[90m(unchanged)\033[0m\n"
    "  \033[1m\033[36m[3/3]\033[0m \033[1m\033[31mBLOCKED\033[0m output/UT/UBOC/c.pdf\n"
)


class TestUploadProgress:
    def test_batch_counter_drives_the_bar(self):
        events = _run(UploadProgressParser(), UPLOAD_TRANSCRIPT)
        assert [e.percent for e in events] == [33, 66, 100]
        assert all(e.stage is Stage.UPLOAD for e in events)

    def test_every_outcome_counts(self):
        """UPLOAD, SKIP and BLOCKED all print the counter — one pattern covers them."""
        events = _run(UploadProgressParser(), UPLOAD_TRANSCRIPT)
        assert "UPLOAD" in events[0].detail
        assert "SKIP" in events[1].detail
        assert "BLOCKED" in events[2].detail

    def test_an_upload_reports_only_on_the_compile_track(self):
        """An upload ingests nothing; bar A must be left alone."""
        events = _run(UploadProgressParser(), UPLOAD_TRANSCRIPT)
        assert all(e.track is Track.COMPILE for e in events)

    def test_ansi_must_be_stripped_first(self):
        """Guards the bug this would otherwise be: raw lines silently never match."""
        raw = "  \033[1m\033[36m[1/3]\033[0m \033[1m\033[32mUPLOAD\033[0m a.pdf"
        assert UploadProgressParser().feed(raw) is None
        assert UploadProgressParser().feed(ansi.strip(raw)) is not None


class TestAnsi:
    def test_strip_removes_every_escape(self):
        assert "\033" not in ansi.strip(UPLOAD_TRANSCRIPT)
        assert ansi.strip("\033[1;36m[1/3]\033[0m ok") == "[1/3] ok"

    def test_parse_carries_style_onto_text(self):
        spans = ansi.parse("\033[1m\033[32mUPLOAD\033[0m done")
        assert spans[0].text == "UPLOAD"
        assert spans[0].style.fg == "green"
        assert spans[0].style.bold is True
        assert spans[1].text == " done"
        assert spans[1].style == ansi.DEFAULT_STYLE

    def test_plain_text_is_one_unstyled_span(self):
        """main.py output arrives clean: warn() checks isatty() (pre_processor.py:39)."""
        spans = ansi.parse("  Groups discovered: 4 (month x method x client)")
        assert len(spans) == 1
        assert spans[0].style == ansi.DEFAULT_STYLE

    def test_reset_shorthand(self):
        assert ansi.parse("\033[31ma\033[mb")[1].style == ansi.DEFAULT_STYLE

    def test_style_carries_across_a_line_boundary(self):
        first = ansi.parse("\033[33mwarning")
        continued = ansi.parse("still yellow", style=first[-1].style)
        assert continued[0].style.fg == "yellow"


# --------------------------------------------------------------------------- #
# Filename parsing — the dropdowns are built from these tokens.
# --------------------------------------------------------------------------- #
class TestCatalogParsing:
    @pytest.mark.parametrize("stem, expected", [
        ("compiled_monthly_report_KHF_FEB_2026", ("KHF", "FEB_2026")),
        ("compiled_monthly_report_UBOC_DEC_2025", ("UBOC", "DEC_2025")),
        # Pre-ADR-004 names still resolve to their CLIENT — the last lead token —
        # so output already on disk keeps being swept by _purge_excluded_client_outputs.
        ("compiled_monthly_report_MT_KHF_FEB_2026", ("KHF", "FEB_2026")),
        ("compiled_monthly_report_HrT_UBOC_DEC_2025", ("UBOC", "DEC_2025")),
        ("compiled_monthly_report_MAY_2026", (ALL, "MAY_2026")),
    ])
    def test_tokens_are_read_from_the_right(self, stem, expected):
        """naming.default_output omits absent tokens, so only the tail is fixed."""
        assert _parse_stem(stem) == expected

    def test_a_lone_lead_token_is_the_client_not_the_method(self):
        """The regression ADR-004 had to close before it could land.

        It used to read one lead token as the METHOD and hand back an empty
        client. ``main._purge_excluded_client_outputs`` bails on a falsy code, so
        the moment filenames lost their method token that sweep would have gone
        silently dead — never deleting wrongly, but never retiring a blacklisted
        client's compiled output either.
        """
        client, month = _parse_stem("compiled_monthly_report_KHF_FEB_2026")
        assert client == "KHF"
        assert month == "FEB_2026"

    @pytest.mark.parametrize("stem", [
        "some_other_report_MT_KHF_FEB_2026",
        "compiled_monthly_report_MT_KHF_XXX_2026",   # not a month abbreviation
        "compiled_monthly_report_MT_KHF_FEB_26",     # not a 4-digit year
        "compiled_monthly_report",
    ])
    def test_foreign_names_are_skipped_not_crashed_on(self, stem):
        """output/ is a user directory; a stray PDF must not stop the dashboard."""
        assert _parse_stem(stem) is None

    def test_months_sort_chronologically_newest_first(self):
        catalog = Catalog(artifacts=tuple(
            Artifact(pdf=None, client="KHF", month=m, methods=("MT",))
            for m in ("FEB_2026", "DEC_2025", "MAR_2026", "JAN_2026")))
        # Alphabetical would give DEC first; the newest month must lead.
        assert catalog.months() == ["MAR_2026", "FEB_2026", "JAN_2026", "DEC_2025"]

    def test_methods_are_the_union_of_what_the_documents_contain(self):
        """ADR-004: a document holds several methods and names no folder.

        The label used to carry the output folder when it differed from the token
        (``MT — MPI``). There is no method folder any more, so there is nothing to
        disambiguate against and the label is the token itself.
        """
        catalog = Catalog(artifacts=(
            Artifact(pdf=None, client="KHF", month="FEB_2026",
                     methods=("DP", "MT")),
            Artifact(pdf=None, client="AZF", month="FEB_2026", methods=("RT",)),
        ))
        assert catalog.methods() == [("DP", "DP"), ("MT", "MT"), ("RT", "RT")]

    def test_filter_matches_every_non_empty_criterion(self):
        artifacts = (
            Artifact(pdf=None, client="KHF", month="FEB_2026", methods=("MT", "UT")),
            Artifact(pdf=None, client="AZF", month="FEB_2026", methods=("MT",)),
            Artifact(pdf=None, client="KHF", month="MAR_2026", methods=("RT",)),
        )
        catalog = Catalog(artifacts=artifacts)
        assert len(catalog.filter()) == 3                       # ALL
        assert len(catalog.filter(method="MT")) == 2
        assert len(catalog.filter(client="KHF")) == 2
        assert len(catalog.filter(month="FEB_2026", client="KHF")) == 1

    def test_the_method_filter_is_a_membership_test(self):
        """One document carries several methods, so it matches each of them."""
        catalog = Catalog(artifacts=(
            Artifact(pdf=None, client="UBOC", month="DEC_2025",
                     methods=("DP", "MPI", "UT", "UTM")),
        ))
        assert len(catalog.filter(method="UTM")) == 1
        assert len(catalog.filter(method="DP")) == 1
        assert len(catalog.filter(method="RT")) == 0

    def test_scan_reads_the_methods_out_of_the_sidecar(self, tmp_path):
        """The filename cannot say them any more — items_table[].method does."""
        pdf = tmp_path / "UBOC" / "compiled_monthly_report_UBOC_DEC_2025.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF-1.4")
        pdf.with_suffix(".json").write_text(json.dumps({
            "ndt_method": "DP/MPI",
            "items_table": [{"method": "MPI"}, {"method": "DP"}, {"method": "MPI"}],
        }), encoding="utf-8")

        cat = catalog.scan(tmp_path)
        assert len(cat.artifacts) == 1
        assert cat.artifacts[0].client == "UBOC"
        assert cat.artifacts[0].methods == ("DP", "MPI")

    def test_a_sidecar_with_no_row_methods_falls_back_to_the_root_token(self, tmp_path):
        """A pre-ADR-004 sidecar names one method at the root and no rows."""
        pdf = tmp_path / "compiled_monthly_report_KHF_FEB_2026.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        pdf.with_suffix(".json").write_text(
            json.dumps({"ndt_method": "MT", "items_table": []}), encoding="utf-8")

        assert catalog.scan(tmp_path).artifacts[0].methods == ("MT",)

    def test_a_missing_or_broken_sidecar_yields_no_methods(self, tmp_path):
        """The dashboard must still open over a half-written output/."""
        (tmp_path / "compiled_monthly_report_KHF_FEB_2026.pdf").write_bytes(b"%PDF")
        broken = tmp_path / "compiled_monthly_report_AZF_FEB_2026.pdf"
        broken.write_bytes(b"%PDF")
        broken.with_suffix(".json").write_text("{not json", encoding="utf-8")

        assert [a.methods for a in catalog.scan(tmp_path).artifacts] == [(), ()]


class TestParseCacheCapture:
    """The Cache Efficiency card reads the parse-cache line off the run's stdout."""

    def test_cache_line_is_captured_as_hits_and_misses(self):
        parser = PipelineProgressParser()
        event = parser.feed("  Parse cache: 116 hit(s), 2 parsed fresh "
                            "(unchanged files reused from a previous run)")
        assert event is None                      # info only — no bar moves
        assert parser.cache_stats == (116, 2)

    def test_cache_stats_start_empty_and_reset(self):
        parser = PipelineProgressParser()
        assert parser.cache_stats is None
        parser.feed("  Parse cache: 5 hit(s), 5 parsed fresh")
        assert parser.cache_stats == (5, 5)
        parser.reset()
        assert parser.cache_stats is None
