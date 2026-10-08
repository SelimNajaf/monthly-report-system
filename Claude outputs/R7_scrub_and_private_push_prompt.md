/caveman

DO NOT GUESS. DO NOT INVENT FACTS. Mark anything unknown as "UNKNOWN / NEEDS VERIFICATION".
Follow `CLAUDE.md`. Context: your R6b report (A, B, C.1, C.2 done).

# R7 — Scrub personal data, push a cleaned history to the private repo

## Operator decisions

- **Q1. Inspector file:** keep the full LAN paths, including the host name. It is gitignored and sent internally.
- **Q2. The new private repo gets a cleaned history.** The original history is not pushed as-is. No real ID value, VÖEN, director name or LAN host goes into it.
- **Q3. `origin` and the local working repo are NOT rewritten in this prompt.** Rewriting happens only in a separate mirror copy.

Order: A0 → A → B → C. STOP where marked.

## A0. Count check (read-only, one short paragraph)

R5 reported 9 refused (all AZF). R6b-A says AZF January to October is 10 refused, plus `UBOC_OCT_2026`. Reconcile the two. Is the difference only October, which is not closed yet? Give the final 2026+ numbers (filable, held, not-yet, refused) with the closed-month rule applied.

## A. Scrub HEAD (working repo)

1. List every **HEAD** hit from C.1, by category, as file:line with the value masked. For each hit, give its role: test data, fixture, comment or docstring, HTML mock-up, or runtime code.
2. **`src/monthly_report/gui/services/settings_writer.py`**: explain why it contains the director's series number or name.
   - If the value is in a comment, a docstring or an example string: replace it with a fake value.
   - If runtime code uses the value (a default, a fallback or a comparison): **STOP and report**. Do not change behaviour.
3. Replace the real values in tests, fixtures and docs with **clearly fake values in the same format**. Validators must still pass.
   - FIN: 7 characters.
   - Series number: same length.
   - VÖEN: 10 digits. Check whether any test validates a checksum.
   - Name: e.g. `TEST DIREKTOR`.
   - LAN host and share: e.g. `\\lan-host\share`.
   - Keep the same fake value wherever the same real value appeared, so that the tests keep their meaning.
4. If the surname-only hits (`generate_inspector_worksheet.py:70`, `tests/test_inspector_registry.py:35–38`) are the same person, scrub them too. If they are a different person, leave them and say so.
5. `tests/test_index_sync.py:63` is the scan's own pattern. If it is a generic pattern, leave it. If it contains the real host, make the pattern generic.
6. Run `python -m pytest -q` on the workstation (expect 2252 passed, 1 xfailed) and on a fresh clone (expect 1719 passed, 534 skipped).
7. Re-scan HEAD with the C.1 patterns: **0 hits**.
8. Commit: `chore(privacy): replace real personal data in tests and docs with fakes`.

## B. Cleaned copy of the history (mirror only, outside the working repo)

1. `pip install git-filter-repo`.
2. `git clone --mirror <local repo path> <%TEMP%>\mrs_private.git`. Never run `filter-repo` in the working repo.
3. Write a replace-text file **outside every repo**, in `%TEMP%`. It maps each real value to the same fake value used in A: FIN, series, full name and its variants, every VÖEN, LAN host and share names. Run `git filter-repo --replace-text <file> --replace-message <file>`.
4. Files that exist only in history and contain mostly LAN paths or personal data (`file_paths_ex.md`, the `stitch_.../settings_diagnostics/code.html` mock-up): after the replace-text, check them again. If anything real is left, report it. Do not drop files without listing them.
5. Re-scan the **whole** rewritten mirror (`git log -p --all`, messages included) with the C.1 patterns: **0 hits**. Report:
   - commit count before and after;
   - branches and tags;
   - that the tree of the rewritten `main` tip equals the working repo HEAD after A (`git diff` empty, or explain).
6. Delete the replace-text file after the scan. This is your own temp file, so the no-delete rule does not apply to it.

**STOP after B.5** and wait for the private repo URL.

## C. Push (only after the URL is given)

1. From the mirror: `git push <URL> --all` and `git push <URL> --tags`. Do not push `refs/remotes/*`.
2. Show the pushed refs and `git ls-remote <URL>`.
3. **Do not** add the new URL as a remote of the working repo, and do not change `origin`. The working repo will be switched later, in a separate step, after the operator checks the new repo on his MacBook.

## Red lines

- No `--live`, no browser, no `--probe`.
- No history rewrite in the working repo. No change to `origin`.
- Production behaviour does not change. Existing `print()` texts do not change.
- Never print a real ID value, VÖEN or full name in your report. Mask them.
