"""scripts/build_verdict_corpus.py — selection, idempotency and the no-touch rule.

Synthetic ``input/`` trees only; the real corpus is exercised by
``tests/test_verdict_regression.py``. What is pinned here is that the builder is
fail-closed (no unique source = nothing written), never overwrites, never moves
or changes a source, and writes the tracked hash list on the first build only.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts"))

import build_verdict_corpus as bvc                                  # noqa: E402


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes())
            for p in sorted(root.rglob("*")) if p.is_file()}


@pytest.fixture
def tree(tmp_path: Path) -> dict[str, Path]:
    """input/ with one archived report, one quarantined, one retest look-alike."""
    inp = tmp_path / "input"
    (inp / "PDF_ARCHIVE").mkdir(parents=True)
    (inp / "SKIPPED_REPORTS").mkdir()
    (inp / "PDF_ARCHIVE" / "RT-X-25-001 (Job A).pdf").write_bytes(b"one")
    (inp / "SKIPPED_REPORTS" / "RT-X-25-002 (Job A).pdf").write_bytes(b"two")
    (inp / "PDF_ARCHIVE" / "RT-X-25-003 R1 (Job A).pdf").write_bytes(b"three-R1")
    (inp / "SKIPPED_REPORTS" / "RT-X-25-003 (Job A).pdf").write_bytes(b"three")
    return {"input": inp, "target": tmp_path / "corpus" / "vr",
            "pins": tmp_path / "pins.sha256", "registry": tmp_path / "none.json"}


_IDS = ["RT-X-25-001", "RT-X-25-002", "RT-X-25-003"]
_PIN_003 = {"RT-X-25-003": _sha(b"three")}


def _build(tree, *, ids=_IDS, pinned=_PIN_003, dry_run=False) -> int:
    return bvc.build(input_dir=tree["input"], target=tree["target"],
                     pins_file=tree["pins"], ids=ids, dry_run=dry_run,
                     registry=tree["registry"], pinned=pinned)


class TestSelection:
    def test_a_single_candidate_is_taken_from_either_folder(self, tree) -> None:
        assert _build(tree) == 0
        assert (tree["target"] / "RT-X-25-001.pdf").read_bytes() == b"one"
        assert (tree["target"] / "RT-X-25-002.pdf").read_bytes() == b"two"

    def test_a_pin_picks_the_original_over_its_retest(self, tree) -> None:
        """The RT-U-25-056 shape: "…-003 R1 (…)" shares the leading token."""
        assert _build(tree) == 0
        assert (tree["target"] / "RT-X-25-003.pdf").read_bytes() == b"three"

    def test_several_candidates_without_a_pin_refuse(self, tree) -> None:
        assert _build(tree, pinned={}) == 1
        assert not tree["target"].exists()
        assert not tree["pins"].exists()

    def test_a_pin_no_candidate_carries_refuses(self, tree) -> None:
        assert _build(tree, pinned={"RT-X-25-003": _sha(b"gone")}) == 1
        assert not tree["target"].exists()

    def test_a_report_with_no_candidate_refuses(self, tree) -> None:
        assert _build(tree, ids=_IDS + ["RT-X-25-009"]) == 1
        assert not tree["target"].exists()


class TestWrites:
    def test_dry_run_writes_nothing(self, tree) -> None:
        assert _build(tree, dry_run=True) == 0
        assert not tree["target"].exists()
        assert not tree["pins"].exists()

    def test_the_sources_are_never_touched(self, tree) -> None:
        before = _snapshot(tree["input"])
        assert _build(tree) == 0
        assert _snapshot(tree["input"]) == before

    def test_the_first_build_writes_the_pin_list(self, tree) -> None:
        assert _build(tree) == 0
        assert bvc.read_pins(tree["pins"]) == {
            "RT-X-25-001": _sha(b"one"), "RT-X-25-002": _sha(b"two"),
            "RT-X-25-003": _sha(b"three")}
        assert b"\r\n" not in tree["pins"].read_bytes()
        assert "(Job A)" not in tree["pins"].read_text(encoding="utf-8")

    def test_a_second_build_copies_nothing_and_keeps_the_pin_list(self, tree, capsys) -> None:
        assert _build(tree) == 0
        pins_before = tree["pins"].read_bytes()
        capsys.readouterr()
        assert _build(tree) == 0
        assert "copied 0, kept 3" in capsys.readouterr().out
        assert tree["pins"].read_bytes() == pins_before

    def test_the_audit_trail_names_each_source(self, tree) -> None:
        assert _build(tree) == 0
        rows = (tree["target"] / bvc.SOURCES_TSV).read_text(encoding="utf-8").splitlines()
        assert rows[0].split("\t") == ["report_no", "sha256", "source", "lan_staged_at"]
        assert "SKIPPED_REPORTS/RT-X-25-003 (Job A).pdf" in rows[3]


class TestRefusals:
    def test_a_target_file_with_other_bytes_is_never_overwritten(self, tree) -> None:
        tree["target"].mkdir(parents=True)
        (tree["target"] / "RT-X-25-001.pdf").write_bytes(b"tampered")
        assert _build(tree) == 1
        assert (tree["target"] / "RT-X-25-001.pdf").read_bytes() == b"tampered"

    def test_a_source_that_drifted_from_the_tracked_pins_refuses(self, tree) -> None:
        assert _build(tree) == 0
        (tree["input"] / "PDF_ARCHIVE" / "RT-X-25-001 (Job A).pdf").write_bytes(b"new")
        assert _build(tree) == 1

    def test_a_pin_list_that_disagrees_with_the_manifest_refuses(self, tree) -> None:
        assert _build(tree) == 0
        assert _build(tree, ids=_IDS[:2]) == 1

    def test_builtin_pins_must_agree_with_the_tracked_list(self, tree) -> None:
        assert _build(tree) == 0
        assert _build(tree, pinned={"RT-X-25-003": _sha(b"three-R1")}) == 1


class TestTheRealPins:
    def test_the_builtin_pins_are_in_the_tracked_list(self) -> None:
        """The seven operator-decided pins (056 + six doubled numbers) survived."""
        tracked = bvc.read_pins(bvc.PINS_FILE)
        assert {rid: tracked.get(rid) for rid in bvc._PINNED} == bvc._PINNED

    def test_rt_u_25_056_is_pinned_to_the_original(self) -> None:
        assert bvc._PINNED["RT-U-25-056"].startswith("c9e77465")
