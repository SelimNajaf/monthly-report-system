# ADR-002 — Desktop dashboard frontend

* **Status:** Accepted
* **Date:** 2026-07-16
* **Supersedes:** nothing. **Companion to:** ADR-001 (tech stack)

ADR-001 predates `main.py`, `uploader.py`, the upload ledger and the parallel
reader. Its closing statement — *"The pipeline is a single CLI entrypoint
enabling unattended `input/ → output/` automation"* — still holds, and this ADR
does not change it. It records a second, optional face on the same system.

---

## Context

The pipeline and uploader are complete and correct, and entirely invisible. Every
signal the system produces — 99 generated reports, 58 quarantined files, a
transaction-safe upload ledger — is legible only to someone reading scrollback in
a terminal. Non-technical stakeholders cannot see the work, so they cannot value
it, and the quarantine queue in particular has no reader: it is a human-in-the-loop
mechanism with no human interface.

The requirement is a dashboard that runs locally, looks like something a manager
would trust, and never blocks while the backend works.

**Non-negotiable constraint:** the backend does not change. `src/monthly_report/`,
`main.py` and `uploader.py` are cohesive, tested and in production. A GUI is a new
reader of that system, not a reason to rewrite it.

---

## Decision 1 — Framework: PySide6

| Criterion | PySide6 | CustomTkinter | Flet |
|---|---|---|---|
| Visual ceiling | QSS, drop shadows, property animation, styled tables | Rounded widgets; no shadows, weak tables | High (Flutter) |
| Non-blocking execution | `QProcess` — async, signal-driven | Manual `after()` polling of a queue | asyncio |
| Local-only | Native | Native | **Runs a local web server** |
| Packaging | First-party PyInstaller hooks | Needs `--add-data` for theme JSON | Bundles a Flutter engine |
| Licence | **LGPL** | MIT | Apache-2.0 |
| Python 3.14.6 | 6.11.1 wheels verified | ok | ok |

**Flet was disqualified on the zero-server requirement** — it serves the UI over a
local HTTP/WebSocket connection, which is precisely the overhead this app was
asked not to have. **CustomTkinter was disqualified** on visual ceiling and the
absence of a first-class table and process API.

**PySide6 over PyQt6 is a licensing decision, not a technical one.** The two are
near-identical in capability. PyQt6 is GPL-or-commercial: shipping this internal
tool against it would either force the whole project under the GPL or require
paid licences per developer. PySide6 is LGPL and carries neither obligation when
dynamically linked, which is what pip installs and what PyInstaller bundles.

**Risk accepted:** PySide6 is ~170 MB frozen and Qt majors move fast. Mitigated by
confining Qt to `gui/` — the pipeline neither imports nor needs it, and CI runs
headless without it.

---

## Decision 2 — Execution: child process, not a worker thread

The brief asked for QThread workers. We used `QProcess` instead, and it satisfies
the underlying requirement (a UI that never freezes) more completely.

`QProcess` is asynchronous. It never blocks, it emits a signal when bytes arrive,
and Qt delivers that signal on the UI thread. The event loop is never waiting on
the backend, so it cannot be wedged by it. There is no thread to marshal across,
no lock, and no shared mutable state.

Three concrete problems a thread would have introduced:

1. **`docx_reader.read_many` drives a `ProcessPoolExecutor`** (docx_reader.py:184).
   In-process, the GUI becomes the spawn parent of every worker.
2. **`sys.stdout` is process-global.** Capturing it with `redirect_stdout` races
   with anything else that prints, and `pre_processor.warn` calls
   `sys.stdout.isatty()` (pre_processor.py:39) — a substitute stream lacking that
   method raises `AttributeError` mid-run.
3. **Threads cannot be killed.** Cancel would be cosmetic.

Under a pipe, `isatty()` is false, so `warn` emits plain text and the console gets
clean output for free — the third problem solves itself.

`QThreadPool` is still used, for the filesystem scans behind the metric cards.
Those are I/O, they are bounded, and they have no stdout.

**Cancel kills the tree.** `QProcess.kill()` reaches the child only;
`ProcessPoolExecutor` workers are grandchildren that outlive it, holding cores and
file handles after the UI claims "Cancelled". `taskkill /PID <pid> /T /F` takes
the tree.

---

## Decision 3 — `_ROOT` injection, and data beside the executable

This is the load-bearing decision, and it exists to prevent silent data loss.

`config.load_settings` resolves every path — `input/`, `output/`, fonts,
translations — against a project root derived from where `settings.yaml` sits
(config.py:59). `main.py` derives that from its own `__file__` (main.py:27).

Under PyInstaller `--onefile`, `main.__file__` is `%TEMP%\_MEIxxxxx\main.py`.
Bundle `config/` into the exe and `project_root` becomes the temp extraction
directory — the pipeline reads `input/` from it and writes `output/` into it, and
**Windows deletes the whole thing when the process exits.** Every generated report
would vanish, with no error, on a build that otherwise looks like it works.

**The fix:** `gui/worker_entry.py` rebinds `main._ROOT` (and `uploader._ROOT`) to
the real application root before calling into either. Both are module globals read
*inside* functions, never at import time, so the assignment takes effect on the
next call. The files on disk are untouched; in a source checkout the injected
value is identical to the one they compute themselves. This is dependency
injection from a composition root, not a modification.

**The consequence:** data directories ship *beside* the executable, never inside
it. This is correct independent of the bug — `input/` and `output/` are mutable
user data and cannot live in a read-only bundle that is discarded on exit.

```
MonthlyReportStudio\
  MonthlyReportStudio.exe          <- one file
  config\  assets\  translations\  images\
  input\   output\
```

**Verified, not assumed.** A frozen onefile build parsed 434 reports across 12
cores in 5.3s and wrote 27 PDFs beside the executable; zero landed under `_MEI*`.

Two supporting details this depends on:

* `multiprocessing.freeze_support()` is the first call in `gui_launcher.py`.
  Windows spawns rather than forks, so each pool worker re-executes the program;
  without it, a frozen build opens one dashboard window per CPU core.
* `JobRunner` inherits the parent environment rather than building one. PyInstaller
  passes `_MEIPASS2` to children so they reuse the parent's extraction. Dropping it
  would make all 12 workers each re-unpack 169 MB before doing any work.

---

## Decision 4 — Filters read filenames, not config

The dropdowns are built by scanning `output/` and parsing report filenames, not by
reading `settings.yaml`. The config cannot answer the question:

* Method **folder** and method **token** differ (`MPI`/`MT`, `FERRITE`/`FC`), and
  nothing exposes the mapping.
* Months are not configured at all — `main.py` discovers them from inspection
  dates and overwrites `settings.target_month` per group (main.py:148).
* `uploader.py` matches `--month FEB_2026` and `--method MT` against *filenames*
  (uploader.py:434).

Reading filenames yields the exact tokens the uploader matches, so a selection
cannot be spelled wrong and a dropdown cannot offer a combination that produces
nothing.

**The filters scope the view, the upload, and — as of Decision 7 — the pipeline.**
The original ADR deferred pipeline scoping to avoid duplicating `main.py`'s
orchestration loop; Decision 7 achieves it without any duplication by teaching
`main.py` itself the same three flags the uploader already takes.

---

## Decision 5 — Dry-run uploads only

The dashboard exposes `--dry-run` and nothing else. No credentials are collected,
no browser launches, no network calls are made. The uploader's `DryRunPage`
sentinel (uploader.py:164) already makes this a first-class mode rather than a
simulation bolted on, and the dry run keeps a separate ledger file so a
simulated batch can never mask a real pending upload.

Live uploads remain a deliberate terminal operation. Revisit when a credential
story (Windows Credential Manager via `keyring`) is agreed.

---

## Decision 6 — Drag-and-drop ingestion, and one sanctioned backend edit

*Added 2026-07-16, after the dashboard shipped.*

Every month began the same way: copy 100–1000 reports into `input/` by hand in
Explorer, then open the dashboard. The window could show the work but not receive
it. Drag-and-drop closes that gap, and doing it exposed the last serial stage.

**A native drop zone, filesystem logic behind the service line.** `DropZone`
(`ui/widgets/`) is the whole Qt surface: `setAcceptDrops(True)`, three event
handlers, a dashed border that lights up on drag-over. It emits raw paths and
decides nothing. `services/ingest_service.py` — QtCore-free, unit-tested headless
— walks the drop recursively, filters to `.docx`/`.pdf`, and copies. The split is
deliberate: a physical drag is the one interaction that cannot be automated in a
test, so as little as possible lives on its side of the line. Everything the drop
*decides* is tested; only the gesture that *triggers* it is not.

Two rules are inherited, not invented. **No-clobber:** an existing name is
skipped and counted, matching `pre_processor.move_to` (pre_processor.py:69), so
re-dropping a folder is idempotent and a name collision never overwrites a
curated file silently — the count makes it visible. **No partial file:** copy to
`<name>.part`, then `os.replace`; a cancelled or crashed ingest leaves nothing
that `rglob("*.docx")` will read as a real report.

**The sanctioned backend edit.** This ADR's own constraint is *"the backend does
not change."* The parallel-conversion requirement overrides it for exactly one
function, `pre_processor.convert_input_pdfs`, on the user's explicit instruction.
The override is bounded and it is paid for:

* Only the **conversion loop** parallelises. Every decision, every `print`, and
  every file move stays serial in the parent. Workers receive a source and a
  destination and do one thing. A stage that mutates `input/` is safe to run
  eight ways only because the mutation itself never does.
* It ships with `tests/test_pre_processor_parallel.py` (a function that had none),
  and the existing suite passing is the proof it changed no behaviour.
* Three bugs a naive `ProcessPoolExecutor` swap would have introduced were found
  and fixed, the first of them silent data loss: two PDFs sharing a leading
  report token both resolve their output name by checking what exists on disk
  (`converted_docx_path`), and in parallel both see the name free and one
  overwrites the other. Fixed by resolving all names in the parent, serially,
  against a reservation set before any work is submitted. (The others: pdf2docx's
  `logging.basicConfig(INFO)` re-hijacking stdout in every spawned worker —
  ordered against in `_convert_init`; and killed workers leaving half-written
  `.docx` — closed by the `.part` protocol, which also fixes a pre-existing hole
  on the serial path.)

**Measured, not claimed.** The brief hoped for 10–12×. On 11 real inspection PDFs
the wall-clock was **398.8 s serial → 100.0 s at 8 workers = 3.99×**, output
byte-identical. The ceiling is not core count: pdf2docx is largely bound by
single-threaded PyMuPDF rendering and page reconstruction, and the workers
contend on memory bandwidth, so throughput saturates well below linear. The
default worker cap is **8, not 12** — a large scanned PDF peaks near 1 GB per
worker, and twelve on a 16 GB machine swap, which is slower than serial. It is
configurable via `performance.max_convert_workers`.

**Two progress bars, because a run is two jobs.** Getting documents *in* (copy,
convert, sort) is bounded differently from turning them into reports (parse,
render), and its size is known up front where the other's is not. One averaged
bar (conversion was worth a flat 20% whether there was one PDF or four hundred)
described neither. `ProgressEvent` now carries a `Track`, the monotonic clamp is
per-track, and `main_window` routes each event to its own bar.

**Cancel reaches one process deeper for free.** `taskkill /PID <pid> /T /F`
already reaped the parser's `ProcessPoolExecutor` grandchildren (Decision 2); the
conversion pool is the same shape one level down, so the same kill covers it. The
only addition is a `.part` sweep after the kill — a worker killed mid-write
cannot tidy up after itself, and the process that knew what it was writing is the
one we just killed, so the sweep belongs on the outside.

---

## Decision 7 — Scoped pipeline runs (the filters now drive Run Pipeline)

*Added 2026-07-16.*

"Run Pipeline" scoped nothing: it ran `main.py` unattended over every group,
while the dropdowns above it scoped only the metrics and the upload. That was a
visible lie — the same three filters that scoped "Start Portal Upload" were
ignored by the button beside it. Decision 7 wires them through.

**No orchestration is duplicated** — the reason Decision 4 gave for deferring
this. `main.py` gains an `argparse` front end (`--month/--method/--client`, the
exact tokens the uploader and catalog already speak) and a single `Scope` value
threaded into two existing stages. The GUI passes the flags through one shared
helper (`main_window._filter_args`) that both the pipeline and the uploader build
their argv from, so the two buttons scope *identically* by construction.

**Where the scope bites, and where it deliberately does not.**

* **Group discovery is the authoritative gate** — `discover_groups` filters its
  returned `(month, method, client)` groups against the scope, using the real
  parsed values. Only in-scope groups are compiled; every other datable report is
  left exactly where it is. Verified headless: a `--month JUN_2026 --method UT`
  run rewrote 6 files (3 reports + 3 sidecars) and left the other 192 output
  files, mtimes included, untouched.
* **Conversion is gated by method only.** A PDF's month is unknowable before the
  document is parsed (the inspection date lives inside it), and its client is
  resolved internally-first by design (the filename prefix deliberately lies).
  Method is the one dimension a filename yields deterministically, so
  `convert_input_pdfs(method=...)` skips only PDFs whose filename-detected method
  is a *known, different* one — an indeterminate `NDT` filename is always
  converted, because skipping a report the user wanted is the worse failure.
* **Sorting and quarantine stay global.** An ASR/ARS or date-less file is
  unprocessable under *any* filter, so moving it to `SKIPPED_REPORTS/` is correct
  cleanup regardless of what is selected — and a date-less file has no month to
  scope by in the first place.

**One consequence surfaced, not fixed.** Serial numbers run per `(month, method)`
shared across that method's clients. A month+method scope (all clients) yields
identical document numbers to a full run; a *single-client* scope can yield a
lower serial, because that client alone becomes 001. Inherent to generating a
subset, and called out in the run banner rather than papered over.

The default — no flags — is byte-for-byte the old unattended behaviour, which the
unchanged existing suite proves.

---

## Consequences

* The GUI is deletable **except** for the `convert_input_pdfs` refactor, which now
  lives in the backend and stands on its own tests. Removing `gui/` and PySide6
  still leaves a working headless pipeline — a faster one than before.
* Nothing else in the backend imports `gui/`; the rest of the pipeline is
  byte-identical without it.
* Dependencies point inward: `ui/ → services/ → monthly_report`. `services` may
  import `QtCore`, never `QtWidgets`; the two parsers import no Qt at all and are
  unit-tested headless.
* **Backend stdout is now an interface.** `tests/test_gui_progress.py` pins it
  against real transcripts, so rewording a print statement fails a test instead of
  silently freezing a progress bar at 45%.
* `pyproject.toml` gained `gui` and `build` extras, and its `dependencies` list was
  corrected — `pdf2docx` and `playwright` were imported by shipped entry points but
  absent from the manifest.
* The frozen artifact is ~170 MB. Acceptable for internal distribution on the
  target hardware; `--onedir` starts faster and is preferred for iteration.

## Risks

* **Stdout coupling.** Mitigated by tests, but a reworded print is still a coupling
  point that a callback would not have. Accepted: a callback means editing the
  backend, which the constraint forbids.
* **`_ROOT` rebinding depends on both entry points keeping `_ROOT` a
  module-global read at call time.** If either inlines
  `Path(__file__).parent` into a function body, the injection silently stops
  working and a frozen build loses reports again. The frozen verification step in
  the README is the guard; it must stay in the release routine.
* **The conversion pool is a new set of frozen grandchildren.** Decision 6 adds a
  second `ProcessPoolExecutor` under the exe. It rides on the same guarantees as
  the parser's: `multiprocessing.freeze_support()` first in `gui_launcher.py`, and
  `_MEIPASS2` inherited so workers reuse the parent's extraction. If either
  regresses, a frozen build opens a window per core or re-unpacks 170 MB per
  worker. Re-verified on a real onefile build.
* **Conversion stdout is a second interface.** The `[pdf]` markers now drive
  bar A, pinned by `tests/test_pre_processor_parallel.py::TestStdoutMarkers` and
  `test_gui_progress.py`. Same coupling as the pipeline's, same mitigation.
* **Qt major upgrades.** Confined to `gui/`; the pipeline is unaffected.
