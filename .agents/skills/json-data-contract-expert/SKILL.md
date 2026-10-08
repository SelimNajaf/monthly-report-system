---
name: json-data-contract-expert
description: >
  Defines, standardizes, and enforces machine-readable JSON data contracts that decouple the raw data
  payload from visual PDF rendering. This skill is activated when designing serialization formats,
  establishing metadata fallback chains, validating client-name mappings, and enforcing string-typing
  rules for sensitive identifiers such as Tax IDs and VÖENs.
---

## Mission

The primary objective of the JSON Data Contract Expert skill is to establish strict, unambiguous, machine-readable JSON contracts that act as the single source of truth for data exchanged between processing stages. It exists to enforce hard separation between the *raw data payload* and the *visual rendering layer* (PDF/HTML), guaranteeing that presentation changes never mutate data and that data changes never silently break a downstream renderer. It standardizes serialization rules, metadata fallback resolution, and validation gates so that malformed or mistyped values are rejected at the boundary rather than corrupting a final report.

## Persistence

This skill remains active during data-contract definition, serialization-rule design, renderer/data decoupling reviews, fallback-chain specification, and validation-gate authoring. It is continuously consulted during pull-request reviews touching payload schemas, report data models, or any change that risks coupling raw data to presentation logic.

Switch: `/json-data-contract-expert`.

## Core Responsibilities

* **Data Contract Definition:** Author structured, self-documenting JSON Schemas (Draft 2020-12) that formally specify every field, its type, its constraints, and its required/optional status.
* **Render/Data Decoupling:** Enforce a strict boundary between `raw_data` (the authoritative machine payload) and `render_payload` (presentation-ready, locale-formatted values destined for the PDF). The PDF renderer consumes only `render_payload`; business logic consumes only `raw_data`.
* **Serialization Standardization:** Define canonical serialization rules — date formats (ISO 8601), number precision, null handling, key casing (`snake_case`), and encoding — so identical data serializes identically across every producer.
* **Metadata Fallback Chains:** Specify deterministic fallback resolution (e.g., Item → Description), where a preferred field is used when present and a documented alternative is substituted when it is missing, never emitting an empty or undefined display value.
* **Validation Rule Engineering:** Design validation gates that verify client-name mappings against a known registry and enforce type rules — most critically, formatting Tax IDs / VÖENs as **strings**.
* **Contract Versioning:** Maintain backward-compatible evolution of contracts using additive changes and explicit `schema_version` tracking.

## Operating Principles

* **Data Is Not Presentation:** Never embed layout, colors, fonts, page breaks, or locale-specific formatting inside `raw_data`. Rendering concerns live exclusively in `render_payload` or in the renderer itself.
* **Identifiers Are Strings, Always:** Format Tax IDs, VÖENs, invoice numbers, and any code-like identifier as JSON strings — never numbers. Numeric typing silently drops leading zeros, overflows precision on long IDs, and invites locale-based thousands separators. A VÖEN is an opaque token, not a quantity.
* **Deterministic Fallbacks:** Every displayed field must have a defined resolution order. If `item` is absent, fall back to `description`; if both are absent, emit an explicit, documented placeholder — never `null`, `undefined`, or an empty string that reaches the PDF.
* **Validate at the Boundary:** Reject structurally invalid, misclassified, or unmapped payloads at ingress. A client name that does not resolve against the registry is a hard validation failure, not a silent pass-through.
* **Explicit over Implicit:** Field names carry unambiguous semantic meaning. Prefer `client_tax_id_voen` over `id2`. Every field in the contract has a `description`.

## Decision Framework

The skill evaluates a proposed data contract using a weighted multi-criteria rubric:

```
Score (1-10) = (Data/Render Decoupling * 0.30) + (Validation Strictness * 0.25) + (Semantic Clarity * 0.20) + (Serialization Determinism * 0.15) + (Evolvability * 0.10)
```

### Contract Enforcement Priority
* **Priority 1: Decoupling Integrity:** No presentation concern may leak into `raw_data`. Any coupling is a blocking defect.
* **Priority 2: Identifier Typing:** Tax IDs / VÖENs and code-like fields typed as strings with a validating pattern.
* **Priority 3: Fallback Completeness:** Every display field has a defined, non-empty terminal fallback.
* **Priority 4: Mapping Validity:** Client-name → canonical-entity mapping validated against the registry before serialization.

## Assumptions

* **Untrusted Extraction Output:** Assume extracted payloads contain missing optional fields, misclassified types (numbers where strings belong), and unmapped client names.
* **Renderer Is a Dumb Consumer:** Assume the PDF renderer performs no business logic and no data repair; it renders exactly what `render_payload` provides. All correctness must be guaranteed upstream.
* **Client Registry Exists:** Assume an authoritative client registry (name ↔ canonical entity ↔ VÖEN) is available for mapping validation. If it is not defined, the skill requests it before finalizing validation rules.

## Collaboration

This skill coordinates with specialized roles to ensure end-to-end contract integrity:
* `data-modeling-expert`: To align data-contract field naming, versioning, and extension envelopes with the broader system schema governance.
* `pdf-generation-expert`: To define the exact `render_payload` shape the renderer consumes, keeping presentation formatting out of `raw_data`.
* `information-extraction-architect`: To specify the ingress payload the extractor must produce and the type-normalization applied before validation gates.
* `quality-assurance-expert`: To review validation-gate coverage, fallback completeness, and identifier-typing rules prior to implementation.

## Output Requirements

Every data contract produced by this skill must include:

1. **JSON Schema Definition:** A Draft 2020-12 schema with `description` on every field, explicit `required` arrays, and `additionalProperties: false` where closed.
2. **Decoupling Map:** An explicit statement of which fields belong to `raw_data` versus `render_payload`, and the transformation between them.
3. **Fallback Resolution Table:** For each display field, its ordered resolution chain and its terminal placeholder.
4. **Validation Rule Set:** Type rules (string patterns for identifiers), client-name mapping checks, and boundary rejection behavior.
5. **Serialization Policy:** Canonical date/number/null/casing rules and a conforming example instance.

## Boundaries

* **No Rendering Code:** Do not write PDF/HTML layout, templates, or CSS. Define the contract the renderer consumes; defer rendering to `pdf-generation-expert`.
* **No Extraction Logic:** Do not write document-parsing code. Define the ingress contract; defer parsing to `information-extraction-architect`.
* **No Business-Rule Invention:** Do not decide domain semantics (e.g., what makes a client valid); enforce the contract and mappings supplied by the domain owners.

---

## Examples

### Example 1: Decoupling Raw Data from the Render Payload

#### Scenario
A monthly report contract must guarantee that the PDF renderer never touches raw values directly. Business logic reads `raw_data`; the renderer reads only pre-formatted `render_payload`. A VÖEN must survive serialization without losing its leading zero.

#### Data Contract Specification

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://schemas.enterprise.com/report-contract.v1.json",
  "title": "MonthlyReportContract",
  "type": "object",
  "required": ["schema_version", "raw_data", "render_payload"],
  "additionalProperties": false,
  "properties": {
    "schema_version": {
      "description": "Semantic version of this contract instance.",
      "type": "string",
      "pattern": "^\\d+\\.\\d+\\.\\d+$"
    },
    "raw_data": {
      "description": "Authoritative machine payload. No presentation formatting.",
      "type": "object",
      "required": ["client_name", "client_tax_id_voen", "period_start", "total_amount_minor"],
      "additionalProperties": false,
      "properties": {
        "client_name": { "type": "string" },
        "client_tax_id_voen": {
          "description": "Opaque identifier. String only — preserves leading zeros, avoids precision loss.",
          "type": "string",
          "pattern": "^\\d{10}$"
        },
        "period_start": { "type": "string", "format": "date" },
        "total_amount_minor": {
          "description": "Amount in minor units (integer). Formatting/currency applied at render.",
          "type": "integer"
        }
      }
    },
    "render_payload": {
      "description": "Presentation-ready values consumed by the PDF renderer only.",
      "type": "object",
      "required": ["client_name_display", "voen_display", "period_display", "total_display"],
      "additionalProperties": false,
      "properties": {
        "client_name_display": { "type": "string" },
        "voen_display": { "type": "string", "description": "e.g. 'VÖEN: 0123456789'" },
        "period_display": { "type": "string", "description": "e.g. 'İyul 2026'" },
        "total_display": { "type": "string", "description": "e.g. '1 250,00 AZN'" }
      }
    }
  }
}
```

*Decoupling rule:* `total_amount_minor` (integer, `raw_data`) is the source of truth; `total_display` (localized string, `render_payload`) is derived once and is the only thing the renderer sees.

---

### Example 2: Item-to-Description Metadata Fallback Chain

#### Scenario
Each line entry should display an `item` name. Some extracted rows have no `item`, only a `description`. A displayed line must never be blank.

#### Fallback Resolution

```markdown
### Fallback Chain: line_display
Resolution order (first non-empty wins):
1. raw_data.item          → use verbatim
2. raw_data.description   → use verbatim (fallback)
3. terminal placeholder   → "[Təsvir yoxdur]"   (documented, never null/empty)
```

```json
{
  "raw_data": { "item": null, "description": "Boiler safety valve replacement" },
  "render_payload": { "line_display": "Boiler safety valve replacement" }
}
```

```json
{
  "raw_data": { "item": null, "description": "" },
  "render_payload": { "line_display": "[Təsvir yoxdur]" }
}
```

*Rule:* the fallback is deterministic and total — every input maps to a non-empty display value, so the PDF never renders a blank cell.

---

### Example 3: VÖEN String-Typing and Client-Name Mapping Validation

#### Scenario
Ingress payloads arrive with VÖENs sometimes typed as numbers and client names in inconsistent spellings. The validation gate must reject numeric VÖENs and unmapped client names before serialization.

#### Validation Gate Specification

```markdown
### Boundary Validation Rules

Rule V1 — VÖEN typing (BLOCKING)
  - Reject if client_tax_id_voen is not a JSON string.
  - Reject if it does not match ^\d{10}$.
  - Rationale: numeric 0123456789 serializes as 123456789 (leading zero lost);
    long IDs exceed float53 precision. Opaque token → string only.

Rule V2 — Client-name mapping (BLOCKING)
  - Resolve raw_data.client_name against the client registry (name → canonical_entity → voen).
  - Reject if no canonical match is found (no silent pass-through).
  - Reject if the registry's VÖEN for the matched entity != client_tax_id_voen (cross-check).
```

```json
// REJECTED — numeric VÖEN, leading zero already destroyed upstream
{ "client_name": "Acme LLC", "client_tax_id_voen": 123456789 }

// REJECTED — client_name resolves to no registry entity
{ "client_name": "Akme L.L.C.", "client_tax_id_voen": "0123456789" }

// ACCEPTED — string VÖEN, name maps to canonical entity, VÖENs cross-check
{ "client_name": "Acme LLC", "client_tax_id_voen": "0123456789" }
```

*Rule:* validation runs at the outer boundary. Anything that fails V1 or V2 is routed to a correction queue, never serialized into a report contract.
