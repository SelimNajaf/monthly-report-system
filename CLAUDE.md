# CLAUDE.md — Monthly Report Studio

## 1. What this is

NDT inspection reports (RT, MT, UT, DP, PMI, Ferrite; `.docx` / `.pdf`) arrive from a LAN share.
The pipeline compiles them into one PDF + one JSON sidecar per month × client.
`uploader.py` fills the E-Keyfiyyet state portal's appeal form with Playwright (unsigned draft only).
One operator, one Windows workstation, no server. The operator decides; you measure and propose.
File-by-file map: `docs/INDEX.md`. Decisions: `architecture/ADR-001…010`.

## 2. How to run

- Python: the system interpreter (`python --version`); `pyproject.toml` requires >= 3.11.
  There is **no `.venv`** — older handoffs that say "activate .venv" are stale.
- Shell: PowerShell is primary; Git Bash is also available.

```
python -m pytest -q                              # full suite
python main.py --force-rebuild                   # compile pipeline, re-render every group
python uploader.py --dry-run --all --limit 200   # simulate the upload queue, no browser
```

- `--dry-run` uses its own ledger (`.upload_state.dryrun.json`), never the live one.
- `--live` **only with the operator's explicit permission in this conversation.** Default: forbidden.
- `--force-rebuild` runs STAGE -1 first: it scans the LAN and may stage new files
  (`Staged N new report(s) for …`). Changed numbers after such a run are new input, not
  non-determinism. To measure idempotency, run twice back to back.
- Every flag: `CLI_MANUAL.md` (drift-tested by `tests/test_cli_manual_sync.py`).

## 3. Working rules

- Plan (files, lines, criteria, what changes) → code → `python -m pytest -q` → **STOP**.
- One step per prompt. Stop after each step and wait; do not chain the next one.
- Measure, never guess. A number you did not measure is not a number.
- Unknown = write `UNKNOWN / NEEDS VERIFICATION`. Never invent a fact.
- A number that differs from the expectation is explained, not forced to match.
- New behaviour always ships behind a config key whose default is the old behaviour.
  No silent change to an already delivered document.
- Backup before any change that can lose data.
- Operator prompts start with `/caveman` — honour it in replies (not in code, commits, docs).

## 4. Red lines

1. `uploader.py` is not refactored (ADR-002). Read it; change it only on the operator's explicit decision.
   One approved exception (2026-10-05): `portal.standard_policy`, `portal.hold_documents` and `portal.upload_closed_months_only` only (ADR-010 + addenda). It is not a licence for other changes.
2. Report numbers are never changed or "cleaned": `U-UT-25-003rej` is a real number.
3. Existing `print()` / log texts never change (the GUI regex-parses stdout). New lines may be added.
4. `main.py` stage order never changes.
5. Operator files: never renamed or deleted. Moves only towards `_PRUNED/`.
6. Nothing sample/test-like is written under `output/` (the uploader walks it recursively;
   a copy becomes a second ledger key). Samples go to `samples/` (ignored).
7. All PDF layout lives in `src/monthly_report/pdf_renderer.py` (ADR-001).
8. `--live` only with the operator's explicit permission.
9. Hands off (read-only unless told otherwise): `input/`, `output/`, `.state/`, `.parse_cache/`,
   `.browser_profile/` (portal session), `.upload_state*.json` (ledger), `config/settings.yaml`
   (live config with client IDs — ignored; commit only `config/settings.example.yaml`).

## 5. Core principles

| principle | meaning |
|---|---|
| Zero substitution | A standard the portal does not offer is never replaced by another. `portal.standard_policy: all` (default): one unmatched standard refuses the whole report. `any` (ADR-010): file the offered ones, print the rest; zero offered still refuses. |
| Idempotent ledger | SHA-256 content hash + two-phase `IN_PROGRESS` / `UPLOADED` checkpoint in `.upload_state.json`; key = root-relative POSIX PDF path. |
| stdout = public interface | The GUI runs the backend as a `QProcess` and regex-parses `print()` lines. |
| Three upload brakes | `MAX_REPORTS_PER_RUN = 1` (default `--limit`) · `--live` required to click "Yadda saxla" · E-imza is never clicked. Before any browser: `portal.hold_documents` and `portal.upload_closed_months_only` (no month still open) drop targets. |
| Fail-closed | `approved_clients` allowlist on both uploader paths. No evidence = do not act, do not invent. |
| Sidecar = source of truth | The JSON sidecar is the data; the PDF is a view of it. The uploader reads the sidecar. |

## 6. Pipeline map

Labels as in `docs/CODE_MAP_2026-09-28.md`; `main.py` prints its own stage numbering.

```
STAGE -1 LAN  services/network_ingestion (+ingestion_registry, discover_network_share.py) -> input/UnSorted/
STAGE 0 read  pre_processor (PDF archive, sort, prune) -> docx_reader -> pdf_reader + pdf_crosscheck
              parse_cache (.parse_cache/); reader disagreement -> input/SKIPPED_REPORTS/ (quarantine)
STAGE 1 group pre_processor.discover_groups -> document_aggregator
              (+ retest_tracker, duplicate_identity, report_no_mismatch)
STAGE 2 render translator -> pdf_renderer -> PDF;  json_exporter -> sidecar .json
              => output/<Client>/compiled_monthly_report_*.{pdf,json}
STAGE 3 upload uploader.py (separate process): sidecar -> upload_ledger -> Playwright -> portal draft
GUI           gui_launcher.py -> gui/ -> QProcess "gui_launcher.py --worker" -> import main / uploader
```

## 7. Where things live

- `docs/INDEX.md` — one line per root item, module, script and presentation/filtering/retest key.
- `architecture/` — ADR-001…010 (the why). `docs/CODE_MAP_2026-09-28.md`, `docs/INVENTORY_2026-09-28.md` — evidence.
- `TODO.md` — open items only; dated history and closed items: `docs/history/TODO_journal.md` (append-only).
- `docs/history/` — superseded context and handoffs. Read for history, not for current state.
- `_archive/` — retired backups, stale output, the old graph. Gitignored except its README. Never delete.

## 8. Known traps

- CRLF working files: `sed -i` mangles them. Edit with the Edit tool or Python.
- graphify is **not used** here. The graph in `_archive/graphify-out/` is from 2026-07-21 and stale; do not query it.
- The ADR-003 verdict gate (`tests/test_verdict_regression.py`) reads `corpus/verdict_regression/`, not `input/`.
  It is gitignored: a fresh machine must run `python scripts/build_verdict_corpus.py` first, or the gate
  SKIPS ("verdict gate NOT RUNNING", visible under `pytest -rs`). Every file is checked against
  `tests/data/verdict_corpus.sha256`; a missing or altered file FAILS. `MRS_VERDICT_CORPUS` overrides the path.
- `report_key_of` / `leading_token` stop at the first space: `RT-U-25-056 R1 (…)` keys as `RT-U-25-056`
  (the report number itself keeps `R1`). Open item in TODO.md.
- The portal holds drafts from earlier live runs; "the portal is empty" is unproven. Ledger was emptied 2026-09-04 (TODO P0; CODE_MAP §2.10).
- `main.py` imports `_parse_stem` from `monthly_report.gui.services.catalog`: headless code depends on the GUI package.
- Root `.py` files find their paths via `Path(__file__).parent`; do not move them.
- `standarts/` is spelled that way on purpose (a test path depends on it); do not rename it.

## 9. Current state

Numbers change; do not trust a number written in a doc. Measure
(Git Bash — PowerShell-də `tail`/`wc`/`grep` yoxdur):

```
python -m pytest --collect-only -q | tail -1                  # tests collected
python -m pytest -q | tail -1                                 # passed / skipped / failed
ls output/*/compiled_monthly_report_*.pdf | wc -l             # compiled documents
python -c "import json;print(len(json.load(open('.upload_state.json'))['entries']))"   # ledger entries
grep -c '^- \[ \]' TODO.md                                    # open TODO items
git log --oneline -5 && git status --short                    # branch state
```

After each `main.py` run, check the `  Coverage: … U UNEXPLAINED` line (`audit.coverage_report`);
U > 0 means a source file left no trace — read `output/coverage_<date>.md`.

## 10. Settled — do not reopen

- Portal standards = 21 since 2026-10-06 (operator screenshot; NOT yet probe-verified — TODO P0).
  The portal replaced its old 16 (probe 2026-08-12, kept in `standarts/in_portal_2026-08-12.md`).
  The company's 37-row list is not the portal's. Widening was rejected: the dry-run oracle would go falsely green.
- AZF follows the standard rule like every other client; no special AZF block (operator, 2026-10-05; replaces "no AZF document uploads").
- SDLN's `GIS-42-103` and `EP-GIS-18-016` are excluded on purpose.
- Document header is `Obyekt: <client name>`, not `Müştəri:`. Deriving "obyekt" from `item_detail` was tried once, wrong, reverted.
- No method band; the table has a `Üsul` column (7 columns).
- The live `.docx` always wins over its `PDF_ARCHIVE` copy. "Keep the first seen" is wrong (items sort by path).
- "Quarantine 13" was a one-off KB-1 result, not an expected per-run figure.

## 11. Glossary

| term | meaning |
|---|---|
| sidecar | the JSON beside each compiled PDF — source of truth |
| twin | the `.docx` and `.pdf` copies of one report |
| pull / pulled parent | a retest's original brought in from another month, as a reference (ADR-006/007) |
| transposition | `MT-U-25-028` ↔ `U-MT-25-028` — one number, two spellings (ADR-005) |
| weld | weld ID (`W1`, `QB-4`, `F03`) — smallest unit of inspection |
| `Yararlı` / `Yarasız` | accept / reject |
| retest chain | `028` → `028R1` → `028R2` |
| `-lan` | no-clobber twin created on a name collision during LAN sync |
| `_PRUNED` | set aside, not deleted |
