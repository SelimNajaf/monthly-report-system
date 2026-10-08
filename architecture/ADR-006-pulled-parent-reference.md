# ADR-006: A pulled cross-month parent is a reference, not a claim

- **Status:** Accepted — implemented behind a key whose default keeps the old drawing
- **Date:** 2026-09-21 (key introduced, `marked`); `hidden` added 2026-09-24 (ADR-009)
- **Depends on:** ADR-004 (one compiled document per client-month); the E3 retest
  roll-up (`presentation.rollup_retests`)
- **Related:** ADR-007 (which parents are pulled at all), ADR-009 (`hidden`)
- **Does not change:** `retest_tracker`'s choice of parent; report numbers; `uploader.py`
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

`retest_tracker.pull_cross_month_parents` brings a retest's ORIGINAL forward from the
month it was reported in, so the retest can be read against it
(`config/settings.example.yaml`, `pulled_parent_style` comment). That row belongs to its
own month's document. Drawn like any other row, it reads as this month's work: it can
join a range, and with `rollup_retests` on the chain draws as ONE line carrying the
parent's number and date, with the retest this month actually did hidden under it
(same comment, `plain`).

## Decision

`presentation.pulled_parent_style` — `plain` | `marked` | `hidden`
(`document_aggregator.pulled_parent_style`, `_PULLED_PARENT_STYLES`). Any unrecognised
value reads as `plain`.

| value | page | JSON sidecar |
|---|---|---|
| `plain` (**default**) | drawn like any row — the behaviour that predates the key | byte-identical to before |
| `marked` | `*` on its Sıra №; a note under the table names its month: "\* {month} hesabatına aiddir, burada arayış üçün göstərilir." (`translations/az.json:45`); never joins a range; a roll-up never folds its retest into it | row gains `"pulled_from": "YYYY-MM"` (`json_exporter.py:87`); the row stays in `items_table` and `total_records` because it is on the page |
| `hidden` | only under `range_mode: by_number` (ADR-009): no line, no `*`, no note; its date and verdict do not count towards its number's line | **byte-identical to `marked`** (keeps `pulled_from`) |

`pulled_from` is read off the parent's own inspection date (`document_aggregator.pulled_from`);
nothing is looked up or guessed.

Under `range_mode: strict`, or with `collapse_ranges: false`, `hidden` reads as `marked`
(`document_aggregator.display_options`): a strict table would print the parent's `53a`
child anchored to a line that is not there.

## Consequences

### Measured

From the `pulled_parent_style` comment in `config/settings.example.yaml`, measured
2026-09-21 over **127 documents** (`collapse_ranges`, `rollup_retests`,
`split_ranges_on_item` on; `unfit_placement: section`), with `retest.pull_weld_check`
at its default `off`:

| | value |
|---|--:|
| marked (pulled) rows | **31** |
| documents carrying them | **11** |
| table lines | 1,755 → 1,808 |
| pages | 149 → 151 (two documents 1 → 2 pages each) |
| each parent found in its own month's document | 31 of 31 |
| reports / `total_records` | unchanged |

### 31 and 30

- **31** is the pulled-parent count with `retest.pull_weld_check: off` (the measurement
  above).
- **30** is the count under `pull_weld_check: strict`: strict refuses exactly one parent,
  `U-RT-26-005` for UBOC_MAR_2026 (`settings.example.yaml`, `pull_weld_check` comment;
  ADR-007). A refused parent is not pulled and no older candidate is tried
  (`retest_tracker.pull_cross_month_parents`, the `continue` after a refusal), so
  31 − 1 = 30 follows from the code. **The derivation is confirmed by measurement**
  (below).
- The live configuration runs `strict` + `hidden`, so neither number is visible on the
  page; both are visible in the sidecars through `pulled_from`.

### Measured under `strict`

Counted 2026-09-24 from the sidecars: every `items_table[]` row carrying `pulled_from`
in `<tree>/*/compiled_monthly_report_*.json`. Live configuration:
`retest.pull_weld_check: strict`, `pulled_parent_style: hidden` (the sidecar is
byte-identical to `marked`, so `pulled_from` is present). Operator's count and this
re-count agree.

| tree | pulled rows | documents carrying them |
|---|--:|--:|
| `_archive/output_backup_20260924_1029` | **30** | **11** |
| `output/` | **30** | **11** |

- 30 = 31 − 1: the measurement confirms the derivation above.
- No row carries `U-RT-26-005` with `pulled_from` in either tree — the refused parent is
  not pulled.
- The document count stays 11: UBOC_MAR_2026, the document of the refused parent, still
  carries 5 other pulled parents.

### What does NOT change

- The parent row is not removed from the report: `report.rows`, `items_table` and
  `total_records` keep it under every value.
- The uploader reads no new key.
- `plain` is byte-identical to the pre-key output, PDF and sidecar.

## Rejected alternatives

**Drop the parent from the document.** Rejected: the retest would print as an orphan
with nothing to be read against, and the sidecar would lose the chain. `hidden` removes
it from the *page* only, and only where the by-number line already stands for the whole
chain (ADR-009).

**Make `marked` the default.** Rejected for the same reason as `rollup_retests`: it
changes how an already delivered document is drawn.

## Tests

`tests/test_pulled_parent_mark.py` — 13 test functions: the `plain` default for an absent
or unknown value, `pulled_from` being the parent's own month, `plain` ranging as before,
`marked` never ranging a pulled parent and keeping its retest visible, `report.rows`
never mutated, no new sidecar key on `plain`, only pulled rows flagged on `marked` with
the count kept, the `*` and one note per month in the approved wording. `hidden` is pinned in `tests/test_range_by_number.py` (D5).

## Open items

- None. The `strict` counts (30 rows, 11 documents) were measured from the sidecars on
  2026-09-24.
