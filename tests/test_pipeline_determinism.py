"""The compile pipeline is a FIXED POINT, and it never eats a filed deliverable.

Two properties, one root cause between them.

Report counts drifted 104 -> 102 -> 101 across three consecutive ``python main.py``
runs. The pipeline was not a fixed point: STAGE 3 (render) moved source files out of
``input/`` *after* STAGE 2 had already decided and printed the group count, so a run's
removals only lowered the count on the NEXT run. Worse, the corpus-volume snapshot was
taken BEFORE that run's quarantining but consumed after it, so a single-month client
sitting exactly on ``filtering.min_total_client_volume`` lost every one of its groups
the moment it lost one file — and the stale-output sweep then hard-deleted their PDFs.

* ``TestTheCorpusIsAFixedPoint`` — run the corpus-mutating stages twice over the same
  tree and demand identical groups, identical rows, and an identical ``input/`` tree.
  STAGE 1 is replaced by a RESCAN of the disk, which is the essential part: run 2 must
  see exactly what run 1 left behind, including anything it moved.
* ``TestLedgerProtectsCompiledOutput`` — both ``output/`` deletion paths consult
  ``.upload_state.json`` and refuse to remove an artifact the uploader has on record.
  A compile run has no authority to destroy a report already filed on the portal.
* ``TestTheIncrementalSkipIsExact`` — the other half of a stable second run:
  ``_group_is_current`` reuses a group nothing touched (three filesystem calls, no
  ReportLab) and answers False for every way a PDF can be stale, month groups that
  gained a document included.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

import main                                                              # noqa: E402
from monthly_report import pre_processor, upload_ledger                  # noqa: E402
from monthly_report.config import load_settings                          # noqa: E402
from monthly_report.document_aggregator import build_monthly_report      # noqa: E402
from monthly_report.upload_ledger import UploadLedger                    # noqa: E402


# --------------------------------------------------------------------------- #
# Fixed-point harness — the stages that mutate input/ and decide the group set
# --------------------------------------------------------------------------- #
def _tables(report_no: str, client: str, date_str: str, standard: str):
    """A minimal metadata block extract_meta / extract_standard can read."""
    return [[
        ["Report No:", report_no],
        ["Date:", date_str],
        ["Client:", client],
        ["ACC Standard:", standard],
    ]]


def _scan(input_dir: Path) -> dict[Path, list]:
    """The cache STAGE 1 would hand downstream — rebuilt by RESCANNING the disk.

    Mirrors main.py's file selection exactly, ``SETTLED_DIRS`` exclusion included, so
    a file some earlier stage moved to ``SKIPPED_REPORTS/`` or ``_PRUNED/`` is gone
    from run 2's corpus just as it would be in production. Tables are re-derived from
    each filename's own spec rather than parsed, so the test needs no ``python-docx``
    and no process pool — the *identity* of the corpus is what is under test here,
    not the parse.
    """
    cache: dict[Path, list] = {}
    for path in sorted(input_dir.rglob("*.docx")):
        if path.name.startswith("~$"):
            continue
        if path.relative_to(input_dir).parts[0].casefold() in pre_processor.SETTLED_DIRS:
            continue
        cache[path] = _SPECS[path.name]
    return cache


def _tree(input_dir: Path) -> list[str]:
    """Every file under ``input/``, root-relative POSIX, sorted.

    The settled directories are deliberately INCLUDED: ``SKIPPED_REPORTS/`` and
    ``_PRUNED/`` are precisely where a drifting run parks the files it removed, so
    leaving them out would hide the drift this test exists to catch.
    """
    return sorted(p.relative_to(input_dir).as_posix()
                  for p in input_dir.rglob("*") if p.is_file())


def _run_once(cfg) -> tuple[tuple, dict[str, list[str]]]:
    """STAGE 0.5 + STAGE 1-as-rescan + STAGE 2 + STAGE 3 without the rendering.

    Returns ``(groups, {"month/method/client": [report_no, ...]})``. Rendering itself
    is skipped — no ReportLab, no fonts — because a PDF's bytes are downstream of the
    only thing in question: which groups exist and which rows they carry.
    """
    input_dir = Path(cfg.input_dir)
    pre_processor.prune_unsorted_redundant(cfg)
    pre_processor.prune_duplicate_docx(cfg)
    cache = _scan(input_dir)
    groups, _quarantined = pre_processor.discover_groups(cfg, cache)
    rows: dict[str, list[str]] = {}
    for month, client, _count, _methods in groups:
        cfg.target_month = month
        # ADR-004: no method argument — one document per client-month, every
        # method inside it, each row carrying its own token.
        report = build_monthly_report(cfg, SimpleNamespace(untranslated=set()),
                                      client_code=client, cache=cache)
        rows[f"{month}/{client}"] = [r.report_no for r in report.rows]
    return tuple(groups), rows


#: filename -> tables, consulted by ``_scan``. Populated per test by ``_corpus``.
_SPECS: dict[str, list] = {}


def _corpus(tmp_path: Path, specs, *, floor: int = 5):
    """Write a fake corpus and return settings pointed at it.

    ``specs`` is ``(filename, report_no, client, date, standard, body)``. ``body``
    is the file's BYTES — distinct per file so STAGE 0.5's byte-identical dedup does
    not fire, except where a test deliberately wants a twin.
    """
    _SPECS.clear()
    for fname, report_no, client, date_str, standard, body in specs:
        (tmp_path / fname).write_text(body, encoding="utf-8")
        _SPECS[fname] = _tables(report_no, client, date_str, standard)
    cfg = load_settings(str(_ROOT / "config" / "settings.yaml"))
    cfg.input_dir = str(tmp_path)
    cfg.output_dir = str(tmp_path / "_out")
    cfg.target_month = "2026-05"
    cfg.raw["filtering"] = {"min_total_client_volume": floor}
    return cfg


class TestTheCorpusIsAFixedPoint:
    """Run N and run N+1 must agree on everything the operator sees."""

    def test_two_runs_agree_on_the_groups_the_rows_and_the_input_tree(self, tmp_path):
        """The live 104 -> 102 -> 101 bug, reproduced in miniature.

        Five UT reports for SDLN in ONE month — exactly the shipped floor of 5, so
        losing a single file collapses the client entirely (``client_volume_ok``:
        ``len(months) >= 2 or count >= floor``). ``UT-SDLN-26-003`` carries an
        unapproved code in its in-body ACC-Standard cell and no parenthesised standard
        in its filename, so STAGE 2's filename-only guardrail passes it and the
        aggregator's body-cell fallback is what rejects it — mechanism one, exactly.
        Before the fix that rejection MOVED the file, and run 2 saw four reports.
        """
        specs = [(f"UT-SDLN-26-00{n}.docx", f"UT-SDLN-26-00{n}", "SDLN",
                  f"1{n}.05.2026",
                  "EP-GIS-42-103" if n == 3 else "ISO 11666",
                  f"body-{n}")
                 for n in range(1, 6)]
        # Byte-identical twin of -005: STAGE 0.5 prunes it on run 1 (_keeper_rank
        # keeps the bare name) and must find nothing left to prune on run 2.
        specs.append(("UT-SDLN-26-005_en.docx", "UT-SDLN-26-005", "SDLN",
                      "15.05.2026", "ISO 11666", "body-5"))
        cfg = _corpus(tmp_path, specs)

        groups_1, rows_1 = _run_once(cfg)
        tree_after_1 = _tree(tmp_path)
        groups_2, rows_2 = _run_once(cfg)

        assert groups_2 == groups_1
        assert rows_2 == rows_1
        assert _tree(tmp_path) == tree_after_1      # zero file drift on the second run

        # And the content is right in BOTH runs: five files, four rows, the unapproved
        # one omitted — and still sitting in input/, not swept into SKIPPED_REPORTS/.
        expected = ["UT-SDLN-26-001", "UT-SDLN-26-002",
                    "UT-SDLN-26-004", "UT-SDLN-26-005"]
        assert rows_1["2026-05/SDLN"] == expected
        assert rows_2["2026-05/SDLN"] == expected
        assert (tmp_path / "UT-SDLN-26-003.docx").is_file()
        assert not (tmp_path / "SKIPPED_REPORTS").exists()
        # The twin was pruned once, recoverably, and the pass is self-terminating.
        assert (tmp_path / "_PRUNED" / "UT-SDLN-26-005_en.docx").is_file()

    def test_a_stage_2_quarantine_does_not_change_the_next_run_s_group_set(self, tmp_path):
        """Step B in isolation: STAGE 2 still quarantines, and that must not cascade.

        Five SDLN files, one of them DATELESS — quarantined by STAGE 2 itself, and
        (unlike an ASR file) counted by ``corpus_client_stats``, so before the fix the
        pre-quarantine snapshot said 5 on run 1 and the post-quarantine corpus said 4
        on run 2: the group existed, then vanished. Now both runs decide on the same
        post-quarantine corpus, so they agree — whatever they decide.
        """
        specs = [(f"UT-SDLN-26-10{n}.docx", f"UT-SDLN-26-10{n}", "SDLN",
                  f"1{n}.05.2026", "ISO 11666", f"body-{n}")
                 for n in range(1, 5)]
        specs.append(("UT-SDLN-26-105.docx", "UT-SDLN-26-105", "SDLN",
                      "not a date at all", "ISO 11666", "body-5"))
        cfg = _corpus(tmp_path, specs)

        groups_1, rows_1 = _run_once(cfg)
        groups_2, rows_2 = _run_once(cfg)

        assert groups_2 == groups_1     # the fixed point, whatever the absolute count
        assert rows_2 == rows_1
        # The dateless file was quarantined exactly once and stays put thereafter.
        assert (tmp_path / "SKIPPED_REPORTS" / "UT-SDLN-26-105.docx").is_file()
        tree_after_2 = _tree(tmp_path)
        _run_once(cfg)
        assert _tree(tmp_path) == tree_after_2


# --------------------------------------------------------------------------- #
# Ledger safeguard — neither output/ sweep may delete a filed report
# --------------------------------------------------------------------------- #
def _compiled_pair(output_dir: Path, client: str, stem: str):
    """Write a fake compiled PDF + JSON sidecar and return the PDF path.

    ADR-004 tree: ``output/<CLIENT>/`` — no method directory level.
    """
    folder = output_dir / client
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / f"{stem}.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    pdf.with_suffix(".json").write_text('{"rows": []}', encoding="utf-8")
    return pdf


def _sweep_settings(output_dir: Path):
    """Settings for ``_purge_excluded_client_outputs`` — floor on, no exclusions."""
    return SimpleNamespace(
        output_dir=str(output_dir),
        raw={"filtering": {"min_total_client_volume": 5},
             "clients": {}, "excluded_clients": []})


class TestLedgerProtectsCompiledOutput:
    """``.upload_state.json`` is a veto on deletion, honoured by both sweeps."""

    def test_an_uploaded_pdf_survives_the_excluded_client_sweep(self, tmp_path, capsys):
        output_dir = tmp_path / "output"
        pdf = _compiled_pair(output_dir, "NOV",
                             "compiled_monthly_report_NOV_MAY_2026")
        cfg = _sweep_settings(output_dir)
        # NOV: one report, one month -> fails client_volume_ok against the floor of 5.
        stats = {"NOV": (1, {"2026-05"})}
        protected = frozenset({upload_ledger.ledger_key(pdf, _ROOT)})

        removed = main._purge_excluded_client_outputs(cfg, stats, protected)

        assert removed == []
        assert pdf.is_file() and pdf.with_suffix(".json").is_file()
        assert "retained (uploaded)" in capsys.readouterr().out

    def test_the_same_sweep_still_deletes_an_unfiled_pdf(self, tmp_path):
        """The guard must not turn the sweep off — an unadmitted client still goes."""
        output_dir = tmp_path / "output"
        pdf = _compiled_pair(output_dir, "NOV",
                             "compiled_monthly_report_NOV_MAY_2026")

        removed = main._purge_excluded_client_outputs(
            _sweep_settings(output_dir), {"NOV": (1, {"2026-05"})}, frozenset())

        assert sorted(removed) == ["compiled_monthly_report_NOV_MAY_2026.json",
                                   "compiled_monthly_report_NOV_MAY_2026.pdf"]
        assert not pdf.exists() and not pdf.with_suffix(".json").exists()

    def test_the_zero_row_purge_honours_the_same_guard(self, tmp_path):
        """Both sweeps share one seam, so both inherit the veto — and both halves
        of a pair are kept or removed together: the sidecar is what hash_report
        identifies the report BY."""
        pdf = _compiled_pair(tmp_path / "output", "KHF",
                             "compiled_monthly_report_KHF_DEC_2025")

        assert main._retire_artifacts(
            pdf, frozenset({upload_ledger.ledger_key(pdf, _ROOT)})) == []
        assert pdf.is_file() and pdf.with_suffix(".json").is_file()

        # PDF first, then the sidecar — the order the caller narrates.
        assert main._retire_artifacts(pdf, frozenset()) == [
            "compiled_monthly_report_KHF_DEC_2025.pdf",
            "compiled_monthly_report_KHF_DEC_2025.json"]
        assert not pdf.exists() and not pdf.with_suffix(".json").exists()

    def test_an_in_progress_entry_is_protected_too(self, tmp_path):
        """The one status nobody can answer is the one you must not delete: the
        portal may already hold those bytes, and the artifact is what an operator
        needs in hand to check."""
        ledger = tmp_path / ".upload_state.json"
        key = "output/KHF/compiled_monthly_report_KHF_DEC_2025.pdf"
        UploadLedger.load(ledger).mark_in_progress(key, "deadbeef", "MR-KHF-25-12")

        assert key in upload_ledger.protected_keys(ledger)

    def test_an_uploaded_entry_is_protected(self, tmp_path):
        ledger = tmp_path / ".upload_state.json"
        key = "output/UBOC/compiled_monthly_report_UBOC_MAY_2026.pdf"
        UploadLedger.load(ledger).mark_uploaded(key, "cafef00d", "MR-UBOC-26-05")

        assert upload_ledger.protected_keys(ledger) == frozenset({key})

    def test_the_empty_snapshot_guard_refuses_to_sweep(self, tmp_path):
        """An empty corpus snapshot is a BROKEN run, not the retirement of every
        client. ``client_volume_ok`` answers False for every code against ``{}``,
        so without this guard the sweep would delete the whole of output/."""
        output_dir = tmp_path / "output"
        pdf = _compiled_pair(output_dir, "UBOC",
                             "compiled_monthly_report_UBOC_MAY_2026")

        removed = main._purge_excluded_client_outputs(
            _sweep_settings(output_dir), {}, frozenset())

        assert removed == []
        assert pdf.is_file() and pdf.with_suffix(".json").is_file()

    @pytest.mark.parametrize("payload", [
        None,                                    # no ledger at all — a first run
        "{ not json",                            # corrupt
        '{"version": 99, "entries": {}}',        # a schema this build cannot read
        '["not", "an", "object"]',               # right syntax, wrong shape
    ])
    def test_a_missing_or_corrupt_ledger_never_blocks_a_compile(self, tmp_path, payload):
        """Fails OPEN, the mirror image of UploadLedger.load — an unreadable UPLOAD
        ledger must never abort a COMPILE. And it never writes."""
        ledger = tmp_path / ".upload_state.json"
        if payload is not None:
            ledger.write_text(payload, encoding="utf-8")

        assert upload_ledger.protected_keys(ledger) == frozenset()

        if payload is None:
            assert not ledger.exists()           # querying did not create it
        else:
            assert ledger.read_text(encoding="utf-8") == payload

    def test_the_key_format_matches_the_uploader(self):
        """One definition of the key, or the reader and the writer drift apart."""
        import uploader                                                  # noqa: E402

        pdf = _ROOT / "output" / "UBOC" / "x.pdf"
        assert upload_ledger.ledger_key(pdf, _ROOT) == "output/UBOC/x.pdf"
        assert upload_ledger.ledger_key(pdf, _ROOT) == uploader._ledger_key(pdf)

    def test_the_live_ledger_is_readable_and_every_key_is_protected(self):
        """Smoke test against the real ledger in the repo root, when present: the
        safeguard is worthless if it cannot parse the file it is guarding."""
        ledger = _ROOT / upload_ledger.LIVE_LEDGER_NAME
        if not ledger.is_file():
            pytest.skip("no live upload ledger in this checkout")
        raw = json.loads(ledger.read_text(encoding="utf-8"))

        assert upload_ledger.protected_keys(ledger) == frozenset(raw["entries"])


# --------------------------------------------------------------------------- #
# Incremental skip — reuse exactly the groups nothing touched, recompile the rest
# --------------------------------------------------------------------------- #
def _compiled_group(tmp_path: Path, *, stamp: float) -> Path:
    """A compiled PDF + sidecar pair written to look NEWER than ``stamp``."""
    pdf = _compiled_pair(tmp_path / "output", "SDLN",
                         "compiled_monthly_report_SDLN_MAY_2026")
    for art in (pdf, pdf.with_suffix(".json")):
        os.utime(art, (stamp + 10, stamp + 10))
    return pdf


class TestTheIncrementalSkipIsExact:
    """``_group_is_current`` reuses a quiet group and refuses every other case.

    The skip is what makes a second run cheap: no ReportLab, no sidecar export, just
    two ``is_file()`` calls and one ``stat()``. That cheapness is only safe because the
    predicate is conservative — every way a PDF can be stale must answer False, or a
    run ships last month's figures to the portal under this month's document number.
    """

    def test_a_quiet_group_is_reused(self, tmp_path):
        pdf = _compiled_group(tmp_path, stamp=1_700_000_000.0)

        assert main._group_is_current(pdf, "SDLN", dirty=set(),
                                      config_stamp=1_700_000_000.0,
                                      incremental=True) is True

    def test_a_group_with_a_new_source_document_is_recompiled(self, tmp_path):
        """The whole point: a month that gained a report must NOT be reused."""
        pdf = _compiled_group(tmp_path, stamp=1_700_000_000.0)
        members = {("2026-05", "SDLN"): [Path("UT-SDLN-26-001.docx"),
                                         Path("UT-SDLN-26-009.docx")],
                   ("2026-05", "UBOC"): [Path("RT-UBOC-26-001.docx")]}
        dirty = main._dirty_clients(members, {"ut-sdln-26-009.docx"})

        # Only the client that owns the new file is dirty — UBOC still reuses.
        assert dirty == {"SDLN"}
        assert main._group_is_current(pdf, "SDLN", dirty=dirty,
                                      config_stamp=1_700_000_000.0,
                                      incremental=True) is False
        assert main._group_is_current(pdf, "UBOC", dirty=dirty,
                                      config_stamp=1_700_000_000.0,
                                      incremental=True) is True

    def test_a_new_file_in_one_month_dirties_the_client_in_every_month(self, tmp_path):
        """Cross-month retest parents: a June file can change May's PDF, so the
        dirty set is keyed on the CLIENT, never on the month."""
        members = {("2026-05", "SDLN"): [Path("UT-SDLN-26-001.docx")],
                   ("2026-06", "SDLN"): [Path("UT-SDLN-26-050.docx")]}

        assert main._dirty_clients(members, {"ut-sdln-26-050.docx"}) == {"SDLN"}

    def test_a_change_in_one_method_dirties_the_whole_client_document(self):
        """ADR-004: the client-month IS the document, so there is no finer unit.

        The dirty set used to be ``(method, client)``, and an MT file left a UT
        PDF reusable. They are now the same PDF.
        """
        members = {("2026-05", "SDLN"): [Path("UT-SDLN-26-001.docx"),
                                         Path("MT-SDLN-26-002.docx")]}

        assert main._dirty_clients(members, {"mt-sdln-26-002.docx"}) == {"SDLN"}

    def test_an_edited_settings_file_defeats_the_skip(self, tmp_path):
        """``settings.yaml`` carries the registry and the floors, so editing it makes
        every compiled PDF stale even though no source report moved."""
        pdf = _compiled_group(tmp_path, stamp=1_700_000_000.0)

        assert main._group_is_current(pdf, "SDLN", dirty=set(),
                                      config_stamp=1_900_000_000.0,
                                      incremental=True) is False

    @pytest.mark.parametrize("casualty", ["pdf", "json"])
    def test_half_a_pair_is_never_reused(self, tmp_path, casualty):
        """BOTH artifacts must exist: the sidecar is what the uploader files by."""
        pdf = _compiled_group(tmp_path, stamp=1_700_000_000.0)
        (pdf if casualty == "pdf" else pdf.with_suffix(".json")).unlink()

        assert main._group_is_current(pdf, "SDLN", dirty=set(),
                                      config_stamp=1_700_000_000.0,
                                      incremental=True) is False

    def test_no_clean_switches_the_skip_off_entirely(self, tmp_path):
        """``incremental=False`` (--no-clean's companion) forces a full re-render."""
        pdf = _compiled_group(tmp_path, stamp=1_700_000_000.0)

        assert main._group_is_current(pdf, "SDLN", dirty=set(),
                                      config_stamp=1_700_000_000.0,
                                      incremental=False) is False

    def test_the_skip_reads_the_disk_and_nothing_else(self, tmp_path):
        """No parse, no ReportLab, no settings load — three filesystem calls. This is
        why a fully-current run costs milliseconds per group instead of seconds."""
        pdf = _compiled_group(tmp_path, stamp=0.0)
        calls: list[str] = []
        real_is_file, real_stat = Path.is_file, Path.stat

        def spy_is_file(self):
            calls.append(f"is_file:{self.suffix}")
            return real_is_file(self)

        def spy_stat(self, **kw):
            calls.append(f"stat:{self.suffix}")
            return real_stat(self, **kw)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(Path, "is_file", spy_is_file)
            mp.setattr(Path, "stat", spy_stat)
            assert main._group_is_current(pdf, "SDLN", dirty=set(),
                                          config_stamp=0.0, incremental=True) is True

        assert calls == ["is_file:.pdf", "is_file:.json", "stat:.pdf"]
