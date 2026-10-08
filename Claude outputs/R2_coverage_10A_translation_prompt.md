/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. The operator is reviewing documents one by one and found gaps.

# R2 — Coverage audit (A), `010A` in ranges (B), Azerbaijani İtem translations (C)

Order: A (read-only) → B (code, own commit) → C (draft only, no `az.json` change) → STOP.

## Advisor pre-check (verify, do not trust)

- `input/RT/BS-RT-26-099.docx`: body `Report No: BS-RT-26-099`, `Date: 14.08.2026`, `Client: BOS SHELF`. It is in no sidecar and has no quarantine reason. Its neighbour `BS-RT-26-100` (same date and client) IS in `BS_AUG_2026`. Why is 099 missing?
- `input/RT/KF-RT-26-070 (KF 2222).docx`: the body says `Report No: KF-RT-26-064`. It is a source-file error (the name says 070, the content is 064). With `block_mismatched_report_no: true` it was removed from `KHE_APR_2026` as a copy. The real 070 content does not exist in `input/`. Confirm.
- `KF-MT-26-028` and `KF-MT-26-029` ARE in `KHF_APR_2026` (dated 07.04 and 09.04). Confirm. The operator may have looked at another month.

## A. Universal coverage audit (read-only)

Goal: for every report the system has as a source, show where it ended up. "Silently missing" must become impossible to overlook.

1. Universe: every source file under `input/` (all subfolders, including `PDF_ARCHIVE`, `UnSorted`, `SKIPPED_REPORTS`, `_PRUNED`), plus the LAN manifest `.state/network_sync_manifest.json` `files` (6245 entries). Do not touch the LAN.
2. For each report number (from the filename AND from the body Report No where parsed), assign exactly ONE outcome with evidence:
   - in sidecar `<doc>` (row found);
   - removed as a mismatch copy (ADR-008);
   - quarantined (reason);
   - pruned (`_PRUNED`, rule);
   - twin dropped (PDF beside a `.docx`);
   - client excluded / inactive / below volume;
   - outside the date window / undated;
   - parse failure;
   - merged by `duplicate_identity`;
   - on the LAN but never staged;
   - **UNEXPLAINED**.
3. Report:
   - counts per outcome, per client, for 2026+ and for all months;
   - the full UNEXPLAINED list;
   - for `BS-RT-26-099`, trace the exact path through the code (file:line) to the point where it is lost, and name the root cause.
4. Sequence gaps: per client + method + year (e.g. `KF-MT-26-`), list every missing number between min and max. Show whether each gap has a source file anywhere (`input/` or the LAN manifest). A gap with a source file anywhere is a bug candidate; a gap with no file is a LAN / operator issue.
5. Propose a permanent guard. Recommendation to critique: a new audit written on every `main.py` run, `output/coverage_<YYYY-MM-DD>.md` (the uploader never reads `.md`, so this is safe under red line 6), plus one NEW stdout summary line `  Coverage: N sources, M in documents, K explained elsewhere, U UNEXPLAINED`. It must be behind a config key, default off.
6. If the root cause of UNEXPLAINED cases is a code bug: describe the fix and its blast radius (how many documents change), but do NOT implement it in this step. Stop after C and wait for approval.

## B. `BS-RT-26-010A` must sit inside the range

Image from the operator: `BS_MAY_2026` prints `BS-RT-26-(001-016)` and a separate row `BS-RT-26-010A`. The operator wants `010A` inside `(001-016)`, with no separate note.

Design (critique it if needed):
- New key `presentation.range_absorb_tails` (default `[]`; live value `["A"]`). Under `range_mode: by_number` only.
- After retest stripping, a number `<base><tail>` whose tail is in the list (exact, case-sensitive) is treated as a member of its base number's unit (`010A` → unit `010`).
- The range, date span and verdict rules include it as if it were `010`.
- `rej`, `test`, `del`, lowercase `a` and `range_tail_allow` behaviour are unchanged. The report number in the sidecar is never changed (red line 2).
- If the base number does not exist in the document (`010A` without `010`), the absorbed number fills the slot of 010 for gap purposes. State this explicitly in a test.
- Tests:
  - default `[]` is byte-identical;
  - `010A` is absorbed;
  - `010B` is not absorbed when the list is `["A"]`;
  - `003rej` is never absorbed;
  - base number missing;
  - verdict rule;
  - sidecar unchanged.
- Live `settings.yaml`: add the key (backup, CRLF). `settings.example.yaml`, INDEX, and a short ADR-009 addendum.
- Then run `python main.py` once and show the new `BS_MAY_2026` table. Report the corpus-wide row and page change, and list every document where an absorbed tail changed a line.
- Commit: `feat(presentation): absorb letter tails into ranges`. Do not push.

## C. İtem / Detal must be Azerbaijani — draft only

Image from the operator: `KHF_AUG_2026` prints `Piping weld` and `Spool`. Earlier: `Welding of the basket arms`, `WQT`, `Pipe to pipe`. The document must be fully Azerbaijani.

1. Collect every İtem value that reaches a PDF and is not translated (not in `translations/az.json`, or printed with the `[AZ?]` marker, or still English after lookup). Use the existing `output/item_translation_review_2026-09-17.md` as a starting point, but re-measure on the current corpus.
2. Write `docs/translation_review_<YYYY-MM-DD>.md` with the columns: English source | count (rows) | documents | proposed Azerbaijani | confidence (high/low) | note.
   - Propose an NDT-correct Azerbaijani term for each. Examples: `Piping weld` → "Boru kəməri qaynağı", `Spool` → "Spul (boru seksiyası)". Flag low confidence for anything ambiguous.
   - Acronyms (WQT, PQR, WPS): propose "Azerbaijani term (ACRONYM)", e.g. WQT → "Qaynaqçının ixtisas sınağı (WQT)".
   - Identifiers (serial numbers, spool IDs, `DB-2`) are not translated: list them separately as "keep as is".
3. Do NOT edit `translations/az.json`. The operator approves the table first; applying it is the next step.
4. Report the counts: unique terms, rows affected, documents affected, and how many of the 2026+ uploadable documents contain an English İtem.

## Red lines

- No `--live`, browser or `--probe`.
- `input/`, `.state/` and the LAN are read-only. Nothing is deleted.
- Existing `print()` texts do not change. `uploader.py` does not change in this step.

STOP after C.
