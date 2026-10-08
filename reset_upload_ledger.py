#!/usr/bin/env python3
"""Empty the portal upload ledger — forget every report, keep the file and schema.

WHEN THIS IS THE RIGHT TOOL. ``uploader.py`` refuses to re-send a report the ledger
already records as ``UPLOADED``; that refusal is the whole point of the ledger and
``--force`` deliberately cannot reach it. So when submissions are withdrawn on the
PORTAL SIDE — deleted drafts that were never e-signed, a re-issue after a document
format change — the local ledger is left claiming reports are filed that no longer
exist there, and nothing will ever go up again. This resets that claim.

ORDER MATTERS, AND IT IS NOT REVERSIBLE BY THIS SCRIPT.

    1. delete the drafts on the portal
    2. confirm the portal list is empty
    3. run this

Run it before step 1 and the next uploader run files a SECOND copy of everything
that is still sitting on the portal — the exact duplicate the ledger exists to
prevent. Back up ``.upload_state.json`` first; a reset cannot be undone from here.

WHAT IT DOES NOT DO. It never deletes the ledger file: ``UploadLedger.load`` treats a
missing file as a first run but an unparseable one as a hard error, and a file that
is present and valid-but-empty is the state that says "nothing is filed" without
ambiguity. Every write goes through ``UploadLedger.reset`` -> ``_flush``, so the
atomic tempfile + fsync + os.replace path is the same one the uploader itself uses.
Nothing in ``uploader.py`` is imported, called or changed — not ``decide``, not the
three brakes, not the approved-clients gate.

    python reset_upload_ledger.py --dry-run          # list what would be forgotten
    python reset_upload_ledger.py --yes              # forget it
    python reset_upload_ledger.py --ledger .upload_state.dryrun.json --yes

AFTER A RESET every compiled artifact loses the protection ``protected_keys`` gave
it, so the next ``python main.py --force-rebuild`` is free to retire stale output the
ledger had been pinning. That is intended, and it is why the backup above is not
optional.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to a legacy codepage that cannot encode the Azerbaijani
# glyphs a report path may carry; force UTF-8 so prints never crash mid-run.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from monthly_report.upload_ledger import (LIVE_LEDGER_NAME,  # noqa: E402
                                          SCHEMA_VERSION, LedgerError,
                                          UploadLedger)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="reset_upload_ledger.py",
        description="Forget every recorded upload so the next run re-sends them. "
                    "Delete the drafts on the portal FIRST.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ledger", metavar="JSON", default=None,
                   help=f"Ledger file to empty (default: {LIVE_LEDGER_NAME} at the "
                        f"project root). Pass the dry-run ledger explicitly to "
                        f"reset that one instead.")
    p.add_argument("--dry-run", action="store_true",
                   help="List the entries that would be forgotten and exit without "
                        "writing anything.")
    p.add_argument("--yes", action="store_true",
                   help="Required to actually write. Without it the script refuses, "
                        "so a mistyped command can never empty the ledger.")
    return p


def _describe(ledger: UploadLedger) -> None:
    """Print one line per recorded report: status, serial, key."""
    for key in sorted(ledger.recorded_keys()):
        entry = ledger.get(key)
        print(f"  {entry.status:<12} {entry.serial or '(no serial)':<20} {key}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.ledger) if args.ledger else PROJECT_ROOT / LIVE_LEDGER_NAME

    try:
        ledger = UploadLedger.load(path)
    except LedgerError as exc:
        # Fail closed, exactly as the uploader does: an unreadable ledger is not an
        # empty one, and overwriting it would destroy the only record of what was
        # sent.
        raise SystemExit(str(exc))

    print(f"ledger : {path}")
    if not path.is_file():
        print("       : file does not exist yet — nothing recorded, nothing to reset.")
        return 0

    keys = sorted(ledger.recorded_keys())
    print(f"entries: {len(keys)}")
    if not keys:
        print("Ledger is already empty — nothing to do.")
        return 0
    _describe(ledger)

    if args.dry_run:
        print(f"\nDRY RUN — nothing written. {len(keys)} entry(ies) would be "
              f"forgotten.")
        return 0
    if not args.yes:
        raise SystemExit(
            "Refusing to write without --yes.\n"
            "  Confirm the portal drafts are deleted, back up the ledger, then "
            "re-run with --yes.")

    removed = sum(1 for key in keys if ledger.reset(key))
    print(f"\n{removed} entry(ies) forgotten. Ledger kept at {path} "
          f"(version={SCHEMA_VERSION}, entries={{}}).")
    if removed != len(keys):
        # Defensive: reset() reports False for a key it did not hold. The keys came
        # from this same ledger a moment ago, so a mismatch means the file changed
        # under us and the operator needs to know rather than read a clean summary.
        print(f"WARNING: {len(keys) - removed} key(s) were already gone — the "
              f"ledger changed while this ran. Re-check it.", file=sys.stderr)
    print("Next: python main.py --force-rebuild, then "
          "python uploader.py --dry-run --all")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
