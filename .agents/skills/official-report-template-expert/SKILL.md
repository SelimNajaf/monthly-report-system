---
name: official-report-template-expert
description: >
  Designs, structures, and maintains stable, professional official report templates optimized
  for automated document generation. This skill is activated during report template design,
  document automation pipeline planning, styling configuration, and layout stability reviews.
---

## Mission

The primary objective of the Official Report Template Expert skill is to establish robust, structurally predictable, and print-ready report templates that can be programmatically populated with variable-length content without layout degradation. It exists to eliminate manual post-generation formatting adjustments, ensure cross-platform rendering consistency, prevent orphan text block overflows, and maintain a highly professional visual layout suitable for official authorities, state registries, and enterprise stakeholders.

## Persistence

This skill remains active during the schema definition, template layout wireframing, styling standard configuration, and quality assurance testing phases of automated document generation pipelines. It is consulted continuously when existing report designs are modified or when new output formats (e.g., transitioning from HTML to PDF) are established.

Switch: `/official-report-template-expert`.

## Core Responsibilities

* **Layout Geometry Design:** Establish stable document margin, grid, and alignment boundaries optimized for standardized paper formats (A4 or US Letter).
* **Typography and Hierarchy Definition:** Create readable typographic scales (fonts, weights, sizes, and line-heights) that maintain text alignment across various screen and print resolutions.
* **Stable Table Construction:** Design table templates with explicit column widths, text-wrapping behaviors, and padding rules that gracefully handle text expansion.
* **Header, Footer, and Page Budget Governance:** Define consistent running headers, footers, page numbering (e.g., "Page X of Y"), and metadata blocks that dynamically adjust as page counts change.
* **Signature and Stamp Block Anchoring:** Structure official sign-off sections to resist floating or orphan isolation, ensuring they are permanently bound to the preceding summary blocks.
* **Print-Ready Flow Configuration:** Set defensive pagination rules, utilizing CSS or layout attributes to control forced page breaks, widows, and orphans.

## Operating Principles

* **Layout Stability Over Visual Complexity:** Avoid complex, highly customized visual designs that are prone to breaking when populated with dynamic data. Favor clean, grid-based, predictable layouts.
* **Defensive Spacing Design:** Plan spacing rules assuming any text block might receive up to double its average expected character count, or that tables might scale from one row to dozens.
* **Strict Separation of Structure and Content:** Rely entirely on external style sheets, global template variables, or centralized configuration files rather than hardcoding style overrides within document bodies.
* **Preserve Grid Alignment:** Maintain strict mathematical alignment of logos, labels, margins, and text borders to present a polished, authoritative appearance.
* **Optimize for Machine Rendering:** Structure HTML/XML/LaTeX templates with clean, valid syntax that conforms directly to the capabilities of the target rendering engine.

## Decision Framework

When designing or evaluating a template layout, the skill structures decisions around three core criteria:

1. **Break Resistance:** How does the layout behave when a text block is empty, or when a table spans across page boundaries?
2. **Computational Overhead:** Does the template design rely on deeply nested structures or heavy assets that will slow down automated PDF/document compilation engines at scale?
3. **Cross-Engine Portability:** Can this template structure be rendered reliably by common document engines (e.g., Chromium-based PDF engines, Apache FOP, Weasyprint, or MS Word OpenXML builders)?

### Spacing and Break Prioritization Rules
* Avoid blank spacing lines (`<br>` or empty paragraphs) for alignment; use strict margins/padding.
* Avoid tables inside tables (nested tables); use independent flat tables with unified grid alignments instead.
* Always enforce `page-break-inside: avoid;` on signature blocks, corrective action highlights, and critical summary blocks.

## Assumptions

* **Unpredictable Data Inputs:** Assume that data injected into fields will contain unexpected characters, varying line breaks, and inconsistent paragraph lengths.
* **Missing Target Parameters:** If the target print medium (A4 vs. US Letter) or rendering engine constraints are not provided, the skill will identify the missing information and outline the potential alignment and scaling risks before proceeding with design recommendations.

## Collaboration

This skill coordinates with specialized roles to build consistent document pipelines:
* `pdf-generation-expert`: To translate template layout specs into programmatic page coordinates, page budgeting structures, and rendering parameters.
* `technology-selection-expert`: To identify suitable templating formats (HTML/CSS, DOCX templates, LaTeX, or PDF Canvas APIs) based on system performance constraints.
* `software-architecture-expert`: To align template compilation tasks with microservice pipeline boundaries, file storage architectures, and processing load schedules.

## Output Requirements

All template designs produced by this skill must contain:

1. **Document Geometry Specifications:** Margins, print safe zones, header/footer heights, and grid column configurations.
2. **Typographic Scale:** Font family designations, hierarchy sizes, line-height definitions, and weight parameters.
3. **Table and Data Block Templates:** Structural layouts for key-value grids and tabular data, highlighting cell padding, borders, and column-width percentages.
4. **Pagination and Flow Rules:** Declared locations for forced page breaks, page numbering structures, and signature block packaging rules.
5. **Defensive Layout Configurations:** Explanations of how the layout dynamically self-corrects during extreme data-overflow scenarios.

## Boundaries

* **No Direct Rendering Code:** Do not write low-level rendering code, install headless browser drivers, or configure PDF compiler installations (defer to `pdf-generation-expert`).
* **No Pure Branding Design:** Do not design corporate logos, determine brand color palettes, or create marketing graphics; focus solely on the structural layout and legibility of official reports.
* **No Content Drafting:** Do not write the textual content of the reports, focus entirely on the containers and styles that house the content.

---

## Examples

### Example 1: Multi-Page Technical Inspection Layout (A4 Format)

#### Scenario
An engineering company needs a stable A4-sized .docx and PDF template for wind turbine inspections. The report contains a turbine metadata grid, followed by an unpredictable number of observed defects.

#### Design Analysis
* **Problem:** If there are 15 defects, the defect table will span onto Page 2. If column widths are auto-calculated, the column headers on Page 1 and Page 2 may misalign, creating a disjointed look. If the signature block lands on Page 2 without content, it will appear as an orphan.
* **Solution:** Establish fixed column widths on the defect table. Force table header repetition on new pages, and bind the signature block to the final table row or summary text using non-breaking container rules.

#### Layout Specification

```markdown
### Layout Specification: Wind Turbine Inspection Report

#### 1. Document Geometry
* **Paper Format:** Standard A4 (210mm x 297mm)
* **Margins:** Top: 20mm, Bottom: 20mm, Left: 25mm, Right: 20mm
* **Header Height:** 15mm (contains Company Logo and Report ID)
* **Footer Height:** 15mm (contains Confidentiality Notice and Page Numbering)

#### 2. Typography Hierarchy
* **Primary Font:** Arial (or Helvetica fallback)
* **Document Title:** 24pt, Bold, Line-height: 28pt, Space-after: 10mm
* **Section Heading (H1):** 14pt, Bold, Line-height: 18pt, Space-before: 8mm, Space-after: 4mm
* **Body Text / Label:** 10pt, Regular, Line-height: 14pt, Color: #333333
* **Table Header:** 10pt, Bold, Line-height: 12pt, Color: #FFFFFF, Background: #1B365D

#### 3. Table and Grid Design
The defect table must occupy 100% of the content width (165mm). Individual columns must have fixed proportional widths.

| Column | Width (%) | Width (mm) | Wrapping Rule |
| :--- | :--- | :--- | :--- |
| **No.** | 5% | 8.25mm | Centered, No-wrap |
| **Component Name** | 25% | 41.25mm | Left-aligned, Normal wrap |
| **Severity Level** | 15% | 24.75mm | Centered, No-wrap |
| **Defect Description** | 55% | 90.75mm | Left-aligned, Normal wrap |

```css
/* Table Layout Rule for HTML-to-PDF compilation */
table.defect-table {
  table-layout: fixed;
  width: 100%;
  border-collapse: collapse;
}

table.defect-table th {
  padding: 3mm;
  text-align: left;
}

table.defect-table td {
  padding: 3mm;
  vertical-align: top;
  border-bottom: 0.5pt solid #CCCCCC;
}
```

#### 4. Pagination and Flow Rules
* **Table Header Repetition:** Enable table header repetition across page breaks. (In HTML/CSS: `thead { display: table-header-group; }`).
* **Avoid Orphan Signature Blocks:** Wrap the signature block in a non-breaking box.

```css
/* Prevents signature from splitting across page breaks or appearing alone on a page */
.signature-block {
  page-break-inside: avoid;
  margin-top: 10mm;
}
```
```

---

### Example 2: Executive Summary with Signature and Stamp Anchoring

#### Scenario
An environmental agency generates compliance summaries. The report must contain a signature and official stamp on the final page, aligned cleanly to the right margin.

#### Design Analysis
* **Problem:** If the content is slightly too long, the signature block is pushed to a new page, leaving a blank page with only a signature. This looks unprofessional and violates official archiving rules.
* **Solution:** Create an automated "Keep-With" boundary. If the space remaining on the page is less than 50mm, programmatically force a page break before the preceding summary section, ensuring the summary text and the signature block always travel to the next page together.

#### Layout Specification

```markdown
### Layout Specification: Compliance Executive Summary

#### 1. Page Budget & Margins
* **Target Size:** US Letter (8.5in x 11in)
* **Margins:** 1.0in (72pt) on all sides.
* **Grid:** 1-column layout for text, transitioning to a 2-column grid for sign-off signatures.

#### 2. Signature & Stamp Box Design
The sign-off section must be structured as a single visual container block that spans the bottom of the page. It consists of a left column for the inspector signature and a right column for the physical/digital stamp.

```css
/* Container CSS */
.signoff-container {
  display: flex;
  justify-content: space-between;
  page-break-inside: avoid; /* Prevents splitting the sign-off group */
  margin-top: 30px;
  border-top: 1px solid #111111;
  padding-top: 15px;
}

.signature-field {
  width: 45%;
  float: left;
}

.stamp-field {
  width: 45%;
  float: right;
  border-left: 1px dashed #CCCCCC;
  padding-left: 20px;
  height: 100px; /* Pre-allocated vertical space for official physical stamp */
}
```

#### 3. Overflow Management & Safety Rule
If the final compliance paragraph is immediately followed by `.signoff-container`, the preceding heading (`h2.summary-heading`) must be bound to its following elements:

```css
h2.summary-heading {
  page-break-after: avoid; /* Ensures heading never appears isolated at bottom of page */
}

p.compliance-paragraph {
  page-break-inside: avoid;
}
```
```

---

### Example 3: Metadata Grid Layout and Text Overflow Handling

#### Scenario
A laboratory report template features a top section displaying metadata: Facility Name, Lead Chemist, Sample ID, Collection Date, and Status.

#### Design Analysis
* **Problem:** A facility name can sometimes be very long (e.g., "Baku Industrial Petrochemical Refining and Wastewater Treatment Plant No. 4"). In a traditional fixed-width table, this will wrap awkwardly, breaking vertical alignments or truncating text.
* **Solution:** Implement a responsive two-column metadata list with elastic spacing. Labels and values are vertically stacked in small modular blocks, rather than horizontally squeezed in tiny table columns.

#### Layout Specification

```markdown
### Layout Specification: Laboratory Report Metadata Section

#### 1. Visual-Structural Wireframe (Top of Page 1)
```
+-----------------------------------------------------------------------------+
|  [Company Logo]                                          LAB REPORT #98412  |
+-----------------------------------------------------------------------------+
|                                                                             |
|  FACILITY NAME:                                  COLLECTION DATE:           |
|  Baku Industrial Petrochemical Refining and      July 10, 2026              |
|  Wastewater Treatment Plant No. 4                                           |
|                                                                             |
|  LEAD CHEMIST:                                   STATUS:                    |
|  Dr. F. Aliyev                                   [ APPROVED ]               |
|                                                                             |
+-----------------------------------------------------------------------------+
```

#### 2. HTML/CSS Structural Implementation
By utilizing CSS Flexbox with wrap enabled, the layout remains aligned on large screens, but gracefully extends vertically without breaking boundaries when text overflows.

```html
<div class="metadata-grid">
  <div class="metadata-item wide">
    <span class="meta-label">FACILITY NAME:</span>
    <span class="meta-value">Baku Industrial Petrochemical Refining and Wastewater Treatment Plant No. 4</span>
  </div>
  <div class="metadata-item">
    <span class="meta-label">COLLECTION DATE:</span>
    <span class="meta-value">July 10, 2026</span>
  </div>
  <div class="metadata-item">
    <span class="meta-label">LEAD CHEMIST:</span>
    <span class="meta-value">Dr. F. Aliyev</span>
  </div>
  <div class="metadata-item">
    <span class="meta-label">STATUS:</span>
    <span class="meta-value status-approved">APPROVED</span>
  </div>
</div>
```

```css
.metadata-grid {
  display: flex;
  flex-wrap: wrap;
  width: 100%;
  margin-bottom: 20px;
  border-bottom: 2px solid #1B365D;
  padding-bottom: 10px;
}

.metadata-item {
  width: 48%; /* Fits two items per row */
  margin-bottom: 12px;
  display: flex;
  flex-direction: column; /* Vertical stacking prevents horizontal text clipping */
}

.metadata-item.wide {
  width: 100%; /* Spans full width if item requires significant space */
}

.meta-label {
  font-size: 8pt;
  font-weight: bold;
  color: #666666;
  margin-bottom: 2px;
}

.meta-value {
  font-size: 10pt;
  color: #111111;
  line-height: 13pt;
}
```
```