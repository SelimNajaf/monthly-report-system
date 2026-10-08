# F1 — Layihə inventarı (2026-09-28)

> Yalnız oxu. Heç bir fayl köçürülməyib, silinməyib, dəyişdirilməyib. Yeganə yaradılan fayl budur.
> Branch: `feature/parse-cache-incremental-ingestion`, HEAD `ece881b` (2026-09-28).
> Sübut üsulu: `git ls-files`, `git check-ignore`, `git log`, `git grep`, `du -sh`, `diff -rq`.
> İstinad sütunu yalnız `*.py *.toml *.ps1 *.sh *.yaml *.json *.txt` fayllarında `git grep` nəticəsidir (ən çox 3); ümumi söz kimi yalançı uyğunluqlar əl ilə təmizlənib və ya dəqiq sətirlə əvəz olunub.
> Bilinməyən = **UNKNOWN / NEEDS VERIFICATION**.
> Gizli sirr faylların (`config/settings.yaml`, `.upload_state.json`, `file_paths_ex.md`) məzmunu buraya köçürülməyib.

Əlavə ölçmələr (bu sessiya, yazmadan):

- `pytest --collect-only -q -p no:cacheprovider` → **1928 tests collected**. Tam suite işlədilməyib.
- `pytest tests/test_cli_manual_sync.py -p no:cacheprovider` → **15 passed** (CLI_MANUAL parser-lərlə sinxrondur).
- Test faylı sayı: **67** (`tests/test_*.py`).

---

## 1. Cədvəl

"son dəyişiklik": `git` = son commit tarixi, `fs` = diskdəki mtime. `input/`, `output/` içinə enilməyib.

| path | növ | ölçü | git-də? | son dəyişiklik | kim istinad edir | sinif | təklif |
|---|---|---|---|---|---|---|---|
| `.agents` | dir | 272K | tracked | git 2026-07-20 / fs 2026-07-10 | .agents/skills/README.md:38 (yalnız sənəd) | agent-tooling | **keep** — 17 layihə skill-i; `/skill-name` konvensiyası bura baxır. |
| `.browser_profile` | dir | 80M | ignored | fs 2026-09-18 | config/settings.example.yaml:607, uploader.py:3190, uploader.py:3246 | operator-data | **keep** — Canlı portal sessiyası; qırmızı xətt. |
| `.claude` | dir | 101K | tracked | git 2026-07-20 / fs 2026-07-14 | yoxdur | agent-tooling | **keep** — Yalnız `skills/graphify` (v0.9.15); qlobal kopya v0.9.30 — Sual 4-ə bax. |
| `.gitattributes` | file | 348B | tracked | git 2026-07-22 / fs 2026-07-22 | yoxdur (git özü oxuyur) | config | **keep** — EOL qaydaları. |
| `.gitignore` | file | 4K | tracked | git 2026-09-24 / fs 2026-09-24 | src/monthly_report/gui/services/settings_writer.py:25 | config | **keep** — `_archive/` sətri əlavə olunmalı olacaq (F2). |
| `.parse_cache` | dir | 22M | ignored | fs 2026-09-28 | config/settings.example.yaml:292, generate_pipeline_summary.py:5, generate_pipeline_summary.py:516 | operator-data | **keep** — Canlı parse cache (3720 fayl); qırmızı xətt. |
| `.pytest_cache` | dir | 219K | ignored | fs 2026-07-15 | yoxdur | generated | **keep** — pytest yaradır, ignored; zərərsiz. |
| `.state` | dir | 3.2M | ignored | fs 2026-09-28 | generate_pipeline_summary.py:5, generate_pipeline_summary.py:1066, reset_and_sync_input.py:17 | operator-data | **keep** — GUI/LAN state; qırmızı xətt. |
| `.upload_state.json` | file | 40B | ignored | fs 2026-09-04 | generate_pipeline_summary.py:6, generate_pipeline_summary.py:481, generate_pipeline_summary.py:489 | operator-data | **keep** — Canlı idempotency ledger; qırmızı xətt. |
| `CLI_MANUAL.md` | file | 22K | tracked | git 2026-09-18 / fs 2026-09-08 | tests/test_cli_manual_sync.py:35, main.py:46 | docs-current | **keep** — Drift testi ilə qorunur (15 passed, 2026-09-28); root-da qalmalıdır — test `_ROOT / "CLI_MANUAL.md"` oxuyur. |
| `Claude outputs` | dir | 80K | tracked | git 2026-09-18 / fs 2026-09-28 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — Prompt/handoff arxivi; adında boşluq var; kod istinadı yoxdur. Sual 6. |
| `HANDOFF.md` | file | 8K | tracked | git 2026-09-18 / fs 2026-09-18 | yoxdur (kod) | docs-stale | **move → docs/history/** — 2026-09-18 vəziyyəti; AGENT_BRIEF (24.09) və HANDOFF_4 (21.09) onu əvəz edir. |
| `PROJECT_CONTEXT.md` | file | 101K | tracked | git 2026-09-24 / fs 2026-09-24 | yoxdur (kod) | docs-current | **split** — Başlıq `Generated: 2026-09-03`; §20, §28 köhnəlib. Sual 2. |
| `README.md` | file | 41K | tracked | git 2026-09-24 / fs 2026-09-24 | pyproject.toml:9, config/settings.example.yaml:665 | docs-current | **keep** — pyproject `readme`; layout bölməsi yenilənməlidir (504 test, 44 fayl kimi köhnə rəqəmlər). |
| `SKILLS_MANIFEST.md` | file | 6K | tracked | git 2026-07-22 / fs 2026-07-22 | yoxdur (kod) | agent-tooling | **move → .agents/skills/ (merge → .agents/skills/README.md)** — Eyni inventarı iki yerdə saxlayır; son dəyişiklik 2026-07-22. |
| `TODO.md` | file | 68K | tracked | git 2026-09-24 / fs 2026-09-21 | yoxdur (kod) | docs-current | **split** — Açıq roadmap (15) aktualdır; tarixli jurnal (138 [x]) tarixdir. Sual 2. |
| `__pycache__` | dir | 400K | ignored | fs 2026-09-24 | yoxdur | generated | **keep** — Python yaradır (root .py-lərin .pyc-si); ignored. |
| `architecture` | dir | 108K | tracked | git 2026-09-28 / fs 2026-09-28 | README.md:56,113,114,266 (link), src/monthly_report/__init__.py:8 | docs-current | **keep** — ADR-001..009 aktualdır; köçürmə README linklərini sındırır. |
| `assets` | dir | 1.5M | tracked | git 2026-07-20 / fs 2026-07-10 | config/settings.example.yaml:26, generate_pipeline_summary.py:86, standarts/generate_add_portal_request.py:40 | config | **keep** — Şriftlər; settings `fonts_dir`. |
| `config` | dir | 120K | tracked | git 2026-09-28 / fs 2026-09-28 | src/monthly_report/gui/services/app_paths.py:51, discover_network_share.py:666 | config | **keep** — settings + fields.yaml. |
| `discover_network_share.py` | file | 29K | tracked | git 2026-09-24 / fs 2026-09-24 | src/monthly_report/services/network_ingestion.py:41-47, tests/test_network_discovery.py:23, tests/test_network_ingestion.py:32 | helper-script | **keep** — Paket onu import edir (`parents[3]` + sys.path); köçürmə `network_ingestion`-u sındırır. |
| `file_paths_ex.md` | file | 3K | ignored | git 2026-09-24 / fs 2026-07-27 | tests/test_network_ingestion.py:500,504 (şərh) | operator-data | **move → _archive/** — LAN yollarının siyahısı (real host adı); fae8fdc ilə untrack olunub, ignored. Yalnız test şərhlərində adı keçir. |
| `generate_inspector_worksheet.py` | file | 10K | tracked | git 2026-07-21 / fs 2026-07-20 | yoxdur (yalnız generate_pipeline_summary.py:81 şərh) | helper-script | **UNKNOWN** — Orphan (test yox, CLI_MANUAL-da yox); `PROJECT_ROOT = parent` — köçürmək kod dəyişikliyi tələb edir. Selim: lazımdırmı? |
| `generate_pipeline_summary.py` | file | 51K | tracked | git 2026-09-18 / fs 2026-09-08 | tests/test_pipeline_summary.py:25, CLI_MANUAL.md:201 | helper-script | **keep** — Test import edir; `PROJECT_ROOT/assets`, `/images` yolları root-a bağlıdır. |
| `graphify-out` | dir | 29M | ignored | fs 2026-07-21 | yoxdur (kod); .claude/skills/graphify/SKILL.md:53 | generated | **archive** — 2026-07-21, commit 3dd0e50; 14 commit geridə. Sual 4. |
| `gui_launcher.py` | file | 2K | tracked | git 2026-07-20 / fs 2026-07-16 | src/monthly_report/gui/services/app_paths.py:67, requirements.txt:10 | entrypoint | **keep** — GUI worker-i bu fayla göstərir. |
| `images` | dir | 48K | tracked | git 2026-07-20 / fs 2026-07-10 | src/monthly_report/config.py:68,80-81, generate_pipeline_summary.py:91 | config | **keep** — Loqolar; settings `images_dir`. |
| `input` | dir | 3.2G | ignored (`input/*`) | git 2026-07-27 / fs 2026-08-10 | config/settings.example.yaml:22 | operator-data | **keep** — Qırmızı xətt. Alt qovluqlar: DP, FERRITE, HT, MPI, PMI, RT, UT, UTM, UnSorted, PDF_ARCHIVE, SKIPPED_REPORTS, _PRUNED. `input/*` ignored. |
| `main.py` | file | 57K | tracked | git 2026-09-24 / fs 2026-09-24 | src/monthly_report/gui/worker_entry.py:58, tests/test_cli_manual_sync.py:31, tests/test_main_scope.py:20 | entrypoint | **keep** — Qırmızı xətt; worker/test import edir. |
| `output` | dir | 16M | ignored (`output/*`), `.gitkeep` tracked | git 2026-07-20 / fs 2026-09-28 | config/settings.example.yaml:23 | operator-data | **keep** — Qırmızı xətt. 9 müştəri qovluğu + `failures/` + ~30 audit .md/.pdf. `output/*` ignored, yalnız `.gitkeep` tracked. |
| `output_backup` | dir | 167M | ignored | fs 2026-09-17 | scripts/prune_lan_duplicates.py:439 | backup | **move → _archive/output_backup/** — 6 snapshot, ledger nüsxələri ilə. `prune_lan_duplicates.py` default yolu buradadır — köçürəndə arqumentlə verilməlidir. |
| `output_backup_20260918` | dir | 15M | ignored | fs 2026-09-18 | yoxdur | backup | **move → _archive/** — 305 fayl; ən yeni fayl 2026-09-18. |
| `output_backup_20260921` | dir | 15M | ignored | fs 2026-09-18 | yoxdur | backup | **move → _archive/** — Adı 0921, amma ən yeni fayl 2026-09-18, qovluq mtime 09-18 — ad yanıltır. |
| `output_backup_20260924_1029` | dir | 16M | ignored | fs 2026-09-24 | yoxdur | backup | **move → _archive/** — 309 fayl. |
| `output_backup_20260924_1220` | dir | 16M | ignored | fs 2026-09-24 | yoxdur | backup | **move → _archive/** — 314 fayl; ən təzə backup. |
| `output_stale` | dir | 89M | ignored | fs 2026-09-08 | yoxdur | backup | **move → _archive/output_stale/** — Əl ilə köçürülmüş retired artefaktlar (.gitignore:30-36). |
| `pyproject.toml` | file | 1K | tracked | git 2026-09-18 / fs 2026-09-07 | setup.ps1:38, setup.sh:38 (`pip install -e .`) | config | **keep** — Paket + pytest config. |
| `requirements.txt` | file | 1K | tracked | git 2026-09-18 / fs 2026-09-07 | setup.ps1:36, setup.sh:36 | config | **keep** — setup skriptləri oxuyur. |
| `reset_and_sync_input.py` | file | 10K | tracked | git 2026-09-24 / fs 2026-09-24 | CLI_MANUAL.md:227, reset_and_sync_input.py:170,196 (öz yolları) | helper-script | **keep** — `PROJECT_ROOT/config`, `/.state` yolları root-a bağlıdır; CLI_MANUAL §5. |
| `reset_upload_ledger.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-04 | tests/test_cli_manual_sync.py:32, tests/test_reset_upload_ledger.py:29,140 | helper-script | **keep** — Testlər həm import edir, həm `_ROOT/"reset_upload_ledger.py"` mətnini oxuyur. |
| `samples` | dir | 384K | ignored | fs 2026-09-21 | yoxdur (kod); TODO.md:205 | operator-data | **move → _archive/samples/** — Kod istinadı yoxdur; E3 nümunə sənədləri + gap audit. `.gitignore:94-100` onu output/-dan kənarda saxlamağı tələb edir. |
| `scripts` | dir | 172K | tracked | git 2026-09-18 / fs 2026-09-17 | pyproject.toml:32, src/monthly_report/duplicate_identity.py:3, src/monthly_report/gui/services/progress.py:8 | helper-script | **keep** — 4 audit/prune skripti. |
| `setup.ps1` | file | 2K | tracked | git 2026-07-22 / fs 2026-07-22 | setup.sh:4 | config | **keep** — Bootstrap; `Python 3.10+` yazır, pyproject `>=3.11` — kiçik uyğunsuzluq. |
| `setup.sh` | file | 2K | tracked | git 2026-07-22 / fs 2026-07-22 | setup.ps1:3 | config | **keep** — Bootstrap (Unix). |
| `skills-lock.json` | file | 502B | tracked | git 2026-07-20 / fs 2026-07-10 | yoxdur | agent-tooling | **move → .agents/ (UNKNOWN)** — `npx skills` lock faylı kimi görünür; alətin onu root-da gözləyib-gözləmədiyi UNKNOWN / NEEDS VERIFICATION. |
| `src` | dir | 2.0M | tracked | git 2026-09-28 / fs 2026-09-07 | pyproject.toml:37, pyproject.toml:41 (pythonpath) | core-code | **keep** — Paket kökü; pyproject `where = ["src"]`. |
| `standarts` | dir | 125K | tracked | git 2026-07-22 / fs 2026-07-22 | tests/test_master_standards_sync.py:30, uploader.py:487, src/monthly_report/method_registry.py:493 | config | **keep** — Ad səhvdir, amma kod/test yolu buna bağlıdır — adı dəyişmə. |
| `tests` | dir | 4.4M | tracked | git 2026-09-28 / fs 2026-09-24 | pyproject.toml:40 | test | **keep** — 67 test faylı. |
| `translations` | dir | 4.0K | tracked | git 2026-09-24 / fs 2026-09-03 | config/settings.example.yaml:24, scripts/audit_item_detail.py:490 | config | **keep** — az.json; settings `translations`. |
| `uploader.py` | file | 178K | tracked | git 2026-09-18 / fs 2026-09-17 | src/monthly_report/gui/worker_entry.py:67, tests/test_cli_manual_sync.py:33, tests/test_composite_standards.py:155 | entrypoint | **keep** — Qırmızı xətt; worker/test import edir. |
| `src/monthly_report/__init__.py` | file | 440B | tracked | git 2026-07-20 / fs 2026-07-10 | scripts/audit_duplicate_identity.py:90, scripts/audit_duplicate_identity.py:153, scripts/audit_retest_rollup.py:86 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/__pycache__` | dir | 532K | ignored | fs 2026-09-24 | yoxdur | generated | **keep** — ignored. |
| `src/monthly_report/cli.py` | file | 3K | tracked | git 2026-07-20 / fs 2026-07-15 | pyproject.toml:34, tests/test_imports.py:18 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/config.py` | file | 4K | tracked | git 2026-07-27 / fs 2026-07-24 | config/fields.yaml:2, config/settings.example.yaml:4, config/settings.example.yaml:5 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/console.py` | file | 4K | tracked | git 2026-09-18 / fs 2026-08-10 | config/settings.example.yaml:267, config/settings.example.yaml:312, config/settings.example.yaml:496 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/date_detector.py` | file | 15K | tracked | git 2026-09-18 / fs 2026-09-04 | scripts/prune_lan_duplicates.py:23, scripts/prune_lan_duplicates.py:61, scripts/prune_lan_duplicates.py:178 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/document_aggregator.py` | file | 73K | tracked | git 2026-09-28 / fs 2026-09-24 | main.py:21, main.py:63, main.py:312 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/docx_reader.py` | file | 11K | tracked | git 2026-09-18 / fs 2026-09-07 | gui_launcher.py:47, gui_launcher.py:48, main.py:19 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/duplicate_identity.py` | file | 15K | tracked | git 2026-09-24 / fs 2026-09-21 | config/settings.example.yaml:492, src/monthly_report/document_aggregator.py:34, src/monthly_report/document_aggregator.py:474 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/extractor.py` | file | 23K | tracked | git 2026-09-18 / fs 2026-09-17 | scripts/audit_duplicate_identity.py:43, scripts/audit_duplicate_identity.py:128, scripts/audit_duplicate_identity.py:142 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/gui` | dir | 895K | tracked | git 2026-09-18 / fs 2026-07-16 | gui_launcher.py:37,41, tests/test_cache_service.py:16 | core-code | **keep** — PySide6 dashboard. |
| `src/monthly_report/inspector_registry.py` | file | 3K | tracked | git 2026-07-21 / fs 2026-07-20 | generate_inspector_worksheet.py:37, src/monthly_report/document_aggregator.py:36, tests/test_inspector_registry.py:18 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/json_exporter.py` | file | 5K | tracked | git 2026-09-24 / fs 2026-09-24 | generate_pipeline_summary.py:17, generate_pipeline_summary.py:295, main.py:21 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/method_registry.py` | file | 29K | tracked | git 2026-09-18 / fs 2026-09-17 | config/settings.example.yaml:522, discover_network_share.py:60, discover_network_share.py:109 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/naming.py` | file | 4K | tracked | git 2026-09-18 / fs 2026-09-08 | config/settings.example.yaml:46, generate_inspector_worksheet.py:39, generate_inspector_worksheet.py:97 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/parse_cache.py` | file | 12K | tracked | git 2026-09-18 / fs 2026-09-07 | config/settings.example.yaml:285, config/settings.example.yaml:291, config/settings.example.yaml:292 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/pdf_crosscheck.py` | file | 9K | tracked | git 2026-09-18 / fs 2026-09-07 | main.py:64, main.py:732, main.py:739 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/pdf_reader.py` | file | 10K | tracked | git 2026-09-18 / fs 2026-09-07 | src/monthly_report/docx_reader.py:163, src/monthly_report/docx_reader.py:164, src/monthly_report/pdf_crosscheck.py:3 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/pdf_renderer.py` | file | 23K | tracked | git 2026-09-24 / fs 2026-09-24 | generate_inspector_worksheet.py:9, generate_inspector_worksheet.py:56, generate_pipeline_summary.py:19 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/pdf_twin.py` | file | 4K | tracked | git 2026-09-18 / fs 2026-09-04 | scripts/prune_lan_duplicates.py:171, src/monthly_report/document_aggregator.py:35, src/monthly_report/document_aggregator.py:335 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/pre_processor.py` | file | 41K | tracked | git 2026-09-18 / fs 2026-09-08 | config/settings.example.yaml:531, discover_network_share.py:608, discover_network_share.py:610 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/report_identity.py` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-08 | discover_network_share.py:62, discover_network_share.py:85, main.py:65 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/report_no_mismatch.py` | file | 5K | tracked | git 2026-09-24 / fs 2026-09-21 | main.py:66, main.py:255, main.py:265 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/retest_tracker.py` | file | 10K | tracked | git 2026-09-24 / fs 2026-09-21 | config/settings.example.yaml:119, config/settings.example.yaml:254, main.py:66 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/services` | dir | 126K | tracked | git 2026-09-24 / fs 2026-09-24 | main.py:76, reset_and_sync_input.py:48 | core-code | **keep** — `gui/services` ilə eyni ad — agent üçün çaşdırıcı (Sual 8). |
| `src/monthly_report/text_norm.py` | file | 6K | tracked | git 2026-09-24 / fs 2026-09-18 | config/settings.example.yaml:517, src/monthly_report/document_aggregator.py:44, src/monthly_report/document_aggregator.py:82 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/translator.py` | file | 2K | tracked | git 2026-07-20 / fs 2026-07-10 | main.py:77, main.py:911, main.py:917 | core-code | **keep** — Pipeline modulu. |
| `src/monthly_report/upload_ledger.py` | file | 16K | tracked | git 2026-09-18 / fs 2026-08-10 | main.py:66, main.py:99, main.py:137 | core-code | **keep** — Pipeline modulu. |
| `scripts/__pycache__` | dir | 64K | ignored | fs 2026-09-17 | yoxdur | generated | **keep** — ignored. |
| `scripts/audit_duplicate_identity.py` | file | 26K | tracked | git 2026-09-18 / fs 2026-09-17 | src/monthly_report/duplicate_identity.py:3 (docstring) | helper-script | **keep** — ADR-005 ölçmə aləti. |
| `scripts/audit_item_detail.py` | file | 22K | tracked | git 2026-09-18 / fs 2026-09-17 | yoxdur (kod) | helper-script | **keep** — Tapşırıq 11-B2 audit. |
| `scripts/audit_retest_rollup.py` | file | 27K | tracked | git 2026-09-18 / fs 2026-09-17 | scripts/audit_duplicate_identity.py:3 (docstring) | helper-script | **keep** — E3 audit. |
| `scripts/prune_lan_duplicates.py` | file | 23K | tracked | git 2026-09-18 / fs 2026-09-17 | yoxdur (kod) | helper-script | **keep** — Özünü `One-off operator tool` adlandırır; default yolu `output_backup/2026-09-17_pre-task11/` (sətir 439). |
| `tests/__pycache__` | dir | 3.4M | ignored | fs 2026-09-24 | yoxdur | generated | **keep** — 3.4M; ignored. |
| `tests/data` | dir | 80K | tracked | git 2026-09-18 / fs 2026-09-07 | tests/test_native_docx_invariance.py:38, tests/test_verdict_regression.py:14 | test | **keep** — 2 JSON fixture. |
| `tests/test_aggregator.py` | file | 6K | tracked | git 2026-07-27 / fs 2026-07-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_allowed_standards.py` | file | 11K | tracked | git 2026-09-18 / fs 2026-09-17 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_cache_service.py` | file | 3K | tracked | git 2026-07-22 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_cache_stats_service.py` | file | 2K | tracked | git 2026-07-27 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_cli_manual_sync.py` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-04 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_client_exclusion.py` | file | 2K | tracked | git 2026-07-21 / fs 2026-07-20 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_client_grouping.py` | file | 23K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_composite_standards.py` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-17 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_console.py` | file | 6K | tracked | git 2026-07-21 / fs 2026-07-20 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_date_repair.py` | file | 20K | tracked | git 2026-09-18 / fs 2026-09-04 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_document_aggregator.py` | file | 11K | tracked | git 2026-09-18 / fs 2026-09-18 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_duplicate_identity.py` | file | 14K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_equipment_extraction.py` | file | 7K | tracked | git 2026-07-20 / fs 2026-07-17 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_extractor.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-17 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_gui_pipeline_args.py` | file | 8K | tracked | git 2026-07-27 / fs 2026-07-27 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_gui_progress.py` | file | 20K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_housekeeping.py` | file | 14K | tracked | git 2026-07-20 / fs 2026-07-16 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_identity_warnings.py` | file | 3K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_imports.py` | file | 2K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_ingest_service.py` | file | 10K | tracked | git 2026-07-20 / fs 2026-07-16 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_ingestion_registry.py` | file | 24K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_inspector_registry.py` | file | 5K | tracked | git 2026-07-21 / fs 2026-07-20 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_json_exporter_equipment.py` | file | 5K | tracked | git 2026-09-18 / fs 2026-09-03 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_ledger_service_reset.py` | file | 3K | tracked | git 2026-07-22 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_main_scope.py` | file | 12K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_master_standards_sync.py` | file | 4K | tracked | git 2026-07-27 / fs 2026-07-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_method_registry.py` | file | 10K | tracked | git 2026-07-27 / fs 2026-07-27 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_metrics_history_service.py` | file | 3K | tracked | git 2026-07-27 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_native_docx_invariance.py` | file | 5K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_network_discovery.py` | file | 8K | tracked | git 2026-07-27 / fs 2026-07-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_network_ingestion.py` | file | 38K | tracked | git 2026-09-18 / fs 2026-09-18 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_parse_cache.py` | file | 6K | tracked | git 2026-07-22 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pdf_crosscheck.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pdf_dispatch.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pdf_reader.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pdf_renderer_columns.py` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-03 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pdf_renderer_header.py` | file | 3K | tracked | git 2026-09-18 / fs 2026-09-03 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pipeline_determinism.py` | file | 23K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pipeline_summary.py` | file | 18K | tracked | git 2026-07-27 / fs 2026-07-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_portal_readiness.py` | file | 4K | tracked | git 2026-07-27 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pre_processor_archive.py` | file | 9K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_progress_counters.py` | file | 19K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pull_weld_check.py` | file | 9K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_pulled_parent_mark.py` | file | 9K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_quarantine_reasons_service.py` | file | 2K | tracked | git 2026-07-27 / fs 2026-07-22 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_range_by_number.py` | file | 24K | tracked | git 2026-09-24 / fs 2026-09-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_range_collapse.py` | file | 17K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_range_merge_keys.py` | file | 18K | tracked | git 2026-09-28 / fs 2026-09-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_range_tail_and_dates.py` | file | 9K | tracked | git 2026-09-24 / fs 2026-09-24 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_report_identity.py` | file | 2K | tracked | git 2026-07-20 / fs 2026-07-15 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_report_no_mismatch.py` | file | 9K | tracked | git 2026-09-24 / fs 2026-09-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_report_serial_format.py` | file | 3K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_reset_upload_ledger.py` | file | 6K | tracked | git 2026-09-18 / fs 2026-09-04 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_serial_cross_month_parent.py` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_settings_writer.py` | file | 11K | tracked | git 2026-07-21 / fs 2026-07-20 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_standard_normalization.py` | file | 10K | tracked | git 2026-09-18 / fs 2026-09-09 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_standard_space_collapse.py` | file | 6K | tracked | git 2026-09-24 / fs 2026-09-18 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_summary_exporter.py` | file | 3K | tracked | git 2026-09-18 / fs 2026-09-08 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_text_norm.py` | file | 2K | tracked | git 2026-07-20 / fs 2026-07-15 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_unfit_section.py` | file | 12K | tracked | git 2026-09-18 / fs 2026-09-18 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_upload_ledger.py` | file | 12K | tracked | git 2026-07-27 / fs 2026-07-27 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_uploader_form.py` | file | 106K | tracked | git 2026-07-27 / fs 2026-07-27 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_uploader_mapping.py` | file | 54K | tracked | git 2026-09-18 / fs 2026-08-12 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_uploader_probe_contract.py` | file | 11K | tracked | git 2026-09-18 / fs 2026-09-09 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_uploader_takeover.py` | file | 7K | tracked | git 2026-07-20 / fs 2026-07-17 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_verdict_regression.py` | file | 9K | tracked | git 2026-09-18 / fs 2026-09-07 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/test_volume_thresholds.py` | file | 8K | tracked | git 2026-07-21 / fs 2026-07-21 | pyproject.toml:40 (testpaths) | test | **keep** — pytest toplayır. |
| `tests/.gitkeep` | file | 49B | tracked | git 2026-07-20 / fs 2026-07-10 | yoxdur | test | **keep** — Zərərsiz. |
| `config/fields.yaml` | file | 2K | tracked | git 2026-07-20 / fs 2026-07-10 | config/settings.example.yaml:25, requirements.txt:6 | config | **UNKNOWN** — `fields_config` açarını heç bir .py oxumur (git grep: yalnız settings.example.yaml:25 və requirements.txt:6 şərhi). Ölü ola bilər — NEEDS VERIFICATION. |
| `config/settings.example.yaml` | file | 42K | tracked | git 2026-09-28 / fs 2026-09-24 | setup.ps1:47, setup.sh:47 | config | **keep** — Commit olunan şablon. |
| `config/settings.yaml` | file | 35K | ignored | fs 2026-09-28 | src/monthly_report/gui/services/app_paths.py:51 | operator-data | **keep** — Canlı sirr config; ignored. |
| `config/settings.yaml.bak` | file | 29K | ignored | fs 2026-09-03 | .gitignore:7 (kod: src/monthly_report/gui/services/settings_writer.py:130) | backup | **keep** — `settings_writer.py` yazır (.gitignore:6-7); köçürmə GUI davranışını dəyişə bilər. |
| `architecture/ADR-001-tech-stack.md` | file | 8K | tracked | git 2026-07-20 / fs 2026-07-10 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-002-gui-frontend.md` | file | 17K | tracked | git 2026-07-20 / fs 2026-07-16 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-003-pdf-direct-extraction.md` | file | 11K | tracked | git 2026-09-18 / fs 2026-09-07 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-004-client-grouping.md` | file | 10K | tracked | git 2026-09-18 / fs 2026-09-08 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-005-duplicate-report-identity.md` | file | 9K | tracked | git 2026-09-18 / fs 2026-09-18 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-006-pulled-parent-reference.md` | file | 6K | tracked | git 2026-09-24 / fs 2026-09-24 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-007-pull-weld-check.md` | file | 5K | tracked | git 2026-09-24 / fs 2026-09-24 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-008-report-no-mismatch.md` | file | 5K | tracked | git 2026-09-24 / fs 2026-09-24 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `architecture/ADR-009-by-number-ranges.md` | file | 13K | tracked | git 2026-09-28 / fs 2026-09-28 | yoxdur (kod); README.md:119-128 | docs-current | **keep** — ADR; README layout-da siyahıda. |
| `standarts/add_portal.md` | file | 879B | tracked | git 2026-07-22 / fs 2026-07-22 | standarts/generate_add_portal_request.py:6, uploader.py:488, uploader.py:498 | docs-current | **keep** — Portala əlavə sorğusunun mənbəyi. |
| `standarts/add_portal.txt` | file | 279B | tracked | git 2026-07-22 / fs 2026-07-22 | yoxdur | docs-stale | **UNKNOWN** — Heç yerdə istinad yoxdur; add_portal.md-nin mətn variantı kimi görünür — NEEDS VERIFICATION. |
| `standarts/add_portal_request.docx` | file | 36K | tracked | git 2026-07-22 / fs 2026-07-22 | standarts/generate_add_portal_request.py:4, standarts/generate_add_portal_request.py:42 | generated | **keep** — Generator çıxışı; rəsmi sorğu. |
| `standarts/add_portal_request.pdf` | file | 49K | tracked | git 2026-07-22 / fs 2026-07-22 | standarts/generate_add_portal_request.py:4, standarts/generate_add_portal_request.py:43, uploader.py:489 | generated | **keep** — Generator çıxışı. |
| `standarts/butun_standartlar.md` | file | 1K | tracked | git 2026-07-22 / fs 2026-07-22 | tests/test_master_standards_sync.py:30, src/monthly_report/method_registry.py:493 | config | **keep** — Markdown-as-data; drift testi oxuyur. |
| `standarts/generate_add_portal_request.py` | file | 15K | tracked | git 2026-07-22 / fs 2026-07-22 | yoxdur (kod) | helper-script | **keep** — Birdəfəlik generator; `standarts/` içindən `parent.parent` ilə root tapır. |
| `standarts/in_portal.md` | file | 672B | tracked | git 2026-07-22 / fs 2026-07-22 | uploader.py:487 (şərh) | docs-current | **keep** — Portalın 16 standartı (probe ilə). |
| `assets/fonts` | dir | 1.5M | tracked | git 2026-07-20 / fs 2026-07-10 | config/settings.example.yaml:26, config/settings.example.yaml:664, config/settings.example.yaml:665 | config | **keep** — DejaVu TTF ignored, README tracked. |
| `images/Mag-Pi Logo.png` | file | 4K | tracked | git 2026-07-20 / fs 2026-07-10 | config/settings.example.yaml:31, generate_pipeline_summary.py:91 | config | **keep** — header_logo. |
| `images/Mohur Logo.png` | file | 38K | tracked | git 2026-07-20 / fs 2026-07-10 | config/settings.example.yaml:32 | config | **keep** — stamp_logo. |
| `samples/e3` | dir | 220K | ignored | fs 2026-09-18 | yoxdur (kod); TODO.md:205 | operator-data | **move → _archive/samples/** — Real müştəri PDF+JSON (AZF JAN 2026, UBOC APR 2026); kod istinadı yoxdur. |
| `samples/gap_audit_2026-09-21.md` | file | 162K | ignored | fs 2026-09-21 | yoxdur | docs-stale | **move → _archive/samples/** — Birdəfəlik audit; kod istinadı yoxdur. |
| `.claude/skills` | dir | 101K | tracked | git 2026-07-20 / fs 2026-07-14 | yoxdur | agent-tooling | **keep** — graphify v0.9.15 (tracked). |
| `.agents/skills` | dir | 272K | tracked | git 2026-07-20 / fs 2026-07-14 | yoxdur (kod) | agent-tooling | **keep** — 17 skill + README. |
| `Claude outputs/ADR_006-009_prompt.md` | file | 5K | untracked | fs 2026-09-24 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — İcra olunub: ADR-006..009 d18fccb-də commit olunub. |
| `Claude outputs/AGENT_BRIEF.md` | file | 15K | untracked | fs 2026-09-24 | yoxdur | docs-current | **UNKNOWN** — 24.09 tarixli, `əvvəlki handoff-lara ehtiyac yoxdur` deyir — ən yeni brief. Gələcək CLAUDE.md-yə mənbə ola bilər; ayrıca saxlanılsın, yoxsa birləşsin — Selim. |
| `Claude outputs/F1_inventory_prompt.md` | file | 5K | untracked | fs 2026-09-28 | yoxdur | docs-current | **move → docs/history/claude-outputs/** — Bu tapşırığın özü; bitəndən sonra tarixdir. |
| `Claude outputs/HANDOFF.md` | file | 7K | tracked | git 2026-09-18 / fs 2026-09-17 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — 2026-09-17 versiyası; root HANDOFF.md onun 09-18 versiyasıdır. |
| `Claude outputs/HANDOFF_2.md` | file | 9K | tracked | git 2026-09-18 / fs 2026-09-18 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — HANDOFF_4 əvəz edir. |
| `Claude outputs/HANDOFF_3.md` | file | 4K | tracked | git 2026-09-18 / fs 2026-09-18 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — 18.09 əlavə; HANDOFF_4 əvəz edir. |
| `Claude outputs/HANDOFF_4.md` | file | 10K | untracked | fs 2026-09-21 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — 21.09; AGENT_BRIEF (24.09) əvəz edir. |
| `Claude outputs/range_merge_prompt.md` | file | 4K | untracked | fs 2026-09-24 | yoxdur | docs-stale | **move → docs/history/claude-outputs/** — İcra olunub: ece881b (2026-09-28). |
| `translations/az.json` | file | 3K | tracked | git 2026-09-24 / fs 2026-09-21 | config/settings.example.yaml:24, scripts/audit_item_detail.py:490 | config | **keep** — Lüğət; render mətni buradan. |
| `src/monthly_report` | dir | 2.0M | tracked | git 2026-09-28 / fs 2026-09-24 | config/settings.example.yaml:492, discover_network_share.py:60, discover_network_share.py:61 | core-code | **keep** — Pipeline paketi. |
| `src/monthly_report_auto.egg-info` | dir | 56K | ignored | fs 2026-09-07 | yoxdur | generated | **keep** — `pip install -e .` yaradır; ignored. |

---

## 2. Xüsusi suallar

### 2.1 Root-dakı `.py` faylları — köçürsək nə sınar?

Hamısı öz kökünü `Path(__file__).resolve().parent` ilə tapır, sonra `config/`, `src/`, `.state/`, `assets/` yollarını ondan qurur. `scripts/`-ə köçən fayl üçün bu kök `scripts/` olur — yollar sınır (müqayisə: `scripts/prune_lan_duplicates.py:58` `parents[1]` işlədir). Deməli, **hər köçürmə kod dəyişikliyi tələb edir**. Bu mərhələdə heç biri üçün "heç nə sınmır" sübutu yoxdur.

| fayl | kök təyini | köçürsək nə sınar (sübut) |
|---|---|---|
| `main.py` | `main.py:60` `_ROOT = …parent` | GUI worker `import main` + `main._ROOT = app_root()` (`src/monthly_report/gui/worker_entry.py:58-61`); `sys.path`-a root əlavə olunur (`worker_entry.py:44-48`); testlər `import main` (`tests/test_cli_manual_sync.py:31`, `test_main_scope.py:20`, `test_pipeline_determinism.py:40`, `test_progress_counters.py:30`, `test_ingestion_registry.py:32`, `test_gui_pipeline_args.py:20` …); CLI_MANUAL drift testi (`tests/test_cli_manual_sync.py:50`). **Qırmızı xətt.** |
| `uploader.py` | `uploader.py:170` | GUI worker `import uploader` + `uploader._ROOT` (`worker_entry.py:67-70`); testlər (`test_cli_manual_sync.py:33,51`, `test_composite_standards.py:155`, `test_range_by_number.py:544`, `test_pipeline_determinism.py:334`). **Qırmızı xətt.** |
| `gui_launcher.py` | `gui_launcher.py:29` | `app_paths.launcher_path()` → `_SOURCE_ROOT / "gui_launcher.py"` (`src/monthly_report/gui/services/app_paths.py:64-67`); `_SOURCE_ROOT = parents[4]` = repo kökü (`app_paths.py:29`). `job_runner.py:216` worker-i bu launcher ilə başladır. |
| `discover_network_share.py` | `:57` | **Paket onu import edir**: `network_ingestion.py:41-47` repo kökünü `sys.path`-a qoyub `from discover_network_share import …`. Testlər: `tests/test_network_discovery.py:23`, `tests/test_network_ingestion.py:32`. |
| `generate_pipeline_summary.py` | `:49` | `tests/test_pipeline_summary.py:25` import; font/loqo `PROJECT_ROOT/"assets"`, `/"images"` (`:86-91`). CLI_MANUAL §4 (`CLI_MANUAL.md:201`) — sinxron testi yalnız `main`, `uploader`, `reset_upload_ledger` parser-lərini yoxlayır (`test_cli_manual_sync.py:49-53`), ona görə bu bölmə başlığındakı ad test sınmadan köhnələ bilər. |
| `reset_and_sync_input.py` | `:43` | Kod importu yoxdur (yalnız şərhlər: `ingestion_registry.py:48`, `network_ingestion.py:596`, `uploader.py:442`). Yollar: `PROJECT_ROOT/"config"/…` (`:170`), `PROJECT_ROOT/".state"/…` (`:196`). CLI_MANUAL §5. |
| `reset_upload_ledger.py` | `:53` | `test_cli_manual_sync.py:32,52` import + parser; `tests/test_reset_upload_ledger.py:29` import, **`:140` faylın mətnini `_ROOT / "reset_upload_ledger.py"` yolundan oxuyur**. Ledger yolu `PROJECT_ROOT / LIVE_LEDGER_NAME` (`:89`). |
| `generate_inspector_worksheet.py` | `:22` | Heç kim import etmir; CLI_MANUAL-da yoxdur (`PROJECT_CONTEXT.md:805` "Orphan"). Köçürsək yalnız öz yolları (`:234` settings) sınır. |

`pyproject.toml` root skriptləri paketləmir (`packages.find where=["src"]`, `:36-37`); yeganə console script `monthly_report.cli:main` (`:34`). `setup.ps1` / `setup.sh` root `.py`-lərə istinad etmir (yalnız `requirements.txt`, `pip install -e .`, `config/settings.example.yaml`). PyInstaller `.spec` repo-da yoxdur (`*.spec` ignored, `.gitignore`; disk-də də yoxdur) — frozen build-in hidden import siyahısı **UNKNOWN / NEEDS VERIFICATION** (`worker_entry.py:42` "Frozen builds bundle both as hidden imports").

**Nəticə:** root `.py`-lərin hamısı yerində qalır. `generate_inspector_worksheet.py` üçün sual Selimdədir (lazımdırmı?).

### 2.2 Böyük sənədlər

| fayl | ölçü / sətir | nə üçündür | sonuncu faydalı yeniləmə (sübut) |
|---|---|---|---|
| `PROJECT_CONTEXT.md` | 104K / 1306 | 32 bölməli, `path:line` sübutlu layihə konteksti (agent üçün) | Mətn `Generated: 2026-09-03` (`:9`). Git-ə 4570af1 (2026-09-18, +1303) ilə girib; d18fccb (2026-09-24) yalnız 5 sətir — §9-da ADR siyahısı. |
| `TODO.md` | 68K / 341 | Auto-Maintenance protokollu jurnal + Known Bugs + Pending Roadmap | fs 2026-09-21; son commit 9d54e26 (2026-09-24, +1 sətir). Tarixli jurnalın son bölməsi "September 18, 2026" (`:188`). ADR-006..009 TODO-da **0** dəfə keçir. |
| `README.md` | 42K / 793 | İctimai təqdimat + setup + istifadə + portal təhlükəsizlik modeli | 2e7a9c3 (2026-09-24, +8/−1, ADR layout sətirləri); böyük dəyişiklik 4570af1 (2026-09-18, +108). |
| `CLI_MANUAL.md` | 22K / 394 | Hər entrypoint üçün flag arayışı | fs 2026-09-08; git-ə 2026-09-18. Sinxron testi bu gün keçir (15 passed). |
| `HANDOFF.md` | 8K / 126 | Chat-məsləhətçi üçün başlanğıc promptu (AZ) | 2026-09-18 (`:35` "İNDİKİ VƏZİYYƏT (2026-09-18)"). |
| `SKILLS_MANIFEST.md` | 6K / 128 | `.agents/skills` layout, format, çağırış protokolu, qeydiyyat | 2026-07-22 (d5a245f). |

**Köhnəlmiş rəqəmlər (sübutlu):**

- README "504-test suite" — `README.md:18,150,761,780`. Faktiki: **1928 test toplandı**, 67 fayl. `PROJECT_CONTEXT.md:1216` bu ziddiyyəti özü qeyd edir.
- PROJECT_CONTEXT "44 pytest files" — `PROJECT_CONTEXT.md:369`. Faktiki 67.
- PROJECT_CONTEXT §20 "The three new, untracked test files" (`:823`) — üçü də artıq tracked.
- PROJECT_CONTEXT §28 yalnız ADR-001..003-ə alt bölmə verir (`:1114-1141`); ADR-004..009 yalnız §9 siyahısında.
- `report_no_mismatch`, `pdf_twin` PROJECT_CONTEXT/README/CLI_MANUAL-da **0** dəfə keçir.
- HANDOFF.md "1 713 keçdi" (`:40`), Claude outputs/HANDOFF.md "1 695"; TODO.md:208 "1 729 passed". Üç fərqli rəqəm.
- TODO roadmap `:339` ".exe packaging" açıq, amma README `:270` "Building the standalone .exe" bölməsi var; `:341` "Direct LAN Network Share Mapping" açıq, amma `src/monthly_report/services/network_ingestion.py` və `reset_and_sync_input.py` mövcuddur. Bağlanmalıdırmı — **UNKNOWN / NEEDS VERIFICATION**.

**Başlıq səviyyəsində təkrarlar:**

| mövzu | README | PROJECT_CONTEXT | CLI_MANUAL | digər |
|---|---|---|---|---|
| Qovluq strukturu | "Project layout" `:116` | §9 `:308` | — | AGENT_BRIEF, HANDOFF_4 |
| Setup / quraşdırma | "Developer setup" `:155`, "Fonts" `:179` | §19 `:740` | §1 Prerequisites `:27` | setup.ps1/sh |
| Arxitektura / stack | "Architecture highlights" `:49`, "Recommended architecture" `:99` | §7 `:233`, §8 `:255`, §18 `:715` | — | ADR-001 |
| Stage ardıcıllığı | "What it does, stage by stage" `:89` | §6 Flow A `:180`, §11 `:415` | §10 counters `:339` | — |
| GUI | "Desktop dashboard" `:216` | §10 `:377` | §8 `:302` | ADR-002 |
| Portal / uploader | "E-Keyfiyyet portal integration" `:515` (+ Safety model, Authentication, Live run, Upload state) | §13 `:533`, §14 `:567`, §16 `:626` | §3 `:108` (+ Ledger states `:182`) | — |
| Housekeeping | "Housekeeping" `:416` | §11 "Key subsystem behaviours" `:428` | §11 Ordering and safety `:376` | — |
| Bug / TODO | — | §25 `:978`, §26 Known Bugs `:1001`, §27 `:1076` | — | TODO.md "Known Bugs" `:213`, "Pending Roadmap" `:326` |
| ADR xülasəsi | layout şərhləri `:119-128` | §28 `:1109` | — | `architecture/` |
| Cari vəziyyət | — | — | — | HANDOFF.md `:35`, TODO jurnalı, Claude outputs/HANDOFF_4, AGENT_BRIEF |
| Skill inventarı | — | §21-də qeyd (`:853`) | — | SKILLS_MANIFEST "Registered skills" `:95` ↔ `.agents/skills/README.md` cədvəli |

**TODO.md sayları** (`grep -E '^\s*[-*] \[ \]'` / `\[[xX]\]`): **açıq 15**, **bağlı 138**. Açıqların hamısı "Pending Roadmap" altındadır (`TODO.md:327-341`). "Known Bugs" altındakı KB-1, KB-1b başlıqda "✅ FIXED" (`:215`, `:260`).

### 2.3 Backup-lar və köhnə çıxışlar

| qovluq | ölçü | tarix (fs) | ignore | məzmun |
|---|---|---|---|---|
| `output_backup/` | 167M | 2026-09-17 | ignored (`.gitignore:26`) | 6 snapshot: `2026-09-03_1059_pre-obyekt-refactor` 35M, `2026-09-04_1102_pre-ledger-reset` 35M, `2026-09-07_pre-adr003` 33M, `2026-09-08_1536_pre-client-grouping` 33M, `2026-09-09_1048_pre-fullrun` 17M, `2026-09-17_pre-task11` 17M. İlk 5-də **`.upload_state.json` və `output/upload_status.json` nüsxələri** var. |
| `output_backup_20260918/` | 15M | 2026-09-18 | ignored (`:28`) | 305 fayl, ən yeni fayl 09-18 |
| `output_backup_20260921/` | 15M | 2026-09-18 (!) | ignored (`:27`, `:28`) | 305 fayl, ən yeni fayl 09-18. **Ad 0921, məzmun 09-18.** `0918` ilə eyni deyil: 144 fərqli fayl (`diff -rq`). |
| `output_backup_20260924_1029/` | 16M | 2026-09-24 | ignored (`:28`) | 309 fayl |
| `output_backup_20260924_1220/` | 16M | 2026-09-24 | ignored (`:28`) | 314 fayl; `_1029` ilə 133 fərqli fayl |
| `output_stale/` | 89M | 2026-09-08 | ignored (`:36`) | 6 alt qovluq (2026-09-04 ×4, 09-07_adr003, 09-08_adr004); `.gitignore:30-35` izah edir: əl ilə köçürülmüş retired PDF+JSON |
| `graphify-out/` | 29M | 2026-07-21 | ignored (`:70`) | `converted/` 17M, `cache/` 3.9M, `graph.json` 2.6M, `graph.html` 2.3M |
| root `__pycache__/` | 400K | 2026-09-24 | ignored (`:83`) | root `.py`-lərin cpython-314 `.pyc`-si |

**Kod istinadı:** yalnız bir: `scripts/prune_lan_duplicates.py:439` — `--rename-audit` arqumentinin **default** yolu `_ROOT / "output_backup" / "2026-09-17_pre-task11" / "pdf_renames_{today}.txt"`. Səbəb: skript özünü "One-off operator tool" adlandırır (`:1`); `--rename` keçidi ad dəyişikliklərinin audit izini həmin tapşırığın (Task 11) backup snapshot-una yazır — o qovluqda `pdf_renames_2026-09-17.txt` və `input_tree_2026-09-17.txt` həqiqətən var. Commit: 4570af1 (2026-09-18). Qovluq köçürülsə, skript default ilə yenidən işlədiləndə köhnə yolu səssizcə **yenidən yaradacaq** (`write_rename_audit` → `out_path.parent.mkdir(parents=True, exist_ok=True)`, `:414`) — xəta yox, root-da yeni `output_backup/` peyda olar. Köçürmədən əvvəl bu default dəyişməli və ya `--rename-audit` ilə yol verilməlidir (kod dəyişikliyi — F1 əhatəsindən kənar). Başqa `.py/.yaml/.toml` istinadı yoxdur.

### 2.4 graphify

- Skill təsviri: "especially when graphify-out/ exists, where the question should be treated as a graphify query first" (`.claude/skills/graphify/SKILL.md:3`); "Fast path … skip Steps 1–5 entirely … Run `graphify query` immediately" (`:53`). Qlobal `~/.claude/CLAUDE.md` də `/graphify` trigger-i qeyd edir.
- Qraf: `GRAPH_REPORT.md:1` "(2026-07-21)", "Built from commit: `3dd0e50e`" (`:12`) — "Initial public release" (2026-07-20). O vaxtdan **14 commit**, `src/ main.py uploader.py`-də **53 fayl, +10720/−1167**.
- `manifest.json`: 117 fayl. Tracked `*.py *.md` = 198; **91-i qrafda yoxdur**. Qrafda olmayan kod: `report_no_mismatch.py`, `duplicate_identity.py`, `parse_cache.py`, `pdf_reader.py`, `pdf_twin.py`, `pdf_crosscheck.py`, `services/network_ingestion.py`, `services/ingestion_registry.py`, `discover_network_share.py`, `generate_pipeline_summary.py`, `reset_and_sync_input.py`, `reset_upload_ledger.py`, 4 `scripts/*.py`, 5 GUI service, 3 GUI widget. Sənəd: `ADR-003..009`, `CLI_MANUAL.md`, `PROJECT_CONTEXT.md`, `TODO.md`, `HANDOFF*.md`, `standarts/*.md`.
- `graph.json`-da `report_no_mismatch` **0**, `duplicate_identity` **0**, `ADR-006` **0**, `ADR-009` **0**, `parse_cache` **0**.
- Qrafda olub artıq olmayan: `tests/test_pre_processor_parallel.py`.
- `main.py`, `uploader.py` qrafdadır, amma 2026-07-21 halında (manifest `ast_hash`).

**Agenti yanıldırmı — bəli, sübut:** skill agentə əvvəl qrafı sorğulamağı deyir; qraf pipeline-ın 2026-07-20 halını göstərir. Məsələn, "report № uyğunsuzluğu necə işlənir?" sualına qraf heç bir node qaytarmaz (0 uyğunluq), agent "yoxdur" nəticəsinə gələ bilər, halbuki `main.py:66` `report_no_mismatch` import edir və ADR-008 var. Eyni risk ADR-003 (PDF birbaşa oxuma) üçün: qrafda `pdf_reader` 0, `pdf2docx` isə 4 dəfə keçir — köhnə arxitektura.

**Versiya fərqi:** repo `.claude/skills/graphify/.graphify_version` = `0.9.15`; qlobal `~/.claude/skills/graphify/.graphify_version` = `0.9.30`; `SKILL.md`, `references/hooks.md`, `references/update.md` fərqlidir. Claude Code hər ikisini görəndə hansının qalib gəldiyi **UNKNOWN / NEEDS VERIFICATION**.

### 2.5 Skills

- `.agents/skills/`: 17 qovluq + `README.md` (`README.md` "Active skills: 17"). 19 fayl tracked.
- `.claude/skills/`: yalnız `graphify` (10 fayl tracked).
- `skills-lock.json` (tracked, 2026-07-10): versiya 1, **iki** skill — `caveman` (`juliusbrussee/caveman`, `skills/caveman/SKILL.md`, sha256 `723fb2a8…`) və `find-skills` (`vercel-labs/skills`, `skills/find-skills/SKILL.md`, sha256 `781bd6d3…`). Qalan 15 skill və graphify lock-da yoxdur (`PROJECT_CONTEXT.md:995` eyni divergensiyanı qeyd edir).
- **`/caveman` haradan yüklənir:** bu sessiyada Skill aləti skill-i "Base directory for this skill: `C:\Users\Admin\.claude\skills\caveman`" ilə yüklədi. `ls -la` göstərir: `~/.claude/skills/caveman -> /c/Users/Admin/.agents/skills/caveman` (symlink, 2026-07-16). Yəni mənbə **istifadəçi home-undakı `~/.agents/skills/caveman`**-dır, repo-dakı `.agents/skills/caveman` deyil. `diff -rq` iki qovluğu **eyni** göstərir. `find-skills` da eyni üsulla symlink-dir. Repo `.agents/skills/` Claude Code tərəfindən birbaşa yüklənmir; `/skill-name` → `.agents/skills/<name>/SKILL.md` qaydası yalnız konvensiyadır (`.agents/skills/README.md:38`, istifadəçi yaddaşı).

### 2.6 `Claude outputs/`

| fayl | git | status | sübut |
|---|---|---|---|
| `AGENT_BRIEF.md` | untracked | **aktual** | 24.09.2026; "bu sənəd təkbaşına kifayətdir, əvvəlki handoff-lara ehtiyac yoxdur" |
| `F1_inventory_prompt.md` | untracked | aktual (bu tapşırıq) | 2026-09-28 |
| `range_merge_prompt.md` | untracked | köhnəlib — icra olunub | ece881b (2026-09-28) "tag/standard/item merge in by_number ranges" |
| `ADR_006-009_prompt.md` | untracked | köhnəlib — icra olunub | d18fccb (2026-09-24) ADR-006..009 əlavə edib |
| `HANDOFF_4.md` | untracked | köhnəlib | 21.09; AGENT_BRIEF əvəz edir |
| `HANDOFF_3.md` | tracked | köhnəlib | 18.09 əlavə, HANDOFF_2 ilə oxunur |
| `HANDOFF_2.md` | tracked | köhnəlib | HANDOFF_4 əvəz edir |
| `HANDOFF.md` | tracked | köhnəlib | 2026-09-17 versiyası; root `HANDOFF.md` onun 09-18 redaktəsidir (`diff --strip-trailing-cr`: yalnız vəziyyət rəqəmləri fərqli) |

Heç bir kod/test `Claude outputs/`-a istinad etmir. Qovluq adında boşluq var.

### 2.7 `samples/`, `standarts/`, `images/`, `assets/` — kod işlədirmi?

- `images/` — **bəli.** `config.py:68` `images_dir`, `:80-81` `header_logo`/`stamp_logo`; settings `images_dir: "images"`, `Mag-Pi Logo.png`, `Mohur Logo.png` (`settings.example.yaml:27,31-32`); `generate_pipeline_summary.py:91`.
- `assets/` — **bəli** (`assets/fonts`). `settings.example.yaml:26,664-668`; `generate_pipeline_summary.py:86-87`; `gui/ui/theme.py:134`; `standarts/generate_add_portal_request.py:40-41`. TTF-lər ignored (`.gitignore`), yalnız `README.md` tracked. **Ölü istinad:** `gui/ui/theme.py:71` "See assets/stitch export DESIGN.md" — `assets/`-də `stitch` yoxdur, `TODO.md:91` onun silindiyini yazır.
- `standarts/` — **qismən.** `butun_standartlar.md`-ni drift testi oxuyur (`tests/test_master_standards_sync.py:30`); runtime kodu yalnız sənəd/şərhdə adını çəkir (`method_registry.py:493`, `document_aggregator.py:419` log mətni, `uploader.py:487-489` şərh). `generate_add_portal_request.py` birdəfəlik generatordur (heç kim çağırmır). `add_portal.txt` heç yerdə istinad olunmur.
- `samples/` — **xeyr.** Kod/test istinadı yoxdur (`tests/test_range_merge_keys.py:177` "E3" bölmə başlığıdır, yol deyil). Ignored (`.gitignore:103`); içində real müştəri PDF+JSON və 164K gap audit.

### 2.8 Gözlənilməyən / dağınıq şeylər

1. **İki `services` paketi:** `src/monthly_report/services/` (LAN ingestion, `main.py:76`) və `src/monthly_report/gui/services/` (GUI). Ad eynidir, rol fərqlidir.
2. **Paket root skriptini import edir:** `network_ingestion.py:41-47` repo kökünü `sys.path`-a qoyub `discover_network_share` import edir — layering tərsinə.
3. **`standarts/`** yazılışı səhvdir, amma test yolu (`test_master_standards_sync.py:30`) ona bağlıdır.
4. **`standarts/` içində kod** (`generate_add_portal_request.py`) və generator çıxışları (`.docx`, `.pdf`) tracked.
5. **`config/fields.yaml`**: `settings.example.yaml:25` `fields_config` açarını heç bir `.py` oxumur (`git grep fields_config|fields.yaml` — yalnız yaml və `requirements.txt:6` şərhi). Ölü config ola bilər — **NEEDS VERIFICATION**.
6. **`.gitignore:18` `!input/.gitkeep`** — amma `input/.gitkeep` 39769c3 (2026-07-27) ilə silinib; `input/` git-də yoxdur.
7. **`.gitignore:27`** `output_backup_20260921/` sətri `:28` `output_backup_*/` ilə artıqdır.
8. **Python versiyası:** `setup.ps1:16` / `setup.sh` "Python 3.10+", `pyproject.toml` `requires-python = ">=3.11"`, README badge 3.11+.
9. **Root `.venv` yoxdur**, amma setup skriptləri onu yaradır; `src/monthly_report_auto.egg-info` var — hansı interpreter işlədilir **UNKNOWN**.
10. **`output/` içində ~30 audit `.md`** (identity_warnings ×7, report_no_mismatch ×3, range_verdict ×2 …) müştəri qovluqları ilə qarışıq. Operator-data — toxunulmur, amma gələcək üçün qeyd.
11. **`file_paths_ex.md`** root-da, ignored, real LAN yolları ilə — `fae8fdc` onu untrack edib, fayl diskdə qalıb.
12. **`config/settings.yaml.bak`** (2026-09-03) — `settings_writer.py:130` yaradır; köhnə (25 gün).

---

## 3. Təklif olunan hədəf struktur

Qaydalar: kod yerində; operator-data yerində; backup → `_archive/` (gitignored, silinmir); köhnəlmiş sənəd → `docs/history/`.

```
Monthly-Report-Auto/
├── main.py  uploader.py  gui_launcher.py        # entrypoint — yerində
├── discover_network_share.py                    # qalır: paket import edir
├── generate_pipeline_summary.py                 # qalır: test import, root yolları
├── reset_and_sync_input.py  reset_upload_ledger.py   # qalır: root yolları / test
├── generate_inspector_worksheet.py              # qalır — taleyi Selimdə
├── README.md  CLI_MANUAL.md  TODO.md            # TODO = yalnız açıq roadmap + bugs
├── CLAUDE.md  INDEX.md                          # F2-də yazılacaq (indi YOX)
├── pyproject.toml  requirements.txt  setup.ps1  setup.sh
├── .gitignore  .gitattributes  skills-lock.json
├── architecture/            # ADR-001..009 — yerində (README linkləri)
├── config/  translations/  assets/  images/  standarts/
├── src/monthly_report/      # dəyişməz
├── scripts/  tests/
├── docs/
│   ├── INVENTORY_2026-09-28.md
│   ├── PROJECT_CONTEXT.md   # root-dan; yenilənməli (split)
│   ├── AGENT_BRIEF.md       # Claude outputs-dan (Selim qərarı)
│   └── history/
│       ├── HANDOFF_2026-09-18.md          # root HANDOFF.md
│       ├── TODO_log_2026-07-10_to_09-18.md # TODO.md jurnal hissəsi
│       └── claude-outputs/  # HANDOFF, _2, _3, _4, *_prompt.md
├── .agents/skills/          # + SKILLS_MANIFEST.md → README.md-yə birləşir
├── .claude/skills/graphify/
├── input/  output/          # operator-data — toxunulmaz
├── .state/ .parse_cache/ .browser_profile/ .upload_state.json
└── _archive/                # gitignored, heç nə silinmir
    ├── output_backup/  output_backup_2026*/  output_stale/
    ├── graphify-out_2026-07-21/
    ├── samples/
    └── file_paths_ex.md
```
