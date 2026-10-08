# ADR-005: Merging rows that carry the same report number in a different order

- **Status:** Proposed — implemented behind an OFF-by-default switch
- **Date:** 2026-09-18
- **Depends on:** ADR-003 (the archived PDF became a readable source again — which is
  what makes a second row appear at all); ADR-004 (one compiled document per
  client-month, so both spellings now land in the same document)
- **Does not change:** `report_identity.report_key`, which keeps segment ORDER and must
  keep it; the aggregator's existing twin dedup; `uploader.py`
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

`scripts/audit_duplicate_identity.py` found pairs of compiled rows whose report numbers
are the **same segments in a different order** — `RT-U-25-090` and `U-RT-25-090`. The
cause is documented in `src/monthly_report/duplicate_identity.py:1-16`: the corpus was
systematically renamed to `<CLIENT>-<METHOD>` while the signed body still reads
`<METHOD>-<CLIENT>`, `resolve_report_no` treats the filename as authoritative, and
`report_identity.report_key` — correctly — preserves segment order, so the two spellings
never meet in the aggregator's twin dedup.

Measured over the live corpus on 2026-09-18 (`scratchpad/collision_detail.py`, a
read-only spy on `duplicate_identity.classify`, run over all 126 compiled groups with the
switch forced on **in memory only**):

| | value |
|---|--:|
| transposed groups | **231** |
| of those, groups with exactly 2 members | **231** (no group is larger) |
| clients affected | UBOC 198, KHF 27, KHE 6 |
| compiled sidecars, switch OFF | 126 |
| compiled rows, switch OFF | 3,271 |

The pairs are not all the same thing, and that is the whole difficulty: the corpus
contains transposed numbers that are one report read twice **and** transposed numbers
that are two separate inspections. The number alone cannot tell them apart.

## Decision

**Merge only on weld evidence, and check the disjoint case FIRST.**

A pair is collapsed only when the two documents' **weld identifiers** prove they are one
physical report. The order of evidence in `duplicate_identity.classify` is deliberate:

| Case | Situation | Verdict |
|---|---|---|
| **A** | two live working documents, both weld sets populated and **disjoint** | `DISTINCT` — nothing merged |
| **B** | two live documents, weld sets equal | `SAME` |
| **C** | two live documents, weld evidence incomplete | `UNDECIDED` |
| **D** | one live document + a settled copy (archived PDF / pruned / quarantined) sharing the filename tail and the client, the settled copy's welds a subset | `SAME` |
| **E/F** | no source file to weigh, or only one spelling on disk | `UNDECIDED` |

**A is checked before anything else** because merging there deletes an inspection from a
document that goes to the state. That error is not symmetric with leaving one row too
many: a row too many is visible and correctable; a deleted inspection is invisible.

`UNDECIDED` keeps **both** rows and names the pair in `report.skipped` under the stable
prefix `DUPLICATE_IDENTITY_UNDECIDED`. The module never writes, moves or renames a file.

### The switch is OFF by default

`filtering.merge_duplicate_identities: false` (`config/settings.yaml:299`,
`config/settings.example.yaml:288`). Merging removes rows, and the caller assigns
`Sıra №` **after** the merge (`document_aggregator.py:408-410`), so turning it on
renumbers every row of every affected month. A default that quietly renumbers a delivered
official document is not acceptable; the operator throws the switch after reading
`output/report_no_collisions_<date>.md`.

### R1 — the winner order, recorded

When a group is `SAME`, `_winner_key` (`duplicate_identity.py:222-228`) picks the
survivor by, in order:

1. **live before settled** — a working document beats a copy in `PDF_ARCHIVE`,
   `_PRUNED` or `SKIPPED_REPORTS`;
2. **`.docx` before `.doc` before `.pdf`** — the document beats the PDF read of it;
3. **more welds before fewer** — the more complete read;
4. **`str(path)`** — so the choice is identical across runs and machines.

Only rank-0 records are candidates. A retest shares its parent's segments by design; an
earlier version of the audit flagged `KF-RT-26-053` / `KF-RT-26-053R1` as a duplicate
because of it.

## Consequences

### Measured, whole corpus, switch ON

| verdict | groups |
|---|--:|
| `eyni sənəd` (SAME) | **215** |
| `iki ayrı yoxlama` (DISTINCT) | **14** |
| `qərarsız` (UNDECIDED) | **2** |
| total | **231** |
| `report.skipped` notes written | **2** |
| compiled rows, switch ON | **3,056** |

3,271 − 215 = 3,056 exactly: every merged group is a pair, so each one frees one row and
one `Sıra №`. The row count was measured with the switch on, not derived from the
subtraction — the two agree.

The collisions are confined to **18 client-months, all of them in 2025 (January–September)**.
Nothing in 2026 collides, which is consistent with the rename being a one-off pass over the
older corpus rather than an ongoing habit:

| month | client | verdicts |
|---|---|---|
| 2025-01 | UBOC | 16 SAME |
| 2025-02 | KHF / UBOC | 2 / 14 SAME |
| 2025-03 | KHF / UBOC | 3 / 29 SAME |
| 2025-04 | KHF / UBOC | 5 / 36 SAME |
| 2025-05 | KHE / KHF / UBOC | 2 / 2 / 35 SAME |
| 2025-06 | KHF | **2 UNDECIDED** |
| 2025-06 | UBOC | 5 SAME |
| 2025-07 | KHF / UBOC | 2 / 22 SAME |
| 2025-08 | KHE / KHF | 4 / 9 SAME |
| 2025-08 | UBOC | 27 SAME + **14 DISTINCT** |
| 2025-09 | KHF | 2 SAME |

Three facts worth recording, because each one was a surprise:

- **All 215 merges are case D**, live document + settled copy. **Zero** groups are case B
  (two live documents with equal weld sets). The duplicate row is always the archived PDF
  original that ADR-003 turned back into a source — not a second working file.
- **The 14 DISTINCT are one cluster**: UBOC, August 2025, RT, `RT-U-25-151…165` against
  `U-RT-25-151…165` (161 is not a collision). Their weld sets do not intersect —
  e.g. `S11` against `S1`. These are 14 real inspections that any number-based rule would
  have deleted.
- **The 2 UNDECIDED are one cluster too**: KHF, June 2025, MT — `KF-MT-25-063` /
  `MT-KF-25-063` (16 welds against 0) and `KF-MT-25-064` / `MT-KF-25-064` (57 against 0).
  Whether the zero means an empty file or a failed read is **UNKNOWN**; the report says so
  and leaves it to the operator rather than guessing.

### What does NOT change

- Nothing on disk. No file is written, moved, renamed or deleted by this module.
- `report_identity.report_key` still keeps segment order. `canon_key` is the only place in
  the codebase that discards it, and it is used for grouping candidates, never as an
  identity.
- Report numbers are never rewritten, normalised or cleaned. Both spellings stay exactly
  as the filename has them.
- With the switch off (the default) `merge_duplicates` returns the records list unchanged
  and no notes.

## Rejected alternatives

**"Keep the first one seen."** The cheap rule: group by `canon_key`, keep the first
record, drop the rest. Rejected on measurement, not on principle. The order records
arrive in is `str(path)`, which is an accident of where the file sits on disk — and in
**169 of the 215** SAME groups the first member is the archived `.pdf`, not the live
`.docx`. The rule would therefore have kept the archive read over the working document in
79% of merges, and it would have merged the 14 DISTINCT groups too, deleting 14 real
inspections in silence. R1's explicit winner order exists because of this measurement.

**A rule that reads the number.** "Two numbers with the same segments are the same
report" — the assumption the whole problem starts from. It is false in this corpus,
measurably: 14 of the 231 pairs are two separate inspections whose weld sets do not
intersect at all. A number-based rule deletes all 14 from an official monthly report and
produces no note, no warning and no visible difference.

**Fixing it in the corpus instead** — rename one spelling on the LAN so the collision
never reaches the pipeline. Not rejected, deferred: it is the right fix for the 14
DISTINCT pairs and `output/report_no_collisions_2026-09-18.md` recommends exactly that.
It is an operator action on the source documents, and the pipeline still has to behave
correctly in the meantime.

**Quarantining an undecidable pair.** Rejected: an undecidable pair is two rows that are
each individually valid. Quarantining removes real inspections from the document to
resolve a bookkeeping question. Both rows stay; the operator gets a named note.

## Tests

`tests/test_duplicate_identity.py` — **13 tests**, all in memory, no file written, read,
moved or renamed: the OFF default (explicit `false` and absent key), `canon_key` being
order-blind but not value-blind, case A / B / C / D / E-F one each, the settled-copy job
mismatch, retests never being candidates, and the live document beating a settled copy in
each of the three settled trees.

Suite after the change: **1,713 passed / 14 skipped**.
