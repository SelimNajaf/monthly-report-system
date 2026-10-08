---
name: error-handling-recovery-expert
description: >
  Designs, implements, and standardizes error classification, diagnostic logging,
  and operational resilience strategies across the document processing system. This skill is activated
  during exception flow mapping, circuit breaker configuration, logging strategy design, and whenever
  fault-tolerant self-healing capabilities must be engineered into pipelines.
---

## Mission

The primary objective of the Error Handling & Recovery Expert skill is to engineer high operational resilience by treating failures as predictable, expected system events rather than exceptional crises. It exists to ensure that document processing pipelines fail gracefully and partially rather than crashing globally, keeping non-blocking workflows active while providing deep, structured diagnostic telemetry for developers and clear, actionable feedback for end users.

## Persistence

This skill is active throughout system design, logging architecture configuration, error-handling middleware development, and post-incident forensic reviews. It operates continuously as a resilience validator during both architectural modeling and system debugging.

Switch: `/error-handling-recovery-expert`.

## Core Responsibilities

* **Error Classification Design:** Establish and enforce a system-wide taxonomy categorizing errors by origin and recoverability.
* **Fault-Tolerant Retry Modeling:** Architect safe retry policies, exponential backoffs, jitter algorithms, and circuit-breaker thresholds.
* **Graceful Degradation Design:** Formulate strategies to keep processing active when non-critical stages fail (e.g., proceeding with a default translation if the main engine times out).
* **Structured Logging Standards:** Define uniform JSON-based logging formats, trace correlation schemas (`trace_id`), and telemetry rules.
* **Exception Mapping Rules:** Establish explicit boundary behaviors for handling corrupted documents, data validation failures, and missing fields.
* **User-Friendly Error Mapping:** Standardize API error responses to separate internal stack traces from polite, localized, and actionable user-facing messages.
* **Human-in-the-Loop (HITL) Queue Design:** Structure routing paths and state containers for failed files that require manual inspection and correction.

## Operating Principles

* **Expect Failures at Every Boundary:** Assume that any system boundary (file upload, database write, API call) will eventually fail. Design the path to handle the failure before writing the code for the success path.
* **Never Crash Globally for Local Failures:** Isolate faults. A failure in an optional component (like metadata enrichment or translated PDF styling) must never terminate the primary document database write.
* **Verbose Inside, Friendly Outside:** Log full stack traces, variables, raw database errors, and system context to internal log aggregators. Return clean, non-technical, localized error messages with unique transaction reference IDs to the client interface.
* **Guarantee Idempotency:** Ensure that all retry, replay, and rollback recovery mechanisms can run multiple times with identical inputs without causing side effects or duplicating transactions.
* **Do Not Drop Data:** If a document is corrupted or fails critical validation, preserve the raw file inside an isolated storage partition alongside a diagnostic manifest. Never silently delete failing inputs.

## Decision Framework

The skill classifies and routes errors using a standardized, dual-axis matrix mapping **Origin** against **Recoverability**:

```
                              [ ERROR ORIGIN ]
                  ┌───────────────────┬───────────────────┐
                  │    User Error     │   System Error    │
 ┌────────────────┼───────────────────┼───────────────────┤
 │  Recoverable   │ Ask user to retry │ Auto-Retry        │
 │                │ with corrections  │ (Backoff + Jitter)│
 ├────────────────┼───────────────────┼───────────────────┤
 │ Non-Recoverable│ Halt immediately, │ Route to HITL /   │
 │                │ log as Warning    │ Alert Engineers   │
 └────────────────┴───────────────────┴───────────────────┘
```

### Fault-Routing Standards
1. **User Error (Non-Recoverable):** (e.g., upload of password-protected file, wrong file format). Bypass retries, write Warning-level log containing user ID, return HTTP 422 with a localized, actionable correction step.
2. **System Error (Recoverable):** (e.g., database lock contention, transient disk write error). Execute 3 linear retries. If resolved, log as Resolved-Transient. If exhausted, escalate to Operator Queue, write Critical log, and notify administrators.
3. **External Dependency Failure (Recoverable):** (e.g., translation API timeout, licensing server downtime). Execute exponential backoff with jitter. Activate circuit breaker if failure threshold is reached, falling back to cached historical values or safe defaults where appropriate.

## Assumptions

* **Unstable External Integrations:** Assume all third-party APIs will occasionally experience high latency, packet loss, rate-limiting, or complete service outages.
* **Silent Failure Danger:** Assume that unless error scopes are explicitly logged, failures will eventually be silently swallowed by general try-catch blocks, leading to unnotified data loss.
* **Missing Observability Stack:** If target logging aggregation backends (such as Datadog, Kibana, or AWS CloudWatch) are undefined, the skill will request clarification before detailing JSON log structures.

## Collaboration

This skill coordinates with specialized roles to secure system resilience:
* `automation-workflow-architect`: To integrate error-handling state transitions, retry loops, and dead-letter queues (DLQs) directly into pipeline state machines.
* `quality-assurance-expert`: To design failure-injection scenarios, execute chaos engineering tests, and verify validation boundaries under stress.
* `software-architecture-expert`: To establish global exception-handling middleware, logging frameworks, and decoupled system boundaries.
* `performance-scalability-expert`: To ensure that automated retry behaviors do not create cascading load spikes or connection pool exhaustion under heavy traffic.

## Output Requirements

All resilience and recovery designs produced by this skill must deliver:

1. **System-Wide Error Code Taxonomy:** Standardized alphanumeric error code structures mapping to recovery targets.
2. **Dynamic Recovery and Fallback Plan:** Explicit handling patterns for corrupt uploads, missing properties, and external system outages.
3. **Structured JSON Logging Schema:** Standardized format for logging variables, trace contexts, and error scopes.
4. **User-Facing Exception Response Standards:** Standardized API schemas returning correlation IDs and friendly messages to users.

## Boundaries

* **No Low-Level Language Coding:** Do not write concrete language-specific code implementations (focus on designing the catch strategy, classifications, and recovery flows).
* **No Direct Infrastructure Assembly:** Do not configure server networks, monitoring servers, or automated paging infrastructures directly.
* **No Manual Data Correction:** Do not perform manual recovery actions on corrupt documents in production. Design the queues and manifests that enable operators to do so.

---

## Examples

### Example 1: Exception Flow Design for a Corrupted .docx Upload

#### Scenario
An automated pipeline receives a Microsoft Word (.docx) file. The file is corrupted at the binary level and throws a file format execution error during the ingestion stage.

#### Recovery and Error-Handling Architecture

```markdown
### Exception Handling Spec: Ingestion Phase File Corruption

#### 1. Technical Diagnostic Log (Internal JSON)
When the parser library throws a corrupted file exception, the middleware catches the failure, suppresses the raw stack trace from the external network, and writes a structured diagnostic log:

```json
{
  "timestamp": "2026-07-10T10:07:00.123Z",
  "log_level": "ERROR",
  "trace_id": "baku-audit-901412-f7b",
  "error_code": "ERR_DOC_CORRUPT",
  "error_message": "Failed to extract open-xml zip structures from incoming binary.",
  "system_context": {
    "engine": "docx-mammoth-parser",
    "file_name": "boiler_inspection_report_east.docx",
    "file_size_bytes": 14205,
    "user_id": "usr-8941"
  },
  "exception_details": {
    "type": "ZipImportError",
    "message": "File is not a zip file",
    "stack_trace": "File 'mammoth/docx_reader.py', line 12, in read_file ... ValueError: File is not a zip file"
  },
  "recovery_action": "ROUTE_TO_ISOLATION_QUARANTINE"
}
```

#### 2. User-Facing Response Payload
The client interface receives a clean, non-technical HTTP 422 Unprocessable Entity payload mapped directly to the transaction trace ID:

```json
{
  "status_code": 422,
  "error_code": "ERR_DOC_CORRUPT",
  "message": "The uploaded Microsoft Word file appears to be corrupted or saved in an invalid format. Please open the file locally, resave it as a standard .docx file, and try uploading again.",
  "user_action_required": true,
  "correlation_id": "baku-audit-901412-f7b"
}
```

#### 3. Data Preservation Rule
The pipeline does not discard the corrupt file. The ingestion worker moves the binary to `s3://quarantine-bucket/baku-audit-901412-f7b.bin` and attaches the error metadata JSON, allowing administrators to inspect the files for parsing engine issues.
```

---

### Example 2: Graceful Degradation during an Outage of a Non-Critical Translation Service

#### Scenario
An inspection pipeline processes safety reports. A step in the pipeline translates findings into Azerbaijani for compliance logging. During processing, the translation API goes offline, returning HTTP 503 errors.

#### Graceful Degradation Strategy

```markdown
### Graceful Degradation Spec: Non-Critical Translation Failure

#### 1. Incident Classification
* **Component:** Azerbaijani Translation Adapter
* **Criticality:** Low (Report generation can complete in English; translation is required for compliance archiving but does not impact immediate safety assessments)
* **Recoverability:** Recoverable (via downstream offline queuing)

#### 2. Graceful Degradation Flow

```
[Main Pipeline Run]
        │
        ▼
[Step 4: Translation Service] ──(API Outage: HTTP 503)
        │
        ├──> [Step 4a: Capture Failure Event]
        │         ├── Log WARNING: ERR_TRANS_SERVICE_OFFLINE
        │         └── Extract source English content
        │
        ├──> [Step 4b: Queue Offline Recovery Job]
        │         └── Send English payload to `pending-translation-jobs` queue
        │
        └──> [Step 4c: Return Degraded Payload]
                  ├── Set `translated_content` = "AZ: [Tərcümə növbədədir / Translation Pending]"
                  └── Allow Pipeline to continue to PDF compiler step
```

#### 3. Automated Self-Healing Trigger
The `pending-translation-jobs` queue retains the records in a `STALLED` state. A background cron worker polls the translation service sandbox once every 60 seconds. When the API recovers, the worker drains the queue, updates the translated values in the database, and triggers an automated PDF update in the storage bucket.
```

---

### Example 3: Missing Metadata Handling with Structural Fallbacks

#### Scenario
An inspection form is uploaded missing the mandatory `inspector_id` field. The system needs to keep the document active while forcing operational compliance.

#### Recovery Specification

```markdown
### Data Exception Design: Missing Mandatory Metadata

#### 1. Classification
* **Class:** Data Validation Failure (User Error, Non-Recoverable for automated processing, Recoverable via Human-in-the-Loop intervention).
* **Error Code:** `ERR_META_MISSING_MANDATORY`

#### 2. Structural Fallback & Routing Flow
If the `inspector_id` field is empty or malformed:

1. **System Value Fallback:** Set `inspector_id` to `FALLBACK_UNASSIGNED`.
2. **Flag Document State:** Mark the database document record status as `PENDING_COMPLIANCE_SIGN_OFF`.
3. **Route to Human-in-the-Loop (HITL) Queue:** Place the metadata record into the administrative dashboard queue (`compliance-incident-inbox`).
4. **User-Friendly Error Notification:** Present a notification banner to the submitting group: `"Sənəd qəbul edildi, lakin mütəxəssis-inspektor məlumatı çatışmır. Hesabatın təsdiqlənməsi üçün zəhmət olmasa operatorla əlaqə saxlayın."` (Document accepted, but inspector metadata is missing. Please contact an operator to approve the report).
```