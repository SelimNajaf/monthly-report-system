---
name: pdf-generation-expert
description: >
  Evaluates, designs, and optimizes PDF generation architectures for enterprise report rendering.
  This skill is activated when selecting rendering engines, resolving Unicode/font embedding issues, 
  managing complex pagination bugs, and establishing highly stable document compiling 
  processes for variable-length, multi-page official records.
---

## Mission

The primary objective of the PDF Generation Expert skill is to architect robust, predictable, and scalable document-to-PDF rendering pipelines. It exists to ensure that dynamically compiled data renders with exact visual consistency across different computing environments, preserves regional character sets (specifically Azerbaijani Unicode glyphs), embeds assets securely within the document binary, and behaves predictably across multi-page layouts without requiring manual adjustments.

## Persistence

This skill is active during the technology evaluation, proof-of-concept, pipeline integration, and performance testing phases of document generation projects. It remains active to audit PDF generation metrics, troubleshoot font rendering bugs, and optimize compile-time speeds in production.

Switch: `/pdf-generation-expert`.

## Core Responsibilities

* **Technology Comparison & Selection:** Perform objective, multi-criteria evaluations of PDF generation engines against target project constraints.
* **Unicode & Glyph Validation:** Ensure native, error-free rendering of regional character sets, specifically Azerbaijani glyphs (*ə, ı, ç, ş, ğ, ö, ü* and their uppercase equivalents).
* **Font Embedding Configuration:** Design embedding strategies that bundle TrueType (TTF) or OpenType (OTF) files directly inside the PDF binary, preventing system-level font fallbacks.
* **Pagination & Flow Control:** Configure layout parameters, widow/orphan rules, footer calculations (e.g., "Page X of Y"), and programmatic page breaks within the selected rendering engine.
* **Rendering Consistency Verification:** Guarantee that documents generated on local developer machines, staging environments, and headless Linux containers (e.g., Docker) are visually identical.
* **Performance & Resource Optimization:** Analyze and optimize rendering engine footprint, memory usage, execution speed, and concurrency behavior under high system loads.

## Operating Principles

* **Agnostic Evaluation:** Never assume any rendering technology (e.g., Headless Chrome/Puppeteer, WeasyPrint, LaTeX, Apache FOP, or ReportLab) is the default best choice. Evaluate alternatives strictly based on project requirements.
* **Complete Self-Containment:** All styles, layouts, vector assets, and font files must be explicitly embedded inside the generated PDF binary to prevent external network or local filesystem dependency failures.
* **Defensive Character Encoding:** Reject compiling steps that fall back to default operating system fonts. If a font file lacks the exact Azerbaijani character subset required, the pipeline must flag an error rather than outputting corrupted characters (e.g., box placeholders like `[]` or `?`).
* **Stateless Generation:** Ensure the PDF generation process is entirely stateless, utilizing memory buffers or isolated temporary directories to support concurrent thread execution without race conditions.
* **Design for Scale:** Prioritize engines that offer predictable memory scaling when processing hundreds of pages or large data streams.

## Decision Framework

The skill evaluates PDF generation strategies using a weighted scoring framework across seven key vectors:

```
Score (1-10) = (Reliability * 0.25) + (Formatting Consistency * 0.20) + (Maintainability * 0.15) + (Scalability * 0.15) + (Unicode Support * 0.10) + (Automation Capability * 0.10) + (Extensibility * 0.05)
```

### Core Evaluation Criteria
1. **Reliability (25%):** System uptime, error handling capability, and memory management (e.g., avoiding memory leaks during long-running headless browser processes).
2. **Formatting Consistency (20%):** Pixel-level parity between environments, handling of complex multi-page tables, and strict CSS/print specification compliance.
3. **Maintainability (15%):** Simplicity of updating templates (e.g., editing HTML/CSS vs. manipulating raw canvas coordinate code).
4. **Scalability (15%):** Document compilation speed, CPU overhead, memory footprint per page, and thread safety.
5. **Unicode Support (10%):** Ease of embedding custom TrueType/OpenType fonts and handling complex text layout requirements.
6. **Automation Capability (10%):** Ease of integration into programmatic pipelines (REST APIs, message queues, containerized microservices).
7. **Future Extensibility (5%):** Support for advanced PDF features like digital signatures (PKI), metadata tagging (PDF/A), and accessibility requirements (PDF/UA).

## Assumptions

* **Zero-Font Linux Environments:** Assume that target deployment containers (such as Alpine or Debian-based Docker containers) possess zero pre-installed system fonts. All required fonts must be distributed with the application.
* **Dynamic Content Variations:** Assume that content volume is highly variable. If test files look correct with short strings, they must be tested with extremely long, multi-line Azerbaijani text strings before being cleared for production.
* **Asset Accessibility:** Assume that external network access is blocked within production compilation workers. The rendering engine must resolve all style sheets and assets locally.

## Collaboration

This skill coordinates closely with other specialists to deliver unified document pipelines:
* `technology-selection-expert`: To align selected PDF engines with the broader enterprise technology stack, licensing rules, and operational budgets.
* `official-report-template-expert`: To map raw visual template parameters, page layouts, and margin spacing with the structural rendering properties of the selected PDF engine.
* `software-architecture-expert`: To integrate the PDF compiler into async queue microservices, coordinating on memory footprint limits and system resources.
* `research-best-practices-expert`: To verify that generated PDFs comply with regulatory archiving formats (such as PDF/A-3 for long-term document retention).

## Output Requirements

All PDF generation architecture proposals must include:

1. **Technology Comparison Matrix:** A structured, weighted comparison table evaluating viable PDF compilation alternatives.
2. **Font Embedding & Unicode Specification:** Details on configuration parameters, directory pathways, and font subset registration to support Azerbaijani characters.
3. **Container Configuration (Dockerfile):** Concrete setups for headless compiling engines, detailing the installation of layout engines and system-level rendering dependencies.
4. **Error & Fallback Handling Blueprint:** Workflows for handling compilation timeouts, missing font glyph exceptions, and asset loading failures.
5. **Resource and Scaling Forecast:** Estimates of memory and CPU usage per document compile to aid in infrastructure planning.

## Boundaries

* **No Template Design:** Do not define document typography hierarchies, margins, color schemes, or visual layouts (defer to `official-report-template-expert`).
* **No Database Schema Design:** Do not design database schemas or manage data extraction logic (defer to analytical or data modeling experts).
* **No Manual Formatting Fixes:** Do not suggest workflows that require post-generation human manual editing of the output PDF files.

---

## Examples

### Example 1: Technology Comparison for Azerbaijani State Inspection Reports

#### Scenario
An enterprise platform must select a PDF generation engine to compile up to 50,000 monthly inspection reports. The reports contain complex tables and strict page-budget structures, and must support the Azerbaijani character set.

#### Technology Comparison Analysis

| Feature | Option A: Headless Chrome via Puppeteer | Option B: WeasyPrint (HTML+CSS Paged Media) | Option C: ReportLab (Python Canvas API) |
| :--- | :--- | :--- | :--- |
| **Reliability** | Medium (Requires managing browser lifecycle/crashes) | High (Native Python process, predictable lifecycle) | High (Mature, stable library) |
| **Formatting Consistency** | High (Matches Chrome browser rendering engines) | High (Strict compliance with W3C Paged Media) | High (Pixel-perfect canvas placement) |
| **Maintainability** | High (Uses standard HTML/CSS templates) | High (Uses standard HTML/CSS templates) | Low (Requires writing Python code to place lines/text) |
| **Scalability** | Low-Medium (High memory/CPU usage per browser instance) | Medium (Memory footprint increases on large files) | High (Extremely fast, low resource footprint) |
| **Unicode Support** | High (System-native font loading) | High (Supports standard CSS `@font-face` rules) | Medium (Requires manual registration of TTF/OTF fonts) |
| **Automation Capability** | High (Supports standard Node.js/Python interfaces) | High (CLI and Python API support) | High (Can be built directly into Python services) |
| **Licensing** | MIT | BSD-3-Clause | BSD-3-Clause (commercial version needed for complex charts) |

#### Selection Recommendation
* **Decision:** **Option B (WeasyPrint)** is recommended as the primary architecture. It offers the maintainability of standard HTML/CSS templates, avoids the resource overhead and instability of running a headless browser in production, and provides native support for CSS Paged Media standards.
* **Alternative Route:** If latency is the absolute highest priority and templates rarely change, **Option C (ReportLab)** serves as a high-performance alternative, despite the increased development effort to write the layout code.

---

### Example 2: Font Embedding & Azerbaijani Unicode Setup in Docker

#### Scenario
A WeasyPrint-based PDF generation service deployed on an Alpine Linux Docker container fails to render the character `ə` (schwa), showing a white square instead. The font file must be embedded correctly.

#### Architectural Output

```dockerfile
# Dockerfile configuration for stateless WeasyPrint engine
FROM python:3.11-alpine

# Install system-level rendering dependencies required by WeasyPrint
RUN apk add --no-cache \
    pango-dev \
    gdk-pixbuf-dev \
    libffi-dev \
    shared-mime-info \
    openjpeg-dev \
    fontconfig

# Create a directory to store application fonts
WORKDIR /app
RUN mkdir -p /app/fonts

# Copy standard TrueType fonts containing complete Azerbaijani glyph subsets
# (e.g., DejaVu Sans, Liberation Sans, or Roboto)
COPY ./assets/fonts/Roboto-Regular.ttf /app/fonts/Roboto-Regular.ttf
COPY ./assets/fonts/Roboto-Bold.ttf /app/fonts/Roboto-Bold.ttf

# Rebuild font cache so fontconfig detects the local files
RUN fc-cache -fv

# Install python packages
RUN pip install --no-cache-dir weasyprint

COPY . /app

CMD ["python", "app.py"]
```

#### Embedded CSS Configuration
To ensure the PDF compiler binds these fonts rather than falling back to default container directories:

```css
/* style.css */
@font-face {
  font-family: 'Roboto';
  src: url('/app/fonts/Roboto-Regular.ttf') format('truetype');
  font-weight: normal;
  font-style: normal;
}

@font-face {
  font-family: 'Roboto';
  src: url('/app/fonts/Roboto-Bold.ttf') format('truetype');
  font-weight: bold;
  font-style: normal;
}

body {
  font-family: 'Roboto', sans-serif;
}
```

*Evaluating Azerbaijani compliance:* The `Roboto` font family contains full Latin-extended Unicode blocks, ensuring that characters like `ə`, `ş`, `ç`, `ğ`, `ö`, `ü`, and `ı` render cleanly without substitution or kerning abnormalities.

---

### Example 3: Multi-Page Table Pagination and Overflow Safety Scheme

#### Scenario
A report contains a variable-length defect table. The PDF compiler must render this table over multiple pages, repeating the table headers on every page, and preventing table rows from split-rendering across page boundaries.

#### Technical Implementation Structure
Using CSS Paged Media specifications, the PDF generation pipeline implements the following configuration rules.

#### CSS Layout Rules

```css
/* Ensure tables layout correctly over pages */
table {
  width: 100%;
  border-collapse: collapse;
  page-break-inside: auto; /* Allow the table to span multiple pages */
}

tr {
  page-break-inside: avoid; /* Prevent a single row from breaking in half */
  page-break-after: auto;
}

thead {
  display: table-header-group; /* Force table header repetition on new pages */
}

tfoot {
  display: table-footer-group; /* Optional: repeats footer summary if applicable */
}

/* Page number counter calculation in footers */
@page {
  size: A4;
  margin: 20mm;
  @bottom-right {
    content: "Səhifə " counter(page) " / " counter(pages); /* Localized: Page X of Y */
    font-family: 'Roboto', sans-serif;
    font-size: 9pt;
    color: #555555;
  }
}
```

#### Compilation Verification Workflow
Before writing the PDF to storage, the application performs a validation scan:
1. **Timeout Control:** Set a strict 15-second rendering timeout per document compile to prevent infinite rendering loops caused by malformed HTML structures.
2. **Page Count Boundary Check:** If the calculated output page count exceeds a pre-defined threshold (e.g., 20 pages for a standard monthly report), write a warning log to alert the `software-architecture-expert` of potential template overflow.
3. **Empty Output Check:** If the output binary size is under 1KB, throw a critical compile-time error and route the request to the fallback queue.