# ADR-003: Direct PDF extraction with two-reader cross-checking

- **Status:** Proposed
- **Date:** 2026-09-07
- **Supersedes:** ADR-001 D1 *for PDF-sourced documents only* (see "Relationship to ADR-001")
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

STAGE -1 (`pre_processor.convert_input_pdfs`, `pre_processor.py:293-504`) converts every
incoming PDF to `.docx` with `pdf2docx` so the rest of the pipeline can stay `.docx`-only.
Task 06 surfaced monthly reports whose `Nəticə` column was wrong. The cause was traced to
that conversion, not to the extractor.

### What the corpus actually is

`input/PDF_ARCHIVE/` holds **793 PDFs / 826 pages / 242 MB**. Measured with PyMuPDF:

| Property | Value |
|---|---|
| PDFs with a non-empty text layer | **793 (100.0%)** |
| Scanned / image-only PDFs | **0 (0.0%)** |
| Unreadable / error | 0 |

Producer distribution — every file is a Word or Excel export:

| Producer | Count | % |
|---|---|---|
| Microsoft Word 2010 | 380 | 47.9% |
| Adobe PDF Library 22.1.117 (Creator: Acrobat PDFMaker 22 — Word) | 265 | 33.4% |
| Microsoft Excel 2016 | 59 | 7.4% |
| Microsoft Word LTSC | 54 | 6.8% |
| Microsoft Word 2013 | 26 | 3.3% |
| Word for Microsoft 365 / Excel 2010 / Word 2016 | 9 | 1.1% |

The source material carries a perfect text layer and real table ruling lines. **OCR is not
needed and rasterisation buys nothing.**

### What pdf2docx does to it

Reference pair `RT-SDL-25-087` (Producer: Microsoft Word 2010). The PDF text layer is
flawless; the converted `.docx` is damaged:

| In the PDF | In the converted .docx |
|---|---|
| `Result` (weld-table column header) | `esult` — the leading letter is lost |
| `RADIOGRAPHIC INSPECTION REPORT` | `A D GRA HI / S INSP IN EP T` |
| `Report No: RT-SDLN-25-087` | `Report N` / `o:` / `RT-` / `SDLN-` / `25-087` across five cells |
| `Item Inspection: SDLN WORK SHOP` | value split over six cells: `S` `DLN` `WO` `RK` `SHO` `P` |

The damage defeats `extractor._canonical_header` (`extractor.py:72-96`): the verdict column
is never mapped, `extract_welds` returns empty, and
`document_aggregator._aggregate_result` (`document_aggregator.py:54-86`) falls back to
scanning every cell. A shattered `Accept / Reject` **column header** leaves a lone `Reject`
cell, which the fallback reads as a real verdict.

### Measured cost of the current path

631 PDF/`.docx` pairs (pairing validated against each PDF internal `Report No:` value; 28
mismatched pairs discarded). Ground truth = the raw PDF text layer after removing the
`Accept / Reject` header phrase.

| Reader | Wrong verdicts / 630 | % | In live method folders (n=453) |
|---|---|---|---|
| **A — current `pdf2docx` + `python-docx`** | **96** | **15.2%** | **36 (7.9%)** |
| B1 — PyMuPDF `find_tables` | 9 | 1.4% | 8 |
| C1 — `pdfplumber` lattice | 55 | 8.7% | 51 |
| B3 — PyMuPDF word-coordinate grid | 62 | 9.8% | 50 |
| B3-C — B3 + header-band merge (see D2) | 10 | 1.6% | 8 |

Of the 36 live-folder errors: **27 read `Yarasız` where the PDF says accept**, and **9 read
`Yararlı` where the PDF records a real reject** — the second class hides a genuine
rejection in an official document.

Independently audited against **delivered** monthly reports
(`output/false_accept_2026-09-07.md`): of 316 delivered rows whose source PDF is still in
the archive, **31 carry the wrong verdict** — 5 rows FALSE ACCEPT (`MT-U-25-028/029/033`,
UBOC MT, March and April 2025) and 26 rows FALSE REJECT (all SDLN RT, September 2025).

### Performance

| Operation | Per PDF | 793 PDFs |
|---|---|---|
| `pdf2docx` conversion (ADR-002 D6) | ~30–40 s/page | ~6.9 h serial / ~52 min at 8 workers |
| PyMuPDF `get_text()` | 11 ms | ~9 s |
| PyMuPDF `find_tables()` | 252 ms | ~200 s |
| PyMuPDF word grid + band merge | ~13 ms | ~8 s (measured over 630 files) |
| `python-docx` parse (for comparison) | 123 ms | — |

---

## Decision 1 — Read PDF sources directly with PyMuPDF; drop the conversion stage

PDF-sourced documents are parsed straight from the PDF into the existing
`list[table][row][cell] -> str` contract that `docx_reader.read_document` already returns.
`pdf2docx` and its `opencv-python-headless` / `numpy` dependencies are removed; **PyMuPDF
becomes an explicit dependency** (today it is only pulled in transitively by `pdf2docx`).

**Rationale.** The conversion stage produces nothing the source did not already contain,
costs two to three orders of magnitude more time, and corrupts 15.2% of verdicts. It does
not even help scans: `pdf2docx` turns a scan into an image-only `.docx`, which
`docx_reader.has_body_text` then quarantines at `main.py:555-567`. Reading directly reaches
the same quarantine decision one stage earlier — and the corpus contains no scans.

## Decision 2 — Two readers, cross-checked; disagreement quarantines, never guesses

- **Primary reader: B1** — PyMuPDF `find_tables()`, with merged `Label: value` cells split
  back into a label cell and a value cell.
- **Cross-check reader: B3-C** — a word-coordinate grid (`page.get_text("words")`; rows
  clustered by y-centre with a ~3 pt tolerance, columns split on x-gaps > ~6 pt), **plus a
  header-band merge**: consecutive rows that contain no digit are glued together
  column-wise by overlapping x-interval. This reconstructs a vertically stacked header cell
  (`Accept/` on one line, `Reject` on the next) into one cell, while data rows — which
  always carry digits — are never merged.
- **Agreement rule.** Both readers agree, the value is accepted. They disagree, **no value
  is invented**: the report goes to the existing quarantine path
  (`input/SKIPPED_REPORTS/`, `main.py:555-567`) and the disagreement is written to an audit
  file naming the field and both answers.

### Measured (n = 630)

| Primary + cross-check | Agree & correct | **Agree but BOTH WRONG (silent error)** | Disagree, quarantined |
|---|---|---|---|
| **B1 + B3-C** | 611 (97.0%) | **0** | **19 (3.0%)** |
| B1 + B3 (unfixed) | 559 (88.7%) | **0** | 71 (11.3%) |
| B1 + C1 | 575 (91.3%) | **9 (1.4%)** | 46 (7.3%) |
| C1 + B3 | 559 (88.7%) | **46 (7.3%)** | 25 (4.0%) |

Live method folders only (n = 453): **B1 + B3-C** gives 445 agree-and-correct (98.2%),
**0 silent errors**, **8 quarantined (1.8%)**.

In all 19 quarantined cases exactly one reader is right — 9 where B3-C is right (all RT;
B1 alone would have produced a **false accept**) and 10 where B1 is right (3 FCM, 7 MT).
Quarantine load is 1–3 reports per month against an average PDF inflow of 42/month.

**Rationale.** A single reader is a silent-failure machine: whichever one is chosen, its
blind spot ships as a confident wrong verdict in an official document. Two readers whose
failure sets are disjoint convert that silent failure into a visible one. The gate for this
decision was therefore *not* accuracy but **zero silent error**, with quarantine volume as
the secondary constraint.

## Decision 3 — Rejected alternatives

| Rejected | Measured reason |
|---|---|
| **C1 — `pdfplumber` lattice** (`vertical/horizontal_strategy: "lines"`) | 55 wrong / 630 (8.7%). On the UT template it splits the stacked `Accept/` + `Reject` header into separate cells — the same failure mode as `pdf2docx`. Worse, it shares the B1 blind spot on RT, so **B1 + C1 produces 9 silent errors, all of them false accepts.** Adding `pdfplumber` + `pdfminer.six` buys nothing. |
| **Any single-reader design** | The best single reader (B1) is still wrong on 9/630, and those errors ship silently. |
| **"Oracle" union of two readers** (pick whichever is right) | Not implementable at runtime: the oracle needs the ground truth it is supposed to produce. Its 0% error figure is a measurement artefact, not a strategy. |
| **C2 — PyMuPDF `get_drawings()` hand-rolled lattice** | Not needed: B1 + B3-C already meets the gate with no new dependency. Kept on file in case a future template defeats both readers. |
| **Tuning B3 tolerances** (`ytol` 2–5, `xgap` 2–12, 9 combinations) | Did not move the UT failures at all. The root cause was the stacked header cell, fixed structurally by the band merge, not by constants. |

## Relationship to ADR-001

ADR-001 D1 chose Python and `python-docx` on `.docx` fidelity ("images are simply not read
into the text model, satisfying 'ignore images' for free").

**That reasoning stands and is not revoked for native `.docx` sources**, which are ~85% of
the corpus and keep the existing `docx_reader` + `extractor` path untouched.

What ADR-001 never covered is PDF sources. `pdf2docx` appears only in the technology table,
never as a reasoned decision. This ADR supersedes ADR-001 **for the PDF path only**: the
`.docx`-fidelity argument cannot justify a converter that corrupts 15.2% of verdicts.
ADR-001 remains Accepted.

ADR-002 D6 (398.8 s to 100.0 s at 8 workers, 3.99x for parallel PDF conversion) becomes
**obsolete rather than wrong** — the stage it optimised ceases to exist.

## Consequences

### Gains

- STAGE -1 conversion disappears: ~6.9 h serial / ~52 min at 8 workers becomes **1–4 min**,
  with no worker pool, no `.part` protocol and no output-name reservation.
- `pdf2docx`, `opencv-python-headless` and `numpy` leave the dependency tree.
- Verdict errors on PDF-sourced documents: 36/453 becomes **0**, with 8 quarantined for
  review.
- Metadata quality rises sharply. Field fill rate over 631 PDFs read directly: `date`
  100.0%, `client` 99.8%, `material` 99.8%, `report_no` 99.5%, `standard` 95.1%. Path A
  leaves `report_no` empty on 376 of them and `standard` on 387.

### Costs and obligations

- A second reader roughly doubles per-document parse cost. Irrelevant in absolute terms
  (~13 ms + ~250 ms per PDF against 30–40 s/page today).
- **The quarantine audit file is mandatory**, not optional. A quarantined report with no
  stated reason forces the operator to re-derive the disagreement by hand.
- `parse_cache` schema goes 1 to 2. The key stays SHA-256 of file bytes
  (`parse_cache.py:65-80`), so a PDF and its old `.docx` can never collide; the bump exists
  because the *meaning* of the `tables` payload changes. All 3 539 existing entries are
  invalidated automatically and rebuilt; `gc()` removes the stale ones.
- KB-1 / KB-1b date repair (`date_detector.py`, `pdf_twin.py`) will almost never fire,
  because a directly-read PDF yields a complete `Date:` field. **The repair path is kept,
  not deleted** — it still serves native `.docx` sources.
- The 660 already-converted, damaged `.docx` files in the corpus must be re-ingested from
  `PDF_ARCHIVE`, and the affected monthly reports recompiled. Delivered output will change;
  a before/after diff is required.
- ~26 tests break by design (see the implementation plan), most of them the entire
  `tests/test_pre_processor_parallel.py` conversion suite.

### Reversibility

Source PDFs are never deleted — `input/PDF_ARCHIVE/` keeps every original. Reverting means
restoring `convert_input_pdfs`, putting `pdf2docx` back in `requirements.txt`, and dropping
`CACHE_SCHEMA` to 1. The parse cache is content-addressed and rebuilds itself, so deleting
it is always safe.

## Open questions

1. Why B3-C still misreads 3 FCM and 7 MT reports (all quarantined, none silent).
2. Whether the 60 verdict errors currently sitting in `SKIPPED_REPORTS` were quarantined
   *because* of this damage — if so, re-ingestion returns them to the corpus and changes
   past monthly reports.
3. STAGE 1 must read `*.pdf` out of `PDF_ARCHIVE`, which `SETTLED_DIRS`
   (`pre_processor.py:52-54`) currently excludes from every scan. How that exception is
   expressed is left to implementation.
