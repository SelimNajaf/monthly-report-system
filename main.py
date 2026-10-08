#!/usr/bin/env python
"""Global automation entry-point for the Monthly Report pipeline.

Run with no arguments to process everything discovered:

    python main.py

Or scope a run to a single month / method / client (the same tokens the portal
uploader and the GUI dropdowns use):

    python main.py --month JUN_2025 --method UT
    python main.py --month 2025-06 --client UBOC

Pure orchestrator — every stage lives in its own cohesive module:

    pre_processor.archive_input_pdfs   STAGE -1: .pdf -> input/PDF_ARCHIVE/ (read in place)
    pre_processor.sort_input_files     STAGE  0: deep-sort loose .docx into method dirs
    pre_processor.prune_*/purge_*      STAGE 0.5: self-healing housekeeping (--no-clean skips)
    docx_reader.read_many              STAGE  1: parse every report once, in parallel
    pre_processor.discover_groups      group by (month, client), quarantine
    document_aggregator.build_monthly_report -> pdf_renderer + json_exporter per group

With no filters it is fully unattended and processes every group it discovers.
When a filter is given, conversion is narrowed by method and only in-scope groups
are compiled; everything else is left untouched. Housekeeping (dedup, quarantine
purge, UnSorted prune) is global — never narrowed by a filter — and moves
redundant files to input/_PRUNED/ rather than deleting them.

Runs are INCREMENTAL end to end. STAGE 0-LAN skips share files whose (size, mtime)
fingerprint is already in the ingestion registry, STAGE 1 reuses the parse cache for
unchanged bytes, and a group whose sources all sat still keeps its existing PDF +
sidecar instead of re-rendering them, logging ``[Incremental Skip] <path> already up
to date.``. --force-rebuild re-renders regardless.

They are also DETERMINISTIC: re-running over an unchanged corpus reports the same
group count and touches no file. Only the stages before group discovery move anything
in ``input/``, so the count printed by one run is the count the next run computes —
STAGE 3 omits rows and names them, but never quarantines their sources. Compiled
output is retired for retired/low-volume clients and for groups that render zero rows,
EXCEPT where .upload_state.json has the artifact on record: a filed deliverable is
never deleted by a compile run.

Every stage narrates its progress as ``[Stage N: Name] [i/total] ...``, flushed
line by line so a long run is visibly moving rather than apparently hung. Turn the
rate down (or off) with ``performance.progress_every`` in settings.yaml. See
CLI_MANUAL.md for the full flag reference.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
import time
from pathlib import Path

# Make the src/ package importable when run as a plain script.
_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT / "src"))

from monthly_report import (config, coverage_audit, docx_reader, document_aggregator,
                            json_exporter, parse_cache, pdf_crosscheck,
                            pdf_renderer, pre_processor, report_identity,
                            report_no_mismatch, retest_tracker, upload_ledger)
from monthly_report.console import (enable_utf8_console, progress_printer,
                                    safe_print)
from monthly_report.gui.services.catalog import _parse_stem
from monthly_report.method_registry import (client_volume_ok, detect_method,
                                            is_active_client, is_excluded_client,
                                            meets_volume)
from monthly_report.naming import (MONTH_ABBR, PDF_ARCHIVE_DIR, PRUNED_DIR,
                                   QUARANTINE_DIR, UNSORTED_DIR, default_output)
from monthly_report.pre_processor import Scope, quarantine, warn
from monthly_report.services import network_ingestion, report_export
from monthly_report.translator import Translator, load_dictionary

#: ``"JUN"`` -> ``6``. The reverse of naming.MONTH_ABBR, so a ``JUN_2025`` token
#: (the uploader/GUI form) can be turned into the ``2025-06`` key discover_groups
#: produces. Built once here rather than scanned per call.
_MONTH_NUM = {abbr: num for num, abbr in MONTH_ABBR.items()}

#: Stage label for the render loop's live counter. Its siblings live next to the
#: stages they name (pre_processor.STAGE_*, docx_reader.STAGE_PARSE); STAGE 3 is
#: the one loop that runs here, in the orchestrator, so its label does too.
STAGE_RENDER = "Stage 3: Rendering"

#: How often a stage prints its ``[i/N]`` line when settings say nothing: every
#: item. A thousand-report corpus can turn that down with
#: ``performance.progress_every`` rather than losing the counter entirely.
DEFAULT_PROGRESS_EVERY = 1

#: The live upload ledger, CONSULTED and never written by this pipeline: a compile
#: run has no authority to delete a deliverable that has been filed on the portal
#: (see _retire_artifacts). The dry-run ledger is deliberately NOT honoured — it
#: records simulated submissions, and letting a simulation pin a real file would be
#: a way to make stale output permanently undeletable.
LEDGER_PATH = _ROOT / upload_ledger.LIVE_LEDGER_NAME


def _display_path(path: Path) -> str:
    """``output/UBOC/report.pdf`` — the path as the operator thinks of it.

    ``output_dir`` resolves to an absolute path, and a counter line carrying
    ``C:/Users/.../Monthly-Report-Auto/output/...`` buries the part that matters.
    An output written outside the project (a configured absolute ``output_dir``)
    keeps its full path, because there the whole path is the information.
    """
    try:
        return path.resolve().relative_to(_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _progress_every(performance: dict) -> int:
    """Read ``performance.progress_every``, tolerating a junk value.

    A malformed number must not stop a run over something as cosmetic as how
    often a counter prints, so anything unparseable falls back to the default.
    A value of 0 (or below) switches the counters off entirely — see
    :func:`console.progress_printer`.
    """
    try:
        return int(performance.get("progress_every", DEFAULT_PROGRESS_EVERY))
    except (TypeError, ValueError):
        return DEFAULT_PROGRESS_EVERY


def _retire_artifacts(pdf_path: Path, protected: frozenset[str]) -> list[str]:
    """Delete a compiled PDF + its JSON sidecar, unless the upload ledger holds it.

    The SINGLE deletion seam for both stale-output sweeps, so a rule added to one can
    never be missing from the other. Returns the filenames actually removed.

    A ledger-recorded artifact is KEPT, and said so out loud: it was filed on the
    E-Keyfiyyet portal (or may have been — see upload_ledger.protected_keys), and a
    compile run has no authority to destroy a filed deliverable because a client
    dipped under a volume floor or a month's sources were all filtered. Both halves
    are kept or neither: the sidecar is what upload_ledger.hash_report identifies the
    report BY, so a PDF without it can no longer even be re-decided by the uploader.
    """
    if upload_ledger.ledger_key(pdf_path, _ROOT) in protected:
        safe_print(f"    retained (uploaded): {pdf_path.name} — recorded in "
                   f"{upload_ledger.LIVE_LEDGER_NAME}, not deleted")
        return []
    removed: list[str] = []
    for art in (pdf_path, pdf_path.with_suffix(".json")):
        if art.exists():
            art.unlink()
            removed.append(art.name)
    return removed


def _purge_excluded_client_outputs(settings, stats,
                                   protected: frozenset[str]) -> list[str]:
    """Delete compiled artifacts whose client is no longer admitted, returning names.

    The sweep counterpart to the empty-group stale-cleanup below: a discovered group
    for a retired/inactive client (or one now dropped for low corpus volume) never
    reaches the compile loop, so its OLD PDF+JSON — produced before the client was
    blacklisted or the volume floor set — would otherwise linger in output/ and still
    upload / show in the audit. Here every sidecar whose filename client token
    resolves to an inactive/excluded client, or one failing the corpus-volume rule
    (``stats``), has its ``.pdf`` + ``.json`` removed — unless the upload ledger
    holds it (see :func:`_retire_artifacts`). Filename token == client code
    (see naming.default_output); an untokened/legacy name is skipped.
    """
    output_dir = Path(settings.output_dir)
    removed: list[str] = []
    if not output_dir.is_dir():
        return removed
    if not stats:
        # No client resolved anywhere in the corpus: input/ is empty or unreadable, or
        # a sync wiped it. That is a BROKEN run, not the retirement of every client —
        # and client_volume_ok answers False for EVERY code against an empty snapshot
        # (method_registry.client_volume_ok) whenever the floor is positive, so
        # sweeping here would delete the whole of output/. The `if not groups: return`
        # bail-out below comes too late to help: this sweep runs before it.
        return removed
    for sidecar in sorted(output_dir.rglob("compiled_monthly_report_*.json")):
        parsed = _parse_stem(sidecar.stem)
        if not parsed:
            continue
        code, _month = parsed
        if not code:
            continue
        if (is_excluded_client(code, settings)
                or not is_active_client(code, settings)
                or not client_volume_ok(code, stats, settings)):
            removed.extend(_retire_artifacts(sidecar.with_suffix(".pdf"), protected))
    return removed


def _written_report_no(src) -> str:
    """The Report № a file's NAME will put in the monthly document.

    The filename half of :func:`report_identity.resolve_report_no`, on its own, so the
    identity warning can show the operator the exact string that will ship.
    """
    meta = docx_reader.parse_filename_metadata(src)
    return report_identity.squash(meta.get("report_no") or "").replace(" ", "")


def _write_identity_audit(settings, noisy) -> Path | None:
    """Write ``output/identity_warnings_<today>.md`` for noisy PDF file names.

    The filename is authoritative for a Report № (``report_identity.resolve_report_no``),
    so a PDF exported as ``KF-FC-25-07.docx.pdf`` ships ``KF-FC-25-07.docx`` into the
    monthly document. Nothing here repairs that: the tail cannot be stripped without
    guessing, and the corpus proves the guess would be wrong — ``U-UT-25-003rej`` is a
    real report number, ``UT-U-25-003 rej`` is a noisy name for ``UT-U-25-003``, and the
    two are indistinguishable by shape. So the row ships as written and the operator
    renames the file, which is the only place the fix belongs.

    ``noisy`` is ``[(path, reason)]``. Returns the path written, or ``None`` when every
    name was clean.
    """
    if not noisy:
        return None
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    path = output_dir / f"identity_warnings_{today}.md"
    lines = [
        f"# Fayl adı — Report № xəbərdarlığı — {today}",
        "",
        f"**{len(noisy)} PDF-in adı** aparıcı hesabat nömrəsi token-inə təmiz uyğun gəlmir. "
        f"Fayl adı Report № üçün səlahiyyətli mənbədir, ona görə aşağıdakı sətirlər aylıq "
        f"sənədə **`Yazılan Report №` sütunundakı kimi** düşür.",
        "",
        "Sistem adı **təmizləmir**: `U-UT-25-003rej` həqiqi hesabat nömrəsidir, "
        "`UT-U-25-003 rej` isə `UT-U-25-003`-ün küylü adıdır — forma ilə fərqləndirmək mümkün "
        "deyil. Düzgün həll: **`input/PDF_ARCHIVE/`-də faylın adını dəyiş**, sonra bu qrupu "
        "yenidən compile et.",
        "",
        "| # | Fayl | Səbəb | Yazılan Report № | Aparıcı token |",
        "|--:|---|---|---|---|",
    ]
    for i, (src, why) in enumerate(noisy, 1):
        lines.append(f"| {i} | `{Path(src).name}` | {why} | `{_written_report_no(src)}` | "
                     f"`{report_identity.leading_token(Path(src).name)}` |")
    lines += ["", "---", "",
              "Əhatə: bu yoxlama **PDF mənbələrə** tətbiq olunur — ADR-003-dən sonra Report № "
              "onların adından gəlir. Doğma `.docx` adı kurasiya olunmuş mənbədir və burada "
              "yoxlanmır.", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_mismatch_audit(settings, mismatches, cache) -> Path | None:
    """Write ``output/report_no_mismatch_<today>.md`` — name/body serial mismatches.

    Same shape as the identity audit. Every file whose filename serial differs from
    its in-body ``Report No`` serial (``report_no_mismatch``), with the evidence an
    operator needs to fix the source on the LAN. Nothing is renamed or re-numbered.
    Returns the path written, or ``None`` when there is nothing to list.
    """
    if not mismatches:
        return None
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    path = output_dir / f"report_no_mismatch_{today}.md"
    blocking = report_no_mismatch.block_enabled(settings)
    copies = sum(1 for m in mismatches if m.is_copy)
    input_dir = Path(settings.input_dir)
    lines = [
        f"# Fayl adı ≠ içəridəki Report № — {today}",
        "",
        f"**{len(mismatches)} faylda** fayl adındakı seriya (`-YY-NNN`) sənədin içindəki "
        f"`Report No` seriyasından fərqlidir. Fayl adı Report № üçün səlahiyyətli "
        f"mənbədir, ona görə sətir aylıq sənədə **addakı nömrə ilə** düşür.",
        "",
        "Sistem faylı, adı və nömrəni **dəyişmir**. Düzgün həll: **mənbəni LAN-da "
        "düzəlt**, sonra yenidən compile et.",
        "",
        f"**Surət** ({copies}) — cədvəlləri başqa faylla eynidir və o fayl içəridəki "
        f"nömrə ilə adlanır: eyni yoxlama iki nömrə ilə çap olunur. "
        f"`filtering.block_mismatched_report_no: true` olanda yalnız surətlər sənədə "
        f"düşmür. Bu run: **{'true — surətlər sənədə düşmür' if blocking else 'false — heç nə bloklanmır'}**.",
        "",
        "| # | Fayl | Addakı № | İçəridəki № | Tarix | Tikişlər | Sinif | Eyni cədvəl |",
        "|--:|---|---|---|---|---|---|---|",
    ]
    for i, m in enumerate(mismatches, 1):
        try:
            where = m.path.relative_to(input_dir).as_posix()
        except ValueError:
            where = m.path.name
        welds = report_no_mismatch.weld_ids(cache.get(m.path),
                                            detect_method(m.name_no, settings))
        lines.append(
            f"| {i} | `{where}` | `{m.name_no}` | `{m.body_no}` | {m.date or '—'} | "
            f"{', '.join(welds) or '—'} | {'surət' if m.is_copy else 'surət deyil'} | "
            f"{', '.join(f'`{p.name}`' for p in m.copy_of) or '—'} |")
    lines += ["", "---", "",
              "Əhatə: bu run-ın oxuduğu mənbələr. `--month/--method/--client` ilə "
              "məhdud run yalnız öz mənbələrini yazır.", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _note_range_verdicts(report, settings, tag: str, sink: list) -> None:
    """Print one ``[range-verdict]`` line per Yarasız report inside a Yararlı range.

    ``presentation.range_mode: by_number`` prints a multi-number line Yararlı as
    soon as one number in it ended Yararlı, so a still-rejected report can sit
    under it. It is named here, and collected into ``sink`` for the run-end audit.
    Prints nothing on the default strict mode.
    """
    for report_no, label in document_aggregator.range_verdict_notes(report, settings):
        sink.append((tag, report_no, label))
        safe_print(document_aggregator.format_range_verdict(tag, report_no, label))


def _write_range_verdict_audit(settings, notes) -> Path | None:
    """Write ``output/range_verdict_<today>.md`` — Yarasız reports inside a Yararlı range.

    Same shape as the mismatch audit. ``notes`` is ``[(group tag, report №, PDF
    line)]``, gathered by :func:`_note_range_verdicts`; it is only ever non-empty
    under ``presentation.range_mode: by_number``. Returns the path written, or
    ``None`` when there is nothing to list — then no file is written.

    The name does not match ``compiled_monthly_report_*.json``, so the uploader's
    sidecar sweep (``uploader._report_sidecars``) and the ledger never see it.
    """
    if not notes:
        return None
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    path = output_dir / f"range_verdict_{today}.md"
    lines = [
        f"# Yararlı diapazonda çap olunan Yarasız hesabatlar — {today}",
        "",
        f"**{len(notes)} hesabatın** son nəticəsi Yarasız-dır, amma PDF-də "
        f"\"Yararlı\" yazılmış diapazon sətrinin içində çap olunub "
        f"(`presentation.range_mode: by_number`). Diapazonda ən azı bir Yararlı "
        f"nömrə olanda sətir Yararlı yazılır.",
        "",
        "JSON sidecar hər hesabatı **öz nəticəsi ilə** saxlayır — bu siyahı yalnız "
        "PDF görünüşünü izah edir. Heç bir fayl, ad və nömrə dəyişmir.",
        "",
        "| # | Qrup | Report № | PDF sətri |",
        "|--:|---|---|---|",
    ]
    for i, (tag, report_no, label) in enumerate(notes, 1):
        lines.append(f"| {i} | {tag} | `{report_no}` | `{label}` |")
    lines += ["", "---", "",
              "Əhatə: bu run-ın compile etdiyi və yenidən istifadə etdiyi qruplar. "
              "`--month/--method/--client` ilə məhdud run yalnız öz qruplarını yazır.", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_date_repair_audit(settings, repairs) -> Path | None:
    """Write ``output/date_repair_audit_<today>.md`` for the run's repaired dates.

    A repaired date is a date NO human typed in full: KB-1 took the year off the
    report number, KB-1b took the month and year off the archived PDF original's
    filename. Both are reconstructions, and a reconstruction that is wrong files a
    report into the wrong month silently — so every one of them is written down with
    the evidence it was built from, for an operator to check against the source.

    The DAY DIFFERS column is the one to read first. KB-1b keeps the cell's day (it
    is what the inspector typed for this report) and imports only the month/year from
    the filename; where those two disagree about the day, the filename is describing
    the export/job rather than this weld. The month is unaffected — the disagreement
    never moves a report between months — but the exact day is worth a glance.

    Returns the path written, or ``None`` when the run repaired nothing.
    """
    if not repairs:
        return None
    output_dir = Path(settings.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    path = output_dir / f"date_repair_audit_{today}.md"
    differing = [r for r in repairs if r[4].day_delta not in (None, 0)]
    lines = [
        f"# Date repair audit — {today}",
        "",
        f"**{len(repairs)} report(s)** were compiled with a RECONSTRUCTED inspection "
        f"date. Each row names the evidence; none of these dates was typed in full by "
        f"the inspector.",
        "",
        "- `serial` — KB-1: the cell held a day and a month, the year came from the "
        "report number's `-<YY>-`.",
        "- `filename` — KB-1b: the cell was cut past its month, so the month and year "
        "came from the PDF twin's name. The day is the cell's when the cell still "
        "showed one.",
        "",
        f"**{len(differing)} row(s) have a day disagreement** (marked **!**): the cell's "
        f"day and the PDF twin's day are not the same. The month is identical in every "
        f"one of them, so the report's month is not in doubt — only the exact day is.",
        "",
        "`twin-truncated` in the DAY FROM column is the third case: the cell held a "
        "single digit, the twin's day held two and began with it (`'1'` vs `10`), so "
        "the cut had reached into the day itself and the twin supplied the digit it "
        "took. Those rows carry no day disagreement — the day IS the twin's.",
        "",
        "| # | File | Report № | Raw `Date:` cell | PDF twin date | Final date | Source"
        " | Day from | Day differs |",
        "|--:|---|---|---|---|---|---|---|---|",
    ]
    for i, (name, report_no, raw, date, how) in enumerate(repairs, 1):
        twin = how.filename_date.isoformat() if how.filename_date else "—"
        if how.day_delta in (None, 0):
            delta = "—" if how.day_delta is None else "no"
        else:
            delta = f"**! {how.day_delta:+d}d**"
        lines.append(f"| {i} | `{name}` | `{report_no}` | `{raw!r}` | {twin} | "
                     f"{date.isoformat()} | {how.source} | {how.day_source} | {delta} |")
    lines += ["", "---", "",
              "- Correct a wrong row at its source: fix the `Date:` cell in the "
              "`.docx` and re-run; the repair then never fires for that file.",
              "- `output/` is git-ignored — this file is machine-local, like the "
              "documents it names.", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _config_stamp(settings) -> float:
    """Newest mtime among the inputs that shape EVERY compiled report.

    A group's PDF is a function of more than its own source files: ``settings.yaml``
    carries the client registry, volume floors, title and doc-number patterns, and the
    translations file decides every rendered Azerbaijani string. Either one edited
    after a PDF was written makes that PDF stale no matter how quiet its sources were,
    so the incremental skip compares against this stamp. Unreadable/missing files
    contribute nothing — a stamp of ``0.0`` simply never blocks a skip.
    """
    newest = 0.0
    for candidate in (_ROOT / "config" / "settings.yaml",
                      Path(settings.translations_path)):
        try:
            newest = max(newest, candidate.stat().st_mtime)
        except OSError:
            continue
    return newest


def _dirty_clients(members, changed_names) -> set[str]:
    """Client codes owning at least one new/changed source file.

    Deliberately coarser than the ``(month, client)`` group key. A retest compiled
    this month can pull its ORIGINAL out of an earlier month
    (``document_aggregator`` cross-month parents), so a file landing in June can
    change May's PDF for the same client. Widening the blast radius to the whole
    client keeps that correct; it costs at most a few extra renders.

    It used to be keyed ``(method, client)``. Under ADR-004 a document spans every
    method of a client-month, so the method half named nothing a group could be
    looked up by; the client alone gives the identical guarantee.
    """
    dirty: set[str] = set()
    if not changed_names:
        return dirty
    for (_month, client), paths in members.items():
        if any(p.name.casefold() in changed_names for p in paths):
            dirty.add(client)
    return dirty


def _group_is_current(out_path: Path, client: str, *,
                      dirty: set[str], config_stamp: float,
                      incremental: bool) -> bool:
    """True when the group's compiled PDF + sidecar can stand as they are.

    Every condition must hold: the feature is on, no report for this client is new or
    changed, BOTH artifacts exist, and neither ``settings.yaml`` nor the translations
    file has been edited since the PDF was written. Anything unknown or unreadable
    answers False — a needless re-render costs a second, a wrongly reused PDF ships
    stale figures to the portal.
    """
    if not incremental or client in dirty:
        return False
    json_path = out_path.with_suffix(".json")
    try:
        if not (out_path.is_file() and json_path.is_file()):
            return False
        return out_path.stat().st_mtime >= config_stamp
    except OSError:
        return False


def _normalize_month(token: str) -> str:
    """Canonicalize a month token to ``YYYY-MM``.

    Accepts the uploader/GUI form ``JUN_2025`` and ``JUN 2025``, the pipeline's own
    ``2025-06`` / ``2025-6``, and the short ``YY-MM`` LAN-share form ``26-08``
    (2-digit year, assumed 20xx). Raises ``ValueError`` on anything else, so a typo
    fails loudly at the boundary instead of silently matching no group.
    """
    text = token.strip()
    iso = re.match(r"^(\d{4})-(\d{1,2})$", text)
    if iso:
        year, month = int(iso.group(1)), int(iso.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    short = re.match(r"^(\d{2})-(\d{1,2})$", text)   # 26-08 -> 2026-08
    if short:
        year, month = 2000 + int(short.group(1)), int(short.group(2))
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}"
    abbr_form = re.match(r"^([A-Za-z]{3})[_ ](\d{4})$", text)
    if abbr_form:
        month = _MONTH_NUM.get(abbr_form.group(1).upper())
        if month:
            return f"{int(abbr_form.group(2)):04d}-{month:02d}"
    raise ValueError(
        f"unrecognized --month {token!r}; expected e.g. JUN_2025, 2025-06 or 26-06")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="main.py",
        description="Compile monthly NDT reports. With no filters, processes "
                    "every discovered group; filters scope the run.")
    p.add_argument("--month", metavar="MON_YYYY",
                   help="Only this month (e.g. JUN_2025, 2025-06 or 26-06).")
    p.add_argument("--date", dest="month", metavar="YY-MM",
                   help="Alias of --month (accepts the short 26-08 form too).")
    p.add_argument("--method", metavar="TOKEN",
                   help="Only this NDT method token (e.g. UT, MT).")
    p.add_argument("--client", metavar="CODE",
                   help="Only this client code (e.g. UBOC).")
    p.add_argument("--no-clean", action="store_true",
                   help="Skip housekeeping — leave the input/ tree exactly as found "
                        "(no dedup, no quarantine purge, no UnSorted prune).")
    p.add_argument("--force-rebuild", action="store_true",
                   help="Re-render every in-scope group even when nothing changed "
                        "(disables the incremental compile skip).")
    return p


def _build_scope(args: argparse.Namespace) -> Scope:
    """Turn parsed CLI flags into the pipeline's :class:`Scope`.

    Exits 2 on a malformed ``--month`` — argparse's own exit code for a bad
    argument, so the failure reads the same whether argparse or this raised it.
    """
    month = None
    if args.month:
        try:
            month = _normalize_month(args.month)
        except ValueError as exc:
            build_parser().error(str(exc))   # prints usage, raises SystemExit(2)
    return Scope(
        month=month,
        method=(args.method or "").upper() or None,
        client=(args.client or "").upper() or None)


def main(argv: list[str] | None = None) -> int:
    enable_utf8_console()   # report names carry Azerbaijani glyphs — see console.py
    args = build_parser().parse_args(argv)
    scope = _build_scope(args)
    do_clean = not args.no_clean
    settings = config.load_settings(str(_ROOT / "config" / "settings.yaml"))
    dictionary = load_dictionary(settings.translations_path)
    # Read once, up here: the first stage that narrates itself is STAGE -1, long
    # before the parse-cache settings are needed further down.
    performance = settings.raw.get("performance", {}) or {}
    progress_every = _progress_every(performance)
    # audit.coverage_report (default off): every source file gets one outcome,
    # written to output/coverage_<today>.md with one stdout line at run end.
    coverage = (coverage_audit.Collector(settings)
                if coverage_audit.is_enabled(settings) else None)

    safe_print("=" * 70)
    safe_print("  MONTHLY REPORT ORCHESTRATOR")
    safe_print(f"  Input root: {settings.input_dir}")
    if scope.is_empty:
        safe_print("  Scope: every discovered group (unattended)")
    else:
        safe_print(f"  Scope: month={scope.month or 'ALL'} "
                   f"method={scope.method or 'ALL'} client={scope.client or 'ALL'}")
    if not do_clean:
        safe_print("  Housekeeping: skipped (--no-clean)")

    # STAGE 0-LAN — sync fresh reports off the LAN network share into input/UnSorted/
    # BEFORE any local processing. Read-only on the share (copy, never move/edit); an
    # offline share degrades to a warning and the run proceeds on local files; an
    # unconfigured share is a silent no-op. Wrapped so an ingestion glitch can never
    # stop a local compile.
    sync_month = scope.month or settings.target_month
    #: Case-folded filenames that are new or changed in THIS run — the input to the
    #: incremental compile skip below. Fed from the share sync here and from the parse
    #: cache's misses after STAGE 1.
    changed_names: set[str] = set()
    try:
        sync = network_ingestion.sync_from_lan(settings, sync_month, log=safe_print)
    except Exception as exc:   # defensive: local run must survive any LAN failure
        safe_print(f"  [LAN Sync] skipped (unexpected {type(exc).__name__}: {exc}) "
                   "— proceeding with local input/ files.")
    else:
        changed_names.update(n.casefold() for n in sync.staged)
        changed_names.update(n.casefold() for n in sync.modified)
        if sync.roots_scanned and sync.unreachable_all:
            safe_print("  [LAN Sync] Network share unreachable, proceeding with "
                       "local input/ files.")
        elif sync.roots_scanned:
            dupes = (f", {sync.skipped_dupes} already present"
                     if sync.skipped_dupes else "")
            safe_print(f"  [LAN Sync] Scanned {sync.share_label} "
                       f"({sync.roots_reachable}/{sync.roots_scanned} root(s) reachable). "
                       f"Staged {sync.staged_count} new report(s) for {sync_month}"
                       f"{dupes} -> input/{UNSORTED_DIR}/")
            # The O(1) accounting: how many candidates the registry answered for
            # without touching the network, and what it cost.
            refreshed = (f" {sync.modified_count} changed report(s) refreshed."
                         if sync.modified_count else "")
            safe_print(f"  [LAN Sync] {sync.checked:,} files checked in "
                       f"{sync.elapsed_s:.2f}s: {sync.unchanged:,} unchanged (skipped), "
                       f"{sync.staged_count} new report(s) staged.{refreshed}")

    # STAGE -1 — pre-archive: any .pdf dropped under input/ is moved to
    # input/PDF_ARCHIVE/, where STAGE 1 reads it directly. No conversion (ADR-003).
    pdfs = pre_processor.archive_input_pdfs(settings, method=scope.method)
    found = len(pdfs["archived"]) + len(pdfs["skipped"]) + len(pdfs["failed"])
    if found:
        safe_print(f"  PDFs: {found} found — {len(pdfs['archived'])} archived "
              f"-> input/{PDF_ARCHIVE_DIR}/, "
              f"{len(pdfs['skipped'])} skipped (already archived)")
        if pdfs["failed"]:
            safe_print(f"  PDFs: {len(pdfs['failed'])} failed to archive (left in place): "
                  f"{[n for n, _ in pdfs['failed'][:3]]}")
    else:
        safe_print("  PDFs: none found")

    # STAGE 0 — pre-process: deep-sort loose .docx (any depth) into method folders.
    sort = pre_processor.sort_input_files(settings, progress_every=progress_every)
    if sort["moved"]:
        by_folder: dict[str, int] = {}
        for _name, folder in sort["moved"]:
            by_folder[folder] = by_folder.get(folder, 0) + 1
        safe_print(f"  Sorted {len(sort['moved'])} loose file(s): " + ", ".join(
            f"{n} -> input/{f}/" for f, n in sorted(by_folder.items())))
    else:
        safe_print("  Sorted loose files: none (already organized)")
    if coverage is not None:
        coverage.add_unmatched(sort["unmatched"])
        coverage.add_quarantined((Path(r).name, "ASR/ARS excluded")
                                 for r in sort.get("quarantined") or ())
    if sort.get("quarantined"):
        safe_print(f"  ASR/ARS quarantined on sort: {len(sort['quarantined'])} "
              f"-> input/{QUARANTINE_DIR}/")
    if sort["unmatched"]:
        preview = sort["unmatched"][:5]
        more = "" if len(sort["unmatched"]) <= 5 else f" (+{len(sort['unmatched']) - 5} more)"
        safe_print(f"  Unmatched (left in place): {len(sort['unmatched'])} -> {preview}{more}")
    if sort["conflict"]:
        safe_print(f"  Skipped (name conflict): {sort['conflict']}")

    # STAGE 0.5 — housekeeping: recoverable, content-verified cleanup of the input
    # tree. Clear UnSorted redundancies first, then dedup what remains in the method
    # folders. Global (not scoped): correct cleanup under any filter. See --no-clean.
    if do_clean:
        unsorted_pruned = pre_processor.prune_unsorted_redundant(settings)
        if unsorted_pruned:
            safe_print(f"  Pruned {len(unsorted_pruned)} redundant UnSorted file(s) "
                  f"already settled -> input/{PRUNED_DIR}/")
        dupes_pruned = pre_processor.prune_duplicate_docx(settings)
        if dupes_pruned:
            safe_print(f"  Pruned {len(dupes_pruned)} byte-identical duplicate .docx "
                  f"(kept cleanest name) -> input/{PRUNED_DIR}/")

    # STAGE 1 — parse every report ONCE, in parallel across CPU cores. The result
    # cache is reused by discover_groups and every build_monthly_report, so no file
    # is ever parsed twice WITHIN a run (the old pipeline parsed each 2-3x).
    #
    # ACROSS runs, a persistent content-hash parse cache skips re-parsing a .docx whose
    # bytes are unchanged since a previous run (parse_cache). This is what keeps a
    # recurring monthly run O(new/changed files) instead of O(the whole history sitting
    # in input/) — every historical report stays on disk (cross-month retest parents
    # need it) but is parsed only once. --no-clean leaves the cache untouched; a clean
    # run GCs entries for files that have since left input/.
    input_dir = Path(settings.input_dir)
    files = [p for p in sorted(input_dir.rglob("*.docx"))
             if not p.name.startswith("~$")
             and p.relative_to(input_dir).parts[0].casefold() not in pre_processor.SETTLED_DIRS]
    # Archived PDFs are read from PDF_ARCHIVE/ directly (ADR-003). The rglob above
    # deliberately still skips that folder — pdf_sources is the one reader of it,
    # takes only *.pdf, and drops any PDF whose report already exists as a curated
    # .docx, so a hand-checked document is never displaced by its own source.
    files += pre_processor.pdf_sources(settings, method=scope.method)
    if coverage is not None:
        coverage.add_parsed(files)
    use_cache = bool(performance.get("parse_cache", True))
    cache_dir = _ROOT / str(performance.get("parse_cache_dir",
                                            parse_cache.DEFAULT_CACHE_DIRNAME))
    safe_print(f"  Parsing {len(files)} report(s) across {os.cpu_count()} core(s)...")
    t0 = time.perf_counter()
    if use_cache:
        cache, read_errors, textless = parse_cache.read_many_cached(
            files, cache_dir, progress_every=progress_every)
        stats = parse_cache.read_many_cached.last_stats
    else:
        cache, read_errors, textless = docx_reader.read_many(
            files, progress_every=progress_every)
        stats = None
    elapsed = time.perf_counter() - t0
    safe_print(f"  Parsed {len(cache)} file(s) in {elapsed:.1f}s "
          f"({len(files) / elapsed:.0f} files/s)" if elapsed > 0 else
          f"  Parsed {len(cache)} file(s)")
    # A file parsed fresh is one whose BYTES are new or changed since the last run —
    # the second and broader source of "what moved?", covering reports dropped into
    # input/ by hand as well as anything the share sync staged. With the cache off
    # there is no such signal, so `incremental` below turns itself off and every
    # group re-renders, exactly as it always did.
    incremental = (bool(performance.get("incremental_compile", True))
                   and not args.force_rebuild and stats is not None)
    if stats:
        changed_names.update(p.name.casefold() for p in stats.get("miss_paths", ()))
        safe_print(f"  Parse cache: {stats['hits']} hit(s), {stats['misses']} "
                   f"parsed fresh (unchanged files reused from a previous run)")
        # Clean runs retire cache entries for files that have left input/ — keeps the
        # store bounded to the live corpus. Skipped under --no-clean, like every other
        # housekeeping pass.
        if do_clean:
            reclaimed = stats["store"].gc(stats["live_digests"])
            if reclaimed:
                safe_print(f"  Parse cache: reclaimed {reclaimed} stale entry(ies)")

    quarantined: list[tuple[str, str]] = []
    for path, msg in read_errors.items():
        if quarantine(input_dir, path):
            quarantined.append((path.name, f"unreadable ({msg})"))
            safe_print(f"  [quarantine] {path.name}: unreadable -> input/{QUARANTINE_DIR}/")

    # PDF cross-check (ADR-003). Two independent readers parse every PDF; where they
    # disagree on the verdict nothing here picks a winner — the report goes to the
    # same quarantine every other unreadable case goes to, and both answers are
    # written to an audit file so the operator settles it with the evidence in hand.
    # Measured: 19 of 630 reach the operator, and zero wrong verdicts get past the
    # agreement.
    disagreements = list(getattr(parse_cache.read_many_cached, "last_disagreements", ())
                         if use_cache else
                         getattr(docx_reader.read_many, "last_disagreements", ()))
    audit = pdf_crosscheck.write_audit(settings.output_dir, disagreements)
    if audit is not None:
        safe_print(f"  PDF cross-check: {len(disagreements)} disagreement(s) "
                   f"audited -> {audit.name}")
    for path in {Path(d.path) for d in disagreements if d.blocking}:
        fields = sorted({d.field for d in disagreements
                         if d.blocking and Path(d.path) == path})
        reason = f"{pdf_crosscheck.DISAGREEMENT_REASON} ({', '.join(fields)})"
        if quarantine(input_dir, path):
            quarantined.append((path.name, reason))
            safe_print(f"  [quarantine] {path.name}: {reason} -> input/{QUARANTINE_DIR}/")
        else:
            safe_print(f"  [quarantine] {path.name}: {reason} "
                       f"(name conflict — left in place)")
        # Off disk now; drop it so discover_groups never sees a source that moved.
        cache.pop(path, None)

    # Filename identity noise (ADR-003 follow-up). A PDF export carries tails a
    # curated .docx never had -- a double extension, a run of underscores, an
    # unrecognised suffix -- and because the filename is authoritative for a Report
    # No, that tail ships into the monthly document. It is NOT cleaned here: see
    # report_identity.identity_noise for why the cleaning rule cannot be written
    # without guessing. It is made loud instead, on the console and in an audit file.
    noisy = [(p, report_identity.identity_noise(p.name))
             for p in sorted(cache) if p.suffix.lower() == ".pdf"]
    noisy = [(p, why) for p, why in noisy if why]
    for src, why in noisy:
        # Two-space indent is deliberate: gui/services/progress._RENDERED anchors on
        # a line STARTING with '[', so an unindented '[identity] ...' line would be
        # parsed as a rendered document. Keep the indent.
        safe_print(f"  [identity] {src.name}: {why} "
                   f"(Report № -> {_written_report_no(src)})")
    warn_audit = _write_identity_audit(settings, noisy)
    if warn_audit is not None:
        safe_print(f"  Identity warnings: {len(noisy)} noisy PDF name(s) "
                   f"audited -> {warn_audit.name}")

    # Filename serial != in-body Report No serial (report_no_mismatch). Warned on
    # every run, never repaired: the source is fixed on the LAN. A COPY (tables
    # identical to the file named with the body's number) is additionally kept out
    # of the document when filtering.block_mismatched_report_no is on — the
    # aggregator does that; this only says so. Two-space indent, as above.
    mismatches = report_no_mismatch.find_mismatches(cache)
    blocking = report_no_mismatch.block_enabled(settings)
    for m in mismatches:
        tail = ""
        if m.is_copy:
            tail = f" — {m.copy_of[0].name} ilə eyni cədvəl"
            if blocking:
                tail += " — sənədə düşmür"
        safe_print(f"  [report-no mismatch] {m.path.name}: ad {m.name_no} ≠ "
                   f"içəri {m.body_no}{tail}")
    mismatch_audit = _write_mismatch_audit(settings, mismatches, cache)
    if mismatch_audit is not None:
        safe_print(f"  Report-no mismatch: {len(mismatches)} file(s), "
                   f"{sum(1 for m in mismatches if m.is_copy)} copy(ies) "
                   f"audited -> {mismatch_audit.name}")

    # Textless reports: the file opened fine but holds no readable text, i.e. a
    # scanned image pasted into Word. Caught here, at the boundary, so the user is
    # told to re-convert with OCR instead of being sent hunting for the missing
    # date field discover_groups would have blamed.
    for path in textless:
        warn(f"[Quarantine Warning] {path.name} has no readable text. It appears to be a "
             f"scanned image. Please convert it to editable Word format using an "
             f"OCR-enabled PDF-to-Word tool before running.")
        reason = "no readable text (scanned image)"
        if quarantine(input_dir, path):
            quarantined.append((path.name, reason))
            safe_print(f"  [quarantine] {path.name}: {reason} -> input/{QUARANTINE_DIR}/")
        else:
            safe_print(f"  [quarantine] {path.name}: {reason} (name conflict — left in place)")
        # The file has moved on disk; dropping it from the cache keeps
        # discover_groups from re-quarantining a source that no longer exists.
        cache.pop(path, None)

    groups, nodate = pre_processor.discover_groups(settings, cache, scope,
                                                   progress_every=progress_every)
    quarantined += nodate
    if coverage is not None:
        coverage.add_quarantined(quarantined)
        coverage.add_discovery(cache, pre_processor.discover_groups.last_members, groups)
    # The corpus-wide client volume snapshot discovery ACTUALLY decided on — taken
    # after its quarantining, published on the side channel. Read, never recomputed:
    # a second snapshot over a different corpus is how the sweep below came to delete
    # output for clients discovery had admitted.
    client_stats = pre_processor.discover_groups.last_client_stats

    # Every date the run reconstructed, written down with its evidence. Emitted here,
    # right after discovery, so the audit describes the classification the rest of the
    # run is built on even if a later stage fails.
    audit = _write_date_repair_audit(settings,
                                     pre_processor.discover_groups.last_repairs)
    if audit is not None:
        safe_print(f"  Date repairs: {len(pre_processor.discover_groups.last_repairs)} "
                   f"reconstructed date(s) audited -> {audit.name}")

    # Which clients own a new/changed file — computed over EVERY discovered group,
    # not just the in-scope ones, so a scoped run still sees a cross-month sibling's
    # changes.
    dirty_clients = _dirty_clients(pre_processor.discover_groups.last_members,
                                   changed_names)
    config_stamp = _config_stamp(settings)
    #: Compiled artifacts the upload ledger has on record — off limits to both
    #: stale-output sweeps below. Read once per run, never written.
    protected = upload_ledger.protected_keys(LEDGER_PATH)

    # Retire stale compiled output for clients that are now blacklisted (active:
    # false / excluded_clients) or dropped for low corpus volume — an unadmitted
    # client must never linger in output/ where the uploader or audit would still
    # pick it up. Global, not scope-narrowed: a retired client is retired everywhere.
    purged = _purge_excluded_client_outputs(settings, client_stats, protected)
    if purged:
        safe_print(f"  Purged {len(purged)} stale output file(s) for excluded/retired "
                   f"clients: {purged[:6]}{' …' if len(purged) > 6 else ''}")

    # Self-heal: a report re-supplied as a searchable file (now parsed and sorted)
    # retires its old image-only copy from SKIPPED_REPORTS/. Runs on the parsed
    # cache, so it fires even when nothing is in scope to compile below.
    if do_clean:
        healed = pre_processor.purge_replaced_quarantine(settings, cache)
        if healed:
            safe_print(f"  Self-healed {len(healed)} quarantine copy(ies) replaced by "
                  f"searchable reports -> input/{PRUNED_DIR}/")
    if quarantined:
        preview = [n for n, _ in quarantined[:5]]
        more = "" if len(quarantined) <= 5 else f" (+{len(quarantined) - 5} more)"
        safe_print(f"  Quarantined {len(quarantined)} unprocessable file(s) "
              f"-> input/{QUARANTINE_DIR}/: {preview}{more}")
    if not groups:
        if scope.is_empty:
            safe_print("  No datable reports found. Nothing to do.")
        else:
            safe_print("  No reports match the selected filter. Nothing to do.")
        return 1
    scoped = "" if scope.is_empty else " in scope"
    safe_print(f"  Groups to compile: {len(groups)}{scoped} (month x client)")
    if scope.method:
        # A deliverable is the WHOLE client-month (ADR-004); --method narrows the
        # rows, so what this run writes is a diagnostic view, not a filing.
        # Shape note: two-space indent and no trailing ".pdf", so none of the
        # gui/services/progress.py group patterns can claim the line — the same
        # rule the [date repair] line follows. Pinned by tests/test_progress_counters.
        safe_print(f"  [scope] --method {scope.method}: compiled documents will carry "
                   f"{scope.method} rows ONLY — partial, not a deliverable.")
    safe_print("=" * 70)

    # ADR-004: one compiled document per client-month, every NDT method inside it.
    # PDFs are segregated into output/<Client>/ — the method subfolder is gone,
    # because a document no longer belongs to one method.

    # Serial suffix runs 001, 002, ... within each month, shared ACROSS its client
    # reports (MAY: UBOC=001, AZF=002, GEMZA=003 ...). ``groups`` is sorted by
    # (month, client), so one month's clients are contiguous. The counter is
    # committed only after a report actually renders, so a group that extracts no
    # rows leaves no gap in the sequence. The official serial no longer carries it
    # (MR-<CLIENT>-<YY>-<MM>); it stays for custom {seq} patterns.
    seq_counters: dict[str, int] = {}

    generated: list[Path] = []
    low_volume: list[str] = []
    reused: list[str] = []
    #: filename -> reason for every row the aggregator's standard gate dropped,
    #: deduped across groups (a cross-month parent rejected while building May must
    #: not be re-reported while building June). These files are LEFT in input/ — the
    #: summary below is the only place the operator learns about them, so it is not
    #: optional narration.
    unapproved: dict[str, str] = {}
    #: (group tag, parent №, retests, why) for every cross-month parent the strict
    #: pull refused (retest.pull_weld_check). Printed at run end — a silent refusal
    #: would leave the operator reading an orphan retest with no reason.
    pull_rejected: list[tuple[str, str, str, str]] = []
    #: (group tag, report №, PDF line) for every Yarasız report drawn inside a
    #: Yararlı range (presentation.range_mode: by_number). Always empty on the
    #: default strict mode. Written to output/range_verdict_<today>.md at run end.
    range_verdicts: list[tuple[str, str, str]] = []
    # Every branch below ends a group, so every branch emits. A counter that
    # skipped the empty and low-volume groups would jump numbers and read as if
    # work had been lost.
    emit = progress_printer(STAGE_RENDER, len(groups), progress_every)
    for index, (month, client, _count, _methods) in enumerate(groups, 1):
        settings.target_month = month
        translator = Translator(dictionary, settings)   # fresh gap-tracking per group
        seq = seq_counters.get(month, 0) + 1
        # scope.method is normally None: a compiled document holds every method of
        # the client-month (ADR-004). A --method run passes the token straight
        # through as a ROW filter, producing a deliberately partial document.
        report = document_aggregator.build_monthly_report(
            settings, translator, scope.method, client_code=client, seq=seq,
            cache=cache, stats=client_stats)
        abbr = MONTH_ABBR[int(month[5:])]
        tag = f"{client} {abbr} {month[:4]}"
        # Collected BEFORE the empty-group branch below: a group every one of whose
        # sources carried an unapproved standard renders zero rows, and that is
        # precisely the case the operator most needs named.
        for name, reason in report.skipped:
            if reason.startswith(document_aggregator.UNAPPROVED_STANDARD_REASON):
                unapproved.setdefault(name, reason)
            refusal = retest_tracker.parse_refusal(reason)
            if refusal is not None:
                pull_rejected.append((tag, *refusal))
        if not report.rows:
            if coverage is not None:
                coverage.add_report(month, client, tag, report, "no rows")
            safe_print(f"\n[{tag}] no documents extracted — skipped.")
            # A discovered group that compiles to ZERO rows is one whose every
            # source was filtered or quarantined downstream (e.g. all carried an
            # unapproved standard). Any compiled PDF/JSON left at this path from a
            # previous run is now stale and would still show the rejected rows, so
            # it is removed — an unapproved standard must never linger in compiled
            # output. Nothing is written here, only a stale artifact cleared, and an
            # already-uploaded pair is retained (see _retire_artifacts).
            stale = default_output(settings, month, subdir=client, client=client)
            for name in _retire_artifacts(stale, protected):
                safe_print(f"    removed stale output: {name}")
            emit(index, f"Skipped (no documents extracted) {tag}")
            continue
        # Dynamic volume floor (settings.yaml volume_thresholds): a group too small
        # is skipped — config-driven, opt-in, off by default. Uses the SAME
        # reports/items counts the sidecar carries, so the upload gate agrees.
        # Placed before the seq commit so a skipped group leaves no serial gap, like
        # the empty-rows skip above.
        #
        # The method token is deliberately EMPTY: the floor is now per client-month
        # across every method, and volume_threshold("") resolves to the `default`
        # entry. The per-method keys in settings.yaml are documented as deprecated.
        reports_n, items_n = len(report.source_reports), len(report.rows)
        if not meets_volume("", reports_n, items_n, settings):
            if coverage is not None:
                coverage.add_report(month, client, tag, report, "low volume")
            low_volume.append(tag)
            safe_print(f"\n[{tag}] low volume ({reports_n} report(s), "
                       f"{items_n} item(s)) — skipped.")
            emit(index, f"Skipped (low volume) {tag}")
            continue
        seq_counters[month] = seq   # commit only on a rendered report -> no gaps
        if coverage is not None:
            coverage.add_report(month, client, tag, report, None)
        out_path = default_output(settings, month, subdir=client, client=client)
        # INCREMENTAL SKIP — the group is already compiled and nothing it is built
        # from moved: no new/changed source file for this client, both artifacts on
        # disk, and neither settings.yaml nor the dictionary edited since the PDF was
        # written. Re-running ReportLab would reproduce the same bytes, so the render
        # and the sidecar export are skipped and the existing pair stands.
        #
        # Placed AFTER the seq commit on purpose: the PDF sitting on disk already
        # consumed this serial, and skipping must not hand it to the next client.
        if _group_is_current(out_path, client, dirty=dirty_clients,
                             config_stamp=config_stamp, incremental=incremental):
            reused.append(tag)
            # Still a current deliverable — the uploader and audit must see it.
            generated.append(out_path)
            safe_print(f"\n[{tag}] up to date -> {out_path.name}")
            safe_print("    reused       : existing PDF + sidecar (no new source reports)")
            # Grep-able marker for the whole-run determinism check: on a second run of
            # an unchanged corpus EVERY group must print this. Additive to the two
            # lines above, which the GUI's progress parser counts — it matches on
            # "-> name", so this line is inert there.
            safe_print(f"[Incremental Skip] {_display_path(out_path)} "
                       f"already up to date.")
            # The reused PDF was drawn from these same settings (config_stamp),
            # so it hides the same verdicts — they are named here too.
            _note_range_verdicts(report, settings, tag, range_verdicts)
            emit(index, f"Reused {_display_path(out_path)}")
            continue
        pdf_renderer.render_pdf(report, settings, translator, out_path)
        # Parallel JSON sidecar: same folder, same stem, .json — a machine-readable
        # mirror of the PDF (reuses this report + translator so values match exactly).
        json_path = json_exporter.export_report_json(
            report, settings, translator, out_path.with_suffix(".json"))
        generated.append(out_path)

        orphans = sum(1 for r in report.rows if r.is_orphan_retest)
        safe_print(f"\n[{tag}] -> {out_path.name}")
        safe_print(f"    json sidecar : {json_path.name}")
        safe_print(f"    doc#         : {report.document_number}   client: {report.client_name}")
        safe_print(f"    documents    : {len(report.rows)} row(s) from {len(report.source_reports)} report(s)")
        safe_print(f"    retests      : {report.retest_pairs} matched, {orphans} orphan(s)")
        if report.pulled_parents:
            safe_print(f"    cross-month  : {report.pulled_parents} parent(s) pulled from earlier month(s)")
        if report.discrepancies:
            safe_print(f"    report-no drift: {len(report.discrepancies)} "
                  f"(filename wins) e.g. {report.discrepancies[0][1]} != {report.discrepancies[0][2]}")
        if report.untranslated:
            safe_print(f"    untranslated : {len(report.untranslated)} flagged {settings.untranslated_marker}")
        _note_range_verdicts(report, settings, tag, range_verdicts)
        emit(index, f"Compiled {_display_path(out_path)}")

    safe_print("\n" + "=" * 70)
    safe_print(f"  DONE. Generated {len(generated)} report(s):")
    for p in generated:
        safe_print(f"    - {p}")
    if reused:
        safe_print(f"  {len(reused)} group(s) already up to date — PDF + sidecar "
                   f"reused, not re-rendered.")
    if low_volume:
        safe_print(f"  {len(low_volume)} low-volume group(s) skipped: "
                   f"{', '.join(low_volume)}")
    if unapproved:
        safe_print(f"  {len(unapproved)} report(s) omitted for an unapproved standard "
                   f"— LEFT IN input/ (fix the ACC-Standard cell, or add the norm to "
                   f"allowed_standards in config/settings.yaml):")
        for name in sorted(unapproved)[:10]:
            safe_print(f"    [unapproved standard] {name}: {unapproved[name]}")
        if len(unapproved) > 10:
            safe_print(f"    … (+{len(unapproved) - 10} more)")
    if pull_rejected:
        safe_print(f"  {len(pull_rejected)} cross-month parent(s) not pulled — the "
                   f"evidence did not match (retest.pull_weld_check: strict):")
        for tag, parent, retests, why in pull_rejected:
            safe_print(f"    [pull rejected] {parent}: {why} — valideyn gətirilmədi "
                       f"({tag}; {retests})")
    verdict_audit = _write_range_verdict_audit(settings, range_verdicts)
    if verdict_audit is not None:
        safe_print(f"  Range verdict: {len(range_verdicts)} Yarasız report(s) "
                   f"inside a Yararlı range audited -> {verdict_audit.name}")
    if coverage is not None:
        # A signal, never a failure: U > 0 does not change the exit code, and an
        # audit that cannot be written must not fail a finished run either.
        try:
            _path, totals = coverage_audit.write(coverage, settings.output_dir)
            safe_print(coverage_audit.coverage_line(*totals))
            safe_print(coverage_audit.item_line(coverage.english))
        except Exception as exc:  # noqa: BLE001
            safe_print(f"  Coverage: not written ({type(exc).__name__}: {exc})")
    safe_print("=" * 70)
    # Export copy (export.enabled, default off): after the closing rule so a
    # disabled run's stdout is byte-identical. Never fails the run.
    try:
        report_export.export_reports(settings, log=safe_print)
    except Exception as exc:  # noqa: BLE001 — a copy must not fail a finished run
        safe_print(f"  Export: not run ({type(exc).__name__}: {exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
