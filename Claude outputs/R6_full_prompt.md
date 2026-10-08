/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. This prompt replaces the R5 prompt and every correction sent after it.

# R6 — Provisional portal list, recount, delete-folder key, probe-chips code, inspector list, private repo

Order: C → D → E → F → G → H. Each code change gets its own commit. STOP where marked.

## Operator decisions (final)

- **P1. The portal probe is postponed.** Portal login is not available now. Nothing in this prompt runs the browser.
- **P2. The portal list was REPLACED.** It now offers EXACTLY these 21 standards and nothing else:
  `API 510, API 570, API 620, API 650, ASME B31.1, ASME B31.3, ASME I-XII, ASTM E 572, ASTM E 1476, AWS D1.1, ISO 3057, ISO 10863, ISO 16809, ISO 17637, ISO 19285, ГОСТ 7512-82, ГОСТ 18442-80, ГОСТ 26790, ГОСТ Р 51780, ГОСТ Р 55724-2013, ГОСТ Р 56512-2015`.
  The old 16 (`EEMUA 153/158`, `API 1104`, `ISO 17636`, `ISO 17640`, …) are gone.
- **P3. Only these 21 may be filed to the portal.** Do **not** change `allowed_standards` (the compile gate). `DNV-RP-B204` and `ISO 10675-12 Level 1` are NOT added. Rows already omitted from PDFs stay as they are.
- **P4.** The 19 low-confidence translations are accepted. No change.
- **P5.** `filtering.exclude_delete_folder_sources` is approved → ON.

## C. Provisional 21-standard portal list (no probe)

- Copy `standarts/in_portal.md` to `standarts/in_portal_2026-08-12.md`. Rewrite `in_portal.md` as the 21, in the operator's spelling, with a header line: `Source: operator screenshot 2026-10-06 — NOT yet probe-verified`.
- `uploader.py` `PORTAL_STANDARDS` = these 21 (ADR-010 exception). Add a code comment with the same "not probe-verified" note.
- Live `settings.yaml` `portal.standard_aliases` (backup first, edit with Python, keep CRLF, show before/after):
  - remove `EEMUA 153/158` and `ASTM E797/E797M` (their targets no longer exist; an alias to a missing option makes the dry-run falsely green);
  - re-add `"ASME I-XII"` for ASME Sections I–XII only (Roman numerals, e.g. `ASME VIII`, `ASME IX`), NOT `ASME B31.x`, since B31.1 and B31.3 are their own options;
  - list other spellings in 2026+ sidecars that would need an alias to hit one of the 21 (e.g. `ISO-17637`, `ASTM E1476`). Give evidence. Add only exact, safe aliases.
- The test that pins the old 2026-08-12 probe JSON to `PORTAL_STANDARDS` will now disagree. Do not delete it: mark it `xfail(strict=True)` with reason `probe pending (TODO P0)`, so it fails loudly once a new probe makes it pass.
- Update the other tests that pin the old 16 or treat EEMUA / API 1104 as filable to the new list. List each changed test.
- Update the existing TODO P0 item: `Probe required before the first --live: confirm the exact text of the 21 options + chip check (--probe-chips)`.
- Fix the ASME comments in both settings files (comments only). Add an ADR-010 addendum: list replaced 16 → 21 on 2026-10-06, provisional. Update CLAUDE.md §10.
- `python -m pytest -q`.
- Commit: `feat(uploader): provisional 21-standard portal list (probe pending)`.

## D. Recount 2026+ (read-only, the uploader's own pre-flight functions, with holds and the closed-month rule)

- filable / held / not-yet / refused, each by document ID;
- for each filable document: standards filed and standards skipped;
- documents that now file COMPLETE (every standard is on the list);
- a diff against the old 15 filable: which stay, which are lost (they relied only on EEMUA 158 / API 1104), and which are new;
- what still blocks each refused document.

## E. Delete-folder key ON

- Set `filtering.exclude_delete_folder_sources: true` in the live config (backup, CRLF).
- Run `python main.py` once.
- Report:
  - NOV_JAN_2026 3→2 rows and UP_FEB_2026 8→7 rows;
  - the Coverage line and the İtem-English line;
  - that the filable list did not change because of E.

## F. `--probe-chips` (code and tests only — do NOT run it)

Implement your minimal plan from R5-A:
- a new flag;
- in `_do_probe`, after the form opens, select 2 options from `PORTAL_STANDARDS` (or `--probe-chips A,B`);
- read the chip texts back;
- write them to the probe JSON as `chip_readback`;
- reset the form.
- No fill, no attach, no save.

Tests:
- parser;
- a fake page proving that no "Yadda saxla", ledger or upload_status write happens;
- `chip_readback` is written.

Commit: `feat(uploader): --probe-chips (not yet run)`.

## G. Inspector request list (Azerbaijani, for the operator to send)

Write `docs/inspector_request_<YYYY-MM-DD>.md` **in Azerbaijani**, 2026+ only. Use plain, non-technical language: the reader is the inspector, not a developer.

**Section 1 — "Faylın içində başqa hesabatın məlumatı var".** Table columns: Hesabat № | Faylın yeri (the full LAN path from the manifest `unc_path`) | Faylın içində yazılan nömrə | Nə lazımdır.
Include:
- U-RT-26-052, -061, -063, -093;
- U-UTM-26-013, -021;
- U-RT-26-070(VG) (body says 067, header weld differs);
- any other 2026+ mismatch copy whose real report is still missing.

"Nə lazımdır" = "Bu nömrənin öz yoxlama məlumatı ilə fayl doldurulsun".

**Section 2 — "Heç bir faylı tapılmayan nömrələr":** KF-MT-26-004, KF-RT-26-097, plus any others for 2026+.

**Section 3 — "Fayl adında səhv":** the 10 `U-RT-26-130…141VG).docx` files (missing "("), with full paths and the correct name for each.

**Section 4 — "Eyni nömrə iki fərqli işdə":** B-MT-26-001 / 002 (`Bosshelf`, March vs `MAG-Pi`, April), with both paths. Ask which one is correct.

Rules:
- No person names, no VÖEN.
- LAN paths are allowed here: this file is for internal sending.
- Add `docs/inspector_request_*.md` to `.gitignore` so the paths never reach a repo.
- No commit needed beyond the `.gitignore` line.

## H. Prepare the move to a new PRIVATE repo

The operator will create an empty private GitHub repo and give the URL. Purpose: view the project on a MacBook and show its scope. The pipeline itself only runs on the Windows workstation (LAN and portal).

1. **Secret scan of the FULL history** (`git log -p --all`), not only HEAD. Look for:
   - the identity-document values in the live `portal.director` block (compare without printing them);
   - 10-digit VÖEN values from the live `clients` block;
   - the director's name;
   - UNC paths and the LAN host;
   - passwords and tokens.

   Report each hit as commit:file:line, with the value masked. Do NOT rewrite history; the operator decides.
2. **Make the repo readable and testable on another machine.** Add a `README.md` section "Quick start on another machine":
   - Python ≥ 3.11;
   - `pip install -r requirements.txt` (Playwright and PySide6 are optional for tests: say which tests need them);
   - `python -m pytest -q`;
   - which tests skip without `corpus/`, the LAN, or `config/settings.yaml`, and why;
   - what only works on the Windows workstation: LAN sync, the uploader browser run, the GUI exe.

   Prove it: `git clone` the repo into a temp folder (no `input/`, `output/`, `corpus/` or live settings there) and run `pytest`. Fix only test-side assumptions, never production behaviour. Report the passed / skipped / failed counts.
3. **STOP and wait for the URL.** When given: `git remote add private <URL>`, `git push private --all`, `git push private --tags`. Do not touch or delete the old `origin`. Show `git remote -v` and the pushed refs.

## Red lines

- No `--live`, no browser, no `--probe` run.
- Nothing is deleted. Existing `print()` texts do not change.
- `allowed_standards` is not changed.

STOP after H.2.
