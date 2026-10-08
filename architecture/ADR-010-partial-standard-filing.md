# ADR-010: Partial standard filing — `portal.standard_policy: all | any`

- **Status:** Accepted — implemented behind `portal.standard_policy`, default `all`
  (today's behaviour); the live configuration sets `any`
- **Date:** 2026-10-05
- **Depends on:** the zero-substitution rule (`uploader.py` module docstring,
  `unmatched_standards`); ADR-004 (one document per client-month)
- **Changes:** `uploader.py` — an approved exception to the ADR-002 red line, scoped
  to this feature only (see below)
- **Does not change:** the sidecar, the PDF, the ledger, `PORTAL_STANDARDS`, the
  matching rules (alias / exact / token / core), any existing stdout line
- **Decision makers:** Operator (decisions D2, QC1–QC4, given in person on
  2026-10-05), implementation engine (measurement)

## Context

The portal's "inspeksiya:" multiselect offers 16 standards (`PORTAL_STANDARDS`,
probe-verified 2026-08-12; `standarts/in_portal.md` is the same list). Since ADR-004
one compiled document holds a whole client-month across every method, so it usually
cites several standards. Under the zero-substitution rule one standard the portal does
not offer refuses the whole document.

Measured on 2026-10-05 (approved clients, months ≥ 2026-01, live config after QC1):
35 target documents, **0** fileable under `all`. Before QC1 the dry-run baseline showed
18 fileable, but that number rested on an `"ASME I-XII"` alias target the live portal
does not offer (operator, QC1) — a false green. The alias entry was removed from the
live config.

## Decision

`portal.standard_policy` in `config/settings.yaml`:

| value | behaviour |
|---|---|
| `all` (default, also when absent) | unchanged: one unmatched standard refuses the whole report (`SKIPPED_UNMATCHED_STANDARD`) |
| `any` | the pre-flight splits the report's standards into fileable and not offered. Zero fileable → refused exactly as under `all`. Otherwise only the fileable ones are filed and a new line is printed: `  standards skipped (policy any): [...]` |

An unknown value raises `ValueError` when the pre-flight consults it.

Unchanged under both values:

- **Live backstop (QC2).** If the live listbox lacks a standard the baseline matched,
  the whole report is refused and the form is reset — the same backstop as before.
- **Nothing is substituted.** A skipped standard is left off, never replaced.
- **AZF (QC3).** No special block; AZF follows the rule like every other client. Today
  every AZF document is refused because its standards (`Doc No: Q00255 …`,
  `Doc No: Q01906 …`) match no portal option.
- **`PORTAL_STANDARDS` is the single source of truth.** `in_portal.md` is not read at
  run time; `tests/test_standard_policy.py` asserts the two name the same 16 documents.

Reporting under `any`: `_simulate_standards` narrates a skipped standard as
"not filed — not offered by the portal (policy any)", never "WILL SKIP REPORT". The
batch summary adds a `standards skipped (policy any): N report(s) …` block. A skipped
standard is not added to the "NOT filed" list, because its report was filed. Under
`all` both lists are empty and the output is byte-identical to before.

## The ADR-002 exception

`uploader.py` is otherwise not refactored (CLAUDE.md §4.1). The operator approved
changes for this feature only: the policy read, the pre-flight split, the dry-run
narration and the summary list. No other code was changed. Comments that claimed
"ASME I-XII" had been added to the portal were corrected (comments only).

## Risks — stated plainly

- **(a) The appeal names less than the inspection used.** An appeal filed under `any`
  lists only the standards the portal offers. The PDF still shows every standard,
  but the portal record alone does not. Reading the record alone, someone could think
  the inspection was judged only against those standards.
- **(c) The dry-run baseline can be falsely green.** The baseline is `PORTAL_STANDARDS`
  plus the alias targets in config. An alias target the portal does not offer makes
  `--dry-run` predict a filing the live listbox will refuse. That is what "ASME I-XII"
  did until QC1. The live backstop still refuses such a report, but the forecast was
  wrong.
- **(d) Selected chips are not read back.** After tagging, the code does not check the
  chips the MUI multiselect shows. The DOM for that is UNKNOWN / NEEDS VERIFICATION.
  The check is not built (QC4). Before the first `--live` with `any`, the operator must
  run `--probe` with a standard tagged and check the chips (TODO P0). Until that item
  is closed, `--live` stays forbidden.

## The 17 documents (measured 2026-10-05)

Approved clients, months ≥ 2026-01, live config, policy `any`. Under `all` none of
these files. Measured with the uploader's own pre-flight (`upload_report` with a
`DryRunPage`; nothing after the pre-flight ran).

| document | filed | left off |
|---|---|---|
| BS_MAY_2026 | API 1104, EEMUA 158,Edition 3,Section 7.5.4 | ASME B31.3 |
| BS_JUN_2026 | API 1104, EEMUA 158,Edition 3,Section 7.5.4 | ASME IX |
| BS_JUL_2026 | API 1104 | ASME B31.3 |
| KHF_FEB_2026 | EEMUA 158 | ASME VIII, ASME B31.3, AWS D1.1 |
| KHF_MAR_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| KHF_JUN_2026 | EEMUA 158 | ASME B31.3, AWS D1.1 |
| KHF_JUL_2026 | EEMUA 158 | ASME VIII, ASME B31.3, ISO 11666 |
| KHF_SEP_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_JAN_2026 | EEMUA 158 | ASME VIII |
| UBOC_FEB_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_MAR_2026 | EEMUA 158 | ASME B31.3 |
| UBOC_APR_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_MAY_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_JUN_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_JUL_2026 | EEMUA 158 | ASME VIII, ASME B31.3 |
| UBOC_AUG_2026 | EEMUA 158 | ASME B31.3 |
| UBOC_SEP_2026 | EEMUA 158 | ASME B31.3 |

`EEMUA 158` is filed as the portal option "EEMUA 153/158" (alias). Still refused under
`any` (zero fileable): 10 AZF, BS_APR/AUG/SEP_2026, KHF_JAN/APR/MAY/AUG_2026,
NOV_JAN_2026 — 18 documents. `TODO.md` separately holds UBOC_FEB_2026 and UBOC_SEP_2026
back until their sources are fixed (operator decision 2026-09-21); the code does not
block them.

## Tests

`tests/test_standard_policy.py`: default and parsing; partial match files only the
matches; zero matches refuses; `all` still refuses a partial match; the exact new line,
which no GUI regex matches; dry-run narration agrees with the pre-flight; live listbox
missing a fileable option refuses the whole report (QC2); batch summary lists; the
`in_portal.md` sync. Every earlier test passes with the policy forced to `all`.
`tests/test_standard_normalization.py` now pins its own alias map instead of reading the
live config (it used "ASME I-XII" from there).

## Addendum (2026-10-05): `portal.hold_documents` — operator hold (D5)

The operator held UBOC_FEB_2026 and UBOC_SEP_2026 back on 2026-09-21 by a TODO note
only; the code did not block them (see "The 17 documents" above). Decision D5 moves the
hold into code under the same ADR-002 exception, scoped to this key only.

- `portal.hold_documents` (default `[]`): document IDs `<CLIENT>_<MON>_<YYYY>`, the
  tail of the compiled filename. A malformed ID stops the run with a config error.
- A held document is dropped right after target resolution (`_apply_hold`), before
  the limit, the ledger and any browser, under `--dry-run` and `--live` alike. New
  line: `  HELD by operator (portal.hold_documents): <id>`. The summary lists it as
  held, never as skipped or failed; the exit code is unchanged.
- Under `[]` the output is byte-identical (`tests/test_hold_documents.py`).
- Live value: `["UBOC_FEB_2026", "UBOC_SEP_2026"]`, until their sources are fixed
  on the LAN (TODO). Releasing a document is removing its ID.

## Addendum (2026-10-05): `portal.upload_closed_months_only` — closed months only (D6)

`true` refuses a document whose month (`_sidecar_period_start`) is the current Asia/Baku month or later, in the same place as the hold, printing `  NOT YET (month not closed): <id>`;
default `false` is byte-identical (`tests/test_closed_months_only.py`). Live value: `true`.

## Addendum (2026-10-06): portal list 16 → 21 (provisional, probe pending)

The portal REPLACED its standards list. The operator reports, from a screenshot of the
live form (2026-10-06), that it now offers exactly 21 standards and that the 16 measured
by `--probe` on 2026-08-12 (EEMUA 153/158, API 1104, ISO 17636, ISO 17640, …) are gone.
A probe run the same day did not reach the form (every browser tab closed); portal login
was then not available, so the operator postponed the probe.

- `PORTAL_STANDARDS` = the 21, in the operator's spelling, under the same ADR-002
  exception (constant and comments only). `standarts/in_portal.md` lists the same 21 with
  the header "Source: operator screenshot 2026-10-06 — NOT yet probe-verified"; the old
  file is kept as `standarts/in_portal_2026-08-12.md`.
- Probe file: `output/portal_form_probe.json` is still the 2026-08-12 dump (16 options);
  a copy is in `_archive/portal_form_probe_2026-08-12.json`.
  `test_registered_standards_match_the_portal_exactly` is xfail ("probe pending (TODO
  P0)", strict) only while that dump is in place; any new dump makes it pass or fail for
  real.
- Live `portal.standard_aliases`: removed `EEMUA 153/158` and `ASTM E797/E797M` (no longer
  options); added `"ASME I-XII"` for Roman-numeral ASME Sections I–XII only
  (`ASME VIII`, `ASME IX`). `ASME B31.1` / `ASME B31.3` are options of their own and are
  not mapped to it. No other 2026+ sidecar spelling needed an alias: the remaining
  unmatched ones are `API 1104`, `EEMUA 158`, `EEMUA 158,Edition 3,Section 7.5.4`,
  `ISO 11666`, `ISO-23278` and the two AZF `Doc No: Q…` references, none of which names
  one of the 21.
- Tests that exercise the matcher on the old 16 now pin them through
  `tests/conftest.py` (`portal_2026_08_12`, `aliases_2026_08_12`) instead of reading
  `PORTAL_STANDARDS` and the local config; the drift lock, the master-list coverage and
  the `in_portal.md` sync follow the 21.
- Before the first `--live`: a probe must confirm the exact text of the 21 options, plus
  the chip check (TODO P0).
