# ADR-001: Technology Stack for the Monthly Report Automation Pipeline

- **Status:** Accepted
- **Date:** 2026-07-10
- **Decision makers:** Chief Project Architect (guidance), implementation engine (analysis)

## Context

We must build a fully automated pipeline that:

1. Reads multiple Microsoft Word (`.docx`) inspection reports written in English.
2. Detects the primary inspection date in each report and filters by a requested month.
3. Extracts specific, **evolving** textual fields (ignoring all images).
4. Translates the extracted content into Azerbaijani using a maintainable JSON
   dictionary to guarantee consistent official terminology.
5. Merges the translated content into a single official monthly report.
6. Generates a professional, stable, print-ready PDF in Azerbaijani whose layout
   uses a structured table system that handles long text without corruption.

The workspace begins empty. No language, PDF engine, or parsing library is assumed.
Priorities, in order: **long-term maintainability, robust table rendering, PDF
layout stability, and end-to-end automation** over quick but fragile solutions.

Runtime environment is **Windows 11** (PowerShell), which materially affects the
PDF-engine choice because some engines depend on system-level native libraries
that are painful to install and pin on Windows.

---

## Decision 1 — Programming language & runtime: **Python**

### Options compared

| Concern | Python | Node.js |
|---|---|---|
| `.docx` parsing fidelity | `python-docx` — de-facto standard; exposes paragraphs, tables, runs, and styles; images are simply not read into the text model, satisfying "ignore images" for free | `mammoth` flattens to HTML (structure loss); the `docx` package is write-oriented; parsing is weaker |
| Date detection | `datetime` + `python-dateutil` (robust flexible parsing) | Weaker/heavier date libraries |
| Dictionary translation (JSON) | Trivial (`json`, dict lookup) | Trivial |
| Self-contained PDF options | ReportLab, WeasyPrint, Typst bridge | Mostly Puppeteer (bundles Chromium — heavyweight) |
| CLI automation on Windows | Excellent; single `venv`, no external runtime | Good |
| Maintainability for a document/data pipeline | Strong ecosystem fit | Acceptable |

### Rationale

`python-docx` is the decisive factor: it is the most faithful and widely used
`.docx` reader available in any ecosystem, and its text model naturally omits
images. Python also pairs with the strongest **self-contained** PDF engine
(ReportLab) and offers first-class CLI automation. Node.js is viable but every
sub-requirement is either equal or weaker.

**Decision:** Python (3.11+).

### Risks / mitigations

- *Risk:* Python packaging drift. *Mitigation:* pinned `requirements.txt` + a
  project-local `.venv`; `pyproject.toml` with a `src/` layout.

---

## Decision 2 — PDF engine: **ReportLab (Platypus)**

### Options compared

| Engine | Table stability | Long-text wrapping | Azerbaijani glyphs (ə ğ ı ö ş ç ü) | Windows install | Maintainability |
|---|---|---|---|---|---|
| **ReportLab (Platypus)** | ★★★ deterministic; automatic row height; splits tables across pages | ★★★ cell content as `Paragraph` flowables wraps cleanly | ★★★ embed Noto Sans / DejaVu Sans TTF | ★★★ **pip only, no system binary** | ★★ layout defined in Python (verbose) |
| **Typst** | ★★★ excellent | ★★★ | ★★★ | ★★ requires external `typst` binary to install & pin | ★★★ clean, template-first markup |
| **WeasyPrint (HTML+CSS)** | ★★ CSS page-break/table-splitting quirks | ★★★ | ★★★ | ★ needs GTK/Pango/Cairo — notoriously hard on Windows | ★★★ HTML/CSS |
| docx→PDF (LibreOffice / `docx2pdf`) | ★ unpredictable | ★ | ★★ | needs MS Office / LibreOffice installed | ★ fragile, non-deterministic |

### Rationale

ReportLab is the only option that is simultaneously:

- **Self-contained on Windows** — installs via `pip` with zero native system
  dependencies, which is the single biggest reliability factor for unattended
  automation on this platform.
- **Deterministic for tables** — Platypus `Table` + `Paragraph`-in-cell gives
  automatic row heights, controlled column widths, and correct splitting across
  page boundaries. This is precisely what "structured table system that handles
  long text without layout corruption" demands.
- **Unicode-complete** — embedding a Noto Sans / DejaVu Sans TTF fully covers the
  Azerbaijani Latin alphabet, including `ə`, `ğ`, `ı`, `ö`, `ş`, `ç`, `ü`.

**Typst** is the documented runner-up: its template-first authoring is more
maintainable, but it introduces an external binary that must be installed,
version-pinned, and shipped with the automation — an avoidable dependency given
ReportLab meets every hard requirement. **WeasyPrint** is rejected primarily on
the Windows GTK/Pango/Cairo installation risk. **docx→PDF converters** are
rejected as fragile and environment-dependent (require Office/LibreOffice and
produce non-deterministic layouts).

**Decision:** ReportLab (Platypus).

### Risks / mitigations

- *Risk:* ReportLab layouts are defined in Python and are more verbose than a
  template file. *Mitigation:* isolate **all** layout, fonts, and styling in a
  single `pdf_renderer.py` module so the rest of the pipeline never touches
  layout concerns; keep styles data-driven where practical.
- *Risk:* Missing font at render time. *Mitigation:* fonts live in
  `assets/fonts/` and are referenced by `config/settings.yaml`; renderer fails
  fast with a clear message if the TTF is absent.

---

## Decision 3 — Translation strategy: **Dictionary-authoritative + free-prose fallback**

The extracted field text is *mostly controlled/templated vocabulary with some
free prose*. Therefore:

- A **JSON dictionary** (`translations/az.json`) is the **authoritative** source
  for official terminology — it always overrides, guaranteeing consistent wording
  across every monthly report.
- For segments the dictionary does not cover (free prose), the translator
  **flags** the untranslated text (so it is visible and auditable rather than
  silently dropped) and exposes a **clean hook** for an optional machine-
  translation layer to be added later without reworking the pipeline.

**Decision:** dictionary-first with explicit flagging of untranslated segments
and a pluggable MT hook.

### Risks / mitigations

- *Risk:* Free prose accumulates untranslated. *Mitigation:* flagged segments are
  reported per run, turning gaps into a maintainable to-do list for the
  dictionary rather than hidden defects.

---

## Decision 4 — Field extraction: **Config-driven (label + table rules)**

Fields are evolving and their location inside the `.docx` is mixed/uncertain.
Extraction is therefore driven by `config/fields.yaml`, which supports **both**:

- **Label/heading-based** rules (find a field by the label that precedes it), and
- **Table-cell-based** rules (read a value from a known table position/header).

New or changed fields are handled by editing config, not code.

**Decision:** a single config-driven extractor supporting both rule types.

---

## Consequences

- Language: **Python 3.11+**, `src/` package layout, `.venv` + pinned deps.
- Core libraries: `python-docx`, `reportlab`, `PyYAML`, `python-dateutil`.
- All PDF layout concentrated in `pdf_renderer.py`; fonts in `assets/fonts/`.
- Translation and extraction behavior are **configuration-first**, keeping the
  code stable as fields and terminology evolve.
- The pipeline is a single CLI entrypoint (`monthly_report.cli`) enabling
  unattended `input/ → output/` automation.
