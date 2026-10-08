/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Read `CLAUDE.md` first and follow its red lines.

# R1 — Reports export folder + portal standard rule (STEP 1: measure and plan only)

This step writes **no code** and changes **no files**. Measure, plan, list blocking questions, then STOP.

## A. Measure now (read-only) and report exact numbers

1. Compiled documents per client and per month, for months **>= 2026-01** (count sidecars in `output/*/compiled_monthly_report_*.json`). Also give the total for all months.
2. Tests: `python -m pytest --collect-only -q | tail -1` and `python -m pytest -q | tail -1`.
3. Portal standards:
   - The operator's list is `standarts/in_portal.md` (16 rows).
   - Compare it with `output/portal_form_probe.json` `standard_options` (also 16) and with `config/settings.yaml` `allowed_standards` / `standard_aliases`, using the existing separator-blind matcher. Show three lists: only in `in_portal.md`, only in the code's list, in both. A quick advisor check found the same 16, differing only in spelling (`ГОСТ РЕН` vs `ГОСТ Р ЕН`); confirm or correct this.
   - **Neither list contains any ASME option**, yet `standard_aliases` maps ASME B31.x and ASME I–XII to `"ASME I-XII"`. Explain what the uploader does today with an ASME-only document, with file:line evidence.
   - A rough advisor count for 2026+ (not code-exact) found 0 documents uploadable under the current rule and 17 under the "at least one" rule. The difference is mostly ASME B31.3 and ASME VIII, which are not on the portal list. Reproduce this with the real matcher and correct it. Also reconcile it with the "19 uploadable" figure in older handoffs.
   - The standard string splitter matters: e.g. `EEMUA 158,Edition 3,Section 7.5.4` is ONE standard containing commas. Use the uploader's own split function and show how it splits that string.
4. Uploadable documents for months >= 2026-01, under two rules. Use the existing matching code (`uploader` standard key / aliases), read-only, without opening a browser. Do not run `--live`; `--dry-run` is allowed if it writes only its own dry-run ledger. Report per client:
   - **Current rule (zero substitution):** a document uploads only if **every** standard in it is on the portal list.
   - **New rule (at least one):** a document uploads if **at least one** of its standards is on the portal list. Only the matching standards are filed to the portal. A document with **zero** matching standards does not upload.
   - Also list the documents that change category between the two rules, with their non-portal standards.
   - Note `approved_clients` and any other gate that blocks a document independently of standards.

## B. Plan — reports export folder (no code yet)

The operator wants a human-friendly folder, starting from 2026-01 and kept up to date on every run.

Constraints to respect:
- `output/` is the uploader's input. Ledger key = root-relative PDF path, the sidecar sits beside its PDF, and the GUI catalog reads `output/`. Do NOT move or restructure `output/`.
- The new folder is an **export copy** built from `output/`, so the uploader and ledger are untouched.

Proposed design (critique it, improve it if needed):
- `reports/PDF/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.pdf`
- `reports/JSON/<CLIENT>/<YYYY>/<CLIENT>_<YYYY>-<MM>.json`
- The ISO `YYYY-MM` in the name makes alphabetical order equal chronological order, in every file browser.
- New months simply add files; new years add a folder.
- Config keys: `export.enabled` (default `false`), `export.dir` (default `reports`), `export.from_month` (default `"2026-01"`).
- Copies are made with hash comparison: unchanged files are skipped, changed ones are overwritten atomically. **Nothing is ever deleted.** Files in `reports/` that no longer have a source in `output/` are only listed in a report.
- Wiring: either a standalone script (`export_reports.py`), or a call at the very end of `main.py` after the last stage, behind `export.enabled`, without reordering stages and without changing existing prints (new print lines only). Recommend one and justify it.
- `reports/` must be gitignored, and `docs/INDEX.md` must be updated (`test_index_sync`).

Answer:
1. Does anything already read or write a `reports/` path?
2. Exact file names that would be produced for 2026-01+ (count and 5 examples).
3. Risks: the GUI, `.gitignore`, the uploader walking the tree (it must not see `reports/`; prove it with file:line), Windows path length.

## C. Plan — portal standard rule change (no code yet)

This changes `uploader.py`, which is a red line (ADR-002). The operator has explicitly asked for this behaviour; you still only plan here.

1. Locate every place the zero-substitution rule is enforced (file:line): the refusal `SKIPPED_UNMATCHED_STANDARD`, the payload builder, and the dry-run oracle.
2. Does the portal form accept **multiple** standards in one appeal? Check `portal_form_probe.json` and the form-filling code. If it is UNKNOWN, say so. This decides whether "all matching standards are filed" is even possible.
3. Proposed config key: `portal.standard_policy: all | any` (default `all` = today's behaviour).
   - With `any`: file only the matching standards, skip non-matching ones, and print a NEW line naming the skipped standards per document.
   - Zero matches: still refuse.
4. Where should the portal list come from: `in_portal.md` directly, or `config/settings.yaml` `allowed_standards` / aliases? Recommend one, and keep a single source of truth.
5. Which tests change, which new tests are needed, and how ADR-002 / zero-substitution docs get an amendment (new ADR-010?).
6. Risks, stated plainly. For example: the PDF lists a standard that the portal record does not carry.

## Output

- Part A numbers as tables.
- Part B and C plans, each with blocking questions.
- STOP. No code, no file changes, no commit.

## Red lines

- `input/`, `output/`, `.state/`, `.upload_state*.json`, `config/settings.yaml`: read-only.
- No `--live`. No browser.
- Do not delete or move anything.
