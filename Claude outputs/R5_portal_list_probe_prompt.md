/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`.

# R5 — The portal now offers 37 standards: probe, update the list, recount

## New fact (operator, 2026-10-06)

The add-portal request (`standarts/add_portal_request.*`, July 2026) was **approved**. The portal now offers the 16 standards in `standarts/in_portal.md` **plus** these 21:

```
API 510
API 570
API 620
API 650
ASME B31.1
ASME B31.3
ASME I-XII
ASTM E 572
ASTM E 1476
AWS D1.1
ISO 3057
ISO 10863
ISO 16809
ISO 17637
ISO 19285
ГОСТ 7512-82
ГОСТ 18442-80
ГОСТ 26790
ГОСТ Р 51780
ГОСТ Р 55724-2013
ГОСТ Р 56512-2015
```

These are typed from an operator screenshot. The **exact listbox text** must come from a live probe, because the uploader clicks `option` by exact name.

This replaces the 2026-10-05 statement "ASME I-XII is not on the portal".

Order: A → B (operator present) → C → D → E. STOP at the end.

## A. Probe safety proof (read-only)

Before anything runs, prove with file:line that `python uploader.py --probe`:
- never clicks "Yadda saxla", submit, or E-imza;
- never writes the live ledger (`.upload_state.json`) or `output/upload_status.json`;
- writes only `output/portal_form_probe.json`, which `_report_sidecars` excludes.

State exactly what the probe does: does it open the appeal form? Does it read the standards listbox? Does it type into or select anything?

If any of these cannot be proven: STOP and report.

Also answer: can the probe select two standards and read the chips back **without saving** (the P0 chip check in TODO)?
- If yes, with an existing flag: name the flag.
- If not: write the minimal plan for a `--probe-chips` addition (uploader change under the ADR-010 exception), but do NOT implement it yet.

## B. Run the probe (operator present)

1. Tell the operator in one line what to do: log in with Asan İmza and open the appeal form; the script takes over. Then run `python uploader.py --probe`.
2. Back up the old `output/portal_form_probe.json` first (`_archive/portal_form_probe_2026-08-12.json`, copy, not move).
3. Report:
   - the full `standard_options` list as read (exact text, count);
   - a diff against `in_portal.md` + the 21 above, by `_standard_key`: missing, extra, and spelling differences.
4. If the probe count is not 37, or the options differ from the operator's list: STOP after reporting. Do not update anything.

## C. Update the portal list (only if B matches)

Use the probe's exact text everywhere.

- `uploader.py` `PORTAL_STANDARDS`: replace with the probed 37. This is under the ADR-010 exception; change only this constant and any comment that states "16".
- `standarts/in_portal.md`: rewrite as the 37-row table, using the probe text. Keep the existing `test` that asserts `in_portal.md == PORTAL_STANDARDS`, and keep `test_registered_standards_match_the_portal_exactly` green with the new probe file.
- Live `settings.yaml` `portal.standard_aliases` (backup, Python, CRLF, before/after):
  - re-add `"ASME I-XII"` covering ASME Sections I–XII only (Roman numerals, e.g. `ASME VIII`, `ASME IX`);
  - do **not** map `ASME B31.x` to it, because `ASME B31.1` and `ASME B31.3` are now their own options;
  - keep `EEMUA 153/158` and `ASTM E797/E797M`;
  - check whether any other document spelling needs an alias to hit a new option. Examples: `ISO 17637` vs `ISO-17637`, `ASTM E1476` vs `ASTM E 1476`, `GOST` in Latin letters. List what you find, add only exact, safe aliases, and show the evidence.
- Fix the ASME comments in `settings.yaml` and `settings.example.yaml` again (comments only).
- Update ADR-010 with a short addendum: portal list 16 → 37 on 2026-10-06, the probe file, and the alias change. Update CLAUDE.md §10: the "Portal standards = 16" line becomes 37 with the date.
- `python -m pytest -q`.
- Commit: `feat(uploader): portal offers 37 standards (probe 2026-10-06)`.

## D. Recount 2026+ (read-only, pre-flight functions)

With the new list, holds and the closed-month rule, report:
- filable / held / not-yet / refused, each by document ID;
- for every filable document: standards filed and standards still skipped;
- documents that are filable under `standard_policy: all` (every standard on the portal). These now file complete;
- what still blocks each refused document (e.g. AZF Q-documents, ISO 11666, ISO 23278, ISO 10675-1);
- the effect of the change on the `[unapproved standard]` compile gate. `allowed_standards` is a separate list: say whether any of the 21 are missing from it, so rows were silently omitted from PDFs. **Do not change it**; only list.

## E. Enable `filtering.exclude_delete_folder_sources`

Operator approved.
- Set it to `true` in the live config (backup, CRLF).
- Run `python main.py` once.
- Report:
  - NOV_JAN_2026 3→2 rows and UP_FEB_2026 8→7 rows, as simulated;
  - the Coverage line;
  - that the filable list did not change because of E.

## Red lines

- No `--live`. The probe is the only browser run, and only with the operator present.
- Nothing is deleted. Existing `print()` texts do not change.
- Do not touch the portal's existing drafts.

STOP.
