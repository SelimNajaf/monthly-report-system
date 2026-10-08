/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. Context: your R2 report.

# R3 — Coverage fixes, guard, review lists (2026+ focus)

## Operator decisions (final)

- **S1.** Only 2026 and later matter. Do not release or touch the 100 SDLN 2025 files in `SKIPPED_REPORTS`, and do not chase pre-2026 gaps. Audits still count all months, but every list for the operator is 2026+ only.
- **S2.** Translation term: "weld" → **"qaynaq"** everywhere, not "tikiş". `Piping weld` → "Boru kəməri qaynağı". Existing `az.json` entries that render "weld" as "tikiş" must change to "qaynaq" too, so that documents stay consistent. This is a draft-only update in this step (see E).
- **S3.** Coverage guard: approved, with your changes from R2.

Order: A → B → C → D → E. Each code part gets its own commit. STOP at the end.

## A. `duplicate_identity` silent drop → note (fix 2)

- At `duplicate_identity.py:303`, every dropped transposed twin must leave a note in `report.skipped` (or the existing audit channel) naming both spellings.
- No document row may change. Prove it: sidecars byte-identical before and after.
- Tests: the note appears; rows are unchanged.
- Commit: `fix(identity): record merged transposition twins`.

## B. LAN files skipped by name only (fix 1)

- New key `network_ingestion.stage_size_mismatch` (default `false`).
- When `true`: a LAN file whose name matches a local file but whose **size differs** is staged as a `-lan` twin. The existing hash / twin logic then decides.
- **Never stage anything under a path segment named `delete` (case-insensitive)**, under either value of the key. List the 7 such files you found.
- Tests:
  - default is unchanged;
  - a size difference is staged as `-lan`;
  - an equal size is skipped;
  - a `delete\` path is never staged.
- Live `settings.yaml`: set it to `true` (backup, CRLF). Run `python main.py` once. For every newly staged file report where it went and what it changed. In particular:
  - the second `KF-RT-26-070 (KF 2222).docx`: what does its body Report No say? Is it the real 070?
  - `B-MT-26-001` / `002`;
  - `KF-MT-26-041` / `050`.
- Report the row and page change per affected document. Sidecars of untouched documents must be byte-identical.
- Commit: `feat(lan): stage same-name files whose size differs`.

## C. Coverage guard

- Key `audit.coverage_report` (default `false`; live `true`).
- Built from what `main.py` already knows (`report.skipped`, discovery quarantines, the ingestion manifest sizes). Do not re-hash `input/`.
- Write `output/coverage_<YYYY-MM-DD>.md`, with sections:
  - 2026+ first: per client, the outcome counts, the UNEXPLAINED list, and sequence gaps with and without a source file;
  - then the all-months totals.
- One NEW stdout line, 2-space indent, not starting with `[`, not ending in `.pdf`: `  Coverage: N sources, M in documents, K explained elsewhere, U UNEXPLAINED`. Prove it against every GUI regex.
- `U > 0` must never fail the run. It is a signal only.
- Copy your R2 scratch report to `docs/coverage_2026-10-05.md` as the baseline (2026+ section first, no LAN host name, no person names).
- Tests:
  - default off: no file, no line, byte-identical stdout;
  - the file and the line are produced;
  - UNEXPLAINED is counted;
  - the GUI regex negative test.
- INDEX, `settings.example.yaml`, a short CLAUDE.md §9 line ("check the Coverage line after each run").
- Commit: `feat(audit): coverage report per run`.

## D. Header-label leak into İtem (`S/N`, `Qty`, …)

- In `extractor.py`, header labels are being read as İtem values (R2 found 6).
  1. Plan the fix (file:line).
  2. Put the new behaviour behind a key, default the old behaviour. It changes sidecar rows.
  3. Set the key ON in the live config.
  4. Report which rows and documents change (2026+ list).
- Tests for each label.
- Commit: `fix(extractor): header labels never become item values`.

## E. Operator review lists (2026+ only, read-only, no code)

Write `docs/review_2026plus_<YYYY-MM-DD>.md` with:

1. **Standard gate omissions** (`[unapproved standard]`, 47 in 2026+). Group by standard: standard text | report numbers | documents | is it on the portal list (`PORTAL_STANDARDS`)? Example: `BS-RT-26-099` → `DNV-RP-B204`. The operator decides per standard: add it to `allowed_standards`, or treat the source as a typo.
   - Also show what the stdout cap hides today: the `[unapproved standard]` print shows only the first 10 of 379. Propose a NEW line or audit section that lists all of them. Do not change the existing print.
2. **Quarantined in 2026+** (51): report number | reason | file | what the operator should do.
3. **No source file anywhere** in 2026+: `KF-MT-26-004`, `KF-RT-26-097`, plus any others.
4. **Mismatch copies** in 2026+ whose real report is missing (`U-RT-26-005`, `U-UTM-26-013`, `-021`, `U-RT-26-052`, `-061`, `-063`, `-093`, `KF-RT-26-070` unless B finds it).

Also update `docs/translation_review_2026-10-05.md` for S2:
- use "qaynaq" for "weld";
- add a section listing every existing `az.json` entry that currently produces "tikiş" from "weld", with old → new values and the affected 2026+ row count.

Do not edit `az.json`; the operator approves the full table first.

## End

- `python -m pytest -q`.
- Report the final 2026+ uploadable count: run the pre-flight with holds and the closed-month rule. It was 15 before. Explain any change.
- Do not push.

## Red lines

- No `--live`, browser or `--probe`.
- `input/` is changed only by the normal pipeline (staging new LAN files). Nothing is deleted.
- Existing `print()` texts do not change. `uploader.py` does not change.

STOP.
