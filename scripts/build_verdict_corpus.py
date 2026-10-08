"""Build the pinned PDF corpus the ADR-003 verdict gate reads.

``tests/test_verdict_regression.py`` reads 630 PDFs, one per report number in
``tests/data/verdict_regression.json``. It used to find them in
``input/PDF_ARCHIVE/`` by leading token, and that stopped working the day the
gate's own subject did its job: the ADR-003 migration run of 2026-09-07
quarantined 20 of them into ``input/SKIPPED_REPORTS/``. A leading-token lookup
also has a blind spot of its own — ``RT-U-25-056 R1 (…).pdf`` answers to
``RT-U-25-056`` — so once the original left, the retest stood in for it.

This script copies the 630 into ``corpus/verdict_regression/<ID>.pdf`` and pins
their bytes in ``tests/data/verdict_corpus.sha256`` (tracked; report numbers and
hashes only, no filenames). The gate verifies every file against that list.

Selection, per report number, is fail-closed — no fallback, no guess:

1. candidates are the ``*.pdf`` in ``input/PDF_ARCHIVE/`` and
   ``input/SKIPPED_REPORTS/`` whose leading token is the report number;
2. a pinned number takes the candidate carrying its pinned hash, or fails;
3. an unpinned number takes its only candidate, or fails (none / several).

Pins are the tracked hash list once it exists. Before that — the first build —
they are :data:`_PINNED`: ``RT-U-25-056`` (the original, not its ``R1``) and the
six numbers ``PDF_ARCHIVE`` holds twice, each pinned to the copy the gate's old
``sorted`` + ``setdefault`` lookup chose. Which copy the 2026-09-07 measurement
read is unknown; both copies of all six gave the manifested verdicts on
2026-09-28.

The tracked list is written by the first build only. A later build that would
produce any other hash refuses, as does a target file whose hash differs from
its pin; nothing is ever overwritten. ``input/`` is only read. The only writes
are ``<target>/<ID>.pdf``, ``<target>/SOURCES.tsv`` (gitignored audit trail:
source path, hash, LAN staging time) and, on the first build, the tracked list.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report.naming import PDF_ARCHIVE_DIR, QUARANTINE_DIR  # noqa: E402
from monthly_report.report_identity import leading_token  # noqa: E402

MANIFEST = _ROOT / "tests" / "data" / "verdict_regression.json"
PINS_FILE = _ROOT / "tests" / "data" / "verdict_corpus.sha256"
DEFAULT_TARGET = _ROOT / "corpus" / "verdict_regression"
REGISTRY = _ROOT / ".state" / "network_sync_manifest.json"
SOURCE_DIRS = (PDF_ARCHIVE_DIR, QUARANTINE_DIR)
SOURCES_TSV = "SOURCES.tsv"

#: First-build pins (operator decision, 2026-09-28). See the module docstring.
_PINNED = {
    # The original. PDF_ARCHIVE holds only "RT-U-25-056 R1 (…).pdf", which reads Fit/Fit.
    "RT-U-25-056": "c9e77465afd0a8656ba634e1d0aa7d19cbccc7e629813ba4371c1a58a9465a5f",
    # Two different PDFs under one number; the sorted-first copy.
    "MT-KF-25-011": "b8f6f9c4712be2c09ad9c807e4a62a4e4a88544e7213d1e736b74b9eff1cd35b",
    "MT-KF-25-041": "e37260f5daf83b469a6937771b1c612b6ae2fd6541407c2f6e1fab65ac8ec8d7",
    "MT-KF-25-065": "cd0dc63ede5a4482738323af54adda81d2e1a18e5a1285cf21e87555a838c66c",
    "MT-KF-25-075": "85b23a97430c11912434737582f66073c8ed68284f769a46bcae2ca41dad729b",
    "UT-SDLN-25-024": "777d8cd4218976696b65c80db41a1a8d789606d6c07fc055ecce7cccf6f45485",
    "UT-SDLN-25-025": "81afe0f3c11f4ec95f61a1f9a71794ec32bb81830a502a6176257c4b337438e8",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest_ids(manifest: Path = MANIFEST) -> list[str]:
    return [row["id"] for row in json.loads(manifest.read_text(encoding="utf-8"))["pairs"]]


def read_pins(path: Path) -> dict[str, str]:
    """``{report_no: sha256}`` from ``<sha256>  <report_no>.pdf`` lines."""
    pins: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, name = line.split(None, 1)
        pins[Path(name.strip()).stem] = digest
    return pins


def format_pins(pins: dict[str, str]) -> str:
    return "".join(f"{pins[rid]}  {rid}.pdf\n" for rid in sorted(pins))


def candidates(input_dir: Path, ids: list[str]) -> dict[str, list[Path]]:
    wanted = set(ids)
    found: dict[str, list[Path]] = {rid: [] for rid in ids}
    for sub in SOURCE_DIRS:
        for pdf in sorted((input_dir / sub).glob("*.pdf")):
            key = leading_token(pdf.name).upper()
            if key in wanted:
                found[key].append(pdf)
    return found


def select(ids: list[str], found: dict[str, list[Path]],
           pins: dict[str, str]) -> tuple[dict[str, tuple[Path, str]], list[str]]:
    """``({report_no: (source, sha256)}, [error, ...])`` — see the module rules."""
    chosen: dict[str, tuple[Path, str]] = {}
    errors: list[str] = []
    for rid in ids:
        hashed = [(p, sha256(p)) for p in found.get(rid, [])]
        if rid in pins:
            match = [(p, h) for p, h in hashed if h == pins[rid]]
            if match:
                chosen[rid] = match[0]
            else:
                errors.append(f"{rid}: pinned {pins[rid][:16]}... not among "
                              f"{len(hashed)} candidate(s) {[h[:16] for _, h in hashed]}")
        elif len(hashed) == 1:
            chosen[rid] = hashed[0]
        else:
            errors.append(f"{rid}: {len(hashed)} candidate(s), no pin")
    return chosen, errors


def _staged_at(registry: Path) -> dict[str, str]:
    """``{sha256: staged_at}`` from the LAN ingestion registry; empty when absent."""
    if not registry.is_file():
        return {}
    entries = json.loads(registry.read_text(encoding="utf-8")).get("entries", {})
    return {h: (e.get("staged_at") or "") for h, e in entries.items()}


def build(*, input_dir: Path, target: Path, pins_file: Path, ids: list[str],
          dry_run: bool, registry: Path = REGISTRY,
          pinned: dict[str, str] | None = None) -> int:
    pinned = _PINNED if pinned is None else pinned
    tracked = read_pins(pins_file) if pins_file.is_file() else None

    if tracked is not None:
        drift = sorted(set(tracked) ^ set(ids))
        if drift:
            print(f"REFUSE: {pins_file.name} and the manifest disagree on "
                  f"{len(drift)} report number(s): {drift}")
            return 1
        conflict = sorted(rid for rid, h in pinned.items() if tracked.get(rid) != h)
        if conflict:
            print(f"REFUSE: built-in pins differ from {pins_file.name}: {conflict}")
            return 1
    pins = tracked if tracked is not None else pinned
    print(f"pins: {len(pins)} from "
          f"{pins_file.name if tracked is not None else 'built-in first-build list'}")

    chosen, errors = select(ids, candidates(input_dir, ids), pins)
    if errors:
        print(f"REFUSE: {len(errors)} report number(s) without a unique source:")
        for line in errors:
            print(f"  {line}")
        return 1

    keep, copy, clash = [], [], []
    for rid in ids:
        dest = target / f"{rid}.pdf"
        if not dest.exists():
            copy.append(rid)
        elif sha256(dest) == chosen[rid][1]:
            keep.append(rid)
        else:
            clash.append(rid)
    if clash:
        print(f"REFUSE: {len(clash)} file(s) in {target} differ from their pin "
              f"(never overwritten): {clash}")
        return 1

    total = sum(src.stat().st_size for src, _ in chosen.values())
    from_quarantine = sorted(rid for rid, (src, _) in chosen.items()
                             if src.parent.name == QUARANTINE_DIR)
    print(f"selected: {len(chosen)} | from {QUARANTINE_DIR}: {len(from_quarantine)} "
          f"| size: {total / (1 << 20):.1f} MiB")
    print(f"target: {target} | copy: {len(copy)} | already pinned: {len(keep)}")
    if dry_run:
        for rid in copy:
            src, digest = chosen[rid]
            print(f"  would copy {rid}.pdf <- {src.relative_to(input_dir).as_posix()} "
                  f"({digest[:16]}...)")
        print("dry-run: nothing written")
        return 0

    target.mkdir(parents=True, exist_ok=True)
    for rid in copy:
        src, digest = chosen[rid]
        tmp = target / f"{rid}.pdf.tmp"
        shutil.copy2(src, tmp)
        if sha256(tmp) != digest:
            tmp.unlink()
            print(f"REFUSE: {rid} changed while being copied from {src.name}")
            return 1
        os.replace(tmp, target / f"{rid}.pdf")

    staged = _staged_at(registry)
    rows = ["report_no\tsha256\tsource\tlan_staged_at"]
    rows += [f"{rid}\t{chosen[rid][1]}\t{chosen[rid][0].relative_to(input_dir).as_posix()}"
             f"\t{staged.get(chosen[rid][1], '')}" for rid in sorted(chosen)]
    (target / SOURCES_TSV).write_text("\n".join(rows) + "\n", encoding="utf-8")

    if tracked is None:
        pins_file.write_text(format_pins({rid: h for rid, (_, h) in chosen.items()}),
                             encoding="utf-8", newline="\n")
        print(f"wrote {pins_file.name}: {len(chosen)} pins (first build)")
    print(f"done: copied {len(copy)}, kept {len(keep)}, corpus holds "
          f"{len(list(target.glob('*.pdf')))} PDF(s)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input-dir", default=str(_ROOT / "input"))
    ap.add_argument("--target", default=str(DEFAULT_TARGET))
    ap.add_argument("--pins", default=str(PINS_FILE),
                    help="tracked hash list; written only when absent")
    ap.add_argument("--dry-run", action="store_true",
                    help="select and check, print the plan, write nothing")
    args = ap.parse_args(argv)
    # Source names carry non-ASCII (Ş, ”); a cp125x console must not abort the run.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    return build(input_dir=Path(args.input_dir), target=Path(args.target),
                 pins_file=Path(args.pins), ids=manifest_ids(), dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
