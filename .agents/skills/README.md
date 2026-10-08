# Skills Registry

Active inventory of specialized Agentic Skills imported into this project.
Each skill lives in its own subfolder under `.agents/skills/` as a single `SKILL.md`
containing the full, unmodified source definition.

- **Active skills:** 17
- **Source:** `all-random-skills/` (originals left untouched)
- **Import date:** 2026-07-10

## Imported skills

| # | Official name | Folder | Summary |
|---|---------------|--------|---------|
| 1 | document-analysis-expert | [`document-analysis-expert/`](document-analysis-expert/SKILL.md) | Specializes in analyzing and understanding the semantic and structural layout of Microsoft Word (.docx) inspection reports before extraction logic is designed or implemented. |
| 2 | information-extraction-architect | [`information-extraction-architect/`](information-extraction-architect/SKILL.md) | Designs, maintains, and refines resilient data extraction architectures for processing unstructured and semi-structured documents. |
| 3 | translation-terminology-expert | [`translation-terminology-expert/`](translation-terminology-expert/SKILL.md) | Establishes, maintains, and enforces a professional English-to-Azerbaijani terminology system for official inspection reports. |
| 4 | official-report-template-expert | [`official-report-template-expert/`](official-report-template-expert/SKILL.md) | Designs, structures, and maintains stable, professional official report templates optimized for automated document generation. |
| 5 | pdf-generation-expert | [`pdf-generation-expert/`](pdf-generation-expert/SKILL.md) | Evaluates, designs, and optimizes PDF generation architectures for enterprise report rendering. |
| 6 | technology-selection-expert | [`technology-selection-expert/`](technology-selection-expert/SKILL.md) | Evaluates and selects languages, frameworks, libraries, and architectural components based strictly on technical merit, operational requirements, and long-term maintenance costs. |
| 7 | automation-workflow-architect | [`automation-workflow-architect/`](automation-workflow-architect/SKILL.md) | Designs, orchestrates, and refines distributed document automation pipelines. |
| 8 | software-architecture-expert | [`software-architecture-expert/`](software-architecture-expert/SKILL.md) | Architects, structures, and governs the overall software design and structural patterns of the project. |
| 9 | data-modeling-expert | [`data-modeling-expert/`](data-modeling-expert/SKILL.md) | Designs, standardizes, and maintains structured data schemas, configurations, and internal models across the enterprise ecosystem. |
| 10 | quality-assurance-expert | [`quality-assurance-expert/`](quality-assurance-expert/SKILL.md) | Reviews system specifications, architectural designs, data contracts, and workflows prior to implementation from a rigorous quality, safety, and reliability perspective. |
| 11 | error-handling-recovery-expert | [`error-handling-recovery-expert/`](error-handling-recovery-expert/SKILL.md) | Designs, implements, and standardizes error classification, diagnostic logging, and operational resilience strategies across the document processing system. |
| 12 | performance-scalability-expert | [`performance-scalability-expert/`](performance-scalability-expert/SKILL.md) | Analyzes, benchmarks, and optimizes resource utilization, execution throughput, and scaling limits across processing pipelines. |
| 13 | research-best-practices-expert | [`research-best-practices-expert/`](research-best-practices-expert/SKILL.md) | Conducts deep technical research, literature reviews, and industry standard audits prior to architectural or implementation decisions. |
| 14 | caveman | [`caveman/`](caveman/SKILL.md) | Ultra-compressed communication mode that cuts output tokens while preserving full technical accuracy. |
| 15 | find-skills | [`find-skills/`](find-skills/SKILL.md) | Helps users discover and install agent skills from the open agent-skills ecosystem. |
| 16 | json-data-contract-expert | [`json-data-contract-expert/`](json-data-contract-expert/SKILL.md) | Defines and enforces machine-readable JSON data contracts that decouple the raw data payload from PDF rendering, with metadata fallback chains and strict string-typing of identifiers such as Tax IDs and VÖENs. |
| 17 | web-automation-expert | [`web-automation-expert/`](web-automation-expert/SKILL.md) | Enforces robust Playwright-based browser automation with resilient locators and auto-waiting, dry-run console simulation, and hidden internal REST/Fetch API discovery to bypass fragile UI flows. |

## Notes

- **17 active skills** — 13 imported from `all-random-skills/` (s1–s14, deduplicated), the two pre-existing workspace skills `caveman/` and `find-skills/`, plus two newly authored skills `json-data-contract-expert/` and `web-automation-expert/`. The table matches the directories under `.agents/skills/` one-to-one.
- **Deduplicated source:** `s5.md` and `s6.md` both declared `name: pdf-generation-expert` and were byte-identical, so they collapse to a single `pdf-generation-expert/` skill.
- **Content integrity:** every imported `SKILL.md` is a byte-for-byte copy of its source file (verified via SHA-256).
- **Dynamic invocation:** any skill is loaded by typing `/skill-name` in a prompt (resolves to `.agents/skills/<skill-name>/SKILL.md`).

## Manifest

> Merged from `SKILLS_MANIFEST.md` on 2026-09-28; the original is kept unchanged at
> `docs/history/SKILLS_MANIFEST.md`. Its "Registered skills" section is not repeated here:
> the same 17 skills are already listed in the **Imported skills** table above.

Custom **agent skills** for the `Monthly-Report-Auto` project. A skill is a packaged,
reusable instruction set an AI assistant loads on demand — either a behavior mode
(e.g. terse output) or a domain expert persona (e.g. PDF rendering, translation).

### Layout

One directory per skill under `.agents/skills/`, each holding a single `SKILL.md`:

```
.agents/
  skills/
    <skill-name>/
      SKILL.md          # the skill definition (required)
      references/       # optional supporting files the skill points to
```

- `<skill-name>` is a lowercase, hyphenated slug (`web-automation-expert`, `caveman`).
- The slug is the skill's identity: it is what `/`-invocation and the `name:`
  frontmatter must agree on.
- Project-scoped skills live here; assistant-provided skills may also appear under
  `.claude/skills/` — those are not authored in this repo.

---

### `SKILL.md` format

A `SKILL.md` is YAML frontmatter followed by the instruction body.

```markdown
---
name: <skill-name>            # matches the directory slug, exactly
description: >                 # one-line recall summary + trigger phrases; this is
  What the skill does, and the phrases that should invoke it. Kept short — it is the
  only text the assistant reads when deciding whether the skill is relevant.
# optional, mode-style skills only:
levels: [lite, full, ultra]   # selectable intensities, if the skill has them
---

<body: the instructions the assistant applies once the skill is loaded>
```

Frontmatter keys:

| Key | Required | Purpose |
|-----|----------|---------|
| `name` | yes | Identity slug; must equal the directory name. |
| `description` | yes | Single-line recall summary **and** the trigger phrases. Decides relevance. |
| `levels` | no | For mode skills that expose intensities (see `caveman`). |

Body conventions:

- State **persistence** explicitly — does the behavior last one reply, or the whole
  session until countermanded?
- State the **override / off switch** explicitly (e.g. `caveman` turns off on
  `"stop caveman"` / `"normal mode"`).
- Keep the body self-contained: an assistant applies it verbatim without further
  context.

---

### Invocation protocol

Typing `/<skill-name>` (a slash command) means: **read `.agents/skills/<skill-name>/SKILL.md`
and apply it for the remainder of the session**, until the user turns it off or switches
skills. The description's trigger phrases invoke the same behavior in natural language
(e.g. "be brief" loads `caveman`).

Multiple skills can be active at once when they do not conflict (a persona expert plus
an output mode). A mode skill's level is switched inline: `/caveman lite`, `/caveman ultra`.

---

### Authoring guidelines

1. **One skill, one behavior.** A skill is either a *mode* (how the assistant
   communicates or works) or an *expert persona* (a domain it reasons within) — never a
   grab-bag of both.
2. **Description is a recall line, not a manual.** It is the only text weighed when
   deciding to load the skill; put the job and the trigger phrases there, nothing else.
3. **Make persistence and override explicit** in the body. An assistant must know when
   the skill stops applying without guessing.
4. **Keep the body executable.** Concrete rules, examples, and boundaries beat prose.
   Where a rule has a sharp edge (an off switch, a safety carve-out), spell it out.
5. **Slug = `name` = directory.** All three must match, or `/`-invocation cannot resolve.
