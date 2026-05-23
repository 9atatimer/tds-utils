# GitHub Repository Information

This document contains instructions for AI coding agents on how to interact with the GitHub repository.

<!-- Localized for 9atatimer/tds-utils. -->

## Repository Details

-   **Owner:** 9atatimer
-   **Repository:** tds-utils
-   **Default Branch:** master

## Push & PR Flow

### Single PR Workflow (Iterative Review)

Because the `9atatimer` organization has Copilot review enabled, all AI review cycles happen within a single PR. Do not create multiple PRs or close/re-open PRs.

1. **Push:** Push your branch to `origin`.
2. **Draft PR:** Create a **Draft PR** targeting `master` -- the draft state itself is the WIP signal; do not put `[WIP]` in the title.
3. **Title:** Use a clean conventional-commit summary (e.g., `feat(lmde): formalize architecture`).
4. **Iterative AI Review:** Copilot will automatically review the draft. This is an **iterative** process:
   - Address Copilot feedback.
   - Push your changes.
   - Wait for Copilot to review the new changes.
   - Repeat until Copilot is satisfied.
5. **Human Review:** Once the AI review cycles are settled, the human will take over for final review and merging. Do NOT attempt to create a second "final" PR.

## Branch Safety (CRITICAL)

- **NEVER WORK ON THE `master` BRANCH**
- **ALWAYS CHECK CURRENT BRANCH FIRST**: Before any git operations, run `git branch --show-current`
- **IF YOU ARE ON MASTER**: STOP IMMEDIATELY. Warn the human. Do NOT proceed.
- **REQUIRED WORKFLOW**: All changes must be made on a feature branch, then merged via Pull Request

## Branch Naming Convention

All branches created on this repo MUST use an owner prefix:
- Human-driven branches: `tstumpf/feat/description`, `tstumpf/fix/description`,
  `tstumpf/refactor/description`, `tstumpf/docs/description`.
- Agent-driven branches: `claude/feat/description`, `claude/fix/...`,
  `claude/docs/...`. (The agent prefix is set by the harness; humans should
  not push to `claude/...` branches.)

## Development Workflow

1. **Branch Creation:** Create a feature branch from `master`
2. **Implementation:** Make changes locally
3. **Validation:** Run linter, type checker, tests
4. **Stage & Commit:** Stage verified changes, commit with descriptive message
5. **Push:** Push to origin
6. **PR:** Create PR with clear description

## GitHub Tool Usage

Three families of verbs, in **token-frugal preference order**:

1. **`gadmin` (this repo's `bin/gadmin`)** -- preferred for reads (comments,
   CI logs) and writes (replies). Output is filtered to the fields you
   triage on, so it stays small in context. Three sub-tiers, fall back in
   order:
     - `gadmin github` -- bash, requires `gh` CLI on `$PATH`.
     - `gadmin github-octokit` -- node + `octokit` npm package + `$GITHUB_TOKEN`.
     - `gadmin github-gitapi` -- node, native `fetch()` + `$GITHUB_TOKEN`,
       zero deps.
2. **GitHub MCP tools (`mcp__github__*`)** -- use when `gadmin` lacks a verb
   you need. Responses are typed and complete but include large echoed
   payloads (e.g. every reply confirms by echoing the parent comment's
   `diff_hunk`), so they cost ~5–10× more tokens than `gadmin` for the same
   operation. Avoid them for hot loops over many comments.
3. **`gh` CLI** -- last-resort fallback when neither `gadmin` nor MCP cover
   the operation.

**GitHub Actions logs:** `gadmin github actions list-runs` to find runs,
`gadmin github actions get-job --run <ID> --job <NAME>` to retrieve job
output. ANSI codes are stripped automatically.

**One-line rule:** when an event has already delivered the comment body via
the subscription stream, **do not re-fetch it.** The webhook payload is the
source of truth for that thread -- reply directly from the comment ID.

## Review-watch loop (default after opening a PR)

When you open a PR with `gh pr create`, **start the review-watch loop
by default** -- don't wait for the human to ask. This implements the
"Iterative Review" cycle above: address Copilot feedback, push, wait
for re-review, repeat until quiescent. Applies to both human-driven
(`tstumpf/*`) and agent-driven (`claude/*`) PRs.

Two transports, preferring push:

1. **Subscription (push) -- if the GitHub MCP server is loaded.** Call
   `mcp__github__subscribe_pr_activity` with the PR number. Events
   arrive as `<github-webhook-activity>` blocks. Auto-removes on
   merge/close. Idempotent.
2. **Polling (`ScheduleWakeup`) -- when MCP isn't loaded.** Dynamic
   self-pacing. Per the global 240s-max rule in `~/.claude/CLAUDE.md`,
   all wakes here are ≤4 min (the global rule wins; no longer wakes
   without human approval).
   - **First wake after PR open:** ~3 min (180s) -- Copilot needs a
     beat to start; polling before that is wasted.
   - **First wake after a push:** ~2 min (120s).
   - **Empty polls while waiting:** every 2 min (120s).

   Copilot's observed response window is ~4-6 min, so a 2-min cadence
   catches it within ~2 min worst case, average ~3. Pass the loop's
   continuation prompt verbatim to `ScheduleWakeup` so the next wake
   re-enters this flow.

   **On wake, do these in order:**
   1. **Switch to the PR's head branch** (`git switch <BRANCH>`).
      Otherwise `gadmin` may abort with a branch-mismatch warning and
      hide real pending comments. The user can be on any branch
      between turns; the loop is responsible for landing on the
      right one before any `gadmin` call.
   2. **Check the PR state and any new reviews** with
      `gh pr view <NUMBER> --json state,mergedAt,reviews` in one
      call.
      - `state` is `MERGED` or `CLOSED` -> terminate the loop
        immediately, skip the rest of the steps below.
      - Otherwise inspect `reviews` for new entries since the last
        poll to catch **overview-only reviews** (`state=COMMENTED`
        body with no inline comments). `gadmin github pending-comments`
        only surfaces inline comments, so overview-only reviews are
        invisible to it.
        - Overview **with** inline comments -> proceed to step 3.
        - Overview **only** (no inline) -> ack briefly and continue;
          don't reply per overview event.
        - No new review since last poll -> empty poll, increment the
          empty-poll counter, schedule the next wake.
   3. Fetch unaddressed inline comments with
      `gadmin github pending-comments --repo <OWNER/REPO> --pr <NUMBER>`
      and triage per the auto-action threshold below.

**Termination conditions** (any one fires -> stop the loop; in MCP
mode also unsubscribe; in poll mode omit the next `ScheduleWakeup`):

- PR merged or closed.
- 3 consecutive empty polls (~6 min quiescent at the documented
  2-min cadence). Stop fast -- Copilot rarely returns late once
  the response window has passed.
- Architecturally ambiguous comment -> `AskUserQuestion` and stop.
  Don't guess at design calls.
- **Quality drop**: when remaining unaddressed comments are nitpicks
  (style trivia, "consider renaming X to Y" with no concrete reason,
  alternative phrasings of working code), push back -- reject with a
  one-line reason per the threshold below. If Copilot re-asserts the
  same nit on the next pass, post one summary reply ("remaining
  suggestions are stylistic; not addressing in this PR") and stop.
  Don't loop on bikeshedding.
- Human says "stop the loop" / "stop watching" / similar -> stop.
  Don't argue.

**Event taxonomy and triage policy:**

| Event | What to do |
|-------|------------|
| Review overview (`pullrequestreview`, often with N inline comments queued behind it) | Fetch the full review_comments list **once** via `gadmin` and triage the whole batch. Do not reply per inline event. |
| Single inline `pull_request_review_comment` (no review overview, e.g. a human reply) | Triage and act on that one thread. |
| `check_run` failure | Get the failing job's log via `gadmin github actions get-job`; classify (flake / config / real bug); fix or report. |
| `merged` / `closed` | Acknowledge and stop watching; you're auto-unsubscribed (MCP) or omit next wakeup (poll). |
| **Echo of your own reply** (author is you, body matches what you just posted) | **Skip.** Every reply you post comes back as a webhook event ~1s later. Recognise and discard. |

**Auto-action threshold (apply on every event):**

- If the change is **small and unambiguous**, make it, push, reply with
  the SHA. No need to ask first.
- If the change is **ambiguous or architecturally significant**, ask
  the human before acting. Use `AskUserQuestion` so the question is
  in-band.
- If you **disagree** with a comment, reject it with a one-line
  concrete reason. Never just "disagree." Don't be a yes-man to
  Copilot -- reviewer pushback is the point of the loop.
- If **no action is needed** (echo, informational, noise), skip and
  say so briefly.

## Automated Review Response

This is the procedure for handling a batch of review feedback -- whether it
arrived via subscription or you fetched it cold with `gadmin
pending-comments`.

**Step 1: Fetch all comments (once).**
- `gadmin github pending-comments --repo <OWNER/REPO> --pr <NUMBER>` for
  unaddressed comments.
- Fallback: `gadmin github pr-comments --repo <OWNER/REPO> --pr <NUMBER>`
  for everything.
- `--repo` is required.

**Step 2: Triage ALL comments before making changes.** Read every comment,
classify each as one of:
- **Agree** -- will fix.
- **Disagree** -- will reject with a reason.
- **Ambiguous / architecturally significant** -- ask the human first via
  `AskUserQuestion`. Don't guess.

**Step 3: Reject the ones you disagree with** immediately, with reason:
`gadmin github reply --repo <OWNER/REPO> --id <ID> --type reject --msg "Reason for disagreement"`

**Step 4: Implement the agreed fixes locally, commit, and PUSH.** All
fixes go in one commit (or one per logical group), never amend a pushed
commit. Note the resulting SHA.

**Step 5: Accept each fixed comment with the SHA:**
`gadmin github reply --repo <OWNER/REPO> --id <ID> --type accept --msg "Agreed, fixed in <sha>"`

**Step 6: Verify nothing is unaddressed:**
`gadmin github pending-comments --repo <OWNER/REPO> --pr <NUMBER>` -- should
return empty.

**Step 7: Consider documentation follow-ups.** Did an accepted fix reveal a
gap worth a new TODO or a Lessons-Learned entry? Did a rejected suggestion
surface a recurring misconception worth recording? If yes, update the
relevant doc; if not, skip.

**Reply conventions** (independent of which tool posts them):

- Accept replies say: `Agreed, fixed in <sha> -- <one-line summary of fix>`.
- Reject replies say: `<concrete reason>` -- never just "disagree."
- Replies are posted **sequentially**, one tool call per reply. Do not
  batch.

**Execution notes:**

- If `gadmin github` fails, fall back to `gadmin github-octokit`, then
  `gadmin github-gitapi`, then MCP, then raw `gh` -- in that order.
- If you can't annotate at all, ask the human for help rather than
  silently dropping comments.

## Commit Messages

Use conventional commits:
```
feat: add new feature
fix: correct bug in component
refactor: extract shared logic
test: add unit tests for composable
docs: update architecture doc
```
