/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. C', D, E and F are done (`cfcd91c`, `d6826df`). Do not redo them.

# R6b — Small cleanups, inspector request list, prepare the private repo

Order: A → B → C. STOP where marked.

## A. Small cleanups

- `TODO.md`: the item "`AWS D1.1` / `ISO 11666` / `ISO-23278` block 8 of 25" is stale (AWS D1.1 is on the portal list now). Rewrite it to today's state from your D recount: what still blocks, and which documents. Add a journal line.
- Operator decision: `allowed_standards` stays unchanged. `DNV-RP-B204` and `ISO 10675-12 Level 1` are NOT added. No change needed; mention it in the journal line.
- `placeholder_standard: "API 5L"` in the live config: leave it.
- Commit: `docs(todo): standard blockers after the 21-list`.

## B. Inspector request list (Azerbaijani, for the operator to send)

Write `docs/inspector_request_<YYYY-MM-DD>.md` **in Azerbaijani**, 2026+ only, in plain non-technical language. The reader is the inspector.

**Section 1 — "Faylın içində başqa hesabatın məlumatı var".** Table columns: Hesabat № | Faylın yeri (full LAN path from the manifest `unc_path`) | Faylın içində yazılan nömrə | Nə lazımdır.
Include:
- U-RT-26-052, -061, -063, -093;
- U-UTM-26-013, -021;
- U-RT-26-070(VG) (body says 067; header weld differs);
- any other 2026+ mismatch copy whose real report is still missing.

"Nə lazımdır" = "Bu nömrənin öz yoxlama məlumatı ilə fayl doldurulsun".

**Section 2 — "Heç bir faylı tapılmayan nömrələr":** KF-MT-26-004, KF-RT-26-097, and any other 2026+ number with no file anywhere.

**Section 3 — "Fayl adında səhv":** the 10 `U-RT-26-130…141VG).docx` files (missing "("). Give the full path and the correct new name for each.

**Section 4 — "Eyni nömrə iki fərqli işdə":** B-MT-26-001 / 002 (`Bosshelf`, March vs `MAG-Pi`, April), with both paths. Ask which is correct.

Rules:
- No person names, no VÖEN.
- LAN paths are allowed here: the file is for internal sending.
- Add `docs/inspector_request_*.md` to `.gitignore` (keep CRLF), so the paths never reach a repo. Commit only the `.gitignore` line.
- Report the count per section.

## C. Prepare the move to a new PRIVATE repo

The operator will create an empty private GitHub repo and give the URL. Purpose: view the project on a MacBook and show its scope. The pipeline only runs on the Windows workstation (LAN and portal).

1. **Secret scan of the FULL history** (`git log -p --all`), not only HEAD. Look for:
   - the identity-document values in the live `portal.director` block (compare without printing them);
   - 10-digit VÖEN values from the live `clients` block;
   - the director's name;
   - UNC paths and the LAN host;
   - passwords and tokens.

   Report each hit as commit:file:line, value masked. Do NOT rewrite history; the operator decides.
2. **Quick start for another machine.** Add a `README.md` section "Quick start on another machine":
   - Python ≥ 3.11;
   - `pip install -r requirements.txt` (say which tests need Playwright / PySide6);
   - `python -m pytest -q`;
   - which tests skip without `corpus/`, the LAN, or `config/settings.yaml`, and why;
   - what only works on the Windows workstation: LAN sync, the uploader browser run, the GUI exe.

   Prove it: `git clone` into a temp folder (no `input/`, `output/`, `corpus/` or live settings there) and run `pytest`. Fix only test-side assumptions, never production behaviour. Report passed / skipped / failed / xfail. Commit: `docs(readme): quick start on another machine`.
3. **STOP and wait for the URL.** When given: `git remote add private <URL>`, `git push private --all`, `git push private --tags`. Do not touch or delete `origin`. Show `git remote -v` and the pushed refs.

## Red lines

- No `--live`, no browser, no `--probe`.
- Nothing is deleted. Existing `print()` texts do not change. `allowed_standards` is not changed.

STOP after C.2.
