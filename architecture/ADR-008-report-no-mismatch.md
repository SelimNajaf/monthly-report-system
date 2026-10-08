# ADR-008: Filename serial ≠ in-body Report No — warn every run, never repair

- **Status:** Accepted — warning always on; blocking behind an OFF-by-default switch
- **Date:** 2026-09-21
- **Depends on:** `report_identity.resolve_report_no` (the filename is authoritative for
  the Report №)
- **Related:** ADR-005 (same segments, different ORDER — a different problem); ADR-007
  (the first file of this kind was caught as a wrong cross-month parent)
- **Does not change:** any file, filename or report number; `resolve_report_no`;
  `uploader.py`
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

The filename is authoritative for a Report № (`report_no_mismatch.py` module docstring).
Most name/body drift is harmless spelling (`U-RT-26-004` vs `RT-U-26-004`, ADR-005).
This decision is about the other kind: the `-<YY>-<seq>` **serials themselves differ** —
`U-RT-26-005 (Zığ).docx` holds `U-RT-26-004`.

Two different things hide behind one symptom
(`output/report_no_mismatch_2026-09-24.md`):

- **a copy** — the file's tables are identical to another file that is named with the
  body's serial: one inspection printed under two numbers;
- **not a copy** — a stale header, a PDF named after another report. The row is a real
  inspection; only its header is wrong.

## Decision

### Always: warn, never repair

Every run, `main.py` prints one line per file
(`main.py:769-787`):

```
  [report-no mismatch] <file>: ad <name №> ≠ içəri <body №>[ — <sibling> ilə eyni cədvəl][ — sənədə düşmür]
```

followed by a count line, and writes `output/report_no_mismatch_<date>.md` (`main.py:252`,
`_write_mismatch_audit`) listing each file with its date, welds, class (`surət` /
`surət deyil`) and the identical sibling.

The pipeline **never renames a file and never corrects a number**. The source is fixed on
the LAN, then the month is recompiled.

### Optional: keep only a COPY out

`filtering.block_mismatched_report_no` — default **`false`**
(`report_no_mismatch.block_enabled`).

- `true` keeps a **copy** out of the document **and out of a cross-month pull**; the
  reason lands in `report.skipped` under the prefix `report-no mismatch`
  (`report_no_mismatch.BLOCK_REASON`).
- A mismatch that is not a copy is only warned about, under either value.
- Off by default because it changes `report.rows` and `Sıra №`.

A copy requires identical tables **and** the body's serial in the sibling's name
(`copy_siblings`; pinned by test).

## Consequences

### Measured

| | value | source |
|---|--:|---|
| files with name serial ≠ body serial | **22** | `output/report_no_mismatch_2026-09-21.md`, `…_2026-09-24.md`; `report_no_mismatch.py` docstring ("Measured on 2026-09-21 … 22 files") |
| of those, copies | **9** | same audits; `settings.example.yaml` ("22 files, 9 of them copies") |
| not copies | 13 | 22 − 9, from the same tables |
| blocked in the live run | 0 | audit: "Bu run: **false — heç nə bloklanmır**" |

The two audits (2026-09-21 and 2026-09-24) are identical apart from the date line.

The live configuration runs `block_mismatched_report_no: false`: all 22 rows print under
their filename number, including the 9 copies.

### Operator hold, recorded elsewhere

`docs/history/TODO_journal.md` records an operator decision (2026-09-21) not to upload two documents until the
source is fixed; that hold is **not in code** — the uploader does not block them. This ADR
does not change that.

### What does NOT change

- No file is written, moved or renamed; no report number is rewritten or normalised.
- `resolve_report_no` still treats the filename as authoritative.
- With the switch off, every row stays under its filename number (pinned by test).

## Rejected alternatives

**Rename the file or take the body's number.** Rejected: the body is not always right
either (a stale header is exactly a wrong body), and the pipeline never alters the
operator's files or report numbers.

**Block every mismatch.** Rejected: 13 of the 22 are not copies. Blocking them deletes
real inspections from an official document to fix a header.

**Warn only once.** Rejected: the warning is the only thing that tells the operator the
LAN source still needs fixing; it repeats until the file is fixed.

## Tests

`tests/test_report_no_mismatch.py` — 9 test functions: serial parsing, only a different
serial counting as a mismatch, the copy rule, the switch off by default, off keeping
every row, on dropping only the copy with a reason, on keeping a copy out of a
cross-month pull, the pull-refusal reason round-trip, the audit listing every mismatch
with its class.

## Open items

- None of the counts above is UNKNOWN; all are read from committed code comments and
  both audits.
