"""One-off operator tool: retire ``-lan`` ingest duplicates and clean noisy PDF names.

Four independent passes over ``input/``, each opt-in:

``--prune``
    Every file whose stem ends in ``-lan`` (``-lan2``, ``-lan3`` ...) is compared to
    its suffix-free twin IN THE SAME FOLDER. The SHA-256 of BOTH files is recomputed
    here — an earlier audit is evidence, not authority. Byte-identical pairs send the
    ``-lan`` copy to ``input/_PRUNED/``; anything else is left alone and recorded as
    kept. Nothing is ever deleted (the disposal rule in :mod:`naming`).

``--rename``
    A PDF whose Report No is not its whole filename stem
    (:func:`report_identity.identity_noise`) is renamed so the noise moves inside
    parentheses::

        DP-SDLN-26-103___F1895___19.05.26.pdf -> DP-SDLN-26-103 (F1895 19.05.26).pdf

    That is the only shape which clears the warning: ``leading_token`` stops at the
    first space or underscore, and ``parse_filename_metadata`` cuts the report number
    at the first ``(``, so a parenthesised tail makes the two agree. Collapsing the
    underscore runs instead only changes the warning's reason, it does not remove it.
    ``report_key_of`` and ``date_detector.filename_dates`` must come out unchanged —
    that is asserted per file in :func:`_rename_is_safe` BEFORE the rename happens,
    and a file that fails the assertion is kept.

``--fix-lost-paren``
    A PDF name carrying a ``)`` with no ``(`` before it lost its opening
    parenthesis in export::

        RT-SDL-25-047F1802)3''x15.9…  ->  RT-SDL-25-047 (F1802 3''x15.9 …)

    The same batch exported ``RT-SDL-25-046(F1802)3''x15.9…`` correctly, which is
    what makes the repair evidence rather than a guess. Unlike ``--rename`` this
    pass MOVES ``report_key_of`` on purpose — the old key had the job number welded
    into the report number — so it asserts instead that the recovered key is
    claimed by nobody and that a clean sibling proves the shape.

``--fix-twin-docx``
    The ``.docx`` partner of a repaired PDF carries the same bug without the stray
    ``)`` to show it (``RT-SDL-25-047F1802.docx``). Repairing only the PDF would
    split a twin pair that used to agree, so this pass renames the partner to the
    bare report number its clean siblings already use.

Every pass is dry-run by default; ``--apply`` performs it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import re
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import date_detector, docx_reader, report_identity  # noqa: E402
from monthly_report.naming import PRUNED_DIR, QUARANTINE_DIR  # noqa: E402

STAGE_EXTS = {".docx", ".pdf"}
_LAN_TAG = re.compile(r"-lan\d*$", re.IGNORECASE)

# Kept out of the rename pass by operator decision (task 11, A3).
# ``U-UTM-26-001`` collides across clients and ``AZF-FCM-W1-25-06.docx.pdf`` carries
# a double extension whose correct stem cannot be inferred; both stay warned instead.
RENAME_EXCLUDE = {
    "AZF-FCM-W1-25-06.docx.pdf",
    "U-UTM-26-001_______F1945___.pdf",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _stageable(path: Path) -> bool:
    return (path.is_file()
            and path.suffix.casefold() in STAGE_EXTS
            and not path.name.startswith("~$"))


def _walk(input_dir: Path):
    """Every stageable file under ``input/`` except the ``_PRUNED/`` disposal tree."""
    for path in sorted(input_dir.rglob("*")):
        rel = path.relative_to(input_dir).parts
        if PRUNED_DIR in rel:
            continue
        if _stageable(path):
            yield path


def _nonclobber(dest_dir: Path, name: str) -> Path:
    """A free path under ``dest_dir`` — an existing disposal is never overwritten."""
    dest = dest_dir / name
    if not dest.exists():
        return dest
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while (dest_dir / f"{stem}-{n}{suffix}").exists():
        n += 1
    return dest_dir / f"{stem}-{n}{suffix}"


# --------------------------------------------------------------------------- #
# pass 1 — -lan duplicates
# --------------------------------------------------------------------------- #
def find_lan_pairs(input_dir: Path) -> list[dict]:
    """Every ``-lan`` file paired with its same-folder twin, both hashes recomputed."""
    rows: list[dict] = []
    for path in _walk(input_dir):
        if not _LAN_TAG.search(path.stem):
            continue
        twin = path.with_name(_LAN_TAG.sub("", path.stem) + path.suffix)
        if not twin.is_file():
            rows.append({"lan": path, "twin": None, "sha_lan": sha256(path),
                         "sha_twin": "", "decision": "EKIZ YOX - saxlanildi"})
            continue
        sha_lan, sha_twin = sha256(path), sha256(twin)
        rows.append({
            "lan": path, "twin": twin, "sha_lan": sha_lan, "sha_twin": sha_twin,
            "decision": ("_PRUNED-e kochuruldu" if sha_lan == sha_twin
                         else "FERQLI - saxlanildi"),
        })
    return rows


def prune(input_dir: Path, rows: list[dict], apply: bool) -> int:
    """Move every byte-identical ``-lan`` copy to ``input/_PRUNED/``. Returns the count."""
    pruned_dir = input_dir / PRUNED_DIR
    moved = 0
    for row in rows:
        if not row["sha_twin"] or row["sha_twin"] != row["sha_lan"]:
            continue
        if apply:
            pruned_dir.mkdir(parents=True, exist_ok=True)
            dest = _nonclobber(pruned_dir, row["lan"].name)
            shutil.move(str(row["lan"]), str(dest))
            row["decision"] = f"_PRUNED-e kochuruldu ({dest.name})"
        moved += 1
    return moved


# --------------------------------------------------------------------------- #
# pass 2 — noisy PDF names
# --------------------------------------------------------------------------- #
def proposed_name(name: str) -> str | None:
    """The parenthesised spelling of a noisy PDF name, or ``None`` when inapplicable."""
    stem, suffix = Path(name).stem, Path(name).suffix
    token = report_identity.leading_token(name)
    if not token or not stem.startswith(token) or len(stem) == len(token):
        return None
    tail = re.sub(r"[_\s]+", " ", stem[len(token):]).strip(" -")
    if not tail:
        return None
    return f"{token} ({tail}){suffix}"


def _rename_is_safe(old: str, new: str) -> str | None:
    """``None`` when the rename is provably identity-preserving, else the reason.

    Four properties must hold, because each one feeds a different consumer: the
    warning must clear (``identity_noise``), the twin/dedup identity must not move
    (``report_key_of`` -> ``pdf_twin.index``), the filename dates the date-repair pass
    reads must be identical, and the resolved Report No must become the leading token.
    """
    if report_identity.identity_noise(new) is not None:
        return "yeni ad hele de kuyludur"
    if report_identity.report_key_of(new) != report_identity.report_key_of(old):
        return "report_key deyisir"
    if date_detector.filename_dates([new]) != date_detector.filename_dates([old]):
        return "fayl adi tarixi deyisir"
    if (docx_reader.parse_filename_metadata(new)["report_no"]
            != report_identity.leading_token(old)):
        return "Report No aparici token deyil"
    return None


_AUDIT_NAME = re.compile(r"\|\s*`([^`]+\.pdf)`\s*\|")


def audit_names(audit_md: Path) -> set[str]:
    """The filenames listed in an ``output/identity_warnings_<date>.md`` table.

    The rename pass is scoped to this set on purpose. A corpus-wide sweep also finds
    names the pipeline never reported — ASR documents (excluded on sight) and the
    ``RT-SDL-25-047F1802)3''x15.9…`` family, whose leading token is
    ``RT-SDL-25-047F1802``: the parenthesising rule would then pin ``F1802`` INTO the
    Report No rather than out of it, and no mechanical check can tell that apart from
    a real suffix. The operator has since identified that family as a lost opening
    parenthesis; :func:`find_lost_paren` handles it under its own invariants.
    """
    return set(_AUDIT_NAME.findall(audit_md.read_text(encoding="utf-8")))


def find_renames(input_dir: Path, allowed: set[str] | None = None) -> list[dict]:
    """Noisy PDF names with a proposal that provably clears the warning."""
    rows: list[dict] = []
    for path in _walk(input_dir):
        if path.suffix.casefold() != ".pdf":
            continue
        if QUARANTINE_DIR in path.relative_to(input_dir).parts:
            continue
        why = report_identity.identity_noise(path.name)
        if why is None:
            continue
        if allowed is not None and path.name not in allowed:
            continue
        if path.name in RENAME_EXCLUDE:
            rows.append({"path": path, "why": why, "new": None,
                         "decision": "KENARDA (A3) - toxunulmadi"})
            continue
        new = proposed_name(path.name)
        if new is None:
            rows.append({"path": path, "why": why, "new": None,
                         "decision": "ad qurula bilmedi - saxlanildi"})
            continue
        refused = _rename_is_safe(path.name, new)
        rows.append({"path": path, "why": why, "new": new,
                     "decision": "adi deyisdi" if refused is None
                     else f"REDD: {refused}"})
    return rows


# --------------------------------------------------------------------------- #
# pass 3 — names whose OPENING parenthesis was lost in the export
# --------------------------------------------------------------------------- #
# ``RT-SDL-25-047F1802)3''x15.9…`` — a ``)`` with no ``(`` anywhere before it. The
# same batch exports ``RT-SDL-25-046(F1802)3''x15.9…`` correctly: same day, same job,
# same shape. So the ``(`` belonged immediately after the report number, and the
# number ends at its ``-<YY>-<seq>`` group — the anchor
# :func:`report_identity.serial_year` already uses. The stray ``)`` is what makes this
# recoverable: it marks where the lost group closed, so the split is read off the
# name, not guessed.
_LOST_PAREN = re.compile(r"^(.*?-\d{2}-\d{1,4})([A-Za-z]\w*)\)")


def lost_paren_name(name: str) -> tuple[str, str] | None:
    """``(new_name, recovered_token)`` for a lost-``(`` PDF name, else ``None``."""
    stem, suffix = Path(name).stem, Path(name).suffix
    if ")" not in stem or "(" in stem:
        return None
    m = _LOST_PAREN.match(stem)
    if not m:
        return None
    token = m.group(1)
    tail = re.sub(r"[_\s]+", " ", stem[len(token):].replace(")", " ")).strip(" -")
    if not tail:
        return None
    return f"{token} ({tail}){suffix}", token


def _lost_paren_is_safe(old: str, new: str, token: str,
                        keys: dict[str, list[str]]) -> str | None:
    """``None`` when the repair is provably right, else the reason to keep the name.

    This rename **moves** ``report_key_of`` on purpose — the old key
    (``RT-SDL-25-047F1802``) was the bug, the job number having been welded into the
    report number by the missing ``(``. So the twin-identity invariant of
    :func:`_rename_is_safe` cannot apply here; two stricter ones replace it: the
    recovered key must be claimed by no other file (a rename must never merge two
    distinct reports), and a warning-free sibling carrying the same job in
    parentheses must exist to prove the shape.
    """
    if report_identity.identity_noise(new) is not None:
        return "yeni ad hele de kuyludur"
    if date_detector.filename_dates([new]) != date_detector.filename_dates([old]):
        return "fayl adi tarixi deyisir"
    if docx_reader.parse_filename_metadata(new)["report_no"] != token:
        return "Report No aparici token deyil"
    if keys.get(report_identity.report_key(token)):
        return "berpa olunan report_key artiq baskasinindir"
    job = _LOST_PAREN.match(Path(old).stem).group(2)
    prefix = token.rsplit("-", 1)[0] + "-"
    if not any(nm.startswith(prefix) and f"({job})" in nm
               for group in keys.values() for nm in group):
        return "temiz qardas fayl tapilmadi"
    return None


def find_lost_paren(input_dir: Path) -> list[dict]:
    """PDF names missing their opening ``(``, with the repair proved per file."""
    keys: dict[str, list[str]] = {}
    for path in _walk(input_dir):
        keys.setdefault(report_identity.report_key_of(path.name), []).append(path.name)

    rows: list[dict] = []
    for path in _walk(input_dir):
        if path.suffix.casefold() != ".pdf":
            continue
        if QUARANTINE_DIR in path.relative_to(input_dir).parts:
            continue
        proposal = lost_paren_name(path.name)
        if proposal is None:
            continue
        new, token = proposal
        # The file's own key must not count as the collision it is being moved off.
        others = {k: [n for n in v if n != path.name] for k, v in keys.items()}
        refused = _lost_paren_is_safe(path.name, new, token, others)
        rows.append({"path": path, "why": "itmis acan moterize", "new": new,
                     "decision": "adi deyisdi" if refused is None
                     else f"REDD: {refused}"})
    return rows


# The ``.docx`` partner of a repaired PDF carries the SAME export bug, only without
# the stray ``)`` to show it: ``RT-SDL-25-047F1802.docx`` beside the correctly exported
# ``RT-SDL-25-045.docx``/``RT-SDL-25-046.docx``. Repairing only the PDF would split a
# twin pair that used to agree (on a wrong key), so this pass finishes the job. The
# target is not inferred — it is the bare report number the clean siblings already use.
_REPAIRED_PDF = re.compile(r"^([A-Za-z0-9-]+) \(([A-Za-z]\w*) ")


def _has_clean_sibling_docx(names, token: str) -> bool:
    """True if the same report series already exports a bare ``<report-no>.docx``.

    ``RT-SDL-25-045.docx`` proves the shape for ``RT-SDL-25-047``; without such a
    sibling the bare name would be a guess and the file is kept as it is.
    """
    series = token.rsplit("-", 1)[0] + "-"
    return any(name.casefold().endswith(".docx")
               and name.startswith(series)
               and Path(name).stem != token
               and report_identity.identity_noise(name) is None
               and Path(name).stem == report_identity.leading_token(name)
               for name in names)


def find_twin_docx(input_dir: Path) -> list[dict]:
    """``<token><job>.docx`` files whose repaired PDF proves the name is ``<token>.docx``."""
    by_name = {p.name: p for p in _walk(input_dir)}
    rows: list[dict] = []
    for path in _walk(input_dir):
        if path.suffix.casefold() != ".pdf":
            continue
        m = _REPAIRED_PDF.match(path.stem)
        if not m:
            continue
        token, job = m.group(1), m.group(2)
        broken = by_name.get(f"{token}{job}.docx")
        if broken is None:
            continue
        new = f"{token}.docx"
        row = {"path": broken, "why": f"itmis acan moterize ({path.name} cutu)",
               "new": new, "decision": "adi deyisdi"}
        if f"{token}.docx" in by_name:
            row["decision"] = "REDD: hedef ad artiq movcuddur"
        elif report_identity.report_key_of(new) != report_identity.report_key_of(path.name):
            row["decision"] = "REDD: PDF cutu ile report_key uygun gelmir"
        elif date_detector.filename_dates([new]) != date_detector.filename_dates([broken.name]):
            row["decision"] = "REDD: fayl adi tarixi deyisir"
        elif not _has_clean_sibling_docx(by_name, token):
            row["decision"] = "REDD: temiz qardas .docx tapilmadi"
        rows.append(row)
    return rows


def rename(rows: list[dict], apply: bool) -> int:
    """Perform the accepted renames with ``os.replace``. Returns the count."""
    done = 0
    for row in rows:
        if row["new"] is None or row["decision"] != "adi deyisdi":
            continue
        target = row["path"].with_name(row["new"])
        if target.exists():
            row["decision"] = "REDD: hedef ad artiq movcuddur"
            continue
        if apply:
            row["path"].replace(target)
        done += 1
    return done


# --------------------------------------------------------------------------- #
# audits
# --------------------------------------------------------------------------- #
def write_prune_audit(out_dir: Path, rows: list[dict], moved: int, today: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"lan_dedup_{today}.md"
    lines = [
        f"# `-lan` dublikat auditi — {today}",
        "",
        "Hər cütün SHA-256-sı bu run-da **yenidən hesablanıb**. Silinmə yoxdur —",
        f"eyni olanlar `input/{PRUNED_DIR}/`-ə köçürülüb.",
        "",
        f"- yoxlanan `-lan` faylı: **{len(rows)}**",
        f"- SHA eyni (köçürüldü): **{moved}**",
        f"- SHA fərqli və ya əkizsiz (saxlanıldı): **{len(rows) - moved}**",
        "",
        "| # | fayl A (`-lan`) | fayl B (əkiz) | SHA-256 | qərar |",
        "|--:|---|---|---|---|",
    ]
    for i, row in enumerate(rows, 1):
        same = bool(row["sha_twin"]) and row["sha_twin"] == row["sha_lan"]
        digest = (row["sha_lan"] if same else
                  f"A:{row['sha_lan'][:16]}… B:{(row['sha_twin'][:16] or '—')}…")
        twin = row["twin"].as_posix() if row["twin"] else "—"
        lines.append(f"| {i} | `{row['lan'].as_posix()}` | `{twin}` "
                     f"| `{digest}` | {row['decision']} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_rename_audit(out_path: Path, rows: list[dict], today: str,
                       header: list[str] | None = None,
                       append: bool = False) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = list(header) if header is not None else [
        f"# PDF adi temizlenmesi — {today} — Tapsiriq 11 A2",
        "# Qayda: <aparici token><quyruq> -> <aparici token> (<quyruq>)",
        "# Menbe .docx ekizi YOXDUR (hamisi PDF-only SDLN) — ad aparici tokenden qurulub.",
        "# kohne_ad\tyeni_ad\tesas",
    ]
    for row in rows:
        lines.append(f"{row['path'].name}\t{row['new'] or '—'}"
                     f"\t{row['decision']} ({row['why']})")
    body = "\n".join(lines) + "\n"
    if append and out_path.exists():
        with open(out_path, "a", encoding="utf-8") as fh:
            fh.write("\n" + body)
    else:
        out_path.write_text(body, encoding="utf-8")
    return out_path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Retire -lan duplicates and clean noisy PDF names.")
    ap.add_argument("--input-dir", default=str(_ROOT / "input"))
    ap.add_argument("--output-dir", default=str(_ROOT / "output"))
    ap.add_argument("--rename-audit",
                    default=str(_ROOT / "_archive" / "output_backup"
                               / "2026-09-17_pre-task11" / "pdf_renames_{today}.txt"))
    ap.add_argument("--prune", action="store_true", help="run the -lan duplicate pass")
    ap.add_argument("--rename", action="store_true", help="run the noisy-name pass")
    ap.add_argument("--fix-lost-paren", action="store_true",
                    help="repair PDF names whose opening '(' was lost in the export")
    ap.add_argument("--fix-twin-docx", action="store_true",
                    help="repair the .docx partner of an already-repaired PDF")
    ap.add_argument("--from-audit", default=None,
                    help="scope the rename pass to the filenames listed in an "
                         "output/identity_warnings_<date>.md table")
    ap.add_argument("--apply", action="store_true",
                    help="perform the moves/renames (default is a dry run)")
    args = ap.parse_args(argv)

    if not (args.prune or args.rename or args.fix_lost_paren or args.fix_twin_docx):
        ap.error("nothing to do: pass --prune, --rename, --fix-lost-paren and/or --fix-twin-docx")

    today = _dt.date.today().isoformat()
    input_dir = Path(args.input_dir)
    mode = "APPLY" if args.apply else "DRY-RUN"

    if args.prune:
        rows = find_lan_pairs(input_dir)
        moved = prune(input_dir, rows, args.apply)
        audit = write_prune_audit(Path(args.output_dir), rows, moved, today)
        print(f"[prune/{mode}] {len(rows)} '-lan' file(s) checked, "
              f"{moved} byte-identical, {len(rows) - moved} kept -> {audit}")

    if args.rename:
        allowed = audit_names(Path(args.from_audit)) if args.from_audit else None
        if allowed is not None:
            print(f"[rename/{mode}] scoped to {len(allowed)} name(s) "
                  f"from {args.from_audit}")
        rows = find_renames(input_dir, allowed)
        done = rename(rows, args.apply)
        audit = write_rename_audit(
            Path(args.rename_audit.format(today=today)), rows, today)
        print(f"[rename/{mode}] {len(rows)} noisy name(s), "
              f"{done} renamed, {len(rows) - done} kept -> {audit}")

    if args.fix_lost_paren:
        rows = find_lost_paren(input_dir)
        done = rename(rows, args.apply)
        audit = write_rename_audit(
            Path(args.rename_audit.format(today=today)), rows, today,
            header=[
                f"# Itmis acan moterize — {today} — Tapsiriq 11 A2 (operator tesdiqi)",
                "# Qayda: <report no><job>) -> <report no> (<job> <quyruq>)",
                "# Subut: eyni partiyada RT-SDL-25-046(F1802)... duzgun yazilib.",
                "# DIQQET: bu pass report_key-i QESDEN deyisir — kohne acar sehv idi.",
                "# kohne_ad\tyeni_ad\tesas",
            ],
            append=True)
        print(f"[lost-paren/{mode}] {len(rows)} broken name(s), "
              f"{done} renamed, {len(rows) - done} kept -> {audit}")

    if args.fix_twin_docx:
        rows = find_twin_docx(input_dir)
        done = rename(rows, args.apply)
        audit = write_rename_audit(
            Path(args.rename_audit.format(today=today)), rows, today,
            header=[
                f"# Itmis acan moterize — .docx cutu — {today} — Tapsiriq 11 A2",
                "# Qayda: <report no><job>.docx -> <report no>.docx",
                "# Subut: RT-SDL-25-045.docx / RT-SDL-25-046.docx duzgun ixrac olunub.",
                "# Sebeb: PDF-i tek duzeltmek cutu ayirirdi — report_key yeniden uygunlasir.",
                "# kohne_ad	yeni_ad	esas",
            ],
            append=True)
        print(f"[twin-docx/{mode}] {len(rows)} partner(s), "
              f"{done} renamed, {len(rows) - done} kept -> {audit}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
