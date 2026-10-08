# Monthly Report Studio

### Automated NDT Ingestion, Translation & Azerbaijani State Portal Integration Suite

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/tests-2253-2ea44f)
![PDF](https://img.shields.io/badge/PDF-ReportLab-8A2BE2)
![Automation](https://img.shields.io/badge/automation-Playwright-2EAD33)
![Desktop](https://img.shields.io/badge/desktop-PySide6-41CD52)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-informational)

An end-to-end pipeline that turns a messy drop-folder of **English `.docx` / `.pdf` Non-Destructive
Testing (NDT) inspection reports** into **print-ready Azerbaijani monthly reports** — one compiled PDF
per client, each mirrored by a machine-readable JSON sidecar — and then files them, idempotently, into
the **Azerbaijani state quality portal (E-Keyfiyyet)** through a safety-gated browser automation.

It ingests, converts, sorts, de-duplicates, date-filters, extracts, translates, compiles, renders, and
uploads — unattended or through a modern desktop dashboard — with a **2,253-test pytest suite** as the
quality gate behind every stage.

```
input/*.docx  ──▶  read  ──▶  date-filter  ──▶  extract  ──▶  translate  ──▶  merge  ──▶  render  ──▶  output/*.pdf + *.json  ──▶  E-Keyfiyyet
 (English /        (docx,     (by target      (config-      (JSON dict,      (one       (ReportLab   (Azerbaijani,           (Playwright,
  PDF, no          no images)  month YYYY-MM)   driven fields) AZ-authoritative) per-client tables)      + data sidecar)         idempotent)
  images)                                                                       model)
```

---

## Table of contents

- [Architecture highlights](#architecture-highlights)
- [What it does, stage by stage](#what-it-does-stage-by-stage)
- [Recommended architecture](#recommended-architecture)
- [Project layout](#project-layout)
- [Developer setup](#developer-setup-windows--powershell)
- [Quick start on another machine](#quick-start-on-another-machine)
- [Usage](#usage)
- [Desktop dashboard (Monthly Report Studio)](#desktop-dashboard-monthly-report-studio)
- [Handling PDFs](#handling-pdfs)
- [Housekeeping (self-healing cleanup)](#housekeeping-self-healing-cleanup)
- [JSON sidecars (data / presentation decoupling)](#json-sidecars-data--presentation-decoupling)
- [E-Keyfiyyet portal integration](#e-keyfiyyet-portal-integration)
- [AI-Augmented Engineering: an LLM-Driven Development case study](#ai-augmented-engineering-an-llm-driven-development-case-study)
- [Maintainability principles](#maintainability-principles)
- [Publishing this repository](#publishing-this-repository)

---

## Architecture highlights

Five design decisions that carry the suite. Each links to the code that implements it.

### 1 · Dynamic Pre-Processor & Sorter
Loose `.docx`/`.pdf` files land anywhere under `input/` in any order. A pre-processor moves every
dropped PDF into `input/PDF_ARCHIVE/`, where it is read **directly** with PyMuPDF — no conversion
step ([ADR-003](architecture/ADR-003-pdf-direct-extraction.md); the old `pdf2docx` conversion
shattered tables and mis-set the verdict on 15.2% of reports) — then sorts every file
into a method subfolder using a **config-driven method registry** (`ndt_methods` in `settings.yaml`):
zero code changes to onboard a new NDT method. See
[`src/monthly_report/pre_processor.py`](src/monthly_report/pre_processor.py).

### 2 · Hierarchical Retest Traceability
Weld repairs span months: a defect found in one report is re-shot and re-tested weeks later. The suite
maintains **cross-month parent-child mapping** so a retest is traced back to the original inspection,
preserving a coherent repair history rather than treating each month as an island. See
[`src/monthly_report/retest_tracker.py`](src/monthly_report/retest_tracker.py).

### 3 · Data-Decoupled Exporter
Every compiled PDF is written **alongside a parallel JSON metadata sidecar** carrying the same
translated values, reporting period, and per-item table. Downstream tools — including the uploader —
consume structured data and never re-parse a PDF. Presentation and data stay decoupled. See
[`src/monthly_report/json_exporter.py`](src/monthly_report/json_exporter.py).

### 4 · Idempotent Web Uploader
Uploading is a side effect on a live government database, so it is gated by a durable **SHA-256 content
ledger** and a **double-phase transaction lock** — each report is checkpointed `IN_PROGRESS` *before*
the submit and `UPLOADED` *after*, flushed atomically — making every batch resumable and every repeat
run a safe no-op. Driven by Playwright. See [`uploader.py`](uploader.py) and
[`src/monthly_report/upload_ledger.py`](src/monthly_report/upload_ledger.py).

### 5 · Modern PySide6 Dashboard
A fluid, responsive desktop cockpit over the same backend: metric cards, an embedded ANSI-colored live
console, a drag-and-drop ingestion zone, the quarantine queue, and the upload ledger — launching the
pipeline and uploader as child processes and streaming their output. See
[`src/monthly_report/gui/`](src/monthly_report/gui/).

---

## What it does, stage by stage

1. **Read** each `.docx` with `python-docx` — paragraphs and tables only, images ignored.
2. **Date-filter** — detect the primary inspection date and keep only reports in the requested month.
3. **Extract** evolving text fields via rules in [`config/fields.yaml`](config/fields.yaml) (label- **or** table-based).
4. **Translate** to Azerbaijani using the authoritative dictionary [`translations/az.json`](translations/az.json); untranslated free prose is flagged, not dropped.
5. **Merge** all in-month reports into one ordered, per-client model.
6. **Render** a professional PDF with ReportLab — stable tables, automatic row heights, long-text wrapping, embedded Unicode font — and write the matching JSON sidecar.
7. **Upload** each sidecar to E-Keyfiyyet through the safety-gated Playwright flow.

## Recommended architecture

| Concern | Choice | Why |
|---|---|---|
| Language | **Python 3.11+** | `python-docx` is the best `.docx` reader (and ignores images for free); great CLI automation |
| `.docx` parsing | `python-docx` | Faithful paragraph/table/run model |
| Date parsing | `python-dateutil` | Robust, flexible date detection |
| Translation | JSON dictionary (authoritative) + flagging | Consistent official terminology; auditable gaps |
| **PDF engine** | **ReportLab (Platypus)** | **Pip-only, no system binaries on Windows**; deterministic tables, auto row-height, page splitting, TTF embedding for `ə ğ ı ö ş ç ü` |
| Browser automation | **Playwright (Chromium)** | Resilient auto-waiting locators; persistent-profile auth |
| Desktop UI | **PySide6 (Qt 6)** | Native, responsive, threading-safe via child processes |
| Config | YAML (`settings.yaml`, `fields.yaml`) | Fields/terminology evolve without code changes |

Full comparison and rejected alternatives (Typst, WeasyPrint, docx→PDF) are in the
[ADR](architecture/ADR-001-tech-stack.md); the desktop-frontend decisions are in
[ADR-002](architecture/ADR-002-gui-frontend.md).

## Project layout

```
monthly-report-system/
├── architecture/
│   ├── ADR-001-tech-stack.md            # decisions, pros/cons, risks
│   ├── ADR-002-gui-frontend.md          # desktop dashboard: framework, threading, packaging
│   ├── ADR-003-pdf-direct-extraction.md # read PDFs directly, no pdf2docx conversion
│   ├── ADR-004-client-grouping.md       # one document per client-month, all methods
│   ├── ADR-005-duplicate-report-identity.md # transposed report-№ merge on weld evidence
│   ├── ADR-006-pulled-parent-reference.md   # cross-month parent: plain / marked / hidden
│   ├── ADR-007-pull-weld-check.md       # a cross-month pull must match on welds
│   ├── ADR-008-report-no-mismatch.md    # filename serial ≠ body serial: warn, never repair
│   ├── ADR-009-by-number-ranges.md      # one line per number, ranged by number
│   └── ADR-010-partial-standard-filing.md # portal.standard_policy: all | any
├── docs/
│   ├── INDEX.md                         # one line per root item, module, script and config key
│   ├── CODE_MAP_2026-09-28.md           # evidence-backed map of the code
│   └── history/                         # superseded context and handoffs (read for history)
├── Claude outputs/                      # the prompts that drove each development step (see LDD below)
├── config/
│   ├── settings.example.yaml            # committed template — copy to settings.yaml
│   ├── settings.yaml                    # your real values (git-ignored)
│   └── fields.yaml                      # extraction rules (label + table)
├── translations/az.json                 # English -> Azerbaijani dictionary
├── assets/fonts/                        # place Noto/DejaVu TTF here (not committed)
├── input/                               # drop source .docx (or .pdf) reports here
│   ├── UnSorted/                        # transient staging; the sorter empties it
│   ├── PDF_ARCHIVE/                     # originals of auto-converted PDFs
│   ├── SKIPPED_REPORTS/                 # quarantined: unreadable / undatable / scanned
│   └── _PRUNED/                         # recoverable trash: redundant copies housekeeping retired
├── output/                              # generated PDF(s) + JSON sidecars
├── src/monthly_report/                  # pipeline package (cli, reader, extractor, ...)
│   ├── services/                        # LAN ingestion + ingestion registry
│   └── gui/                             # desktop dashboard (main.py borrows one filename parser from it)
│       ├── worker_entry.py              # child-process entry into main.py / uploader.py
│       ├── services/                    # process runner, parsers, filesystem scans
│       └── ui/                          # theme, widgets, pages
├── gui_launcher.py                      # dashboard launcher + --worker dispatch
├── main.py                              # the pipeline (unattended, or scoped: --month/--method/--client)
├── uploader.py                          # portal uploader
├── scripts/                             # one-off audits + the verdict-corpus builder
├── standarts/                           # portal standard lists (the spelling is load-bearing)
├── tests/                               # 2,253-test pytest suite
├── requirements.txt
└── pyproject.toml
```

## Developer setup (Windows / PowerShell)

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) install the package so `monthly-report` and imports work
pip install -e .

# 4. Create your local config from the committed template, then fill it in
Copy-Item config/settings.example.yaml config/settings.yaml
```

> On macOS/Linux, activate with `source .venv/bin/activate` and copy with
> `cp config/settings.example.yaml config/settings.yaml`.

`config/settings.yaml` is git-ignored: it holds your real client VÖENs and the signing director's
identity-document values. Only [`config/settings.example.yaml`](config/settings.example.yaml) — with
obvious placeholders — is committed.

### Fonts (required for PDF)

Download a Unicode font that covers Azerbaijani and place it in `assets/fonts/`
(font binaries are intentionally not committed). Defaults expected by
`config/settings.yaml`:

```
assets/fonts/DejaVuSans.ttf
assets/fonts/DejaVuSans-Bold.ttf
```

See [`assets/fonts/README.md`](assets/fonts/README.md) for sources.

## Quick start on another machine

For reading the code and running the test suite on a machine that is not the Windows
workstation (for example a MacBook). The pipeline itself does not run there: it needs the LAN
share and the portal session.

1. **Python >= 3.11** (`python --version`).
2. **Dependencies:** `pip install -r requirements.txt`.
   - `PySide6` is needed by the tests too: `tests/test_coverage_audit.py`,
     `tests/test_gui_pipeline_args.py` and `tests/test_item_translation_guard.py` import GUI
     modules (`monthly_report.gui.ui.widgets`, `monthly_report.gui.services.job_runner`).
     Without it, collection stops with 3 errors.
   - `playwright` (the Python package) is optional for the tests: 6 uploader test modules
     call `pytest.importorskip("playwright")` and skip without it. No test launches a browser,
     so `playwright install chromium` is not needed.
3. **Fonts:** put `DejaVuSans.ttf` and `DejaVuSans-Bold.ttf` in `assets/fonts/`
   (see [Fonts](#fonts-required-for-pdf)). They are not committed; without them two test
   modules fail at collection and the PDF tests cannot render.
4. **Do not create `config/settings.yaml` from the example just to run the tests.** Leave it
   absent. Many tests check the live config's real contents (client registry, allowed
   standards, inspectors); the placeholder template makes them fail instead of skip.
5. **Run:** `python -m pytest -q`.

What skips on a fresh clone, and why:

| skip reason | why |
|---|---|
| `config/settings.yaml not present` | the live config is gitignored (client VÖENs, director's ID). `tests/conftest.py` reports "Settings file not found" for that path as a skip, only while the file is absent |
| `verdict gate NOT RUNNING: corpus missing` | `corpus/verdict_regression/` is gitignored; built on the workstation by `python scripts/build_verdict_corpus.py` from `input/` |
| `no probe dump committed` | `output/portal_form_probe.json` comes from `uploader.py --probe` against the live portal |
| `no 2026+ sidecar under output/`, `no compiled reports on disk`, `no live upload ledger` | `output/` and `.upload_state.json` are produced on the workstation and not committed |

Measured on a clean `git clone` (Windows, Python 3.14, fonts added, no `input/`, `output/`,
`corpus/` or `config/settings.yaml`), 2026-10-06: **1719 passed, 534 skipped, 0 failed, 0 xfailed**.
The same run on macOS is UNKNOWN / NEEDS VERIFICATION.

Only on the Windows workstation:

- **LAN sync** (STAGE -1 of `main.py`, `discover_network_share.py`): needs the UNC share.
- **The uploader browser run** (`uploader.py` without `--dry-run`, `--probe`): needs the saved
  portal session in `.browser_profile/` and the live config. `--dry-run` needs neither a browser
  nor the LAN, but it reads compiled documents under `output/`, so it has nothing to do on a clone.
- **The GUI `.exe`** (`dist/MonthlyReportStudio.exe`): a Windows PyInstaller build.

## Usage

1. Put the English `.docx` reports in [`input/`](input/).
2. Set the month in [`config/settings.yaml`](config/settings.yaml) (`target_month: "YYYY-MM"`),
   or pass `--month` (CLI wins).
3. Run:

```powershell
# via console script (after `pip install -e .`)
monthly-report --month 2026-07

# or as a module
python -m monthly_report.cli --month 2026-07

# or the full unattended pipeline
python main.py
```

The Azerbaijani PDF and its JSON sidecar are written to [`output/`](output/), organized by method and
client. Every stage prints a live `[Stage N: Name] [i/total] …` counter as it works
(rate: `performance.progress_every` in `config/settings.yaml`).

**Full flag reference for every entry point: [`CLI_MANUAL.md`](CLI_MANUAL.md).**

## Desktop dashboard (Monthly Report Studio)

A local PySide6 dashboard over the same pipeline — metric cards, a live
colour-coded terminal, the quarantine queue and the upload ledger. It changes
nothing about how the backend runs; it launches `main.py` and `uploader.py` as
child processes and reads their output.

```powershell
pip install PySide6          # or: pip install -r requirements.txt
python gui_launcher.py
```

| Tab | What it shows |
|---|---|
| **Dashboard** | Documents processed / generated PDFs+JSONs / quarantined, a drag-and-drop ingestion zone, the Run + Upload controls, two live progress bars and the streaming terminal |
| **Uploader / Registry** | The `.upload_state.json` ledger as a table, with stalled `IN_PROGRESS` entries flagged |
| **Quarantine** | Every file in `input/SKIPPED_REPORTS/`; "Open File" launches it in Word for OCR repair |
| **Settings** | Pre-flight checks (fonts, config, Playwright), resolved paths, dark/light theme |

**Drag and drop to ingest.** Drop `.docx`/`.pdf` files or whole folders onto the
Dashboard — nested folders are walked recursively and copied into `input/` in the
background (existing names are skipped, never overwritten). Uploads are
**dry-run only** — no browser, no credentials.

**Scoped runs.** The Month / NDT Method / Client dropdowns scope everything the
buttons below them do — the metric cards, **Run Pipeline**, and the upload —
passed through as `--month/--method/--client`. Pick JUN 2026 + UT and click Run,
and only those reports are compiled; every other group is left untouched. Leave a
dropdown on "All" to include every value. This works from the terminal too:

```powershell
python main.py                                  # unattended: every discovered group
python main.py --month JUN_2025 --method UT     # only that month + method
python main.py --month 2025-06 --client CLIENT_A  # 2025-06 accepted as well as JUN_2025
```

PDF archiving is narrowed by method only (a PDF's month and client are unknown
until it is parsed); month and client filter authoritatively at group discovery.

**Two progress bars.** *Ingestion & Sorter* tracks copy → PDF-archive → sort;
*Compilation* tracks parse → group → render. There is no conversion stage: a PDF
is archived with a file move and read directly at parse time.

The same launcher runs headless, which is what the dashboard itself calls:

```powershell
python gui_launcher.py --worker pipeline                  # identical to: python main.py
python gui_launcher.py --worker upload --dry-run --all    # identical to: python uploader.py --dry-run --all
```

See [ADR-002](architecture/ADR-002-gui-frontend.md) for why PySide6, why child
processes rather than threads, and why the data directories must sit beside the
executable.

### Building the standalone .exe

```powershell
pip install PySide6 pyinstaller

# Iteration build — starts instantly, no extraction step
pyinstaller --noconfirm --onedir --windowed --name MonthlyReportStudio `
  --paths src --paths . `
  --hidden-import main --hidden-import uploader `
  --collect-submodules monthly_report `
  --collect-all fitz `
  --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore `
  --exclude-module PySide6.QtQuick --exclude-module PySide6.Qt3DCore `
  gui_launcher.py

# Delivery build — one clickable file (~170 MB)
pyinstaller --noconfirm --onefile --windowed --name MonthlyReportStudio `
  --paths src --paths . `
  --hidden-import main --hidden-import uploader `
  --collect-submodules monthly_report `
  --collect-all fitz `
  --exclude-module tkinter --exclude-module PySide6.QtWebEngineCore `
  --exclude-module PySide6.QtQuick --exclude-module PySide6.Qt3DCore `
  gui_launcher.py
```

Then **copy the data directories next to the `.exe`** — this is required, not
optional:

```
dist\MonthlyReportStudio\
  MonthlyReportStudio.exe
  config\  assets\  translations\  images\     <- read by the pipeline
  input\   output\                             <- read and written
```

> **Never `--add-data config;config`.** Bundling `config/` inside the executable
> makes `config.load_settings` resolve the project root to PyInstaller's temp
> extraction directory, so the pipeline would write `output/` into a folder
> Windows deletes on exit — losing every report, silently, on a build that
> otherwise appears to work. `gui/worker_entry.py` pins the root to the
> executable's own directory to prevent this; see ADR-002 Decision 3.

**Verify any frozen build before shipping it** — this is the check that catches
the failure above:

```powershell
cd dist\MonthlyReportStudio
.\MonthlyReportStudio.exe --worker pipeline
# PDFs must appear in .\output\ — never under %TEMP%\_MEI*
```

`--hidden-import main --hidden-import uploader` is required: `worker_entry`
imports them lazily, so PyInstaller's static analysis cannot see them.

## Handling PDFs

**Searchable PDFs are handled for you.** Drop a `.pdf` anywhere under `input/` and the
first pipeline stage converts it to `.docx` in place, then moves the original to
[`input/PDF_ARCHIVE/`](input/) to keep the working folders clean:

```
  [pdf] converting (1/14) MPI-SDLN-26-329___F1882___06.05.26.pdf ...
  [pdf] MPI-SDLN-26-329___F1882___06.05.26.pdf: converted -> MPI-SDLN-26-329.docx -> input/PDF_ARCHIVE/
  PDFs: 46 found — 14 converted, 32 skipped (already present/ASR), 46 archived -> input/PDF_ARCHIVE/
```

Conversion is the slow step (roughly 30–40 s per page), but it is paid **once**: the
archived original is never re-converted, so later runs start instantly.

The `.docx` is named after the **report number**, not the PDF's full filename. Source
PDFs often arrive with a job/date suffix (`MPI-SDLN-26-329___F1882___06.05.26.pdf`), and
because the filename is this pipeline's authoritative source for Report № (inspectors
sometimes mistype the field inside the document), that suffix would otherwise be printed
verbatim as the Report № in the official report. Nothing is lost: the inspection date and
item name are always read from inside the document.

Three kinds of PDF are archived *without* being converted:

| Situation | Why it is skipped |
| :--- | :--- |
| A `.docx` of the same report number already exists | The hand-checked `.docx` wins. Re-converting would replace it with lower-fidelity machine output. |
| A sibling `.docx` already sits next to the PDF | Already converted by an earlier run. |
| ASR/ARS documents | Excluded from compiled reports pipeline-wide. |

A PDF that is locked, encrypted, or malformed is reported and left in place — the rest
of the batch still runs.

### Scanned PDFs still need OCR

The pipeline reads **text**, never pictures. Automatic conversion can only recover text
that is actually in the PDF, so a *scanned* PDF converts to a `.docx` containing one big
image and nothing to read. Those must be converted with an **OCR-enabled** tool first.

### Searchable vs scanned PDFs

|  | Searchable PDF | Scanned PDF |
| :--- | :--- | :--- |
| **How it was made** | Exported from Word, Excel, a CAD tool | Photographed or scanned from paper |
| **What's inside** | A real text layer | One flat image per page |
| **Select text in a viewer?** | Yes | No — you select the whole page image |
| **Converts to usable `.docx`?** | Yes, with any converter | **Only with OCR** |

Converting a scanned PDF *without* OCR still produces a `.docx`, and that is the trap:
the file opens in Word and looks perfectly normal, but it is a picture of a report
pasted onto the page. There is no text in it for the pipeline to read.

### What the pipeline does about it

Every `.docx` is checked for readable text as it is parsed. A file with none is moved to
[`input/SKIPPED_REPORTS/`](input/) and reported:

```
[Quarantine Warning] KF-MT-26-042.docx has no readable text. It appears to be a scanned image. Please convert it to editable Word format using an OCR-enabled PDF-to-Word tool before running.
```

The rest of the run continues normally — one bad file never blocks the batch, and it is
never silently folded into a compiled report as empty rows.

### OCR conversion workflow

Convert the original **PDF** (not the failed `.docx`) with one of:

| Tool | Notes |
| :--- | :--- |
| **Adobe Acrobat Pro** | *Scan & OCR → Recognize Text*, then *Export To → Microsoft Word*. Reliable all-rounder. |
| **ABBYY FineReader** | Best table-structure fidelity — the strongest choice for dense weld-data tables. |
| **Microsoft Word** | *File → Open* the PDF; Word runs its own conversion. Free, already installed, good enough for clean scans. |
| **Smallpdf OCR / PDF2Go OCR** | Free, browser-based. **Do not use for confidential inspection reports** — the file is uploaded to a third-party server. |

### The 10-second check before you re-run

Open the converted `.docx` in Word and try to **click inside a table cell and select the
numbers**:

* **Text highlights, a caret appears** → OCR worked. Ready for the pipeline.
* **The whole block selects as one object with drag handles** → it is still an image.
  OCR did not run. Convert again with a tool from the table above.

Check a couple of *data* cells, not just the title — some tools OCR headings but leave
table bodies as images.

Once it passes, drop the file anywhere under [`input/`](input/) and re-run
`python main.py`. The scan is recursive, so nested client folders are picked up too.
The old, unreadable copy in `SKIPPED_REPORTS/` retires itself — see below.

## Housekeeping (self-healing cleanup)

Every run tidies `input/` after itself. Three passes, all automatic:

| Pass | What it clears |
| :--- | :--- |
| **Duplicate pruning** | Byte-identical `.docx` under different names (`KF-RT-26-070.docx`, `…_en.docx`, `…_en_en.docx`, `…(1).docx`). One survives — the copy already sorted into its method folder, with the cleanest name — and the rest are retired. |
| **Quarantine self-healing** | Once a report you re-supplied as a searchable file is parsed and sorted into `input/RT/`, its old image-only copy in `SKIPPED_REPORTS/` is retired. Quarantine keeps meaning *unresolved*. |
| **UnSorted pruning** | A leftover in `input/UnSorted/` that is already sorted into a method folder or archived in `PDF_ARCHIVE/` is retired, so staging stays transient. |

```
  [pruned] KF-RT-26-070_en.docx: duplicate of KF-RT-26-070.docx -> input/_PRUNED/
  [pruned] KF-RT-26-070.docx: replaced by a searchable report -> input/_PRUNED/
  Pruned 12 byte-identical duplicate .docx (kept cleanest name) -> input/_PRUNED/
```

**Nothing is ever deleted.** Retired files are *moved* to [`input/_PRUNED/`](input/), so a
wrong call is reviewable and restorable — empty the folder yourself once you're happy.

Two rules make this safe to run unattended:

* **Every prune is SHA-256 content-verified.** A file is retired only when a
  byte-identical survivor is proven to exist elsewhere. A same-named file whose contents
  *differ* is a genuinely different report that lost a name race — it is always kept for
  you to look at.
* **Housekeeping is global, never scoped.** Like sorting and quarantine, it is correct
  cleanup under any filter, so `--month`/`--method`/`--client` do not narrow it.

Use `--no-clean` to skip all three passes and leave the input tree exactly as found:

```bash
python main.py --no-clean
```

### Repeated runs are deterministic

Run `python main.py` twice over an unchanged `input/` and the second run reports the
**same** `Groups to compile:` count, moves no file, and prints `[Incremental Skip]` for
every group. The rule that buys this: only the stages **before** group discovery may
touch `input/`. Rendering omits rows and says so, but never quarantines their sources —
a file removed after the count was printed would shrink the corpus only in time for the
*next* run, which is how three consecutive runs once reported 104, 102, then 101 groups.

Two consequences worth knowing:

* A report whose in-body ACC-Standard cell holds an unapproved code has its **row
  omitted** and its **file left in place**. The run-end summary names every one:

  ```
    3 report(s) omitted for an unapproved standard — LEFT IN input/ (fix the
    ACC-Standard cell, or add the norm to allowed_standards in config/settings.yaml):
      [unapproved standard] KF-MT-26-042 (2335) (ASME B31.3).docx: unapproved standard
      'EP-GIS-42-103' not listed in butun_standartlar.md — row omitted
  ```

  The clean **filename** standard is still a hard quarantine gate at discovery — the
  noisy body cell only omits, because across the real corpus it holds project doc
  references, edition suffixes and typos.
* Compiled output **is** retired for retired / low-volume clients and for groups that
  render zero rows — but never for an artifact [`.upload_state.json`](#e-keyfiyyet-portal-upload)
  has on record. Those print `retained (uploaded): … not deleted` instead. A compile run
  has no authority to destroy a report already filed on the portal, and the sidecar is
  what the uploader identifies a report *by*, so both halves are kept or neither.

## JSON sidecars (data / presentation decoupling)

Every time `python main.py` saves a compiled monthly report PDF it also writes a
matching `.json` next to it (same folder, same stem). One compiled document is one
client-month across every NDT method (ADR-004), so `ndt_method` is a `/`-joined token
list and each row names its own:

```
output/CLIENT_A/compiled_monthly_report_CLIENT_A_FEB_2026.pdf
output/CLIENT_A/compiled_monthly_report_CLIENT_A_FEB_2026.json
```

The JSON is a **machine-readable mirror** of the PDF — same translated values, same
reporting period — so downstream tools never re-parse a PDF. `client_voen` is always
a **string** (an opaque Tax ID; quoting preserves leading zeros). Schema:

```json
{
  "client_name": "<CLIENT DISPLAY NAME>",
  "client_voen": "0000000000",
  "reporting_period": "Fevral 2026",
  "ndt_method": "DP/MT/UT",
  "ndt_methods": ["DP", "MT", "UT"],
  "report_serial_no": "MR-CLIENT_A-26-02",
  "total_records": 17,
  "items_table": [
    { "seq_no": "1", "date": "18.02.2026", "report_no": "KF-MT-26-011",
      "standard": "EEMUA 158", "method": "MT", "item_name": "Konstruktiv tikiş",
      "result": "Yararlı" }
  ]
}
```

Client VÖENs live in `config/settings.yaml` under `clients:` (one `voen:` per entry).

## E-Keyfiyyet portal integration

`uploader.py` drives the portal upload from a report's JSON sidecar. Start with the
dry run — it prints a colored, step-by-step simulation and launches **no browser**:

```powershell
python uploader.py --dry-run
# or target a specific sidecar:
python uploader.py --dry-run --report output/CLIENT_A/compiled_monthly_report_CLIENT_A_FEB_2026.json
# or sweep every compiled report (resumable):
python uploader.py --dry-run --all
python uploader.py --dry-run --all --method MT --client CLIENT_A --month FEB_2026
```

The target is the government appeal form at
`https://e-keyfiyyet.gov.az/uqq/new-appeal` (configured under `portal:` in
`config/settings.yaml`).

The sections below cover the safety model and the ledger. For all 17 uploader flags —
including `--probe`, `--pdf`, `--ledger`, `--url` and `--slow` — see
[`CLI_MANUAL.md`](CLI_MANUAL.md#3-uploaderpy--e-keyfiyyet-portal-upload).

### Safety model

This writes to a live government system, so three brakes apply and none of them are
optional:

| Brake | Effect |
| --- | --- |
| `MAX_REPORTS_PER_RUN = 1` | Exactly one report per run — even with `--all`. The summary reports how many were held back. An *interactive* live run replaces this cap with a person: see below. |
| `--live` required | Without it the form is filled and left for review; `Yadda saxla` is never clicked and the ledger is not touched. |
| No e-signature, ever | `E-imza ilə təsdiqlə` is never located and never clicked. Signing stays a human decision. |
| Zero substitution | A standard the portal does not offer is never stood in for. The whole report is skipped instead — see below. |

`--live` also refuses to start until `portal.director` (FİN, seriya nömrəsi, name) is
filled in `config/settings.yaml`.

### Standards: zero substitution

The portal offers a fixed list of normative documents (`PORTAL_STANDARDS`, 21 entries
since 2026-10-06, typed by the operator from a screenshot and NOT yet probe-verified;
the 16 measured by `--probe` on 2026-08-12 were replaced and are kept in
`standarts/in_portal_2026-08-12.md`). It is deliberately NOT the company's master
list: `standarts/butun_standartlar.md` holds the 37 standards we inspect against and
`standarts/in_portal.md` the 21 the portal carries. Widening the constant to the master
list would make `--dry-run` promise filings the live form refuses.

A cell may name several documents ("API 1104 & ASME IX"); `split_standards` cuts it on
`;`, `&`, the word `and`, and on `/`, `,` or `+` when whitespace flanks them — never
inside one name (`EEMUA 153/158`, `ASTM E797/E797M`, `EEMUA 158,Edition 3,…`). Each
part is matched on its own and **all** must be offered: one unoffered part refuses the
whole report, exactly as a lone unoffered standard does. There is no partial filing.

Comparison folds typographic look-alikes first (`_normalize_typography`: NFKC, plus
U+2010–U+2015/U+2212/U+FF0D to `-` and curly quotes to straight). That is an
appearance identity — it can only merge two spellings of one name, never two names;
`ISO 17636` and `ISO 17638` differ in a digit, which nothing there touches.

A report's standards are matched exactly, then by whole-token subset, then by core,
then through the `portal.standard_aliases` range map — every one of those rules names
the *same* document, so all are safe to file.

Anything else is **not substituted**. No placeholder, no method standard for the
discipline. The report is skipped whole with `SKIPPED_UNMATCHED_STANDARD`: nothing is
typed, nothing is saved, and no ledger entry is written — so the report is re-offered
by every later run and uploads itself the day the portal lists the standard. A
government appeal must never name a document the inspection was not assessed against,
draft or otherwise.

This is a real cost: only ~21% of the corpus by row count can be named exactly
(`ASME B31.3` alone is 223 rows and has no portal entry), so most reports will not file
until the portal's list grows or `standard_aliases` maps them to an aggregate option
the portal really does offer. See exactly which, without a browser:

```powershell
python uploader.py --dry-run --all
```

The mirror case is a report citing **no** standard at all — every `standard` cell blank,
as the PMI and ferrite families are. The portal will not accept an appeal that names no
normative document, so those are skipped whole too, with `SKIPPED_EMPTY_STANDARD`, on
identical terms: nothing typed, nothing saved, no ledger entry. This one is fixable
here rather than by the portal — put the standard in the source document and re-run;
the end-of-run summary names every report waiting on it.

### Authentication

Manual and persisted, never scripted. The run opens a Chrome window against the
profile at `portal.user_data_dir` (`.browser_profile/`, git-ignored). Log in there
**once** by hand; the session cookie stays in that directory and later runs reuse it.
The script never handles a portal password.

> This replaces a CDP takeover of your everyday Chrome, which is not achievable:
> port 9222 only exists if Chrome was *started* with `--remote-debugging-port=9222`,
> and Chrome 136+ refuses that flag on the default profile — so an already-open
> window cannot be attached to without relaunching it anyway.

### Live run

```powershell
pip install -r requirements.txt
playwright install chromium

# 1. Read-only: dump the real form's controls so selectors can be verified.
python uploader.py --probe          # writes output/portal_form_probe.json

# 2. Fill one report's form but do NOT save it — review it in the window.
python uploader.py --report <file>.json

# 3. Fill AND save one draft appeal. Review + e-sign it manually in the portal.
python uploader.py --live --report <file>.json

# 4. The whole month, one browser session, one decision per report.
python uploader.py --live --all --interactive
```

### Interactive batch — inspect each form, then decide

```powershell
python uploader.py --live --all --interactive
```

Every matched report is filled in the open window and the run then **stops and asks**,
in the terminal, before `Yadda saxla`:

```text
----------------------------------------------------------------------
[INTERACTIVE CONFIRMATION] Report <SERIAL> (<CLIENT>) form filled on screen.
Inspect the open browser window. Choose action:
  [Enter] or 'y' : SAVE draft appeal & proceed to next report
  's'            : SKIP this report (do not save)
  'q'            : QUIT batch upload session
----------------------------------------------------------------------
Your choice [Y/s/q]:
```

| Answer | What happens |
| :--- | :--- |
| `[Enter]` / `y` | Clicks `Yadda saxla`, waits for the redirect to `/uqq/projects`, records `UPLOADED`, moves to the next report |
| `s` | Saves nothing, leaves the ledger exactly as it was, reloads the form so the next report starts clean |
| `q` | Ends the batch there and closes the browser; every remaining report stays pending |
| Ctrl-C / closed stdin | Same as `q` — no operator, no draft |

One Python process, one login, one browser: the session stays up across the whole
batch. The prompt is **on by default** for `--live --all` on a terminal and lifts the
one-report cap (the operator is the brake); `--no-interactive` turns it off, and it
disables itself automatically when stdin is not a terminal — which is what keeps the
GUI, which runs this as a piped child process, from blocking on a question nobody can
see. An explicit `--limit N` still caps an interactive run.

**Run `--probe` first.** The portal needs an authenticated session, so its markup
could not be read while `uploader.py` was written — the locators in `upload_report`
are derived from the field labels in the spec, not from the live DOM, and should be
reconciled against the probe output before any `--live` run. When a fill fails, a
screenshot and DOM dump land in `output/failures/` so the miss is diagnosable.

A confirmed save appends a `SUCCESS` record to `output/upload_status.json` (a
human-readable audit trail; `.upload_state.json` still owns idempotency).

### Upload state: never send the same report twice

An upload is a side effect on the portal's database, so every run is gated by a
durable state ledger — `.upload_state.json` at the project root (`--dry-run` uses its
own `.upload_state.dryrun.json`, so simulating can never suppress a real upload).
Each entry records a **SHA-256 over the sidecar's bytes plus the PDF's bytes**, so a
report is identified by its *content*, not its timestamp:

| Ledger state | What the next run does |
| :--- | :--- |
| never seen | uploads it |
| `UPLOADED`, content unchanged | **skips it** — repeat runs are a safe no-op |
| `UPLOADED`, content changed | **re-uploads it** — a regenerated report after a data correction is detected and sent again, not skipped forever |
| `IN_PROGRESS` (died mid-submit) | **flags and skips it** — see below |

The ledger is written *before* the submit (`IN_PROGRESS`) and again *after*
(`UPLOADED`), and flushed atomically each time. That checkpoint is what makes a batch
resumable: if `--all` drops at report 5 of 10, reports 1–4 are already recorded and
are skipped on the next run, and reports 6–10 were never touched, so they upload
normally.

Report 5 is the honest edge case. A leftover `IN_PROGRESS` means the process died
*during* the submit — the portal may or may not have committed the row, and there is
no way to know from this side. Retrying blindly is the exact duplicate the ledger
exists to prevent, so it is flagged and skipped. Verify that report on the portal,
then push it through explicitly:

```powershell
python uploader.py --all --force        # send flagged (interrupted) reports anyway
```

To reset state by hand, delete the report's key from `.upload_state.json` (it is
plain, readable JSON), delete the whole file to reset everything, or:

```powershell
python uploader.py --reset output/CLIENT_A/compiled_monthly_report_CLIENT_A_FEB_2026.pdf
```

> A client-side ledger gives *at-most-once for reports that completed*, plus an
> explicit flag on the single in-flight one. True exactly-once needs an idempotency
> key accepted by the portal — which needs the REST API described next.

### Prefer a hidden REST API over UI automation

Driving the browser is the most fragile and slowest way to move data. Before relying
on UI automation, **check whether the portal exposes an internal JSON API** — one
authenticated request can replace the whole click-through form, and it is immune to
markup changes between releases. Once you have portal access:

1. Open the portal in **Google Chrome** and press **F12** (DevTools).
2. Go to the **Network** tab and click the **Fetch/XHR** filter.
3. Perform the action you want to automate (log in, open the upload page, submit a
   report) and watch the requests that appear.
4. Look for calls to paths like `…/api/…`, `…/rest/…`, or any request whose
   **Response** is `application/json`. Select one and inspect:
   - **Headers** — the method (`GET`/`POST`), the full URL, and the auth token /
     session cookie the browser already sends.
   - **Payload** — the JSON body the form posts (field names map to our sidecar).
   - **Response** — the JSON the server returns on success.
5. Right-click a promising request → **Copy → Copy as cURL** to replay it outside the
   browser and confirm it works with just the auth token.

If a stable JSON endpoint exists, wire it into `uploader.py` as a direct
authenticated request (reusing the logged-in session) instead of the form-filling
flow — faster, deterministic, and drift-proof. Reserve the Playwright UI path for
when no such endpoint is reachable.

## AI-Augmented Engineering: an LLM-Driven Development case study

This suite is deliberately presented as a case study in **LLM-Driven Development (LDD)** — a
disciplined workflow in which large language models are collaborators under a hard test gate, not
autocomplete. The engineering value on display is as much *process* as it is code.

**Graphify — archived, not used.** A graphify knowledge graph was built once (2026-07-21) and is now
stale; it and the project copy of the skill are archived, not used. See `_archive/README.md`. The
current map is `docs/INDEX.md`.

**A rigorous, iterative prompt-engineering loop.** Features were specified, decomposed, and driven
through explicit prompts to two model families used for their complementary strengths — **Claude Fable
5** and **Gemini** — with each proposed change reviewed, reconciled, and constrained by the existing
architecture (config-first design, decoupled data/presentation, idempotent side effects) before it
landed. The prompts themselves are committed in [`Claude outputs/`](Claude%20outputs/) — one file
per step (inventory, code map, verdict gate, coverage fixes, portal-list probe, privacy scrub) —
and the decisions they produced are recorded as ADRs in [`architecture/`](architecture/).

**Test-driven development as the non-negotiable gate.** Every stage — method/client resolution, date
detection, extraction, translation flagging, retest tracing, the JSON sidecar contract, the upload
ledger's state machine, GUI process arguments — is pinned by tests. The result is a **2,253-test pytest
suite** that runs as the quality gate on every change:

```powershell
pytest -q
```

The payoff is behavior you can trust under refactoring: the ledger's `IN_PROGRESS`/`UPLOADED` invariants,
the SHA-256 idempotency contract, and the "one report per run" safety brake are all executable
specifications, not prose promises.

## Maintainability principles

- **Configuration-first:** evolving fields, methods, clients, and terminology change in YAML/JSON, not code.
- **Layout isolated:** all PDF layout lives in `src/monthly_report/pdf_renderer.py`.
- **Data/presentation decoupled:** every PDF has a JSON twin; downstream tools read data, never pixels.
- **Idempotent side effects:** uploads are content-hashed and checkpointed; repeats are safe no-ops.
- **Auditable translation:** untranslated segments are flagged for follow-up, never silently dropped.
- **Self-contained:** no system-level native dependencies — reliable Windows automation.
- **Test-gated:** a 2,253-test suite guards every stage.

## Publishing this repository

This project is engineered for safe public release. Secrets and generated artifacts are excluded by
[`.gitignore`](.gitignore); only [`config/settings.example.yaml`](config/settings.example.yaml) (with
placeholders) is committed, never your real `config/settings.yaml` or `.browser_profile/`. After
cloning, copy the template and fill it in as shown in [Developer setup](#developer-setup-windows--powershell).

The public repository ([SelimNajaf/monthly-report-system](https://github.com/SelimNajaf/monthly-report-system))
is a single-commit snapshot of the working repository, without its development history: earlier
commits carried personal identifiers that were later replaced by fakes in the files themselves.
Personal IDs (FİN, ID-card series, VÖENs) and the LAN host are fakes; the source documents, the
compiled reports, the portal session and the upload ledger are not included.

---

<div align="center">
Built by <a href="https://github.com/SelimNajaf">Selim Najaf</a> — an LLM-Driven Development portfolio project.
</div>
