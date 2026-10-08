# ADR-007: A cross-month pull must be proven by weld evidence

- **Status:** Accepted — implemented behind an OFF-by-default switch
- **Date:** 2026-09-21
- **Depends on:** ADR-006 (what a pulled parent looks like once it is pulled)
- **Related:** ADR-005 (the same principle — weld identifiers, not numbers, decide
  identity); ADR-008 (the file that triggered this decision is a name/body mismatch)
- **Does not change:** how the candidate parent is chosen; report numbers; any file on
  disk; `uploader.py`
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

A retest whose original is not in its month gets the **latest earlier original of its
series** pulled in (`retest_tracker.pull_cross_month_parents`). That is a number-based
rule, and the number is not a reliable identity in this corpus:

- **a report number can be given to two jobs** — `output/report_no_collisions_2026-09-18.md`
  lists numbers reused across different welds and standards;
- **a file can carry another report's content** — `U-RT-26-005 (Zığ).docx` holds
  `U-RT-26-004`, weld `QB-4`, while the retests of `U-RT-26-005` inspected `QB-5`
  (`tests/test_pull_weld_check.py` docstring; `output/report_no_mismatch_2026-09-24.md`
  row 12).

So the latest earlier original is not always the retest's own original.

## Decision

`retest.pull_weld_check: off | strict` (`retest_tracker.pull_weld_check`). Absent or
unrecognised reads as `off`.

- **`off` (default)** — pull as before the key existed.
- **`strict`** — the chosen parent must pass `retest_tracker.parent_evidence` first:
  1. **Welds readable on both sides:** every weld the retests inspected must be one the
     parent inspected (retest welds ⊆ parent welds). Weld ids are upper-cased, spaces
     removed, cut at `/`, and every trailing repair tail `R<n>` / `RW<n>` stripped
     (`weld_bases`; `QB-5RW` → `QB-5`, `W6/1` → `W6`). Cells containing `:` are
     dropped as header text.
  2. **Welds unreadable on either side:** the filename job group (the `(…)` tail), the
     standard and the İtem / Detal must each be equal for the parent and every retest.
  3. **A parent that fails is not pulled. No older candidate is tried.** The retest
     prints as an orphan, and `report.skipped` records
     `çarpaz-ay valideyn <№> gətirilmədi (<retests>): <why>` — e.g. `tikiş QB-4 ≠ QB-5`,
     or `tikiş oxunmadı; standart A ≠ B`. The shape is a contract: `main.py` reads it back
     with `retest_tracker.parse_refusal`.

At run end `main.py` prints a count and one `[pull rejected] <parent>: <why> — valideyn
gətirilmədi (<group>; <retests>)` line per refusal (`main.py:1029-1033`). The
`pull_weld_check` comment in `config/settings.example.yaml` says the same.

## Consequences

### Measured

`config/settings.example.yaml`, `pull_weld_check` comment, measured 2026-09-21:
of **31** pulled parents, `strict` refuses **one** — `U-RT-26-005` for UBOC_MAR_2026,
whose file carries `U-RT-26-004`'s content (weld `QB-4`; the retests inspected `QB-5`).

| | value | source |
|---|--:|---|
| pulled parents under `off` | 31 | `settings.example.yaml` |
| refused under `strict` | 1 (`U-RT-26-005`, QB-4 ≠ QB-5) | `settings.example.yaml`; code path `parent_evidence` rule 1 |

The live configuration runs `strict`.

### What does NOT change

- The candidate is still the latest earlier original; `strict` only accepts or refuses
  it.
- No file is written, moved or renamed. The mismatched file is fixed on the LAN
  (ADR-008).
- `off` is exactly the behaviour that predates the key (pinned by test).

## Rejected alternatives

**Fall back to an older candidate when the latest fails.** Rejected by design
(`parent_evidence` docstring: "There is no fallback to an older candidate"). A second
guess on the same number-based rule is the same error one step further back; an orphan
retest with a named reason is visible and correctable.

**Trust the number.** That is `off`, and it is how `U-RT-26-004`'s content was pulled in
as `U-RT-26-005`'s parent.

## Tests

`tests/test_pull_weld_check.py` — 11 test functions: the `off` default for an absent or
unknown value, repair tails / slashes / header text stripped, weld mismatch refused, weld
subset pulled, no fallback to an older candidate, secondary evidence pulling and
refusing, welds on one side only falling back to secondary evidence, `off` pulling the
mismatched parent as before, the refusal reaching `report.skipped` with the retest kept.
The `parse_refusal` round-trip is pinned in `tests/test_report_no_mismatch.py`.

## Open items

- **UNKNOWN / NEEDS VERIFICATION:** whether the refusal count is still 1 on the current
  corpus; the only recorded measurement is 2026-09-21.
