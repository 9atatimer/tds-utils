# WIP: Tech Radar Skill

> **Status:** WIP -- design conversation in progress, no implementation yet
> **Date:** 2026-05-18
> **Authors:** Todd + Claude (Opus 4.7)
> **Depends on:** [CLAUDE.md](../../CLAUDE.md), existing `prompts/SKILL.*.md` files
> **Note:** Freeform working doc capturing a design conversation, *not* a
> finished spec. Pick up where the "Open Decisions" section leaves off.

---

## Motivation

Idea raised by Todd:

> Create a `SKILL.TECH_RADAR.md` that documents the live technologies we're
> currently using, and the motivations for using those over others. Use it to
> guide future Claude incarnations into making good technology and architecture
> decisions when designing future solutions.

The question on the table: is a markdown of active technologies (and rejected
alternatives) the right shape, or is there something better?

---

## Reframes that happened during the conversation

These shifted the design and are worth capturing because they invalidate
earlier "lightweight personal repo" instincts.

### Reframe 1: tds-utils is not a utility repo

Initial framing assumed tds-utils was a "personal utility repo" and that
heavyweight process (ADRs, decision history) would be overkill.

Todd corrected:

> This isn't a "utility repo" -- this is my soul in digital form. tds-utils is
> the kernel of my development environment. Check the dates -- it's decades
> old. It applies to my whole approach to development software.

**Implication:** invest accordingly. Document not just *what* but *why*, and
treat the history of decisions as itself valuable. The "this is too much
ceremony for a personal repo" reflex is wrong here.

### Reframe 2: two stacks, not one

The radar concept actually splits cleanly across two domains:

1. **LMDE** ("Local MDE" -- Todd's coinage). The local dev environment as a
   coherent system: shells, editor, multiplexer, CLI tooling, local services,
   AI/agent stack, credentials. tds-utils *is* the LMDE in concrete form.
2. **Per-project tech stacks.** Language, web framework, DB, deploy target,
   test framework for any given developed product. These should be influenced
   by a central suggestion (so new projects start from a known-good default)
   but they belong with the **project scaffolding**, not the dev environment.

These are different artifacts with different audiences. Conflating them was
the first design mistake.

### Reframe 3: reachability is load-bearing

Todd's framing:

> We need to be mindful of the way you actually work. You look for local
> per-project context, starting with an AGENT.md (CLAUDE.md in your case). If
> you can't reach it, it might as well not exist.

**Implication:** the radar pattern must be introduced into every project that
should follow it -- via CLAUDE.md hooks pointing to a local SKILL.TECH_RADAR.md.
Hence the radar *pattern itself* belongs in `template-tools` (so every
scaffolded project inherits it). tds-utils gets its own home-grown radar
because tds-utils *is* the dev environment, not a developed product.

---

## Definitions

### Tech Radar

A living snapshot of currently-adopted technologies, conventions, and tools,
with brief rationale per entry and an explicit "Hold" list of things
deliberately *not* used. Inspired by the ThoughtWorks Tech Radar
(Adopt / Trial / Assess / Hold rings), simplified for repo use.

Key properties:
- One living document, edited in place
- Answers "what are we using right now, and what should I reach for?"
- Decays if not maintained -- needs a clear update discipline

### ADR (Architecture Decision Record)

A small, immutable markdown file capturing *why* a single decision was made at
a point in time. Canonical format:

- **Title** -- e.g. "ADR-007: Use SQLite for log-hoarder index"
- **Status** -- Proposed / Accepted / Superseded by ADR-NNN
- **Context** -- what problem forced the decision
- **Decision** -- what we picked
- **Consequences** -- what we gain, what we give up

Lives in-repo (commonly `decisions/NNNN-<slug>.md`), append-only, never edited
after acceptance -- superseded by a new ADR if the decision changes.

**Radar vs ADRs:** complementary. Radar tells you *what's current*; ADRs tell
you *why we moved from A to B in March*. For tds-utils, both arguably justified
given the decades-long history; for a normal small repo, inline rejection notes
in the radar capture 80% of ADR value.

### LMDE

"Local MDE" -- Todd's coinage for his local development environment as a
coherent, opinionated system. tds-utils embodies the LMDE (dotfiles, shells,
editor, CLI tooling, local services).

Distinguishes:
- **LMDE choices** -- shell, editor, multiplexer, local services. Durable,
  cross-cutting, owned by tds-utils.
- **Project-stack choices** -- web framework, DB, deploy target. Scoped,
  template-able, owned by template-tools.

---

## Architectural decision

```
+-----------------------------------------------------+
| tds-utils (the LMDE itself)                         |
|                                                     |
|   prompts/SKILL.TECH_RADAR.md  <-- this design doc  |
|     - Covers LMDE only                              |
|     - Links to CLAUDE.md, SKILL.CODING.md, etc.     |
|     - Authoritative for shells, editor, multiplexer,|
|       CLI tools, local services, AI/agent stack,    |
|       credentials                                   |
|                                                     |
|   CLAUDE.md  <-- adds ingest hook for the radar     |
+-----------------------------------------------------+
                       |
                       | references / philosophy
                       v
+-----------------------------------------------------+
| template-tools (does NOT yet exist -- aspirational)  |
|                                                     |
|   <template>/prompts/SKILL.TECH_RADAR.md            |
|     - Pattern definition + per-project stack        |
|       defaults                                      |
|     - Scaffolded into every new project             |
|     - Each project's radar evolves independently    |
|     - References tds-utils for cross-cutting        |
|       philosophy (TDD, hexagonal, BSD-first, etc.)  |
+-----------------------------------------------------+
                       |
                       v
+-----------------------------------------------------+
| <any developed project>                             |
|                                                     |
|   prompts/SKILL.TECH_RADAR.md  (seeded from         |
|     template-tools, then evolves locally)           |
|   CLAUDE.md  (loads its own radar)                  |
+-----------------------------------------------------+
```

**Order of work agreed:** build the tds-utils/LMDE radar first, refine it,
*then* extrapolate the pattern to template-tools.

---

## Proposed structure for `prompts/SKILL.TECH_RADAR.md` (tds-utils)

Matches the existing `prompts/SKILL.*.md` house style (see SKILL.DESIGN.md for
reference).

```
# SKILL: LMDE Tech Radar

> Purpose: Snapshot of the LMDE's current tech choices and their rationale,
>          to guide additions and prevent drift.
> When to use: Before adding tooling, services, or languages to the LMDE.
> Scope: tds-utils (the LMDE) only. Per-project stacks live in template-tools.
> References: CLAUDE.md, SKILL.CODING.md, SKILL.DESIGN.md, TESTING.md

---

## When to Invoke This Skill
- About to add a new CLI tool, language, or local service to the LMDE
- Considering replacing or removing existing LMDE tech
- Evaluating a new AI/agent tool, MCP server, or skill pattern
- Onboarding a new machine and questioning a default
- NOT for per-project tech (template-tools owns that)

## Update discipline
[Single paragraph: when adding / removing / replacing LMDE tech, update this
file in the same change. Otherwise it rots. This is the most important rule
in the file.]

## Philosophy (do not duplicate -- link out)
- Architecture: CLAUDE.md "Code Architecture" + SKILL.DESIGN.md
- Testing: TESTING.md
- Shell style: CLAUDE.md "Shell Script Structure" + STYLE.BASH.md
- Cross-platform discipline: CLAUDE.md "Platform & Shell"

## Adopt -- what we use right now
Per-domain sections. Candidate domains (based on actual repo contents):
  - Shells (zsh on macOS, bash on Linux)
  - Languages for tooling (Go, Python, zsh/bash, elisp, TypeScript -- when each)
  - Editor (Emacs)
  - Multiplexer (tmux)
  - Search / nav (fzf, find -- verify ripgrep usage)
  - Git tooling (git, gh, custom aliases in git-aliases/)
  - AI / agent stack (Claude Code, MCP, ollama via cline-ollama, clai)
  - Credentials (1Password CLI via designomatic-exec wrapper)
  - Local services (dnsmasq, Caddy, ollama, loopback aliases)
  - Package management (brew on mac, apt/dnf on Linux -- verify)

Each entry format:
  - **What:** one line
  - **Why:** one line
  - **Considered / rejected:** one line (or "--" if none)

## Hold -- deliberately not using
Short list, each with a sentence of why:
  - bash on macOS (use zsh)
  - Docker for local dev (run services directly)
  - VS Code / Cursor as primary editor (use Emacs + Claude Code)
  - GNU coreutils as default on macOS (BSD-first per CLAUDE.md)
  - npm-installed CLIs as primary distribution (prefer brew / system)
  - [more -- to be filled with Todd]

## Open questions / on the radar
Things being evaluated but not decided. Useful so future-me knows "this is
being thought about; don't paper over it with a default."

## Decisions log (optional, lightweight)
Inline mini-ADRs for non-trivial shifts:
  - YYYY-MM-DD | what changed | why | supersedes [entry]
Only added when something interesting happens. If a section's Adopt entry
already captures the rationale, skip.
```

### CLAUDE.md hook

For this skill to actually fire, CLAUDE.md needs a line in the "ingest when..."
block (same shape as TESTING.md and GITHUB.md entries):

> Designing or evaluating LMDE tech (a new CLI tool, language, local service,
> or AI tooling change) → SKILL.TECH_RADAR.md.

Without this hook the radar is invisible to future-Claude and rots immediately.

---

## Open decisions (pick up here)

### 1. Backfill source of truth

How do we populate the initial Adopt / Hold sections?

- **Option A -- Claude infers + Todd corrects.** Claude drafts from repo state
  (bin/, macos/, emacs/, git config, project memories), Todd fixes the *why*s
  in review. Faster; risk that Claude puts words in Todd's mouth on rationale.
- **Option B -- Interview-driven.** Claude drafts a skeleton, then asks per
  section ("why zsh over fish?", "why Emacs over Neovim?"). Slower; captures
  more of what only exists in Todd's head.
- **Option C -- Skeleton only, Todd fills in.** Claude produces empty section
  structure with prompts; Todd writes the content over time. Lowest risk of
  putting words in Todd's mouth; slowest to become useful.

### 2. Decisions log: inline or separate `decisions/` directory

- **Inline in the radar** (low ceremony, fine for v1).
- **Separate `decisions/NNNN-*.md` directory** (true ADRs -- immutable,
  supersedeable, full history). More ceremony but matches "soul in digital
  form" weight.

A middle path: start inline, graduate to a `decisions/` dir if Todd finds
himself wanting to revisit *changes* in stance rather than just current state.

### 3. CLAUDE.md hook wording

Confirm the proposed line above, or refine it.

### 4. Order of work -- confirm

Agreed sequence:

1. Build `prompts/SKILL.TECH_RADAR.md` for the LMDE in tds-utils
2. Add CLAUDE.md hook
3. Refine through use
4. Extrapolate pattern to `template-tools` (separate repo, doesn't exist yet)

### 5. Cross-cutting philosophy -- where do *decisions* about it live?

The radar links *out* to existing philosophy docs (CLAUDE.md, SKILL.CODING.md,
SKILL.DESIGN.md). But if Todd wants ADRs for the *philosophy itself* ("why
hexagonal", "why TDD-after-design", "why BSD-first on macOS"), where do those
live? Three options Claude raised, none chosen:

- In tds-utils (already canonical home for philosophy docs) -- recommended
- Separate philosophy/principles repo, referenced by tds-utils and template-tools
- Duplicated where relevant (rejected -- drifts)

This is a v2 question; not blocking the LMDE radar.

---

## Memory written during the design conversation

In `/Users/stumpf/.claude/projects/-Users-stumpf-workplace-tds-utils/memory/`:

- `project_tds_utils_nature.md` -- tds-utils is the decades-old kernel, not a
  utility repo. Justifies heavier docs/process than small-repo heuristics
  would suggest.
- `project_lmde_term.md` -- LMDE = "Local MDE", Todd's coinage. Distinguishes
  global dev environment from per-project stacks.
- Both linked from `MEMORY.md` index.

---

## Repo state at time of writing

- Branch: `master`, clean, in sync with `origin/master`
- HEAD: `3f8fa41 Set up golang dev. (#40)`
- No tech-radar file exists yet
- Other concurrent Claude session (mentioned at the start of the conversation)
  did not touch this work
- Concurrent session note: a second Claude was running in this dir during the
  design conversation. State is now confirmed quiesced.

---

## How to pick this up

1. Read the **Reframes** section to re-anchor on *why* this is bigger than a
   simple utility doc.
2. Skim the **Architectural decision** ASCII diagram for the tds-utils <->
   template-tools split.
3. Decide the five **Open decisions** above (or at least #1, #2, #3 -- those
   block the first draft).
4. Ask Claude to draft `prompts/SKILL.TECH_RADAR.md` per the proposed
   structure, using the chosen backfill approach.
5. Add the CLAUDE.md hook in the same change.
6. Iterate through use; defer template-tools work until the LMDE radar feels
   right.
