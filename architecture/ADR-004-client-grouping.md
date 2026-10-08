# ADR-004: One compiled document per client-month, across every NDT method

- **Status:** Proposed
- **Date:** 2026-09-08
- **Supersedes:** the grouping key established in ADR-001; the output-tree and serial
  conventions recorded in `docs/history/TODO_journal.md` (July 24, 2026)
- **Depends on:** the `Üsul` column added September 03, 2026 — this decision is the
  reason that column exists
- **Decision makers:** Operator (direction), implementation engine (measurement)

## Context

A compiled deliverable was keyed `(month × method × client)`. One client's month
therefore produced one PDF + sidecar per NDT method, each with its own serial, its own
folder and its own portal appeal. Measured over the live `output/` tree on 2026-09-08:

| | value |
|---|--:|
| compiled sidecars | 278 |
| distinct clients | 8 |
| distinct client-months | **103** |
| worst case | KHF FEB 2025 and APR 2025 — **7 documents each** (DP, FC, HRT, MT, PMI, RT, UT) |
| uploader `--dry-run --all` targets | 66 |

The split was never a requirement of the regulator. The E-Keyfiyyet appeal form asks
for the standards a submission covers; it has no method field, no method dropdown and
no method radio (`uploader.py:1663-1859` maps the whole form — none of its controls is
a method). Filing seven appeals for one client-month therefore repeats the client, the
VÖEN, the director's identity document and the date range seven times to say one thing.

On September 03, 2026 the compiled table gained a seventh column, `Üsul`
(`pdf_renderer.py:56`, `:314-317`), fed by `ReportRow.method`
(`document_aggregator.py:124-127`) and mirrored into the sidecar's
`items_table[].method` (`json_exporter.py:71`). That entry records the intent plainly:
"Method is now a table column, so the banner only repeated it." Once the method is on
the row, keeping it in the group key only splits the deliverable.

### Why it is safe to change now, and was not before

The ledger key is the compiled PDF's root-relative path
(`upload_ledger.py:129-143`, `uploader.py:2153-2163`), so moving or renaming compiled
output rewrites **every** key: previously-filed reports would read as never uploaded.
That was the blocking risk. It is gone:

- `.upload_state.json` is `{"version": 1, "entries": {}}` — emptied on 2026-09-04 after
  the operator confirmed the portal drafts were deleted (`docs/history/TODO_journal.md`, September 04).
- The portal side is empty.
- The data itself is trustworthy for the first time: serials are correct (B1),
  verdicts are correct (ADR-003), dates are correct (KB-1 / KB-1b).

## Decision

**One compiled document per `(month × client)`.** Every NDT method the client had that
month is one document; each row names its own method in the `Üsul` column.

Four sub-decisions, all confirmed by the operator before implementation:

### D1 — The official serial drops the method

`MR-<CLIENT>-<YY>-<MM>` (`MR-UBOC-25-12`). `{method}` had no meaning left: no single
token names a document that spans several. One client-month is one document, so the
serial is still unique without a method or a sequence number.

`{method}` stays a supported placeholder in `branding.doc_number_pattern` for a
hand-edited custom pattern (`naming.document_number` still formats it), it is simply
not in the official one. The empty-client `NA` guard is untouched.

### D2 — `output/<CLIENT>/`, and `_parse_stem` is fixed with it

`output/UBOC/compiled_monthly_report_UBOC_DEC_2025.pdf`. The method folder level
(`MPI/`, `FERRITE/`, `HT/`…) is gone: it mirrored the input method dirs, and a document
no longer belongs to one.

**This uncovered a latent trap that had to be closed in the same change.**
`catalog._parse_stem` counted filename tokens from the right and read a LONE lead token
as the *method*, returning an empty client. `main._purge_excluded_client_outputs` —
the sweep that retires a blacklisted or below-floor client's compiled output — guards
with `if not code: continue`. Dropping the method token from filenames would therefore
have turned that sweep into a silent no-op: never deleting wrongly, never deleting at
all. `_parse_stem` now returns `(client, month)`, and a legacy two-token name still
resolves to its client, so output already on disk keeps being swept.

The GUI's method dropdown survives and changes meaning: it filters documents that
**contain** a method, read from the sidecar rather than the filename
(`catalog._sidecar_methods`). `uploader.py --method` moved the same way — from a
filename substring test to `_sidecar_has_method`.

### D3 — The unmatched-standard gate is unchanged; only its cost is now reported

Current behaviour, unchanged: one standard the portal does not offer refuses the
**whole** document (`uploader.py:1706-1725`), nothing is typed, nothing is saved, no
ledger entry is written and no substitute is ever filed. The zero-substitution rule is
untouched.

Merging widens the blast radius — one unlisted standard used to hold back one method's
sheet (8 rows), it now holds back the client's whole month (30+). That is accepted, not
mitigated: part-filing a document, or dropping the offending rows at compile time,
would put an incomplete official record in front of the regulator. What was added is
visibility: `_print_blocked_standards_list` names each held-back document, the standard
that blocked it, which method cited it and how many rows it cost. Reporting only.

`_fill_missing_standards` (`document_aggregator.py:89-105`) was the one place where
merging would have *created* a substitution. It fills a blank `Standart` cell from "the
batch", and the batch used to be one method; across a merged document a DP row could
inherit an MT row's `EEMUA 158`. It now batches by `r.method`, which keeps the
behaviour byte-identical to the pre-merge groups.

### D4 — Portal `Nəticə:` — informational loses to real work

`portal_result` reads the sidecar's `ndt_method`, which is now a `/`-joined token list.
"Məlumat üçün" only when **every** method in the document is informational
(UTM / HrT / PMI); one real inspection makes the filing "Yararlı".

Measured: of the 25 post-cutoff client-months, **10 mix** informational and pass/fail
methods (e.g. UBOC DEC 2025 = DP + MT + UT + UTM). The weaker claim would be the wrong
one to make about a document that contains pass/fail work. The PDF is unaffected — its
own `Nəticə` column stays per row, so informational rows still read "Məlumat üçün"
there.

## Consequences

### Measured

| | before | after |
|---|--:|--:|
| compiled sidecars | 278 | 103 |
| uploader `--dry-run --all` targets | 66 | 25 |
| documents for KHF FEB 2025 | 7 | 1 |
| test suite | 1,533 passed / 14 skipped | 1,585 passed / 14 skipped |

### What changed shape

| Concern | Before | After |
|---|---|---|
| Group key | `(month, method, client)` | `(month, client)`; methods reported as a 4th tuple field, never keyed |
| `Scope.matches` | `(month, method, client)` | `(month, client)` — `Scope.method` survives as a row filter |
| Serial counter | `(month, method)` | `month` |
| Incremental dirty set | `(method, client)` | `client` (`_dirty_clients`) |
| Output path | `output/<FOLDER>/<CLIENT>/…_<METHOD>_<CLIENT>_…` | `output/<CLIENT>/…_<CLIENT>_…` |
| Ledger key | `output/MPI/UBOC/…_MT_UBOC_DEC_2025.pdf` | `output/UBOC/…_UBOC_DEC_2025.pdf` |
| Sidecar `ndt_method` | one token | `/`-joined list, plus a new `ndt_methods` array |
| Volume floor | per-method `volume_thresholds.<METHOD>` | `volume_thresholds.default`, per client-month |
| Row order | date, then report № | **method**, then date, then report № |

### The three things that would have broken silently

Each was found by tracing the old key rather than by a test going red, and each is now
pinned in `tests/test_client_grouping.py`:

1. **Cross-month retest parents.** `pull_cross_month_parents` filters on one method
   token, and the aggregator only called it `if method is not None`
   (`document_aggregator.py:359-362`). Passing `None` for a merged group would have
   disabled the pull entirely — undoing B1's traceability with every test still green.
   The aggregator now loops the methods its rows carry and de-duplicates by Report №.
2. **The standards borrow crossing a method boundary** (D3 above).
3. **`_parse_stem` reading the client as a method** (D2 above).

### Deliberately not changed

- The two-pass `discover_groups` structure and the corpus volume snapshot taken between
  the passes — the determinism fix. The snapshot was always client-keyed
  (`method_registry.corpus_client_stats`), so the method never entered it.
- Stage order; nothing touches `input/` after group discovery.
- The three uploader brakes, the fail-closed `approved_clients` allowlist,
  `UploadLedger.decide`, the two-phase checkpoint, `_ROOT` injection.
- `pdf_renderer.py` — the row ORDER changed, in the aggregator; the layout did not
  (ADR-001: layout here, logic there).
- `retest_tracker.py`, `inspector_registry.py`.

### Inspector signatures: no change, and the reason is worth recording

`resolve_inspector` routes on exactly two keys, `client_code` and the report month's
first day (`inspector_registry.py:45-79`); `inspector_matrix.clients` is keyed by client
code and `date_routing` by date. The method has never been part of it. So "one document,
several methods, possibly several inspectors" is not a risk this configuration can
express — the same person already signs a client's UT and MT reports. The merge produces
zero signature changes.

## Rejected alternatives

**Keep informational methods in a separate document** (group key
`(month, client, informational?)`, so at most two documents per client-month). It would
have removed the D4 ambiguity entirely and cost only ~10 extra documents. Rejected
because it re-splits the deliverable the operator asked to merge, on an axis the portal
does not model either — and the D4 rule loses no information, since the per-row verdict
is still in the PDF.

**Drop unmatched-standard rows at compile time** so the rest of the document can file.
Rejected: it would bring portal knowledge into the offline pipeline, and rows dropped
that way appear in no document at all — an official monthly report silently missing
inspections that were performed.

**Keep a fixed `NDT` token in the filename** (`…_NDT_UBOC_DEC_2025.pdf`) so
`_parse_stem` would not need changing. Rejected as hiding the bug rather than fixing it:
the sweep would keep working by accident, and the next name change would break it again.
