# Chores Webhooks

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-10-02  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

A dead simple feature addition to chores. Instead of cron, a chore can
select itself to be triggered by webhook.

It defines a path under our chores webhook endpoint. It names, by label --
never by value -- which of the known pre-shared keys that path responds
to. When the chores system receives a push on that hook carrying the
proper key, it triggers the chore, with the webhook payload as context.

That's it.

## Story sets

| File | Theme |
|---|---|
| STORIES.triggering.md | a push on a hook making its chore run |

## Notes

**Settled in session (Todd's words, 2026-10-02):**

- A chore's trigger is cron or webhook; a webhook chore defines its own
  path under the chores webhook endpoint.
- A webhook chore names its pre-shared key by label, chosen from the known
  keys; values never appear in a definition.
- A push on the path with the proper key triggers the chore, with the
  webhook payload as its context.
- No Access layer on the webhook endpoint: the pre-shared key is the
  authentication. cloudflared is still needed, to hang the local port off
  the internet.
- Its own tunnel, separate from the Ollama Gateway's, built close to that
  pattern (tds-internal `DESIGN.ollama-gateway-infra.md`, PR #125) so the
  Cloudflare configuration stays as DRY as possible.
- The endpoint sits behind the LMDE's local proxy layer (nginx/haproxy),
  which anything local needing a public port plays nice with, so
  throttling and maximum payload sizes are centralized there.

**Still open:**

- A delivery that arrives while the laptop is asleep or offline fails, and
  GitHub does not redeliver on its own. Lost, like a missed schedule slot
  today, or caught up somehow?
- The payload is written by whoever pushed (branch names, commit messages,
  PR text) and becomes the chore's context. The chore's budget and
  ceilings bound its spend, not what that text steers it toward. Accepted?
- Whether the LMDE proxy layer is the Ollama Gateway's deadline proxy
  grown into a shared front door, or a new piece both sit behind (PR #369,
  in review).

**Leans on:** the chores design (`CHORES.DESIGN.md`, APPROVED), whose only
trigger today is a cron schedule; the Ollama Gateway's tunnel pattern and
its edge record in tds-internal.
