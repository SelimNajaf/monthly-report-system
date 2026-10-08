# ADR-009: One line per report number, ranged by number — a plain, short table

- **Status:** Accepted — implemented behind keys whose defaults keep the old drawing;
  the live configuration turns them on
- **Date:** 2026-09-24
- **Depends on:** ADR-004 (method blocks inside one client-month document); ADR-006
  (`pulled_parent_style: hidden` is defined here); ADR-007 (`strict` pulls)
- **Does not change:** the JSON sidecar (one entry per report, each with its own
  verdict); report numbers; `uploader.py`
- **Decision makers:** Operator (direction, decisions D1–D8 and Q1–Q6), implementation
  engine (measurement)

## Context

The director asked for a document that is plain and short. The strict drawing was
neither:

- dates were mixed — March parents printed in the April document (cross-month pulls,
  ADR-006);
- retest chains printed as lettered sub-rows (`2a`, `2b`) with an amber background
  (`row_style: retest_highlight`);
- unfit retests could move to a second table (`unfit_placement: section`);
- a verdict change broke a range, so a run of consecutive numbers split into many lines.

## Decision

Five presentation keys, each read in `document_aggregator.py` (`range_mode`,
`range_tail_allow`, `row_order`, `row_style`, `pulled_parent_style`) and resolved together
in `display_options`. Every default is the drawing that predates the key. Decisions D1–D8
are the labels used in `tests/test_range_by_number.py`. The operator also answered six
open questions (source: notes of the 2026-09-24 operator session):

| | question | operator's answer |
|---|---|---|
| Q1 | what "volume" counts for `method_volume` | the visible lines; a `hidden` parent is not counted |
| Q2 | which numbers the D8 list names | numbers inside a Yararlı range whose chain's **last** verdict is Yarasız |
| Q3 | a number that does not end in digits | never ranges; the exception is `range_tail_allow` |
| Q4 | `pulled_parent_style` against `range_mode` | `hidden` + `strict` reads as `marked`; `marked` + `by_number`: the unit carrying the parent is one line of its own, with `*`, and never ranges |
| Q5 | informational methods | print "Məlumat üçün" |
| Q6 | name of the default `row_order` | `method_date` |

### `range_mode: by_number` (default `strict`)

One line per report **number**, then consecutive numbers range. The retest suffix is
stripped (`strip_retest`): `U-RT-26-014`, `014R1`, `014RW`, `014RW1` are one number, and
`U-RT-26-(012-017)` is one line.

**D1 — what breaks a range** (`_can_merge_units`, `_number_units`): a missing number,
a different prefix, a different label tail (`" (Dashgil 2)"`), different zero padding,
standard, method, or İtem — the last **only with `split_ranges_on_item: true`** (live:
true). Inside one number, members must agree on standard and İtem or that number never
ranges. **A verdict change does NOT break a range.**

**D2 — Tarix** (`_date_span`): min–max over every report in the line, compact form:
`01–21.04.2026` (one month), `31.03–15.04.2026` (across months),
`28.12.2025–05.01.2026` (across a year), one date for one day. The by_number layout gives
Tarix **27 mm**, taken from Nəticə (`pdf_renderer._COL_MM_BY_NUMBER =
[12, 27, 40, 33, 14, 35, 22]` against strict's `[12, 24, 40, 33, 14, 35, 25]`; same
183 mm total). Strict keeps its widths.

**D3 — Nəticə** (`_range_result`, `_number_line`): a single number prints its chain's
**last** verdict. A range prints **Yararlı when any number in it ended Yararlı**;
otherwise the shared verdict (an informational method stays "Məlumat üçün"); otherwise
Yarasız. `Sıra №` is 1..N, no `2a/2b`.

### D4 — no second table

Under by_number, `unfit_placement` is ignored and reads as `inline`; `rollup_retests` is
ignored (a chain is already one line) (`settings.example.yaml`, `range_mode` comment).

### D5 — `pulled_parent_style: hidden`

The cross-month parent is not drawn; its date and verdict do not count towards its
number's line. The sidecar is byte-identical to `marked` (ADR-006).

### D6 — `row_order: method_volume` (default `method_date`)

The method with the most printed reports first (a hidden pulled parent does not count),
ties by method name. Inside a block by_number always sorts by number.

### D7 — `row_style: method_zebra` (default `retest_highlight`)

No amber retest shading; method blocks alternate white / `#F2F2F2`, first block white.
The header is never changed.

### `range_tail_allow` (default `[]`; live `["T"]`)

A number whose tail is in the list — exact, case-sensitive — ranges, **only with numbers
carrying the same tail**: `RT-KF-25-(080-106)T`. A tail not in the list never ranges; a
number that does not end in digits keeps its own line, spelled as written. `rej`, `test`,
`del` are not in the list and are never to be added: `U-UT-25-003rej` is a real number
(Q3 in `_NUMBER_WITH_TAIL`: "such a number never ranges").

### Key interactions (`display_options`)

- `collapse_ranges: false` **wins over** by_number — each row prints its own Sıra №.
- `rollup_retests` and `unfit_placement` are ignored under by_number.
- `hidden` under `range_mode: strict` (or with `collapse_ranges: false`) reads as
  `marked`.
- `split_ranges_on_item` is honoured.

### Why

The portal looks at the document's overall result (operator's statement). The JSON
sidecar does not change and remains the source of truth: one entry per report, each with
its own verdict.

## Risk — stated plainly

**On the PDF, reports whose final verdict is Yarasız are printed under a range line that
reads Yararlı. The inspector signs this PDF.**

Measured in `output/range_verdict_2026-09-24.md` (counted from its table):

| | value |
|---|--:|
| Yarasız reports printed inside a Yararlı range line | **95** |
| of those, in plain-number ranges | 82 |
| of those, in `T`-tail ranges (from `range_tail_allow: ["T"]`) | 13 |
| documents affected | **37** |
| documents affected by the 13 `T`-tail reports | 2 (KHF JUL 2025, KHF AUG 2025) |

Mitigation — naming, not preventing:

- one `[range-verdict] <group>: <№> Yarasız → "Yararlı" diapazonda çap olundu: <line>`
  stdout line per report (`document_aggregator.format_range_verdict`, printed from
  `main._note_range_verdicts`, also for reused groups);
- `output/range_verdict_<date>.md` at run end, no file when there are none
  (`main._write_range_verdict_audit`).

Nothing in the pipeline stops a document with such a line from being rendered or
uploaded. **Accepting this risk is the operator's decision**, per document.

## Consequences

### Measured

Source: operator session of 2026-09-24. Baseline = `_archive/output_backup_20260924_1029`
(127 documents, the drawing before this ADR), measured in stage 3. Result = the run with
this ADR's keys on (128 documents: the same 127 plus `KHE_SEP_2026`, which is new, 1 line
and 1 page).

| | baseline (127 documents) | result, same 127 documents | result, all 128 documents |
|---|--:|--:|--:|
| table lines | 1,787 | **1,478** | 1,479 |
| pages | 151 | **140** | 141 |

The document and page counts were re-counted from the two trees on 2026-09-24: the backup
holds 127 compiled sidecars whose PDFs sum to 151 pages; `output/` holds 128 whose PDFs sum
to 141; the only sidecar present in `output/` and absent from the backup is
`KHE/compiled_monthly_report_KHE_SEP_2026.json`, whose PDF is 1 page. The line counts are
the session's measurement.

| | value | source |
|---|---|---|
| JSON sidecar diff | **0** | stage 3: backup ↔ run 1, 126 / 126 byte-identical, the 2 other differences are new reports arriving from the LAN; stage 4: 130 JSON files, diff 0. Verified (session measurement) |
| tests | 1,886 passed / 14 skipped / 0 failed | commit `9d54e26`; re-run with this ADR |

### What does NOT change

- JSON sidecar: one entry per report with its own verdict; a hidden parent keeps its row
  and `pulled_from`.
- `report.rows` is never mutated; every key at its default draws exactly the pre-key
  table (the "(a)" tests in `tests/test_range_by_number.py`).
- No file, filename or report number is changed.

## E1–E3 + blank methods

A follow-up in the operator session of 2026-09-24/28: by_number ranges still broke on the
job tag, the standard and the İtem, so the table stayed long. Four more presentation keys,
all read in `document_aggregator.py` and resolved in `display_options`. They are ignored
under `strict` and while `collapse_ranges` is false. **At their defaults the table is
byte-identical to the one drawn before they existed** (`tests/test_range_merge_keys.py`).

### Decisions (Selim)

| | decision | key (default → live) |
|---|---|---|
| E1 | the job tag (`" (2236)"`) is ignored: it no longer breaks a range, and a range line prints no tag. A single number keeps its own name | `range_ignore_tag` (false → true) |
| E2 | many standards in one cell: a different standard no longer breaks a range; the cell lists each distinct standard once, comma-separated, in number order. Two spellings of one standard (`ISO 23278` / `ISO-23278`; space, hyphen, underscore and case ignored, `_standard_key`) print once, as first seen | `range_merge_standards` (false → true) |
| E3 | İtem is one value: the one seen on the most report **numbers** (a retest chain is one vote), a tie goes to the smallest number, blanks never count | `range_item: split \| dominant` (split → dominant) |
| — | PMI and FCM (the item is an identifier: serials, `Pipe 1…7`) print `—` when the range carries 2+ distinct items. A one-item range and a single number keep their own item. Read only under `dominant` | `range_item_blank_methods` (`[]` → `["PMI", "FCM"]`) |

Still breaking a range: a missing number, prefix, method, zero padding, a number tail
(`range_tail_allow`). The verdict rule (D3) and the `[range-verdict]` audit do not change.

### Measured

Source: `python main.py --force-rebuild` runs of 2026-09-24 and 2026-09-28, counted from
the PDFs with pdfplumber (a table line = a row whose first cell is a number).

| | before E1–E3 | after |
|---|--:|--:|
| table lines (128 documents) | 1,479 | **605** |
| pages | 141 | **129** |
| JSON sidecar diff | — | **0** (130 / 130 byte-identical) |
| `[range-verdict]` lines | 95 | **127**, in **44** documents |
| ranges whose dominant İtem hides another item | — | **125** |
| lines printing `—` | — | **20** (PMI 17, FCM 3) |
| cells with the same standard printed twice | 2 | **0** |

- The 20 `—` lines: PMI has 24 ranges, 17 with 2+ items. FCM has 4 ranges, 3 with 2+
  items (AZF JAN 2025 ×2, AZF APR 2025). The other 8 keep their item.
- The 125 ranges are ranges with 2+ distinct items under `dominant`, by method: MT 51,
  DP 20, UT 18, PMI 17, RT 9, UTM 6, FCM 3, FC 1. PMI's 17 and FCM's 3 now print `—`;
  the other 105 print the dominant item.
- The 2026-09-28 run (FCM added) also staged 14 new reports from the LAN
  (`Staged 14 new report(s)`). That run counts 608 lines / 129 pages. The only sidecar
  differences are those 14 added reports, in KHF MAR 2026, KHF SEP 2026 and
  UBOC SEP 2026, and nothing was removed. The other 127 sidecars are byte-identical.
- Blank Standart cell: 38 lines, all PMI, FC or HT. The cause is the source, not this
  change. In each case the sidecar `standard` is `""` for every report in the line, and
  the same reports print blank in `_archive/output_backup_20260924_1029` and
  `_archive/output_backup_20260924_1220`.

### The uploader reads the sidecar only

The portal payload never comes from the PDF, so none of these keys reach the portal:

- `uploader.py:398`: `load_report_json` reads the `.json` sidecar.
- `uploader.py:1751`: `payload = build_portal_payload(json_data, portal_cfg)`, which
  holds every form field, standards included.
- `uploader.py:343-355`: `_file_integrity` reads the PDF's bytes only to compute its
  size and SHA-256.
- `uploader.py:1891`: `file_input.set_input_files(str(pdf_path))` attaches the PDF
  as a file.
- There is no PDF text parsing in `uploader.py` (no pdfplumber, pypdf or fitz).

### Risks — stated plainly

- **Report ↔ standard is not visible on the PDF.** A cell such as
  `AWS D1.1, ISO 23278` does not say which number used which standard.
- **Report ↔ İtem is not visible on the PDF.** 105 range lines print one dominant item
  for numbers that carry other items; 20 print `—`.
- The sidecar still holds, for each report, its own standard, item and verdict, and
  it remains the source of truth. **The inspector signs the PDF**, which shows less than
  the sidecar. Accepting this is the operator's decision.

## Rejected alternatives

Considered with the operator on 2026-09-24:

1. **Break the range when the verdict changes.** That is `strict`. Rejected: the document
   gets longer, which is what the director asked to fix.
2. **Spell a mixed verdict out on the line** (`"Yararlı, 003 – Yarasız"`). Rejected.
3. **"A range is always Yararlı."** This was the first decision. It was replaced by the
   current rule: Yararlı when at least one number in the range ended Yararlı, Yarasız
   when none did.

Reason for the chosen rule: the portal reads the document's overall result, and the
sidecar stays the source of truth, each report with its own verdict.

## Tests

`tests/test_range_by_number.py` — 42 test functions (D1–D8, plus the defaults drawing the
pre-key table). `tests/test_range_tail_and_dates.py` — 21 test functions (compact dates,
Tarix width, `range_tail_allow`). `tests/test_range_merge_keys.py` — 28 test functions
(E1–E3, `range_item_blank_methods`, defaults byte-identical, sidecar unchanged).

## Open items

- None of the measurements above is UNKNOWN. The line counts rest on the 2026-09-24
  session measurement; the document and page counts were also re-counted from the
  backup and `output/` trees.

## Addendum 2026-10-05 — `range_absorb_tails` (default `[]`; live `["A"]`)

Operator request: `BS_MAY_2026` printed `BS-RT-26-(001-016)` and a separate line
`BS-RT-26-010A`. `010A` belongs inside the range, with no separate note.

**Rule.** Under by_number only. After the retest marker is stripped, a number
`<base><tail>` whose tail is in the list — exact, case-sensitive, and only a single
upper-case letter is read — takes the slot of its base number: `010A` ranges as if it
were `010`. It sorts right after `010`, may follow it in a run (same slot), and a run
continues from it to `011`. If `010` is absent, `010A` fills that slot. A run that
covers one slot only (`010` + `010A` with no neighbour) draws each number on its own
line, so no `(010-010)` label can appear. A number alone keeps its own name.

**Unchanged.** The date span and the D3 verdict rule count the absorbed number like
any other number, and the `[range-verdict]` audit names it when it ended Yarasız inside
a Yararlı line. `rej`, `test`, `del`, a lowercase `a` and any multi-letter entry are
never absorbed (the reader drops them). `range_tail_allow` keeps its meaning and is
read first for a tail listed in both. Strict mode ignores the key. The sidecar does not
read it: every report keeps its own number (red line 2).

**Measured** (one `python main.py` run, 2026-10-05, 0 new LAN files staged): table lines
over all groups 620 → 619; the one document that changed is `BS_MAY_2026`
(2 lines → 1: `BS-RT-26-(001-016)`, 17 reports). Pages 131 → 131. All 130 sidecars are
byte-identical to the run before.

**Tests.** `tests/test_range_absorb_tails.py` — default `[]` draws what absence draws,
`010A` absorbed, `010B` / `010a` / `003rej` not, base number missing, one-slot run,
retest chain, verdict rule and audit, strict ignores the key, sidecar unchanged.
