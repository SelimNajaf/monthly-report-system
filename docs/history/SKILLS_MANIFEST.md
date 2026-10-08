# Skills Manifest

Custom **agent skills** for the `Monthly-Report-Auto` project. A skill is a packaged,
reusable instruction set an AI assistant loads on demand — either a behavior mode
(e.g. terse output) or a domain expert persona (e.g. PDF rendering, translation).

This document defines the on-disk layout, the `SKILL.md` format, the invocation
protocol, the authoring rules, and the registry of skills currently installed.

---

## Layout

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

## `SKILL.md` format

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

## Invocation protocol

Typing `/<skill-name>` (a slash command) means: **read `.agents/skills/<skill-name>/SKILL.md`
and apply it for the remainder of the session**, until the user turns it off or switches
skills. The description's trigger phrases invoke the same behavior in natural language
(e.g. "be brief" loads `caveman`).

Multiple skills can be active at once when they do not conflict (a persona expert plus
an output mode). A mode skill's level is switched inline: `/caveman lite`, `/caveman ultra`.

---

## Authoring guidelines

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

---

## Registered skills

### Modes

| Skill | Levels | Summary |
|-------|--------|---------|
| **`/caveman`** | `lite` · `full` (default) · `ultra` · `wenyan-lite` · `wenyan-full` · `wenyan-ultra` | Ultra-compressed output mode — terse "caveman" phrasing that cuts output tokens ~65% while keeping full technical accuracy. Triggers: `"caveman mode"`, `"talk like caveman"`, `"less tokens"`, `"be brief"`, `/caveman`. Persists every response; off on `"stop caveman"` / `"normal mode"`. |
| **`/find-skills`** | — | Helps discover and install agent skills when the user asks "how do I do X", "find a skill for X", or wants to extend capabilities. |

### Domain expert personas

These map one-to-one onto the pipeline's stages, so the right expertise can be summoned
for the layer being worked on.

| Skill | Domain |
|-------|--------|
| `/software-architecture-expert` | Overall software design and structural patterns of the system. |
| `/automation-workflow-architect` | Designs and orchestrates the distributed document-automation pipeline. |
| `/performance-scalability-expert` | Resource use, throughput, and scaling limits (the parse-cache work lives here). |
| `/document-analysis-expert` | Semantic and structural layout of Microsoft Word `.docx` reports. |
| `/information-extraction-architect` | Resilient extraction from unstructured/semi-structured report content. |
| `/data-modeling-expert` | Structured schemas, configuration, and internal data models. |
| `/json-data-contract-expert` | Machine-readable JSON sidecar contracts decoupling raw data from consumers. |
| `/translation-terminology-expert` | English→Azerbaijani terminology system (`translations/az.json`). |
| `/official-report-template-expert` | Stable, professional official report templates. |
| `/pdf-generation-expert` | PDF rendering architecture for enterprise report output. |
| `/web-automation-expert` | Playwright (sync) browser automation for the e-Keyfiyyet portal uploader. |
| `/error-handling-recovery-expert` | Error classification, diagnostic logging, and recovery. |
| `/quality-assurance-expert` | Reviews specs, designs, contracts, and workflows before implementation. |
| `/technology-selection-expert` | Chooses languages, frameworks, libraries, and components. |
| `/research-best-practices-expert` | Deep technical research, literature reviews, standards audits. |

> Registry drawn from `.agents/skills/*/SKILL.md`. When a skill is added or removed,
> update this table so the manifest stays the single source of truth for what is installed.
