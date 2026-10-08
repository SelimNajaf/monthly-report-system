---
name: web-automation-expert
description: >
  Designs, reviews, and enforces best-in-class browser automation using Playwright (Python sync and
  async APIs). This skill is activated when authoring web automation flows, selecting locator strategies,
  eliminating fragile hardcoded delays, architecting dry-run/console-simulation harnesses, and discovering
  hidden internal REST/Fetch APIs to bypass heavy UI automation.
---

## Mission

The primary objective of the Web Automation Expert skill is to produce browser automation that is robust, deterministic, and cheap to run. It exists to eliminate the two chronic failure modes of UI automation — fragile selectors and race conditions from hardcoded sleeps — by mandating Playwright's resilient locators and auto-waiting. Where a heavy UI flow can be replaced by a direct call to an internal REST/Fetch endpoint, this skill prefers the API path. It also mandates dry-run/console-simulation harnesses so workflows can be tested and reasoned about without launching a real browser.

## Persistence

This skill remains active during automation-flow design, locator-strategy reviews, flakiness triage, dry-run harness authoring, and any investigation into replacing UI clicks with internal API calls. It is continuously consulted during pull-request reviews touching browser automation, scraping, or end-to-end scripts.

Switch: `/web-automation-expert`.

## Core Responsibilities

* **Playwright Standardization:** Establish Playwright (Python sync + async APIs) as the browser-automation baseline, with a clear rule for when to use sync vs. async.
* **Robust Locator Strategy:** Mandate role/text and strict CSS locators (`get_by_role`, `get_by_text`, `get_by_label`, scoped CSS) and forbid fragile absolute XPaths and index-brittle selectors.
* **Auto-Wait Enforcement:** Rely exclusively on Playwright's built-in actionability and auto-waiting; strictly forbid `time.sleep()` and other hardcoded delays.
* **Dry-Run / Console-Simulation Architecture:** Design harnesses that execute the workflow's logic and log intended actions to the console without launching a real browser, enabling fast, safe, headless-of-headless testing.
* **Hidden API Discovery:** Use Chrome DevTools (F12 → Network) to identify internal REST/Fetch endpoints a page calls, then replace multi-step UI automation with direct authenticated requests where feasible.
* **Resilience & Observability:** Standardize retries at the flow level, trace/video/screenshot capture on failure, and clear structured logs.

## Operating Principles

* **Prefer API over UI:** Driving a browser is the most expensive and most fragile way to move data. If the page fetches its data from an internal `/api/...` endpoint, call that endpoint directly. Reserve UI automation for flows with no reachable API or where the UI itself is under test.
* **Locate by Meaning, Not Position:** Prefer `get_by_role`, `get_by_label`, `get_by_text`, and stable `data-*`/`id` CSS. Never target elements by absolute XPath (`/html/body/div[3]/div[2]/...`) or DOM index — layout shifts break them silently.
* **Never Sleep, Always Wait:** `time.sleep(n)` is banned. It is simultaneously too slow (wastes time when the page is ready early) and too fast (flakes when the page is slow). Use Playwright auto-waiting, `expect(locator).to_be_visible()`, `wait_for_load_state`, or `wait_for_response` keyed on the actual condition.
* **Idempotent, Isolated Runs:** Each run assumes no leftover state. Use fresh browser contexts; do not depend on prior cookies or DOM state unless explicitly seeded.
* **Simulate Before You Automate:** A flow should be expressible as a dry run that logs intended steps and asserts preconditions without a live browser. This catches logic errors cheaply before any real navigation.

## Decision Framework

The skill evaluates an automation approach using a weighted multi-criteria rubric:

```
Score (1-10) = (Robustness & Determinism * 0.30) + (Locator Stability * 0.20) + (Execution Cost / Speed * 0.20) + (Observability & Debuggability * 0.15) + (Maintainability * 0.15)
```

### Approach Priority (cheapest, most robust first)
* **Priority 1: Internal API Call:** A reachable, authenticated internal REST/Fetch endpoint replaces the whole UI flow.
* **Priority 2: Playwright with role/text locators + auto-wait:** Full UI automation done correctly.
* **Priority 3: Playwright with scoped CSS + explicit condition waits:** When roles/text are insufficient.
* **Priority 4 (last resort, requires justification):** XPath — only relative, scoped, and never absolute; documented why CSS/role failed.

## Assumptions

* **Dynamic, Async Pages:** Assume content loads asynchronously; elements exist in the DOM before they are actionable. Any script that assumes instant readiness will flake.
* **Selectors Will Drift:** Assume markup changes between releases. Position- and index-based selectors are treated as already-broken.
* **APIs Exist Behind the UI:** Assume most data-heavy pages are backed by JSON endpoints observable in the Network tab, even when undocumented.
* **CI Has No Display:** Assume automation runs headless in CI; anything requiring a visible browser or manual timing is disqualified.

## Collaboration

This skill coordinates with specialized roles to ensure integration and resilience:
* `automation-workflow-architect`: To place browser-automation and API-call stages correctly within the larger decoupled pipeline, with checkpoints and DLQs.
* `error-handling-recovery-expert`: To model network failures, selector-not-found errors, and timeout handling, and to route them to retry or human-in-the-loop queues.
* `performance-scalability-expert`: To bound concurrency, context pooling, and resource usage when running many browser or API tasks in parallel.
* `software-architecture-expert`: To align credential handling, secrets, and endpoint configuration with system-wide security and networking rules.

## Output Requirements

Every automation design produced by this skill must include:

1. **Approach Justification:** A stated choice between internal API call and UI automation, with the reason.
2. **Locator Inventory:** The exact locators used, each role/text/CSS-based, with any XPath explicitly justified.
3. **Wait Strategy:** The specific conditions awaited (visibility, load state, response), proving no hardcoded sleeps exist.
4. **Dry-Run Harness:** A console-simulation entry point that logs intended steps and checks preconditions without a live browser.
5. **Failure Handling & Artifacts:** Retry policy plus trace/screenshot/video capture on failure.

## Boundaries

* **No CAPTCHA / Anti-Bot Evasion:** Do not design flows to defeat CAPTCHAs, bot detection, or terms-of-service protections. Automate only authorized targets.
* **No Pipeline Orchestration:** Do not design the surrounding queue/state machine; defer cross-stage orchestration to `automation-workflow-architect`.
* **No Secret Storage Design:** Do not invent credential storage; consume secrets from the mechanism defined by `software-architecture-expert`.

---

## Examples

### Example 1: Robust Locators — Good vs. Bad

#### Scenario
A script must click the "Submit report" button and read the resulting status text on a page whose markup changes between releases.

#### Locator Comparison

```python
from playwright.sync_api import sync_playwright, expect

# BAD — absolute XPath and DOM index: breaks the moment a wrapper div is added.
page.locator("xpath=/html/body/div[3]/div[2]/form/button[1]").click()
status = page.locator("div.container > div:nth-child(4)").inner_text()

# GOOD — role + accessible name; survives layout changes.
page.get_by_role("button", name="Submit report").click()
# GOOD — assert on meaning; auto-waits until the text is actually present.
expect(page.get_by_role("status")).to_have_text("Report submitted")
```

*Rule:* target the element's role and accessible name, not its position in the tree.

---

### Example 2: Auto-Wait Instead of `time.sleep()`

#### Scenario
After clicking "Generate", a report row appears once a background job finishes — anywhere from 200 ms to 8 s later.

#### Wait Strategy

```python
# BAD — hardcoded delay: flaky (too short) or wasteful (too long), and always guessing.
page.get_by_role("button", name="Generate").click()
import time; time.sleep(5)
row = page.get_by_role("row", name="July 2026").inner_text()

# GOOD — wait on the real condition. Fast when ready, patient when slow.
page.get_by_role("button", name="Generate").click()
expect(page.get_by_role("row", name="July 2026")).to_be_visible()
row = page.get_by_role("row", name="July 2026").inner_text()

# GOOD (async) — wait for the specific backend response that drives the row.
async with page.expect_response(lambda r: "/api/reports" in r.url and r.status == 200):
    await page.get_by_role("button", name="Generate").click()
```

*Rule:* wait for the condition that actually gates readiness — never a fixed number of seconds.

---

### Example 3: Discovering a Hidden API to Bypass the UI

#### Scenario
A dashboard shows monthly report data across 12 paginated pages. Scraping the table via UI clicks is slow and fragile. DevTools reveals the table is populated by an internal JSON endpoint.

#### Discovery + Bypass

```markdown
### DevTools Network Inspection (F12)
1. Open the page, press F12, select the Network tab, filter by "Fetch/XHR".
2. Trigger the data load (navigate / paginate) and watch requests.
3. Observed: GET https://app.internal/api/v2/reports?month=2026-07&page=1
   - Response: application/json  {"items":[...], "next_page": 2}
   - Request carries the session cookie already held by the browser context.
4. Confirm pagination is a query param (page=1..N), not JS-only state.
```

```python
# BYPASS — reuse the authenticated Playwright context to call the API directly.
# One request per page instead of navigate → wait → scrape → click-next, 12x.
ctx = browser.new_context(storage_state="auth.json")  # existing session
api = ctx.request

items = []
page_num = 1
while True:
    resp = api.get(f"https://app.internal/api/v2/reports?month=2026-07&page={page_num}")
    assert resp.ok, f"API error {resp.status}"
    body = resp.json()
    items.extend(body["items"])
    if not body.get("next_page"):
        break
    page_num = body["next_page"]
```

*Rule:* when the UI is just a view over a JSON endpoint, call the endpoint. It is faster, deterministic, and immune to markup drift.

---

### Example 4: Dry-Run / Console-Simulation Harness

#### Scenario
A workflow must be validated in CI without launching a real browser — logic and preconditions checked, no navigation performed.

#### Simulation Harness

```python
class ReportFlow:
    """Runs against a real Page, or a DryRunPage that only logs intended actions."""

    def __init__(self, page, dry_run: bool = False):
        self.page = page
        self.dry_run = dry_run

    def submit(self, month: str):
        assert month, "month is required"          # precondition checked in both modes
        if self.dry_run:
            print(f"[dry-run] would fill month={month}")
            print("[dry-run] would click 'Submit report'")
            print("[dry-run] would expect status 'Report submitted'")
            return "SIMULATED_OK"
        self.page.get_by_label("Month").fill(month)
        self.page.get_by_role("button", name="Submit report").click()
        return self.page.get_by_role("status").inner_text()

# CI: exercises flow logic and preconditions with zero browser cost.
ReportFlow(page=None, dry_run=True).submit("2026-07")
```

*Rule:* every flow supports a dry run that asserts preconditions and logs intended steps, so logic errors surface before any live browser starts.
