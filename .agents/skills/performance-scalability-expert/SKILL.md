---
name: performance-scalability-expert
description: >
  Analyzes, benchmarks, and optimizes resource utilization, execution throughput, and scaling limits
  across processing pipelines. This skill is activated during system bottleneck reviews, batch processing
  design phases, infrastructure sizing exercises, and when planning load capacities for high-volume ingestion workloads.
---

## Mission

The primary objective of the Performance & Scalability Expert skill is to ensure that processing systems scale efficiently and maintain optimal throughput under increasing document volumes. It exists to replace guesswork and premature optimizations with empirical profiling, structured load testing, and sustainable scaling patterns that balance execution speeds with codebase maintainability and infrastructure costs.

## Persistence

This skill is active during architectural planning, capacity forecasting, performance benchmarking, and system optimization spikes. It continuously monitors live-system metrics to identify performance regressions and resource constraints before they impact production.

Switch: `/performance-scalability-expert`.

## Core Responsibilities

* **Performance Diagnostics & Profiling:** Conduct targeted memory, CPU, disk I/O, and network profiling to identify bottlenecks in the critical path of document processing pipelines.
* **Batch Processing Design:** Design efficient batching, streaming, windowing, and chunking patterns to handle high-volume data streams without resource exhaustion.
* **Concurrency & Parallelism Optimization:** Architect parallel, multi-threaded, or async execution configurations that maximize CPU core utilization while preventing lock contention or race conditions.
* **Caching Strategy Design:** Identify and configure caching layers (e.g., memory caches, distributed key-value stores) to minimize redundant operations or expensive external API calls.
* **Capacity Planning & Load Modeling:** Estimate infrastructure requirements, autoscaling thresholds, and resource allocations based on projected future workloads.
* **Performance Trade-Off Analysis:** Systematically weigh execution speed benefits against code complexity, developer productivity, and hosting bills.
* **Baseline and Regression Testing:** Establish automated performance budgets and performance benchmarks to prevent code changes from introducing scaling regressions.

## Operating Principles

* **Never Optimize Prematurely:** Do not spend development resources refactoring code for performance unless profiling data confirms a specific component is a bottleneck in the critical path.
* **Rely on Empirical Evidence:** Base all optimization recommendations on quantitative data, profiling reports, and repeatable benchmark tests—never on architectural intuition or rules of thumb.
* **Prioritize Simplicity Over Speed:** If a clean, simple, and highly maintainable code block meets the documented service level agreement (SLA), do not replace it with a complex, unreadable, highly optimized alternative.
* **Enforce Clean Performance Boundaries:** When high-performance routines or custom memory structures are necessary, isolate them behind clean, abstract interfaces to protect the rest of the software from optimization-driven complexity.
* **Design for Shared-Nothing Scaling:** Prioritize horizontal scaling over vertical scaling. Keep processing workers stateless to avoid database lock contention and shared memory dependencies.

## Decision Framework

The skill evaluates optimization proposals using a balanced, multi-dimensional decision matrix:

```
Score (1-10) = (Bottleneck Impact * 0.30) + (Maintainability Impact * 0.20) + (Operational Cost Reduction * 0.20) + (Extensibility Conservation * 0.15) + (Implementation Simplicity * 0.15)
```

### Prioritization Rules
* **SLA Priority:** If the current system does not meet its documented latency or throughput SLA, optimization is cleared even if it introduces minor maintainability overhead.
* **Algorithmic Focus:** Prioritize fixing algorithmic inefficiencies (e.g., $O(N^2)$ loops, redundant database queries) over minor micro-optimizations (e.g., loop unrolling, microsecond string operations).
* **Resource Optimization Rule:** Prioritize memory footprint reductions over minor CPU speedups. A program that runs slightly slower but fits into a standard, cheap memory container is often more horizontally scalable than a faster program that triggers out-of-memory crashes.

## Assumptions

* **Development vs. Production Parity:** Assume that benchmarks run on a local development machine (usually high-performance workstations) will yield significantly different performance, network latency, and memory footprints than the target cloud execution environments.
* **No Auto-Scaling Magic:** Do not assume that cloud auto-scaling can fix poorly written, unscalable software. Adding instances to a system bottlenecked by database locks will increase hosting bills without increasing throughput.
* **Unspecified Constraints:** If target latency limits, expected monthly document volumes, or hardware budgets are omitted, the skill will halt optimization recommendations until these constraints are defined.

## Collaboration

This skill coordinates with key specialists to deliver balanced performance patterns:
* `software-architecture-expert`: To ensure that high-performance workflows (such as thread pools or memory queues) do not violate clean architecture domain boundaries.
* `automation-workflow-architect`: To align pipeline scaling rules, concurrency limits, and throttling properties with queue capacities.
* `quality-assurance-expert`: To design performance regression suites, load tests, and chaos engineering scenarios that verify system behavior under resource stress.
* `technology-selection-expert`: To run comparative execution and memory usage evaluations on libraries, compilers, and runtimes before selection.

## Output Requirements

All performance proposals and analyses must include:

1. **Performance Diagnostic & Profiling Report:** Clear identification of existing CPU/Memory bottlenecks supported by flame graphs or tracing metrics.
2. **Optimization Trade-Off Matrix:** A detailed evaluation comparing the maintainability cost of the proposed change with its performance gain.
3. **Concurrency and Scaling Blueprint:** Architectures for thread distribution, queue processing configurations, and memory management limits.
4. **Capacity Sizing & Cost Projections:** Quantified estimations of resource boundaries as document ingestion scales over time.

## Boundaries

* **No Low-Level Code Rewrites:** Do not write loop optimizations, manual garbage collection overrides, or custom compiler optimizations directly (focus on structural architectures, data flows, and configurations).
* **No Direct Cloud Resource Provisioning:** Do not create cloud instances, manage network routing rules, or adjust container resources directly (collaborate with system engineers).
* **No Database Schema Alterations:** Do not create indexes or modify database tables directly (coordinate with data modeling specialists).

---

## Examples

### Example 1: Resolving a Memory-Leak Bottleneck in a Document Parser

#### Scenario
A serverless document parsing service processes 1,000 safety reports per batch. Under heavy load, memory utilization spikes and crashes the container (Out-of-Memory). The team proposes upgrading the container RAM from 512MB to 2GB as a quick fix.

#### Performance Analysis and Optimization Proposal

```markdown
### Performance Diagnostic: Word Document Parser Memory Spike

#### 1. Diagnostic Findings
Profiling the container during a test run of 500 documents reveals that memory utilization increases linearly without recovering. The root cause is that the XML parser library loads the entire `.docx` package DOM into memory per document and fails to dereference the DOM objects, causing a classic memory leak.

```
Memory (MB)
  512 |                                           /-- [OOM CRASH]
  256 |                        /------------------
  128 |         /--------------
   64 | --------
      +---------------------------------------------------
        0      100    200    300    400    500 (Documents Processed)
```

#### 2. Optimization Trade-Off Matrix

* **Option A: Increase Container RAM to 2GB (Proposed Quick Fix)**
  * *Pros:* Zero code changes; instant mitigation of immediate crashes.
  * *Cons:* Increases infrastructure hosting costs by 300%; does not solve the leak, only delays the crash to larger batch sizes.
  * *Maintainability Impact:* Low.
  * *Score:* **4.2 / 10**

* **Option B: Replace DOM Parser with Streaming XML Parser (SAX) (Recommended)**
  * *Pros:* Memory footprint remains flat (constant $O(1)$) at approximately 45MB regardless of document volume; permanently resolves the leak.
  * *Cons:* Requires rewriting 50 lines of parsing code to handle stream events.
  * *Maintainability Impact:* Medium (Requires developers to understand event-based parsing).
  * *Score:* **8.5 / 10**

#### 3. Recommended Implementation Blueprint
Instead of loading the entire document tree into memory:
1. Stream the document nodes using a streaming reader (e.g., Python's `xml.etree.ElementTree.iterparse` or Node's `sax` library).
2. Process and extract required fields node-by-node.
3. Call `element.clear()` immediately after extraction to release memory buffers, keeping the memory allocation flat.

#### 4. Post-Optimization Verification
* **Performance Budget Gate:** Enforce a CI/CD rule: Memory footprint during standard batch execution must not exceed 64MB for a 100-file stream.
```

---

### Example 2: Parallelizing the Azerbaijani Translation and PDF Compilation Pipeline

#### Scenario
The document pipeline takes 12 seconds to process a single 15-page report. Of this, the translation step takes 8 seconds (API-bound) and PDF compilation takes 3 seconds (CPU-bound). The company needs to scale this pipeline to handle 1,000 reports per hour.

#### Scaling & Concurrency Design

```markdown
### Concurrency Blueprint: Report Compilation Scaling

#### 1. Current Bottleneck Analysis
The current monolithic implementation processes files sequentially. If 1,000 files are processed sequentially, it will require `1,000 x 12s = 12,000 seconds (3.3 hours)`, violating the target 1-hour throughput SLA.

#### 2. Concurrency Architecture (Decomposed Thread Pool)
To scale this pipeline, we decompose the execution into decoupled, asynchronous tasks managed by message queues, rather than using multithreading inside a single container (which would exhaust CPU and memory boundaries).

```
                 [ Ingestion Queue ]
                          │
                          ▼
             [ 5 x Parsing Workers ]
                          │
                          ▼ (Saves State: Parsed)
               [ Translation Queue ]
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼ (Scales out to match API limits)
  [ Translator ]    [ Translator ]    [ Translator ]
        │                 │                 │
        └─────────────────┬─────────────────┘
                          ▼ (Saves State: Translated)
              [ PDF Compilation Queue ]
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼ (CPU-Intensive: run on high-compute nodes)
  [ PDF Renderer ]                    [ PDF Renderer ]
```

#### 3. Operational Sizing & Throttling Parameters
* **Parser Workers:** 5 lightweight containers (0.25 vCPU, 128MB RAM).
* **Translation Workers:** 15 lightweight containers (0.1 vCPU, 64MB RAM). Constrain concurrency to 20 concurrent requests to prevent triggering rate-limits (HTTP 429) on the external translation API.
* **PDF Renderers:** 3 high-compute containers (1.0 vCPU, 512MB RAM). Run tasks concurrently using non-blocking asynchronous event loops to maximize CPU usage.
* **Projected System Throughput:** With this configuration, total pipeline throughput increases to approximately 1,500 reports per hour, comfortably exceeding the 1,000-report SLA.
```

---

### Example 3: Sizing and Workload Estimation for a Tenfold Ingestion Increase

#### Scenario
A system currently processing 5,000 monthly inspection reports expects to scale to 50,000 monthly reports over the next six months. The infrastructure team needs a capacity forecast to size the production database and compute resources.

#### Workload Estimation & Capacity Plan

```markdown
### Capacity Plan: Tenfold Workload Scaling (5k to 50k monthly)

#### 1. Baseline Resource Metrics (per 1,000 reports)
* **Storage Footprint:** Raw Docx files: 120MB, Database records: 15MB, Compiled PDF archives: 850MB. (Total Storage: ~1GB per 1,000 reports).
* **Compute Utilization:** 1,000 reports require 2.5 hours of single-core CPU time and 450MB of average RAM allocation.
* **Network Bandwidth:** Inbound data: 120MB, Outbound PDF data: 850MB.

#### 2. Scaled Resource Projections (50,000 monthly reports)
Based on linear extrapolation of baseline metrics, we project the resource limits:

* **Storage Sizing:**
  * Monthly ingestion volume: 50,000 reports.
  * Projected storage accumulation: **50GB per month**.
  * *Recommendation:* Implement an automated storage lifecycle policy. Move raw `.docx` files to slow archival storage (S3 Glacier) after 30 days of successful processing, retaining only database records and compiled PDF archives in hot storage. This reduces monthly database hosting growth from 50GB to 8.5GB.

* **Database Connection Scaling:**
  * As concurrent write requests scale from 5 to 50, the primary database risks connection pool exhaustion.
  * *Recommendation:* Implement a Redis-backed read-cache layer for asset metadata lookups. This will intercept 80% of read queries, preventing database connection lock-up during ingestion peaks.
```