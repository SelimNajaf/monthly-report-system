# INDEX — where everything is

One line per item. Sources: `docs/INVENTORY_2026-09-28.md` (classes), `docs/CODE_MAP_2026-09-28.md`
(roles, stages), `config/settings.example.yaml`, `architecture/`. Kept honest by `tests/test_index_sync.py`:
every root item, every `src/monthly_report/**/*.py` and every `scripts/*.py` must be listed here, and every
backticked path here must exist unless its line is marked `(runtime)`.

`(runtime)` = created at run time, machine-local, untracked or gitignored — may be absent on a clean checkout.

Classes (from the inventory): entrypoint · core-code · helper-script · test · config · docs-current ·
docs-stale · agent-tooling · operator-data · generated · backup.

Stages (CODE_MAP labels): `-1 LAN` · `0 read` · `1 group` · `2 render` · `3 upload` · util · GUI · audit.
`main.py` prints its own numbering (e.g. "STAGE 0-LAN" for `-1 LAN`); mapping in CODE_MAP's header.

## 1. Root

| path | what | class |
|---|---|---|
| `.agents/` | project skill library (17 skills + `.agents/skills/README.md`); the slash-command skill convention reads here | agent-tooling |
| `.browser_profile/` | live portal session cookie — red line (runtime) | operator-data |
| `.claude/` | local Claude Code folder; `.claude/skills/` is empty since graphify moved to `_archive/` (runtime) | agent-tooling |
| `.gitattributes` | EOL rules (`*.py`, `*.md` LF in the repo) | config |
| `.gitignore` | secrets, operator data, `_archive/*`, build output | config |
| `.parse_cache/` | content-hash parse cache — red line (runtime) | operator-data |
| `.pytest_cache/` | pytest scratch (runtime) | generated |
| `.state/` | LAN sync manifest, GUI metrics, cache stats, quarantine reasons — red line (runtime) | operator-data |
| `.upload_state.json` | live idempotency ledger — red line (runtime) | operator-data |
| `.upload_state.dryrun.json` | separate ledger used by `--dry-run` (runtime) | operator-data |
| `CLAUDE.md` | auto-loaded agent brief: rules, red lines, traps | docs-current |
| `CLI_MANUAL.md` | every entry point's flags; drift-tested by `tests/test_cli_manual_sync.py`; must stay at root | docs-current |
| `Claude outputs/` | the operator's prompts, one per development step; committed 2026-10-08 as the LDD record (README) | docs-stale |
| `README.md` | public overview, setup, portal safety model; `pyproject.toml` `readme` | docs-current |
| `TODO.md` | open items only; history in `docs/history/TODO_journal.md` | docs-current |
| `__pycache__/` | bytecode of the root `.py` files (runtime) | generated |
| `_archive/` | retired backups, stale output, old graph; gitignored except `_archive/README.md`; never delete | backup |
| `architecture/` | ADR-001…010 | docs-current |
| `assets/` | fonts (`assets/fonts/`; TTF files ignored, README tracked) | config |
| `config/` | settings template + dead `config/fields.yaml` | config |
| `corpus/` | ADR-003 verdict-gate corpus: `corpus/verdict_regression/<ID>.pdf` (630 pinned copies) + `SOURCES.tsv`; built by `scripts/build_verdict_corpus.py`; gitignored, never committed (runtime) | operator-data |
| `discover_network_share.py` | read-only LAN share scanner CLI + shared primitives; imported by the package | helper-script |
| `docs/` | this index, code map, inventory, `docs/history/` | docs-current |
| `file_paths_ex.md` | local list of LAN paths; ignored, contains a real host name (runtime) | operator-data |
| `generate_inspector_worksheet.py` | one-page inspector-assignment PDF; nothing calls it | helper-script |
| `generate_pipeline_summary.py` | on-demand Azerbaijani executive-summary PDF from live state | helper-script |
| `gui_launcher.py` | opens the GUI or dispatches `--worker <kind>` | entrypoint |
| `images/` | header logo and stamp (`images/Mag-Pi Logo.png`, `images/Mohur Logo.png`) | config |
| `input/` | source reports, `PDF_ARCHIVE`, `SKIPPED_REPORTS`, `_PRUNED` — red line (runtime) | operator-data |
| `main.py` | pipeline orchestrator, stages -1…2 — red line | entrypoint |
| `output/` | compiled PDFs + sidecars, audit `.md` files — red line; only `output/.gitkeep` tracked | operator-data |
| `pyproject.toml` | package metadata, `monthly-report` console script, pytest config | config |
| `reports/` | export copy of `output/`: `PDF\|JSON/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>`; written by `main.py` when `export.enabled`; gitignored, never deletes (runtime) | generated |
| `requirements.txt` | pinned dependencies for the setup scripts | config |
| `reset_and_sync_input.py` | **destructive**: wipes `input/`, then cutoff-dated LAN sync | helper-script |
| `reset_upload_ledger.py` | empties the ledger, keeps file and schema | helper-script |
| `samples/` | demo documents kept out of `output/`; ignored (runtime) | operator-data |
| `scripts/` | read-only audit scripts, one prune tool, the verdict-corpus builder | helper-script |
| `setup.ps1` | Windows bootstrap | config |
| `setup.sh` | Unix bootstrap | config |
| `skills-lock.json` | `npx skills` lock (caveman, find-skills) | agent-tooling |
| `src/` | package root (`src/monthly_report/`) | core-code |
| `standarts/` | standards lists (spelling deliberate; a test path depends on it) | config |
| `tests/` | pytest suite + `tests/data/` fixtures (incl. `tests/data/verdict_corpus.sha256`, the verdict corpus's 630 pinned hashes) | test |
| `translations/` | `translations/az.json` EN→AZ dictionary | config |
| `uploader.py` | Playwright portal filler, stage 3 — red line (ADR-002) | entrypoint |

Inside folders, worth knowing:

- `config/settings.example.yaml` — the committed template; the live file is `config/settings.yaml` (runtime).
- `config/settings.yaml` — live config with client IDs; gitignored, absent on a fresh clone (runtime).
- `config/settings.yaml.bak` — written by `src/monthly_report/gui/services/settings_writer.py` (runtime).
- `src/monthly_report_auto.egg-info/` — stale `pip install -e .` leftover (runtime).
- `docs/CODE_MAP_2026-09-28.md` — module map, unknowns with evidence, dead-code candidates.
- `docs/INVENTORY_2026-09-28.md` — every root item with class and evidence.
- `docs/history/` — `docs/history/TODO_journal.md`, `docs/history/PROJECT_CONTEXT_2026-09-03.md`,
  `docs/history/SKILLS_MANIFEST.md`, `docs/history/handoffs/`. History, not current state.
- `standarts/butun_standartlar.md` — company master list (drift-tested); `standarts/in_portal.md` — the portal's list (21, provisional, 2026-10-06); `standarts/in_portal_2026-08-12.md` — the old 16.

## 2. Package `src/monthly_report/`

| path | what | stage |
|---|---|---|
| `src/monthly_report/__init__.py` | package root, `__version__` | util |
| `src/monthly_report/cli.py` | `monthly-report` console script; one month, skips grouping/sidecar/ledger/crosscheck (legacy path) | 2 render |
| `src/monthly_report/config.py` | loads `config/settings.yaml`, resolves paths, fails fast on missing fonts | util |
| `src/monthly_report/console.py` | safe `print` on Windows cp125x consoles; `progress_printer` | util |
| `src/monthly_report/coverage_audit.py` | `audit.coverage_report`: every source file under `input/` gets one outcome → `output/coverage_<date>.md` + one `Coverage:` stdout line | audit |
| `src/monthly_report/date_detector.py` | primary inspection date, month filter, date repair from the PDF twin | 1 group |
| `src/monthly_report/document_aggregator.py` | builds one `MonthlyReport`: rows, retest numbering, merges, ranges, pulled parents | 1 group |
| `src/monthly_report/docx_reader.py` | `.docx` tables to text grids; routes `.pdf` to the PDF readers; process pool | 0 read |
| `src/monthly_report/duplicate_identity.py` | merges transposed Report № pairs (ADR-005) | 1 group |
| `src/monthly_report/extractor.py` | header-driven meta + weld-row extraction | 0 read |
| `src/monthly_report/inspector_registry.py` | picks the signing inspector per client from `inspector_matrix` | 1 group |
| `src/monthly_report/json_exporter.py` | writes the JSON sidecar next to each PDF | 2 render |
| `src/monthly_report/method_registry.py` | method/client detection; approved/active/volume/allowed_standards gates | util |
| `src/monthly_report/naming.py` | month tables, folder names, document number, default output path | util |
| `src/monthly_report/parse_cache.py` | content-hash parse cache in `.parse_cache/` | 0 read |
| `src/monthly_report/pdf_crosscheck.py` | compares the two PDF readers; verdict disagreement quarantines (ADR-003) | 0 read |
| `src/monthly_report/pdf_reader.py` | PyMuPDF direct PDF reading, two independent reconstructions (ADR-003) | 0 read |
| `src/monthly_report/pdf_renderer.py` | ReportLab A4 Azerbaijani PDF — the only module that knows layout (ADR-001) | 2 render |
| `src/monthly_report/pdf_twin.py` | finds a report's original PDF in `PDF_ARCHIVE` | 0 read / 1 group |
| `src/monthly_report/pre_processor.py` | `input/` tree: PDF archive, sort, prune, `discover_groups`, quarantine | 0 read / 1 group |
| `src/monthly_report/report_identity.py` | Report № rules: retest markers, comparison keys, filename vs body | util |
| `src/monthly_report/report_no_mismatch.py` | filename serial ≠ body serial: warn every run, optional block (ADR-008) | 1 group |
| `src/monthly_report/retest_tracker.py` | cross-month parent pull + `pull_weld_check` (ADR-006/007) | 1 group |
| `src/monthly_report/text_norm.py` | `İ`-safe casefold, typography and blank normalisation | util |
| `src/monthly_report/translator.py` | EN→AZ via `translations/az.json`; unknowns flagged | 2 render |
| `src/monthly_report/upload_ledger.py` | `.upload_state.json` ledger: `IN_PROGRESS`/`UPLOADED`, content hash | 3 upload |
| `src/monthly_report/services/__init__.py` | headless service package (not the GUI one) | util |
| `src/monthly_report/services/ingestion_registry.py` | O(1) fingerprint index over `.state/network_sync_manifest.json` | -1 LAN |
| `src/monthly_report/services/network_ingestion.py` | `sync_from_lan`: LAN share → `input/UnSorted/`; cutoff bulk sync | -1 LAN |
| `src/monthly_report/services/report_export.py` | `export_reports`: copies compiled PDF + sidecar into `reports/` (hash compare, atomic, orphans listed) | 2 render |
| `src/monthly_report/gui/__init__.py` | docstring only | GUI |
| `src/monthly_report/gui/app.py` | composition root: settings, fonts, `MainWindow` | GUI |
| `src/monthly_report/gui/worker_entry.py` | `--worker pipeline\|upload` child: sets `_ROOT`, calls `main.main` / `uploader.main` | GUI |
| `src/monthly_report/gui/services/__init__.py` | GUI service layer; QtCore allowed, QtWidgets not | GUI |
| `src/monthly_report/gui/services/ansi.py` | ANSI SGR → coloured spans | GUI |
| `src/monthly_report/gui/services/app_paths.py` | app root, settings, `.state`, launcher path; frozen vs source | GUI |
| `src/monthly_report/gui/services/cache_service.py` | parse-cache status, size, purge | GUI |
| `src/monthly_report/gui/services/cache_stats_service.py` | last run's cache hit/miss in `.state/cache_stats.json` | GUI |
| `src/monthly_report/gui/services/catalog.py` | scans `output/` into a catalog; `_parse_stem` — **imported by `main.py`** | GUI (+ main) |
| `src/monthly_report/gui/services/ingest_service.py` | copies dropped files into `input/` | GUI |
| `src/monthly_report/gui/services/job_runner.py` | QProcess child runner, stdout stream, cancel | GUI |
| `src/monthly_report/gui/services/ledger_service.py` | read-only ledger projection; single-entry reset | GUI |
| `src/monthly_report/gui/services/metrics.py` | three disk counts: documents, generated, quarantined | GUI |
| `src/monthly_report/gui/services/metrics_history_service.py` | last run's counts and deltas | GUI |
| `src/monthly_report/gui/services/progress.py` | progress events parsed from stdout | GUI |
| `src/monthly_report/gui/services/quarantine_reasons_service.py` | captures `[quarantine]` reasons into `.state/quarantine_reasons.json` | GUI |
| `src/monthly_report/gui/services/quarantine_service.py` | `SKIPPED_REPORTS` listing, open / reveal file | GUI |
| `src/monthly_report/gui/services/settings_service.py` | settings load, health / pre-flight, portal readiness | GUI |
| `src/monthly_report/gui/services/settings_writer.py` | atomic write of the 5 `portal.director` values, keeps a .bak copy | GUI |
| `src/monthly_report/gui/services/summary_exporter.py` | dashboard summary to CSV / JSON | GUI |
| `src/monthly_report/gui/ui/__init__.py` | docstring only | GUI |
| `src/monthly_report/gui/ui/main_window.py` | window; one-job-at-a-time; builds pipeline/upload args | GUI |
| `src/monthly_report/gui/ui/theme.py` | colours, fonts, QSS; installs DejaVu fonts | GUI |
| `src/monthly_report/gui/ui/pages/__init__.py` | re-exports the 4 pages | GUI |
| `src/monthly_report/gui/ui/pages/dashboard_page.py` | metrics, controls, live progress, terminal | GUI |
| `src/monthly_report/gui/ui/pages/quarantine_page.py` | quarantine list (human-in-the-loop queue) | GUI |
| `src/monthly_report/gui/ui/pages/settings_page.py` | pre-flight list, director form, resolved paths | GUI |
| `src/monthly_report/gui/ui/pages/uploader_page.py` | ledger table, upload modes | GUI |
| `src/monthly_report/gui/ui/widgets/__init__.py` | re-exports widgets | GUI |
| `src/monthly_report/gui/ui/widgets/badge.py` | status pill for table cells | GUI |
| `src/monthly_report/gui/ui/widgets/console_view.py` | live terminal for child stdout | GUI |
| `src/monthly_report/gui/ui/widgets/drop_zone.py` | file drop target | GUI |
| `src/monthly_report/gui/ui/widgets/metric_card.py` | animated number card | GUI |
| `src/monthly_report/gui/ui/widgets/page_header.py` | shared page header strip | GUI |
| `src/monthly_report/gui/ui/widgets/preflight_dialog.py` | portal readiness pass/fail modal | GUI |
| `src/monthly_report/gui/ui/widgets/sidebar.py` | left navigation | GUI |
| `src/monthly_report/gui/ui/widgets/status_pill.py` | coloured dot + status word | GUI |

No GUI page or widget has a direct test.

## 3. Root `.py` files

All find their paths via `Path(__file__).parent` — moving one breaks it.

| path | what | stage |
|---|---|---|
| `main.py` | orchestrator: LAN → PDF archive → sort → housekeeping → parse → groups → PDF + sidecar; incremental | -1…2 |
| `uploader.py` | fills the portal appeal form; saves only with `--live`; never signs; ledger-idempotent | 3 upload |
| `gui_launcher.py` | GUI entry and `--worker` dispatcher | GUI |
| `discover_network_share.py` | LAN scanner CLI; primitives imported by `src/monthly_report/services/network_ingestion.py` | -1 LAN |
| `generate_pipeline_summary.py` | executive-summary PDF from sidecars, `input/`, `.parse_cache/`, `.state/`, ledger | audit |
| `generate_inspector_worksheet.py` | inspector-assignment PDF; no caller, no test | audit |
| `reset_and_sync_input.py` | deletes `input/`, then cutoff-dated LAN sync (manual, destructive) | -1 LAN |
| `reset_upload_ledger.py` | empties the ledger (manual) | 3 upload |

Also: `standarts/generate_add_portal_request.py` — one-off generator of the standards request `.docx`/`.pdf`; no caller.

## 4. `scripts/`

| path | what | stage |
|---|---|---|
| `scripts/audit_duplicate_identity.py` | read-only measurement of transposed Report № pairs; source of ADR-005 | audit |
| `scripts/audit_item_detail.py` | read-only İtem/Detal trailing-colon audit; translation review table | audit |
| `scripts/audit_retest_rollup.py` | read-only measurement of what retest roll-up changes | audit |
| `scripts/build_verdict_corpus.py` | copies the 630 ADR-003 gate PDFs from `PDF_ARCHIVE`/`SKIPPED_REPORTS` into `corpus/verdict_regression/`; hash-pinned, idempotent, `--dry-run`; reads `input/`, never moves or deletes | test |
| `scripts/prune_lan_duplicates.py` | one-off operator tool: moves `-lan` duplicates to `_PRUNED`, cleans PDF names | 0 read |

## 5. Config keys (`config/settings.example.yaml`)

Values are not listed — they change. Read the template's comments and the live `config/settings.yaml`.

| key | what | ADR |
|---|---|---|
| `presentation.collapse_ranges` | draw consecutive identical reports as one range line | none (referenced in ADR-006, ADR-009) |
| `presentation.rollup_retests` | print a retest chain as one line carrying the final verdict | none (referenced in ADR-006, ADR-009) |
| `presentation.unfit_placement` | Yarasız rows inline or in a separate section after the main table | none (referenced in ADR-006, ADR-009) |
| `presentation.split_ranges_on_item` | a different İtem breaks a range | none (referenced in ADR-006, ADR-009) |
| `presentation.pulled_parent_style` | how a cross-month pulled parent is drawn (plain / marked / hidden) | ADR-006 |
| `presentation.range_mode` | strict rules or one line per report number | ADR-009 |
| `presentation.range_tail_allow` | number tails allowed to range under by_number | ADR-009 |
| `presentation.range_absorb_tails` | one-letter number tails (`010A`) that take their base number's slot in a by_number range | ADR-009 |
| `presentation.range_ignore_tag` | a different job tag no longer breaks a by_number range | ADR-009 |
| `presentation.range_merge_standards` | a different standard no longer breaks a by_number range | ADR-009 |
| `presentation.range_item` | split or dominant İtem in a by_number range | ADR-009 |
| `presentation.range_item_blank_methods` | methods whose multi-item range prints "—" as İtem | ADR-009 |
| `presentation.row_order` | order of method blocks | ADR-009 |
| `presentation.row_style` | table body shading | ADR-009 |
| `filtering.min_total_client_volume` | client volume floor | none |
| `filtering.merge_duplicate_identities` | merge transposed Report № pairs | ADR-005 |
| `filtering.block_mismatched_report_no` | keep a filename≠body copy out of the document | ADR-008 |
| `filtering.reject_item_header_labels` | a column header (`Qty`, S/N, `DetailNo`, `Number of holes`) or N/A read as the Item: value is rejected; fallback to Description (default off) | none |
| `filtering.exclude_delete_folder_sources` | a source whose bytes match a share file under a `delete` folder feeds no row; reason "from delete folder" (default off) | none |
| `filtering.collapse_standard_spaces` | collapse runs of blanks inside a standard's name | none |
| `retest.pull_weld_check` | require weld evidence before a cross-month pull | ADR-007 |
| `network_ingestion.stage_size_mismatch` | stage a same-name LAN file whose size differs as a `-lan` twin (default off); a share folder named `delete` is never staged | none |
| `network_ingestion.stage_size_mismatch` | stage a same-name LAN file whose size differs as a `-lan` twin (default off); a share folder named `delete` is never staged | none |
| `audit.coverage_report` | write `output/coverage_<date>.md` and print `  Coverage: N sources, M in documents, K explained elsewhere, U UNEXPLAINED` (default off) | none |
| `export.enabled` / `export.dir` / `export.from_month` | copy compiled PDF + sidecar into `reports/` after each `main.py` run (default off) | none |
| `portal.standard_policy` | `all`: one unoffered standard refuses the report; `any`: file the offered ones, print the rest | ADR-010 |
| `portal.hold_documents` | document IDs (`UBOC_FEB_2026`) the operator holds back; refused before any browser action, ledger untouched (default `[]`) | ADR-010 addendum |
| `portal.upload_closed_months_only` | `true` = a document for the current (Asia/Baku) or a later month is refused before any browser action, ledger untouched (default `false`) | ADR-010 addendum (D6) |

## 6. Known quirks

- **Two `services` packages.** `src/monthly_report/services/` is headless (LAN ingestion);
  `src/monthly_report/gui/services/` is the GUI layer. Same name, different roles. Headless code imports
  the GUI one: `main.py` → `src/monthly_report/gui/services/catalog.py` `_parse_stem`; `generate_pipeline_summary.py` → four GUI services.
- **`sys.path` hack.** `src/monthly_report/services/network_ingestion.py` puts the repo root on `sys.path`
  to import the root script `discover_network_share.py` (layering inverted).
- **`assets/` has no `stitch` folder.** `src/monthly_report/gui/ui/theme.py` mentions it in a comment only;
  no runtime behaviour.
- **`config/fields.yaml` is dead.** No `.py` has ever read `paths.fields_config`; extraction is hardcoded
  in `src/monthly_report/extractor.py`.
- **`generate_inspector_worksheet.py` hardcodes person names** in a module-level list, against
  `src/monthly_report/inspector_registry.py`'s "no inspector name is hardcoded" claim.
- **`src/monthly_report/pdf_twin.py` docstring is stale**: it says every PDF is converted to `.docx`; since
  ADR-003 nothing is converted.
- **`src/monthly_report/cli.py` diverges from `main.py`**: it skips grouping, sidecar, ledger and crosscheck.
- **`output/upload_status.json` is stale** (runtime): records from before the 2026-09-04 ledger reset;
  `generate_pipeline_summary.py` reads it.
