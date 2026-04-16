# SKILL: Design Document Authoring & Review

> **Purpose:** Author, review, and improve design documents that are useful to both AI agents and human engineers.
> **When to use:** Before implementing a new system, major feature, or architectural change.
> **References:** `docs/design/TEMPLATE.md`, `docs/design/STYLE-GUIDE.md`

---

## When to Invoke This Skill

- User asks to write, draft, or create a design doc
- User asks to review or improve an existing design doc
- User is about to start a feature that lacks a design doc
- User asks "how should we design X?"

---

## Authoring a New Design Doc

### 1. Gather Context

Before writing, understand:
- **What problem are we solving?** (not what we're building)
- **Who is the audience?** (AI agents implementing it + human reviewers)
- **What already exists?** Check `docs/design/` for related docs
- **What are the constraints?** (tech stack, timeline, dependencies)

### 2. Start from the Template

Copy `docs/design/TEMPLATE.md` to a new file following naming conventions:

| Pattern | Use For |
|---------|---------|
| `DESIGN.<name>.md` | Feature or component design |
| `ARCHITECTURE.md` | System-level design |
| `INTEGRATION.md` | How components connect |

### 3. Fill Sections in Order

**Do not skip sections.** Write them in this order:

1. **Header block** -- Status starts as DRAFT, fill date and authors
2. **Overview** -- 2-3 sentences max. If you can't explain it briefly, you don't understand it yet
3. **Goals** -- Testable success criteria. Each goal should be verifiable
4. **Non-Goals** -- Explicit scope boundaries. Think: "what will someone ask for that we should say no to?"
5. **Architecture Overview** -- ASCII diagram of major components and data flow
6. **Design** -- The meat. Break into subsystems, each with responsibilities and interfaces
7. **State Machine** -- If the system has lifecycle states (most do), document transitions
8. **Data Model** -- Tables, fields, relationships, constraints
9. **Security Considerations** -- Auth, secrets, attack vectors, mitigations
10. **Key Decisions** -- Table of choices with rationale. This is the most valuable section for future readers
11. **Open Questions** -- Be honest about unknowns. This builds trust
12. **Rejections** -- Alternatives considered and explicitly dismissed, each with a one-line reason. Prevents future maintainers from relitigating settled decisions. Distinct from Non-Goals (which is scope) and Key Decisions (which is what was chosen) -- this captures what was *not* chosen and why
13. **Future Considerations** -- Explicitly deferred work
14. **Related Documents** -- Links to other design docs

### 4. Apply the Style Guide

Follow `docs/design/STYLE-GUIDE.md` rigorously:

- **Be explicit** -- No "handle errors gracefully"; specify retry counts, timeouts, fallback behavior
- **Be testable** -- No "fast response times"; specify P95 latency targets
- **Be unambiguous** -- No "the system"; name the specific component
- **Prefer tables over prose** -- State machines, decisions, responsibilities all belong in tables
- **Use ASCII diagrams** -- They work everywhere, including in AI agent prompts

---

## Reviewing an Existing Design Doc

### Quality Checklist

Run through these checks:

**Structure:**
- [ ] Has all required sections (header, overview, goals, non-goals, design, key decisions, open questions, rejections)
- [ ] Header has status, date, authors
- [ ] Status uses standard vocabulary (DRAFT / REVIEW / APPROVED / IMPLEMENTED / SUPERSEDED)

**Content quality:**
- [ ] Overview is 2-3 sentences, explains the "why"
- [ ] Goals are testable and measurable
- [ ] Non-goals explicitly exclude likely scope creep
- [ ] Architecture has a diagram (ASCII preferred)
- [ ] State machines have both diagram AND transition table
- [ ] Key decisions have rationale (not just the choice)
- [ ] Open questions are honest about unknowns
- [ ] Rejections section captures alternatives that were considered and dismissed, each with a one-line reason

**Style:**
- [ ] No vague language ("gracefully", "efficiently", "properly")
- [ ] No walls of text -- uses tables, lists, diagrams
- [ ] ASCII-only in diagrams and prose (no smart quotes, no Unicode arrows)
- [ ] Consistent heading levels (no skipping H2 -> H4)
- [ ] Blank lines after headings and before lists

**Completeness:**
- [ ] Could an AI agent implement this without asking clarifying questions?
- [ ] Could a new team member understand the "why" behind each decision?
- [ ] Are error cases and edge cases documented?

### Review Output Format

When reviewing, organize feedback as:

```
## Design Doc Review: [Title]

### Blocking Issues
- [Issues that must be fixed before implementation]

### Suggestions
- [Improvements that would strengthen the doc]

### Questions
- [Clarifications needed from the author]

### Strengths
- [What the doc does well -- reinforce good patterns]
```

---

## Improving a Design Doc

When asked to improve an existing doc:

1. **Read the full doc first** -- Understand the intent before suggesting changes
2. **Check against the template** -- Identify missing sections
3. **Apply the style guide** -- Fix vague language, add tables, improve diagrams
4. **Preserve the author's intent** -- Improve clarity without changing decisions
5. **Add, don't remove** -- Missing sections should be added; existing content should be refined

### Common Improvements

| Problem | Fix |
|---------|-----|
| Missing non-goals | Ask: "what will users request that's out of scope?" |
| Vague goals | Add numbers: latency targets, error rates, coverage |
| No state machine | Look for lifecycle states in the design section and extract them |
| Prose-heavy design | Convert responsibilities and transitions to tables |
| Missing key decisions | Look for implicit choices and make them explicit with rationale |
| No open questions | Every design has unknowns -- be honest about them |
| No rejections section | Look at the conversation/PR history for alternatives that were debated and dropped; surface them with one-line reasons so they don't get relitigated |

---

## Connecting Design Docs to Implementation

A design doc's value is realized when it drives implementation:

1. **Before coding:** Read the design doc. If anything is unclear, improve the doc first
2. **During planning:** Use `SKILL.PLANNING.md` to create a TODO_PLAN from the design doc
3. **During coding:** Use `SKILL.CODING.md` to implement against the design doc
4. **After implementation:** Update the design doc status to IMPLEMENTED; note any deviations

### Design Doc -> TODO_PLAN Flow

```
docs/design/DESIGN.feature.md    (what to build and why)
         |
         v
docs/TODO_PLAN.feature.md        (how to build it, step by step)
         |
         v
Implementation                    (the code)
```

The design doc answers **what** and **why**. The TODO_PLAN answers **how** and **in what order**.

---

## Status Transitions

```
DRAFT  -->  REVIEW  -->  APPROVED  -->  IMPLEMENTED
                |                            |
                v                            v
            (revise)                    SUPERSEDED
```

- **DRAFT -> REVIEW:** Author believes doc is complete enough for feedback
- **REVIEW -> APPROVED:** Reviewers agree on the approach
- **APPROVED -> IMPLEMENTED:** Code matches the design
- **IMPLEMENTED -> SUPERSEDED:** A newer design replaces this one (link to it)
- **REVIEW -> DRAFT:** Significant revisions needed (back to drafting)
