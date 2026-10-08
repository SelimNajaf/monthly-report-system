#!/usr/bin/env python3
"""Reset the local input/ tree to zero and re-sync fresh reports off the LAN share.

A one-shot operator utility for the production cutover. It (1) PERMANENTLY DELETES
the entire local ``input/`` tree plus the dedup state that would otherwise suppress
a re-ingest, and (2) runs a date-gated sync from the SMB share
(``\\\\<host>\\<share>\\...``), staging only reports dated on or after a cutoff (default
``2025-12-01``). DOCX twins are preferred over their .pdf.

    python reset_and_sync_input.py                 # reset (asks), then sync since 2025-12-01
    python reset_and_sync_input.py --dry-run       # show what would happen, change nothing
    python reset_and_sync_input.py --no-purge       # sync only, keep input/ as-is
    python reset_and_sync_input.py --cutoff 2026-01-01 --yes

WHY THE DELETE IS TOTAL: the sync dedups against every stem under ``input/`` (all of
it — ``PDF_ARCHIVE/``, ``SKIPPED_REPORTS/``, ``_PRUNED/``), against the
``.parse_cache/`` content digests and against ``.state/network_sync_manifest.json``.
Anything left behind reads as "already ingested" and the fresh sync stages nothing,
so a half-purge is a silent no-op. The share is the source of truth — everything
deleted here is re-copied from it.

READ-ONLY on the share: the sync only ever reads network files (walk + copy). Nothing
on ``\\\\<host>\\<share>`` is written, renamed, moved or deleted. Every deletion below is a
LOCAL path.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
from pathlib import Path

# Windows consoles default to a legacy codepage that cannot encode the Azerbaijani /
# Turkish glyphs in these report paths; force UTF-8 so prints never crash mid-run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from monthly_report.config import load_settings  # noqa: E402
from monthly_report.naming import UNSORTED_DIR  # noqa: E402
from monthly_report.services import network_ingestion  # noqa: E402

#: Default internal-date cutoff — the engagement starts December 2025; older reports
#: on the share are legacy noise.
_DEFAULT_CUTOFF = dt.date(2025, 12, 1)

#: Local dedup state that must die with the input tree. Every one of these makes the
#: sync believe a report is already ingested; leaving any behind turns the re-sync
#: into a no-op. Paths are relative to the project root.
_MANIFEST_REL = Path(".state") / "network_sync_manifest.json"


def _count_files(root: Path) -> int:
    """Number of files anywhere under ``root`` (0 when it does not exist)."""
    if not root.is_dir():
        return 0
    return sum(1 for p in root.rglob("*") if p.is_file())


def _parse_cache_dir(settings) -> Path:
    """The configured ``.parse_cache`` directory (same lookup the sync uses)."""
    perf = settings.raw.get("performance", {}) or {}
    return Path(settings.project_root) / str(perf.get("parse_cache_dir", ".parse_cache"))


def _hard_reset(settings, *, dry_run: bool, keep_cache: bool = False,
                log=print) -> int:
    """PERMANENTLY DELETE the local input tree and its dedup state; return file count.

    Removes every child of ``input/`` — working folders, ``UnSorted/``,
    ``PDF_ARCHIVE/``, ``SKIPPED_REPORTS/``, ``_PRUNED/`` — then recreates the empty
    ``input/`` and ``input/UnSorted/`` shells. Also deletes the sync manifest and (unless
    ``keep_cache``) the parse cache, because both are dedup sources: a surviving digest
    would make the fresh sync skip the very report it is meant to re-stage.

    Nothing on the network share is touched. In ``dry_run`` nothing is deleted; the
    counts that WOULD be deleted are still reported.
    """
    input_dir = Path(settings.input_dir)
    manifest = Path(settings.project_root) / _MANIFEST_REL
    cache_dir = _parse_cache_dir(settings)

    n_input = _count_files(input_dir)
    n_cache = 0 if keep_cache else _count_files(cache_dir)

    if dry_run:
        log(f"[Reset] Would DELETE {n_input} file(s) under {input_dir}.")
        log(f"[Reset] Would DELETE the sync manifest ({manifest.name}) "
            f"and {n_cache} parse-cache entr(ies)."
            if not keep_cache else
            f"[Reset] Would DELETE the sync manifest ({manifest.name}); "
            "parse cache kept (--keep-cache).")
        return n_input

    if input_dir.is_dir():
        for child in list(input_dir.iterdir()):
            try:
                if child.is_dir():
                    shutil.rmtree(child)
                else:
                    child.unlink()
            except OSError as exc:
                log(f"[Reset] could not delete {child.name} "
                    f"({type(exc).__name__}: {exc}).")
    (input_dir / UNSORTED_DIR).mkdir(parents=True, exist_ok=True)

    try:
        manifest.unlink(missing_ok=True)
    except OSError as exc:
        log(f"[Reset] could not delete {manifest.name} ({type(exc).__name__}: {exc}).")
    if not keep_cache and cache_dir.is_dir():
        shutil.rmtree(cache_dir, ignore_errors=True)

    log(f"[Reset] Deleted {n_input} file(s) under input/ — tree is at zero state.")
    log(f"[Reset] Cleared sync manifest"
        + ("." if keep_cache else f" and {n_cache} parse-cache entr(ies)."))
    return n_input


def _confirm(prompt: str) -> bool:
    """Interactive yes/no; a closed stdin (EOF) is a safe 'no'."""
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=("PERMANENTLY DELETE the local input/ tree and its dedup state, "
                     "then re-sync reports off the LAN share by inspection date."),
    )
    ap.add_argument("--cutoff", metavar="YYYY-MM-DD", default=None,
                    help="Date cutoff; older reports are skipped "
                         "(default: 2025-12-01).")
    ap.add_argument("--no-purge", action="store_true",
                    help="Skip the local reset; sync only.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report intended reset + sync without deleting, copying, or "
                         "writing the manifest.")
    ap.add_argument("--yes", action="store_true",
                    help="Skip the delete confirmation prompt.")
    ap.add_argument("--keep-cache", action="store_true",
                    help="Keep .parse_cache/ (faster re-parse, but its content "
                         "digests will suppress re-staging of identical reports).")
    return ap


def _parse_cutoff(raw: str | None) -> dt.date:
    if not raw:
        return _DEFAULT_CUTOFF
    return dt.date.fromisoformat(raw.strip())


def main(argv: list[str] | None = None) -> int:
    ns = _build_arg_parser().parse_args(argv)
    try:
        cutoff = _parse_cutoff(ns.cutoff)
    except ValueError:
        print(f"Invalid --cutoff {ns.cutoff!r}; expected YYYY-MM-DD (e.g. 2025-12-01).")
        return 2

    settings = load_settings(PROJECT_ROOT / "config" / "settings.yaml")

    print("=" * 70)
    print("Input hard reset + date-gated network sync"
          + (" (DRY RUN)" if ns.dry_run else ""))
    print(f"  Cutoff:   inspection date >= {cutoff.isoformat()}")
    print(f"  Staging:  input/{UNSORTED_DIR}/")
    print("=" * 70)

    # --- Reset ------------------------------------------------------------------------
    if ns.no_purge:
        print("[Reset] Skipped (--no-purge).")
    else:
        pending = _count_files(Path(settings.input_dir))
        if pending and not ns.dry_run and not ns.yes:
            print(f"[Reset] WARNING: this PERMANENTLY DELETES {pending} file(s) under "
                  f"{settings.input_dir} (including PDF_ARCHIVE/, SKIPPED_REPORTS/ and "
                  "_PRUNED/), the sync manifest"
                  + ("" if ns.keep_cache else " and the parse cache")
                  + ". They are re-copied from the share, which is never modified.")
            if not _confirm("[Reset] Delete and re-sync from zero? [y/N] "):
                print("[Reset] Aborted by operator — nothing deleted, nothing synced.")
                return 1
        _hard_reset(settings, dry_run=ns.dry_run, keep_cache=ns.keep_cache)

    # --- Sync -------------------------------------------------------------------------
    manifest_path = PROJECT_ROOT / ".state" / "network_sync_manifest.json"
    lan_sources = (settings.raw.get("network_ingestion") or {}).get("lan_sources") or []

    if ns.dry_run:
        target = network_ingestion._share_label(
            network_ingestion.normalize_unc(lan_sources[0])) if lan_sources else "(none)"
        print(f"[LAN Sync] Would scan {target} ({len(lan_sources)} root(s)) and stage "
              f"reports dated >= {cutoff.isoformat()} -> input/{UNSORTED_DIR}/ "
              f"(manifest: {manifest_path}).")
        print("=" * 70)
        return 0

    if not lan_sources:
        print("[LAN Sync] No network_ingestion.lan_sources configured — sync skipped.")
        print("=" * 70)
        return 0

    result = network_ingestion.sync_since(settings, cutoff, manifest_path=manifest_path)

    if result.unreachable_all:
        print("[LAN Sync] Network share unreachable, proceeding with local input/ files.")
    else:
        print(f"[LAN Sync] {result.up_to_date} files up to date; "
              f"{result.staged_count} new report(s) staged; "
              f"{result.legacy_skipped} legacy reports skipped (< {cutoff:%Y-%m}).")
        if result.twin_skipped:
            print(f"[LAN Sync] {result.twin_skipped} redundant .pdf twin(s) skipped "
                  f"(editable .docx preferred).")
        if result.rejected:
            print(f"[LAN Sync] {result.rejected} non-report file(s) rejected by the "
                  f"filename filter (admin docs, ~$ lock files, unregistered clients).")
        print(f"[LAN Sync] Scanned {result.share_label} "
              f"({result.roots_reachable}/{result.roots_scanned} root(s) reachable).")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
