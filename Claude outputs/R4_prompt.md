/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. Context: your R3 report.

# R4 — Reconcile the upload count, `delete`-folder sources, hold BS_MAR_2026, apply İtem translations

Order: A → B → C → D. Each code or config change gets its own commit. STOP at the end.

## A. 15 vs 17 — reconcile by name (read-only)

The D6 pre-flight (commit `d149400`, 2026-10-05) listed **15** filable documents: UBOC 7, KHF 5, BS 3, i.e. the ADR-010 list minus UBOC_FEB_2026 and UBOC_SEP_2026. Your R3 pre-flight says **17**.

1. List your 17 by document ID, with the standards filed and skipped for each.
2. Diff the list against ADR-010's table minus FEB/SEP. Name the two extra documents and the exact reason each became filable: new rows from B, D's İtem fix, a new LAN file, or something else, with file:line or sidecar evidence.
3. Also reconcile the totals: D6 had 36 documents (15 + 2 held + 2 not-yet + 17 refused), R3 has 40. Name every document that was added.

No code here. If the difference reveals a bug, describe it and STOP before C.

## B. Sources staged from `delete` folders (measure, then key — default off)

R3 found 229 files in `input/` that were staged in earlier runs from LAN folders named `delete`. The inspector put them there to discard them.

1. Measure: which of those 229 currently feed a row in a **2026+** sidecar? For each, give: report number | document | the `delete` path | whether a non-delete twin with the same number exists, and which one the row came from.
2. Implement key `filtering.exclude_delete_folder_sources` (default `false`). When `true`, a source whose manifest `unc_path` contains a `delete` path segment (case-insensitive) is not used for any row.
   - Its files are **not moved or deleted**. Moving operator files only towards `_PRUNED/` is allowed, but do not move anything in this step.
   - Record each excluded source in `report.skipped` and in the coverage report under a new outcome "from delete folder".
3. Tests:
   - default is byte-identical;
   - the exclusion works;
   - a non-delete twin with the same number still feeds the row;
   - the coverage outcome is counted.
4. Do NOT enable it in the live config. Show the list from step 1 and the effect with the key ON (rows and documents that change in 2026+, simulated in memory). The operator decides.
5. Commit: `feat(filtering): exclude sources staged from delete folders (off by default)`.

## C. Hold `BS_MAR_2026` (config only)

`B-MT-26-001` / `002` exist twice: `Bosshelf` dated March, and `MAG-Pi` dated April, in `BS_APR_2026`. Until the operator confirms which inspection is real, hold the March document.

- Add `"BS_MAR_2026"` to `portal.hold_documents` in the live `settings.yaml` (backup first, edit with Python, keep CRLF, show before/after).
- No commit needed (the file is gitignored).
- Add an open item to `TODO.md` / the journal: "B-MT-26-001/002 reused across Bosshelf (Mar) and MAG-Pi (Apr) — operator to confirm".

## D. Apply the İtem translations

The operator reviewed `docs/translation_review_2026-10-05.md`. Scope rules (final):

- Translate **only values that render in the İtem / Detal column**.
- Do **not** translate the Üsul column (MT, UT, RT, DP, HrT, PMI…), report numbers, standards, dates, the verdict, or identifiers (`DB-2`, spool numbers, serials). Those stay exactly as they are.
- "weld" → **"qaynaq"** (S2), including the existing entries in section 5 of the review file (`Structural weld` → "Konstruktiv qaynaq", etc.).

Steps:

1. First prove where `translations/az.json` is used (file:line): only for İtem, or also for other fields such as header labels, Üsul, or the pdf_renderer captions. If one shared key would change something outside the İtem column (e.g. `Weld ID`), do not change that key. List it instead.
2. Remove from the review table every row that is not an İtem value. Keep the "keep as is" identifiers out of `az.json`.
3. Apply the remaining translations to `az.json`. The low-confidence rows are applied too, but each one is listed in the report so the operator can do a final check.
4. Add a guard: a test or audit that fails if any **2026+** sidecar İtem renders with `[AZ?]` or is a known English term. New English items must be visible, not silent. If a hard test is wrong for future LAN data, make it an audit line instead, and explain the choice.
5. `python -m pytest -q`, then `python main.py` once. Report:
   - İtem lines still in English in 2026+ documents (expected 0, list any);
   - documents re-rendered;
   - pages;
   - the Coverage line;
   - whether any of the filable documents changed status (they should not; this is presentation only, so sidecars change in the item field only).
6. Commit: `feat(i18n): Azerbaijani İtem translations; weld → qaynaq`.

## End

- Final 2026+ count: filable, held, not-yet and refused, each by document ID.
- Do not push.

## Red lines

- No `--live`, browser or `--probe`.
- Nothing is deleted or moved. `uploader.py` does not change. Existing `print()` texts do not change.

STOP.
