/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. Context: your own R1 Step 1 report (measurements and plans B and C).

# R1 Step 2 — implement the `reports/` export and `portal.standard_policy`

## Operator decisions (final — do not re-ask)

- **D2 confirmed by the operator in person.** `uploader.py` may be changed for this feature only. This is an explicit exception to the ADR-002 red line. Keep the change minimal; no unrelated refactoring.
- **QB1:** export every client, including unapproved ones.
- **QB2:** export both PDF and JSON.
- **QC1:** `ASME I-XII` is **not** on the live portal. `standarts/in_portal.md` is correct.
  - Remove the whole `"ASME I-XII"` entry from `portal.standard_aliases` in the live `config/settings.yaml`.
    - Back it up first (`config/settings.yaml.bak_<YYYYMMDD_HHMM>`).
    - Edit with Python, preserving CRLF.
    - Touch nothing else in that file.
    - Show the before/after lines.
  - Correct the docstring and comments that claim ASME I-XII was "added to the portal after the last probe". Comments only.
- **QC2:** under `any`, if the live listbox lacks an option that the baseline matched → refuse the **whole** report (fail-closed), same as today's backstop.
- **QC3:** AZF follows the rule like every other client. **No** special AZF block.
  - This replaces the settled rule "no AZF document uploads". Update `CLAUDE.md` §10 accordingly.
- **QC4:** do not build chip read-back now. The DOM is unknown.
  - Add a P0 TODO: "before the first `--live` with policy `any`, run `--probe` with a standard tagged and verify the chips".
  - Until that is closed, `--live` stays forbidden.

## Part B — `reports/` export (do first, own commit)

Implement your Step 1 plan B as written, plus the decisions above:

- Module: `src/monthly_report/services/report_export.py`.
- Called at the end of `main()` after the closing print, behind `export.enabled` (default `false`).
- Config keys:
  - `export.enabled`
  - `export.dir` (default `reports`)
  - `export.from_month` (default `"2026-01"`)
- Layout:
  - `reports/PDF/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.pdf`
  - `reports/JSON/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.json`
- Client from the `output/<Client>` folder; month logic as in `_sidecar_period_start`.
- Copy behaviour:
  - Hash compare; unchanged files are skipped.
  - Changed files are overwritten atomically with `os.replace`, and the file name is printed.
  - A `PermissionError` (file open in a viewer) is printed and the run continues.
- Two sources mapping to the same target → refuse both and print it.
- **Never delete anything.** Orphans are listed on stdout only.
- New stdout lines must not match the GUI regexes. Use the form `  Export: copied N, unchanged M, overwritten K, orphan J, failed F`, and prove it with a test against `progress.py` `_RENDERED`.
- `.gitignore`: add `reports/` (preserve CRLF). `docs/INDEX.md`: add a `(runtime)` line. `settings.example.yaml`: commented keys.

Tests:
- naming and sorting;
- skip when unchanged;
- overwrite when changed;
- collision refusal;
- orphan listing;
- `from_month` filter;
- `enabled: false` → byte-identical stdout and no `reports/` folder;
- the GUI regex negative test.

Then:
1. Set `export.enabled: true` in the live `settings.yaml` (backup, CRLF).
2. `python -m pytest -q`.
3. Run `python main.py` once. Report the `Staged N` line, the Export line, and the file count in `reports/` (expected 100 = 50 × 2, unless LAN brings new files — explain any difference).
4. Run it a second time → expect `copied 0`.

Commit: `feat(export): reports/ folder with PDF and JSON per client/year`.

## Part C — `portal.standard_policy: all | any` (own commit)

Implement your Step 1 plan C as written, plus the decisions above:

- Default `all` = today's behaviour, byte-identical on every code path.
- Under `any`:
  - split the standards into filable and skipped before the pre-flight;
  - zero filable → refuse (`SKIPPED_UNMATCHED_STANDARD`, as today);
  - otherwise file only the filable standards;
  - print a NEW line `  standards skipped (policy any): [...]`.
- `_simulate_standards` and the batch summaries must tell the truth under `any` (no "WILL SKIP REPORT" for a skipped token).
- Single source of truth: `PORTAL_STANDARDS`. Add a test asserting that `standarts/in_portal.md` equals `PORTAL_STANDARDS` by `_standard_key`. Do not read the `.md` at runtime.
- Do not change the existing 58 test references; they must stay green under `all`.

New tests:
- partial match files only the matches;
- zero matches refuses;
- the new print line;
- dry-run agrees with pre-flight;
- QC2 live-listbox-missing → whole report refused;
- the `in_portal.md` sync.

Docs:
- New `architecture/ADR-010-partial-standard-filing.md`: context, decision, the approved ADR-002 exception, risks (a), (c), (d) from your Step 1 written plainly, and the 17 documents with their dropped standards.
- Update `CLAUDE.md`: §5 zero-substitution row, §10 AZF line, §4 note on the ADR-002 exception scope. Stay ≤ 150 lines.
- Update `docs/INDEX.md` and `TODO.md` (P0 probe item, see QC4).

Then:
1. Set `portal.standard_policy: any` in the live `settings.yaml` (backup, CRLF).
2. `python -m pytest -q`.
3. First prove from code (file:line) that `uploader.py --dry-run` writes **only** `.upload_state.dryrun.json`, and never `output/upload_status.json` or the live ledger. If you cannot prove it, do NOT run it — STOP and report.
4. If proven: run `python uploader.py --dry-run --all --limit 200` and report the uploadable count for months ≥ 2026-01 per client. Expected 17 (UBOC 9, KHF 5, BS 3). Explain any difference; the ASME alias removal may change other months.
5. Report the full list of documents that would upload, with the standards filed and the standards skipped.

Commit: `feat(uploader): portal.standard_policy any — file matching standards only (ADR-010)`. Do not push.

STOP after Part C.

## Red lines

- No `--live`. No browser. No `--probe` in this step.
- `input/`, `output/` (except what `main.py` normally writes), `.state/`, and the live ledger stay untouched by you.
- Nothing is deleted. Existing `print()` texts do not change.
- `main.py` stage order does not change.
