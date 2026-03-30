# Skill: TODO_PLAN.md Maintenance

This skill defines how to maintain the project's `TODO_PLAN.md` file at the
repository root. This is the single source of truth for what needs doing, what
has been done, and what we learned along the way.

---

## Purpose

`TODO_PLAN.md` is a **self-contained operational document**. A cold-start agent
should be able to read this file and know: what the project has accomplished,
what work is active, what the next steps are, and what pitfalls to avoid.

It is not a design doc (those live in `docs/design/`). It is not a changelog
(that's git history). It is the **living task plan** for the project.

---

## File Structure

```markdown
# {Project Name} — TODO Plan

> **Status:** Active | Complete
> **Created:** YYYY-MM-DD
> **Updated:** YYYY-MM-DD
> **Design:** link to design doc (if applicable)

## How to Use This File
- Rules for agents (branch workflow, commit conventions, blockers)
- Mandatory standards (links to SKILL.CODING.md, STYLE.*.md, TESTING.md)
- Key reference documents table

## What We've Accomplished
- Detailed summary of completed work — enough to orient a cold-start agent
- Not just checkboxes — describe what exists and how it works

## Active Work: {Feature Name}
- Full phase breakdowns with task checklists inline
- Acceptance criteria per phase
- Commit points

## Lessons Learned
- Numbered entries with enough context to be useful months later

## Blockers
- Anything blocking progress, with date and unblock action
```

---

## Rules for Agents

### The plan lives inline, not by reference

Put the actual task details directly in `TODO_PLAN.md`. Do not create thin
indexes that point to separate plan files. An agent should never have to chase
links to find out what to do next.

Design docs stay in `docs/design/` — link to them for context. But the **task
breakdown** belongs in `TODO_PLAN.md`.

### Adding Work

- When a design doc produces a phased plan, transfer the tasks into the
  **Active Work** section. Reference the design doc for context, don't
  duplicate the design rationale.
- Group tasks by phase with clear dependency ordering.
- Include acceptance criteria and commit points per phase.
- Keep task descriptions short — one line. If it needs explanation, add a
  brief note below the checkbox.

### Updating Progress

- Mark tasks `[x]` as you complete them. Do not batch — mark each task done as
  soon as it is done.
- If a task turns out to be unnecessary, strike it with `~~` and add a brief
  reason: `~~Task description~~ (superseded by X)`
- If you discover new work mid-implementation, add it to the Active section
  immediately. Do not wait until the end.

### Moving to Completed

- When all tasks in a feature/area are done, move the summary from Active Work
  into **What We've Accomplished**.
- Write enough detail that a cold-start agent can understand what exists —
  not just "Phase 1 done" but what was actually built, what files were created,
  what patterns were established.

### Recording Lessons Learned

This is the most important section. Record lessons when:

- An assumption turned out to be wrong
- A tool or API didn't behave as documented
- A debugging session took longer than expected and the root cause was
  non-obvious
- An approach was tried, rejected, and replaced — capture *why* so the next
  agent doesn't repeat the experiment
- Something worked unexpectedly well and should be repeated

**Format:**

```markdown
### {N}. {Short title}
{What happened and what to do differently. 2-4 sentences max.}
```

A good lesson learned saves someone 30+ minutes in a future conversation.

**Do not record:**
- Obvious things ("tests should pass before merging")
- Things already documented in style guides or CLAUDE.md
- Implementation details that belong in code comments

### General

- Keep the file focused. One active feature at a time is ideal. If multiple
  features are active, give each its own `## Active Work` section.
- Review and prune `TODO_PLAN.md` at the start of any major new work session.
  Remove stale items, update anything that has drifted.
- Do not drop `PLAN.md` files — the project uses `TODO_PLAN.md` exclusively.
  `PLAN.md` is in `.gitignore`.
