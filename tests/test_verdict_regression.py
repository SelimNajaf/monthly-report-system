"""The ADR-003 release gate: **zero silent errors**, over the whole corpus.

The rule the two-reader design rests on is not "be accurate". It is: *when the two
readers agree, the answer is right.* A disagreement is safe — the report is
quarantined and a human settles it. An agreement that is wrong is not, because
nothing downstream will ever question it, and the last time that happened it put
"Yarasız" on 26 accepted reports and "Yararlı" on 5 rejected ones in documents that
had already been delivered.

So this file asserts one number above all: **silent errors == 0**, over all 630
PDF/docx pairs in the corpus, not a sample. If that number moves, the release
stops. Everything else here exists to make a failure legible.

``tests/data/verdict_regression.json`` carries the ground truth: for each pair, the
verdict read from the **raw PDF text** with the ``Accept / Reject`` column header
stripped out — any surviving ``Reject`` means the report was rejected. That is
independent of both readers and of every table reconstruction, which is what makes
it usable as an oracle here and unusable at runtime (a live run has the same text,
but no way to know which ``Reject`` was a header and which was a verdict without the
grid it is trying to build).

Corpus-backed by necessity: the failures being guarded against are template
geometry, and no synthetic fixture reproduces the RT film-section grid or the UT
stacked header. The manifest holds report numbers only — no filenames, clients or
paths.

The corpus is a pinned copy, not ``input/``: ``scripts/build_verdict_corpus.py``
copies the 630 PDFs to ``corpus/verdict_regression/<ID>.pdf`` (or wherever
``MRS_VERDICT_CORPUS`` points), and ``tests/data/verdict_corpus.sha256`` pins
every one of them by hash. No corpus directory means the gate skips, and says so
under ``pytest -rs``; a corpus that is there but incomplete or altered FAILS —
a gate that quietly measured the wrong files would also report zero errors.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

_MANIFEST = json.loads(
    (Path(__file__).parent / "data" / "verdict_regression.json").read_text(encoding="utf-8"))
_PAIRS = _MANIFEST["pairs"]

#: ``<sha256>  <ID>.pdf`` per manifested report — tracked, written by the first
#: ``scripts/build_verdict_corpus.py`` run.
_PINS_FILE = Path(__file__).parent / "data" / "verdict_corpus.sha256"

_DEFAULT_CORPUS = Path(__file__).resolve().parent.parent / "corpus" / "verdict_regression"

_NOT_RUNNING = "verdict gate NOT RUNNING: corpus missing — see TODO P1"


def _corpus_dir() -> Path:
    env = os.environ.get("MRS_VERDICT_CORPUS")
    return Path(env) if env else _DEFAULT_CORPUS


def _read_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _PINS_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            digest, name = line.split(None, 1)
            pins[Path(name.strip()).stem] = digest
    return pins


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@functools.lru_cache(maxsize=None)
def _corpus_problems(corpus: Path) -> tuple[str, ...]:
    """Every manifested report whose corpus file is absent or not the pinned bytes."""
    if not _PINS_FILE.is_file():
        return (f"pin list {_PINS_FILE.name} missing",)
    pins = _read_pins()
    problems: list[str] = []
    for row in _PAIRS:
        rid = row["id"]
        path = corpus / f"{rid}.pdf"
        if rid not in pins:
            problems.append(f"{rid}: no pin")
        elif not path.is_file():
            problems.append(f"{rid}: missing")
        elif _sha256(path) != pins[rid]:
            problems.append(f"{rid}: sha256 mismatch")
    return tuple(problems)


def _require_corpus() -> Path:
    corpus = _corpus_dir()
    if not corpus.is_dir():
        pytest.skip(f"{_NOT_RUNNING} (expected at {corpus})")
    problems = _corpus_problems(corpus)
    if problems:
        pytest.fail(f"corpus {corpus} is not the pinned one — {len(problems)} of "
                    f"{len(_PAIRS)} report(s) wrong: {list(problems)}")
    return corpus


def _worker_init(src_dir: str) -> None:
    if src_dir and src_dir not in sys.path:
        sys.path.insert(0, src_dir)


def _read(path_str: str):
    """Both readers' verdicts for one PDF. Runs in a worker; must import there."""
    from monthly_report import pdf_crosscheck, pdf_reader
    primary, crosscheck, _has_text = pdf_reader.read_both(path_str)
    found = pdf_crosscheck.compare(primary, crosscheck, path=path_str)
    return (path_str,
            pdf_crosscheck.verdict_of(primary),
            pdf_crosscheck.verdict_of(crosscheck),
            pdf_crosscheck.blocks(found))


@pytest.fixture(scope="module")
def measured() -> dict[str, dict]:
    """Read every manifested PDF once, in parallel, and hand back the results.

    Module-scoped: 630 PDFs through two readers is ~3.5 minutes serially, ~40
    seconds across the pool, and every assertion below reads the same numbers.
    """
    corpus = _require_corpus()
    wanted = {row["id"]: corpus / f"{row['id']}.pdf" for row in _PAIRS}

    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    by_path = {str(p): rid for rid, p in wanted.items()}
    results: dict[str, dict] = {}
    truth = {row["id"]: row for row in _PAIRS}

    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2)),
                             initializer=_worker_init,
                             initargs=(src_dir,)) as pool:
        for path_str, primary, crosscheck, blocking in pool.map(_read, list(by_path)):
            rid = by_path[path_str]
            results[rid] = {"primary": primary, "crosscheck": crosscheck,
                            "blocking": blocking, **truth[rid]}
    return results


class TestTheCorpus:
    """The files the gate reads are the pinned ones — checked before anything else."""

    def test_corpus_matches_the_pinned_hashes(self) -> None:
        _require_corpus()


class TestTheGate:
    """The one that stops a release."""

    def test_no_silent_errors(self, measured) -> None:
        silent = [r for r in measured.values()
                  if r["primary"] == r["crosscheck"] and r["primary"] != r["truth"]]
        assert silent == [], (
            f"{len(silent)} report(s) where BOTH readers agreed and BOTH were wrong — "
            f"these ship a false verdict with nothing to flag it: "
            f"{[r['id'] for r in silent]}")

    def test_it_really_covered_the_whole_corpus(self, measured) -> None:
        """A gate that quietly measured 12 files would also report zero errors."""
        assert len(measured) == len(_PAIRS) == 630

    def test_no_silent_errors_in_live_folders(self, measured) -> None:
        """The subset that actually reaches a delivered document."""
        live = [r for r in measured.values() if r["live"]]
        assert len(live) == 453
        assert [r["id"] for r in live
                if r["primary"] == r["crosscheck"] and r["primary"] != r["truth"]] == []


class TestQuarantineVolume:
    """How much the operator is asked to settle by hand. 19 was judged workable."""

    def test_the_quarantine_set_is_exactly_the_measured_one(self, measured) -> None:
        got = sorted(rid for rid, r in measured.items()
                     if r["primary"] != r["crosscheck"])
        expected = sorted(row["id"] for row in _PAIRS
                          if row["primary"] != row["crosscheck"])
        assert got == expected
        assert len(got) == 19

    def test_every_quarantined_case_has_one_correct_reader(self, measured) -> None:
        """Not required by the gate, but true today, and worth knowing if it stops
        being true: it means the operator's job is to pick, never to re-derive."""
        undecidable = [rid for rid, r in measured.items()
                       if r["primary"] != r["crosscheck"]
                       and r["truth"] not in (r["primary"], r["crosscheck"])]
        assert undecidable == []

    def test_a_disagreement_always_blocks(self, measured) -> None:
        """``compare()`` must quarantine exactly when the verdicts differ — a
        disagreement it fails to block is a silent error by another route."""
        assert [rid for rid, r in measured.items()
                if r["blocking"] != (r["primary"] != r["crosscheck"])] == []


class TestTheCasesThatCausedThis:
    """Named reports from the investigation. Each one is a bug that shipped."""

    @pytest.mark.parametrize("report_no", ["RT-SDL-25-086", "RT-SDL-25-087"])
    def test_accepted_rt_reports_read_as_accepted(self, measured, report_no) -> None:
        """The operator's pair: pdf2docx shattered `Accept / Reject`, the lone
        `Reject` cell became the verdict, and an accepted report shipped Yarasız."""
        row = measured[report_no]
        assert row["truth"] == "Fit"
        assert row["primary"] == row["crosscheck"] == "Fit"

    @pytest.mark.parametrize("report_no", ["MT-U-25-028", "MT-U-25-033"])
    def test_rejected_mt_reports_are_not_read_as_accepted(self, measured, report_no) -> None:
        """The dangerous direction: a real rejection hidden as Yararlı."""
        row = measured[report_no]
        assert row["truth"] == "Unfit"
        assert row["primary"] == row["crosscheck"] == "Unfit"

    def test_the_ut_stacked_header_is_reassembled(self, measured) -> None:
        """UT-SDLN-25-001 is what the header-band merge was built for: `Accept/`
        and `Reject` on two text lines. Without the merge the cross-check reader
        said Unfit here, and 46 UT reports with it."""
        row = measured["UT-SDLN-25-001"]
        assert row["truth"] == "Fit"
        assert row["crosscheck"] == "Fit"

    @pytest.mark.parametrize("report_no", ["RT-U-25-176", "RT-U-25-029", "RT-SDLN-26-699"])
    def test_the_rt_film_grid_reaches_the_operator(self, measured, report_no) -> None:
        """The primary reader's blind spot. It says Fit, the truth is Unfit — a
        false accept. It must NOT be shipped: the cross-check has to disagree."""
        row = measured[report_no]
        assert row["truth"] == "Unfit"
        assert row["primary"] == "Fit"
        assert row["crosscheck"] == "Unfit"
        assert row["blocking"] is True


class TestTheManifest:
    """Guard the oracle itself — a corrupted manifest would pass everything."""

    def test_it_holds_the_measured_corpus(self) -> None:
        assert len(_PAIRS) == 630
        assert {row["truth"] for row in _PAIRS} == {"Fit", "Unfit"}
        assert len({row["id"] for row in _PAIRS}) == 630

    def test_the_readers_disagreed_on_19_of_them(self) -> None:
        assert sum(1 for row in _PAIRS
                   if row["primary"] != row["crosscheck"]) == 19

    def test_neither_reader_is_safe_alone(self) -> None:
        """The reason there are two. Each is wrong on ~10 reports, and if one of
        these ever hits 0 the pairing was probably weakened, not improved."""
        assert sum(1 for row in _PAIRS if row["primary"] != row["truth"]) == 9
        assert sum(1 for row in _PAIRS if row["crosscheck"] != row["truth"]) == 10

    def test_the_two_failure_sets_do_not_overlap(self) -> None:
        """The property that makes the cross-check work at all."""
        b1 = {row["id"] for row in _PAIRS if row["primary"] != row["truth"]}
        b3 = {row["id"] for row in _PAIRS if row["crosscheck"] != row["truth"]}
        assert b1 & b3 == set()

    def test_every_manifested_report_is_pinned_by_hash(self) -> None:
        """The pin list is the corpus's identity; it must cover exactly the manifest."""
        pins = _read_pins()
        assert set(pins) == {row["id"] for row in _PAIRS}
        assert all(len(h) == 64 and set(h) <= set("0123456789abcdef")
                   for h in pins.values())
