# Repo Chores

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-09-28  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

I am struggling with repos, workflows and changing tools, and it has made
me appreciate the importance of infrastructure as code.

A repo should be able to define its own chores, in the repo. Not as the
only way to define a chore -- the machine's own herd stays -- but as a
way. The chores system watches a `.chores/` directory at the root of a
repo and provisions that repo's chores from it, and it notices and
responds when those chores change.

Those chores are sandboxed to that repo only. Gotta stay in your lane.

A repo chore is never accepted until a human has reviewed it. When a
repo's chores arrive or change, an LLM assesses the diff, estimates what
it will cost, and recommends accepting or denying it. Then a human
actually accepts the change. Nothing a repo declares runs on the
recommendation alone.

## Story sets

| File | Theme |
|---|---|
| STORIES.declaring.md | a repo writing its chores down, next to its code |
| STORIES.accepting.md | a new or changed repo chore meeting a human before it runs |
| STORIES.confining.md | a repo chore staying in its repo's lane |
| STORIES.following.md | the herd keeping up as repos and their chores change |

## Notes

**Settled in session (Todd's words, 2026-09-28):**

- Repos may define chores in a `.chores/` directory at the repo root. This
  is in addition to the machine's own chore definitions, not a
  replacement.
- The chores system watches for and responds to changes to a repo's
  chores.
- A repo chore is sandboxed to its repo -- "stay in your lane".
- Human acceptance is the gate: no repo chore runs until a human has
  accepted it, and a change to one needs accepting again. An LLM assesses
  the diff, gives a cost estimate and a recommendation (accept or deny);
  the human makes the decision.

The stories were drafted by the agent from those four points and have
not yet been read back; strike or reword any that are not yours.

**Still open (nobody's yet):**

- Which repos are watched: every clone on the machine, or only repos the
  operator has named.
- Which copy of a repo's `.chores/` is the one that counts. A working
  checkout changes branch under you; the release worktree exists
  because live config read from a branch-switchable checkout once
  pointed the herd at nothing (tds-utils `AGENT.md`, "Two release
  units").
- What "its repo only" covers: files, network, credentials, backends,
  budget, the other repos on the machine.
- Whose backends, credentials and ceilings a repo chore spends against,
  and whether a repo can declare its own limits or only ask for them.
- What runs while a change waits for acceptance: the last accepted
  version, or nothing.
- What a denial means for the repo: the chore stays off until the next
  change, or until the human says otherwise.
- Whether removing a chore from a repo also needs acceptance.
- What the assessing LLM's own spend is bounded by, and what happens
  when it cannot produce an assessment.

**What the idea leans on that exists (placement only):**

- The chores tool, its APPROVED design (`docs/design/CHORES.DESIGN.md`)
  and its concept (`docs/concepts/lmde-chores/`). That design keeps
  definitions in one `$CHORES_HOME` and names filesystem sandboxing a
  Non-Goal; both meet this idea head on.
- The release units and pointers (`bin/tds-release`, `~/.tds/`), the
  existing answer to "which copy of config is live".
- Claude Code Routines in tds-internal: git-as-truth specs with a drift
  check, the cloud sibling of the same shape.

**What the idea leans on that does not exist yet:**

- A way for the chores system to know which repos exist on the machine.
- Any per-repo confinement for a run.
- An acceptance record: who accepted which version of which repo chore,
  and on what assessment.
