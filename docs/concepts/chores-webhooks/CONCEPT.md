# Chores Webhooks

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

Chores today fire on a clock. I want them to fire when a repo changes, too:
GitHub tells my laptop that something happened in a repo, and the chore that
cares about it runs. That is a whole new kind of chore trigger -- webhooks --
beside the schedule.

The thing that made it obvious: my skills had silently drifted for weeks,
because the copy every session loads only moves when somebody remembers to
pull. A push to the repo should be enough. Chores is the herd that already
runs jobs on this laptop; it should be the thing that hears the push and
acts on it.

To hear GitHub at all, the laptop needs a road in from the internet. That
road is a cloudflared tunnel, set up the way the Ollama Gateway's road is:
the edge declared in tds-internal, the daemon on the laptop part of the
LMDE.

## Story sets

| File | Theme |
|---|---|
| STORIES.triggering.md | a change in a repo making the right chore run |
| STORIES.guarding.md | who can make a chore run from outside, and what they can make it do |
| STORIES.missing.md | what happens to a change the laptop was not awake to hear |

## Notes

**Settled in session (Todd's words, 2026-10-02):**

- Chores gets a new trigger: webhooks from GitHub, so chores can fire off
  repo changes. It is "a whole new chore trigger", alongside the schedule.
- The road in is a cloudflared tunnel, addressed "in a similar manner" to
  the Ollama Gateway's: build on the cloudflared edge record (tds-internal
  `DESIGN.ollama-gateway-infra.md`, PR #125) and its tds-utils counterpart
  (`OLLAMA-GATEWAY.DESIGN.md`, PR #369).
- No Access layer on the chores webhook endpoint: deliveries are
  authenticated with a pre-shared key. cloudflared is still needed, to hang
  a local port off the internet.
- Stay close to the pattern established for the Ollama Gateway, so the
  Cloudflare configuration is as DRY as possible.

The stories were drafted by the agent from the points above and have not
yet been read back; strike or reword any that are not yours.

**My reading, for Todd to confirm or strike:** the first chore on the road
is keeping the laptop's skills current -- a push to the skills repo's
default branch brings the local copy up to it (tds-utils issue #377).

**Still open (nobody's yet):**

- Which repos and which kinds of change fire chores: pushes to a default
  branch only, or also PRs, reviews, comments, releases.
- Who says which chore a change fires: the chore's definition, the repo,
  or both.
- What a change that arrives while the laptop is asleep or offline turns
  into: lost, recorded as missed (as a schedule slot is today), or caught
  up when the laptop wakes.
- Whether many changes in a burst fire a chore many times or once.
- How much of the Ollama Gateway's Cloudflare configuration this shares,
  given "as DRY as possible": the same tunnel with another hostname or
  path, or its own tunnel built the same way. The gateway's whole host sits
  behind Access, and this endpoint does not.
- Where the pre-shared key lives and how it reaches GitHub and the laptop,
  and whether one key serves every repo or each has its own.
- Whether anything a change carries (branch names, commit messages, PR
  text -- all written by whoever pushed) may reach a chore's prompt, given
  that a chore can spend money and act on the laptop.
- How this meets the repo-chores concept, where a repo declares its own
  chores and the herd follows them as they change: that concept's
  "following" stories want exactly this signal.

**Leans on, existing:** the chores design (`CHORES.DESIGN.md`, APPROVED),
whose only trigger is a cron schedule and whose Non-Goals rule out
filesystem and network sandboxing of a run -- which an outside trigger
meets head on; the LMDE's "never routable" non-goal, which the Ollama Gateway
already crosses for one road; the cloudflared edge record and the
gateway's laptop component; the Access service-token pattern in
tds-internal.

**Leans on, not existing yet:** any way for chores to be told about an
event rather than finding it on a tick; any record of which deliveries
arrived and what they fired.
