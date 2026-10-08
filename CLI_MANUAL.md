# CLI Command Reference

Every command-line entry point in this project, with every flag.

This file is the **flag reference**. `README.md` is the narrative: what the pipeline
does, why the portal upload is built the way it is, how the desktop dashboard works.
When the two overlap, the parser in the source is the authority — and
`tests/test_cli_manual_sync.py` fails if a flag here and a flag in
[main.py](main.py) / [uploader.py](uploader.py) ever drift apart.

**Contents**

1. [Prerequisites](#1-prerequisites)
2. [`main.py` — the compile pipeline](#2-mainpy--the-compile-pipeline)
3. [`uploader.py` — E-Keyfiyyet portal upload](#3-uploaderpy--e-keyfiyyet-portal-upload)
4. [`generate_pipeline_summary.py` — on-demand audit PDF](#4-generate_pipeline_summarypy--on-demand-audit-pdf)
5. [`reset_and_sync_input.py` — destructive input reset](#5-reset_and_sync_inputpy--destructive-input-reset)
6. [`reset_upload_ledger.py` — forget every recorded upload](#6-reset_upload_ledgerpy--forget-every-recorded-upload)
7. [`discover_network_share.py` — LAN share scanner](#7-discover_network_sharepy--lan-share-scanner)
8. [`gui_launcher.py` — desktop dashboard](#8-gui_launcherpy--desktop-dashboard)
9. [`monthly-report` — single-report console script](#9-monthly-report--single-report-console-script)
10. [Reading the live progress counters](#10-reading-the-live-progress-counters)
11. [Ordering and safety](#11-ordering-and-safety)

---

## 1. Prerequisites

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # Windows PowerShell
source .venv/bin/activate           # macOS / Linux

python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .                    # installs the `monthly-report` console script
playwright install chromium         # uploader only — not needed for --dry-run

cp config/settings.example.yaml config/settings.yaml
```

`setup.ps1` / `setup.sh` run exactly these steps and are idempotent.

| Requirement | Detail |
|---|---|
| Python | 3.11+ |
| `config/settings.yaml` | Copied from `settings.example.yaml`. Never overwritten if present. |
| Fonts | A Unicode TTF covering Azerbaijani Latin (`ə ğ ı İ ö ş ç ü`) in `assets/fonts/`. `generate_pipeline_summary.py` specifically needs `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf`. See `assets/fonts/README.md`. |
| Portal auth | Manual and persistent. Log in by hand once in the Chrome profile at `portal.user_data_dir` (default `.browser_profile/`); the session persists. **No password is ever handled by this code.** |
| `portal.director` | Blank in the example config and **required for `--live`**. Without it the uploader aborts before a browser opens. |
| Environment variables | None. There is no `.env` — all configuration is YAML. |

---

## 2. `main.py` — the compile pipeline

Reads the `input/` tree, parses every report, and compiles one PDF + JSON sidecar per
`(month × client)` group into `output/<CLIENT>/`. **One client-month is ONE document**
(ADR-004): every NDT method the client had that month is in it, and each row names its
own in the `Üsul` column. The serial follows — `MR-<CLIENT>-<YY>-<MM>`.

```bash
python main.py                                   # everything discovered, unattended
python main.py --month 2026-06                   # one month
python main.py --date 26-06                      # same thing, short form
python main.py --month JUN_2026 --method UT --client UBOC
python main.py --no-clean                        # leave input/ exactly as found
python main.py --force-rebuild                   # re-render even if nothing changed
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--month` | `MON_YYYY` | all months | Compile only this month. Accepts `JUN_2025`, `2025-06` or `26-06`. |
| `--date` | `YY-MM` | — | Alias of `--month`, same destination. Accepts the same three forms. |
| `--method` | `TOKEN` | all methods | **Diagnostic only — the compiled document is PARTIAL.** Keeps only this NDT method's rows (`UT`, `MT`, `RT`, `DP`, `FC`, …). It no longer selects groups: a deliverable is the whole client-month across every method (ADR-004), so a run with this flag writes a document that is missing rows and says so on the console. It still narrows PDF archiving: a PDF whose filename names a *different known* method is left fully untouched, so a later unscoped run picks it up. |
| `--client` | `CODE` | all clients | Compile only this client code (e.g. `UBOC`). |
| `--no-clean` | — | off | Skip housekeeping: no duplicate pruning, no quarantine purge, no `UnSorted/` prune, no parse-cache GC. The input tree is left exactly as found. |
| `--force-rebuild` | — | off | Re-render every in-scope group even when nothing changed, bypassing the incremental-compile skip. |

**Exit codes** — `0` compiled at least one group; `1` nothing to do (no datable reports,
or no group matched the filter); `2` malformed `--month`.

**Scoping is not cleanup.** Housekeeping and quarantine are deliberately global: a
duplicate or an undatable file is wrong under any filter, so it is dealt with regardless
of what `--method`/`--client`/`--month` selected. Only which groups get *compiled* is
filtered.

**Incremental by default.** A group whose source reports are all unchanged since the last
run keeps its existing PDF + sidecar instead of re-rendering identical bytes, logging
`[Incremental Skip] output/… already up to date.`. It re-renders when a report for that
client is new or changed — in ANY method, since they share one document, and including
in a neighbouring month (cross-month retest parents) — when either artifact is missing,
or when `settings.yaml` / the translations file was edited after the PDF was written. Requires `performance.parse_cache`;
`--force-rebuild` bypasses it for one run.

**Deterministic across runs.** Run it twice over an unchanged `input/` and the second run
reports the same `Groups to compile:` count, moves no file, and prints `[Incremental
Skip]` for every group. Only the stages *before* group discovery touch `input/`, so the
count one run prints is the count the next run computes. A report whose in-body
ACC-Standard cell holds an unapproved code has its **row omitted** and its **file left in
place** — the run-end summary names every one under `[unapproved standard]`, so fix the
cell or add the norm to `allowed_standards`. Compiled output *is* retired for retired /
low-volume clients and for groups that render zero rows, but never for an artifact
`.upload_state.json` has on record: those print `retained (uploaded)` instead.

---

## 3. `uploader.py` — E-Keyfiyyet portal upload

Fills the portal appeal form from a compiled report's JSON sidecar and attaches its PDF.
**It never clicks "E-imza ilə təsdiqlə"** — signing stays a human act, always.

```bash
python uploader.py --probe                        # map the live form, write nothing
python uploader.py --dry-run --all                # simulate the whole queue, no browser
python uploader.py                                # fill the newest report, do not save
python uploader.py --live                         # fill and save one draft
python uploader.py --live --all --no-interactive  # unattended batch over everything
python uploader.py --live --all --limit 3         # ...but stop after three
python uploader.py --force --report output/KHF/compiled_monthly_report_KHF_DEC_2025.json
```

### Mode flags

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--probe` | — | off | Open the appeal form, pick the document type so its fields render, dump every control to **`output/portal_form_probe.json`**, print a standards-drift reconciliation, and exit. Fills nothing, saves nothing. This is how the live selectors and the live dropdown of aggregate standards get mapped. |
| `--probe-chips` | `A,B` (optional) | off | `--probe`, then tag standards in the "inspeksiya:" box with the same click path the upload uses, read the chips back and add `chip_request`, `chip_results`, `chip_expected`, `chip_readback`, `chip_match` to **`output/portal_form_probe.json`**, then reload the form. Without a value: the first two `PORTAL_STANDARDS` the live listbox offers. No other field is filled, no PDF is attached, "Yadda saxla" is never clicked, the ledger is not touched. |
| `--live` | — | off | Actually click **"Yadda saxla"** and save a draft appeal. Without it the form is filled and left on screen for review, and nothing is submitted. Requires `portal.director` in `config/settings.yaml` — the check runs *before* a browser opens. |
| `--dry-run` | — | off | Print a coloured step-by-step simulation against a fake page. Launches no browser, touches no network, and uses a separate ledger (`.upload_state.dryrun.json`). Playwright is not required. |

### Selecting what to upload

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--all` | — | off | Sweep every `output/**/compiled_monthly_report_*.json` sidecar. Resumable — already-uploaded reports are skipped via the ledger. Reports dated before December 2025, excluded clients, unapproved clients and below-threshold volumes are filtered out here. |
| `--report` | `JSON` | newest sidecar under `output/` | Single-report mode: the compiled `.json` sidecar to upload. |
| `--pdf` | `PDF` | the sidecar's `.pdf` twin | Override the attached PDF. Single-report mode only — combining it with `--all` is refused. |
| `--method` | `TOKEN` | all | `--all` filter: only documents CONTAINING this method (`MT`, `UT`, `DP`, …), read from the sidecar's `items_table[].method` — the filename no longer carries a method token, and one document holds several. Case-insensitive. |
| `--client` | `CODE` | all | `--all` filter: only reports for this client code (e.g. `KHF`). |
| `--month` | `MON_YYYY` | all | `--all` filter: only reports for this month token (e.g. `FEB_2026`). |
| `--limit` | `N` | `1` | Process at most N reports in one run. Must be ≥ 1. See the cap rules below. |

**The December 2025 portal cutoff.** The portal takes appeals for **December 2025
onward**, so a report whose reporting month starts before `2025-12-01` is refused during
target resolution as `SKIPPED_PRE_DEC_2025` — "Report date is prior to December 2025
portal upload cutoff". It applies on both paths and before every other gate: `--all`
drops the report and carries on with the rest; a hand-picked `--report` exits. The month
comes from the sidecar's `reporting_period`, falling back to the filename's month token.
This is what keeps `--all` off the 2024 / early-2025 back catalogue that stays in
`output/` (the same `2025-12-01` cutoff `reset_and_sync_input.py` syncs against).

### Prompts and pacing

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--interactive` | — | off | Ask in the terminal before every "Yadda saxla": inspect the filled form, then `[Enter]`/`y` to save and continue, `s` to skip this report, `q` to end the run. Already the default for a `--live --all` batch on a terminal. Needs `--live` — a run that cannot save has nothing to confirm. |
| `--no-interactive` | — | off | Never prompt: save every report the ledger selected without asking. For unattended and GUI-driven runs. Also the automatic behaviour when stdin is not a terminal. |
| `--slow` | `MS` | `0` | Pause this many milliseconds before every browser action so the fill can be watched (e.g. `2000`). Ignored under `--dry-run`. |

### Ledger and recovery

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--force` | — | off | Upload even when the ledger flags the report as `IN_PROGRESS` — interrupted mid-submit. **Only after verifying on the portal that the appeal is genuinely absent**: this can create a duplicate. |
| `--ledger` | `JSON` | `.upload_state.json` | Override the upload-state ledger path. `--dry-run` uses `.upload_state.dryrun.json`. |
| `--reset` | `PDF [PDF ...]` | — | Forget the upload state of these report PDFs and exit, so a later run re-uploads them. Equivalent to deleting their keys from the ledger by hand. |
| `--url` | `URL` | `portal.url` | Override the portal URL the run waits for. |

### The one-report cap, exactly

The default `--limit` is **1**. That is a safety floor, not a preference: a fill-only run
leaves the form on screen for review, and a second report would overwrite it unseen.

- Without `--live`, the cap is **always 1**, whatever `--limit` says.
- With `--live --all` on a terminal, the run is interactive by default and lifts the cap
  to the whole queue — you are confirming each save anyway.
- With `--live --all --no-interactive`, the cap lifts to the whole queue and the batch
  runs unattended in one continuous loop.
- **An explicit `--limit` always wins.** `--limit 1` and the default 1 are tracked
  separately, so asking for a cap out loud is never overruled by either lift.

### Ledger states

| State | Meaning | Next run does |
|---|---|---|
| *(no entry)* | Never uploaded | Uploads |
| `UPLOADED`, content unchanged | Already on the portal | Skips |
| `UPLOADED`, content changed | Report was recompiled | Uploads again |
| `IN_PROGRESS`, content changed | Interrupted, then recompiled | Uploads (no `--force` needed) |
| `IN_PROGRESS`, content unchanged | Interrupted mid-submit — may or may not exist on the portal | **Blocks.** Verify on the portal, then re-run with `--force` |

The ledger key is the project-relative POSIX path of the PDF; the content hash covers the
sidecar bytes followed by the PDF bytes. Writes are atomic. A human-readable audit trail
is appended to `output/upload_status.json`, and failure evidence (screenshot + HTML) lands
in `output/failures/`.

**Exit codes** — `0` clean; `1` if anything was blocked or failed.

---

## 4. `generate_pipeline_summary.py` — on-demand audit PDF

Optional. Builds the executive audit PDF from what is already on disk — sidecars,
`input/`, the parse cache, the ingestion registry and the upload ledger. Nothing in the
compile or upload path depends on it.

```bash
python generate_pipeline_summary.py                    # latest CLOSED month
python generate_pipeline_summary.py --month 2026-06
python generate_pipeline_summary.py --date 26-06       # same thing
python generate_pipeline_summary.py --all              # cumulative, all periods
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--month` / `--date` | `AY` | latest closed month | Target month: `YYYY-MM` (`2026-06`), `YY-MM` (`26-06`) or `MMM_YYYY` (`JUN_2026`). |
| `--all` | — | off | Cumulative audit across all periods, not split by month. Cannot be combined with `--month`. |

An official report is only issued for a **closed** month — asking for the current,
incomplete or a future month is refused. Output:
`output/pipeline_executive_summary_report_<YYYY>_<MM>.pdf`, also copied to the canonical
`output/pipeline_executive_summary_report.pdf`. `--all` writes
`output/pipeline_executive_summary_report_all.pdf` and never touches the canonical name.

---

## 5. `reset_and_sync_input.py` — destructive input reset

> **Destructive.** This permanently deletes the local `input/` tree and the dedup state,
> then re-syncs reports off the LAN share by inspection date. Deleted files are **not**
> moved to `_PRUNED/` — they are gone. Run `--dry-run` first.

```bash
python reset_and_sync_input.py --dry-run              # show what would happen
python reset_and_sync_input.py --cutoff 2026-01-01
python reset_and_sync_input.py --no-purge             # sync only, delete nothing
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--cutoff` | `YYYY-MM-DD` | `2025-12-01` | Date cutoff; reports older than this are skipped. |
| `--no-purge` | — | off | Skip the local reset entirely; sync only. |
| `--dry-run` | — | off | Report the intended reset and sync without deleting, copying, or writing the manifest. |
| `--yes` | — | off | Skip the delete confirmation prompt. Unattended use only. |
| `--keep-cache` | — | off | Keep `.parse_cache/`. Faster re-parse, but its content digests will suppress re-staging of identical reports. |

---

## 6. `reset_upload_ledger.py` — forget every recorded upload

> **Irreversible, and order-critical.** Emptying the ledger tells the uploader that
> nothing is filed. Run it **only after** the drafts are deleted on the portal and the
> portal list is confirmed empty — the reverse order files a second copy of every
> report still sitting there, which is the duplicate the ledger exists to prevent.
> Back up `.upload_state.json` first; this script cannot undo itself.

The file is emptied, never deleted: it is rewritten as
`{"version": 1, "entries": {}}` through the ledger's own atomic write (tempfile →
`flush` → `fsync` → `os.replace`). Nothing in `uploader.py` is imported or changed —
not `decide`, not the three brakes, not the approved-clients gate.

```bash
python reset_upload_ledger.py --dry-run          # list what would be forgotten
python reset_upload_ledger.py --yes              # forget it
python reset_upload_ledger.py --ledger .upload_state.dryrun.json --yes
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--ledger` | `JSON` | `.upload_state.json` | Which ledger to empty. Pass the dry-run ledger explicitly to reset that one instead. |
| `--dry-run` | — | off | List every recorded entry and exit without writing. Wins over `--yes`. |
| `--yes` | — | off | Required to actually write. Without it the script refuses, so a mistyped command can never empty the ledger. |

Every recorded status is forgotten, `IN_PROGRESS` included — a reset means the
operator has already resolved that ambiguous report on the portal.

**Afterwards** no compiled artifact is protected any more (`protected_keys` returns
an empty set), so the next `python main.py --force-rebuild` is free to retire stale
output the ledger had been pinning. That is intended; it is also why the backup is not
optional.

---

## 7. `discover_network_share.py` — LAN share scanner

Read-only. Catalogs the remote NDT report folders and writes
`LAN_NETWORK_DISCOVERY_REPORT.md` at the project root. A no-op when
`network_ingestion.lan_sources` is empty.

```bash
python discover_network_share.py
python discover_network_share.py --json --report scans/share-2026-08.md
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--json` | — | off | Also print the raw discovery result as JSON to stdout. |
| `--report` | `PATH` | `./LAN_NETWORK_DISCOVERY_REPORT.md` | Override the report output path. |

---

## 8. `gui_launcher.py` — desktop dashboard

No argparse of its own. With no arguments it opens the PySide6 dashboard, which drives
`main.py` and `uploader.py` as child processes and reads their printed narration to move
its progress bars.

```bash
python gui_launcher.py                              # open the dashboard
python gui_launcher.py --worker pipeline --month 2026-06
python gui_launcher.py --worker upload --live --all
```

`--worker pipeline` forwards everything after it to `main.py`; `--worker upload` forwards
to `uploader.py`. These are the dashboard's own subprocess entry points — useful for
reproducing exactly what a GUI run did, not for daily use.

---

## 9. `monthly-report` — single-report console script

Installed by `pip install -e .`. The older single-report path; `main.py` is the pipeline.

```bash
monthly-report --month 2026-06
python -m monthly_report.cli --month 2026-06 --out reports/june.pdf
```

| Flag | Argument | Default | Effect |
|---|---|---|---|
| `--month` | `YYYY-MM` | `target_month` from settings | Month to compile. |
| `--config` | `PATH` | `config/settings.yaml` | Settings file to load. |
| `--out` | `PATH` | derived from `output.filename_pattern` | Output PDF path. |

Returns `1` if no reports matched.

---

## 10. Reading the live progress counters

Every stage of `main.py` narrates itself in one shape, flushed line by line so a long run
is visibly moving rather than apparently hung:

```
[Stage -1: PDF Convert] [pdf] (12/40) converted KF-MT-26-005.pdf -> KF-MT-26-005.docx
[Stage 0: Sorter] [105/1053] Sorting report into method folder: KF-UT-26-011.docx -> input/UT/
[Stage 1: Parsing] [500/1053] Processing parse_cache...
[Stage 1: Parsing] [3/12] Parsed report: KF-UT-26-011.docx
[Stage 2: Grouping] [640/1053] Classifying report: KF-DP-26-002.docx
[Stage 3: Rendering] [5/14] Compiled output/UBOC/compiled_monthly_report_UBOC_JUN_2026.pdf
```

Two things are worth knowing when reading them:

- **Stage 1 counts twice, with different denominators.** The first pass hashes every file
  and answers from the parse cache (`[500/1053]`); the second parses only what the cache
  missed (`[3/12]`). One shared denominator would show a counter that sprints through the
  hits and then appears to stall on the real work.
- **Stage 3 counts every group, not every PDF.** A group that is skipped (no documents,
  low volume) or reused (already up to date) still advances the counter, so the numbering
  never has gaps.

Rate is controlled by `performance.progress_every` in `config/settings.yaml`:

| Value | Behaviour |
|---|---|
| `1` (default) | One line per item, per stage. |
| `25` | Every 25th item. The first and last item of a stage always print. |
| `0` | Counters off. The per-stage summary lines remain. |

The desktop dashboard's progress bars read the per-stage summary lines, not these
counters, so turning the counters down never affects the GUI.

---

## 11. Ordering and safety

**Compile before upload.** `uploader.py` reads what `main.py` wrote; with an empty
`output/` it exits telling you to run `python main.py` first.

**Work up the ladder for a portal run**, each rung proving the next is safe:

```bash
python uploader.py --probe                        # 1. are the selectors still valid?
python uploader.py --dry-run --all                # 2. what would the queue do?
python uploader.py                                # 3. fill one form, review on screen
python uploader.py --live                         # 4. save one draft
python uploader.py --live --all --interactive     # 5. batch, confirming each save
python uploader.py --live --all --no-interactive  # 6. unattended batch
```

Three things this tool will not do, by construction: it never signs (`E-imza ilə
təsdiqlə` is never clicked), it never handles a password, and it never saves a draft
without `--live`.
