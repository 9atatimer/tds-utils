# Landing tds-utils via tedium

Moved from tds-utils `AGENT.md` (Issue#292 enrolled the repo). The rules are in `tedium.toml` on `master`; the gates and github-workflow skills assume what follows.

This repo lands PRs through the tedium merge bot; the rules are in
`tedium.toml` on `master` and the gates skill assumes what follows.

- **Required checks.** `gate` (the `dist-ci.yml` job that needs every
  other job) must be green on the PR head AND on the staging commit tedium
  builds on `tedium/merge` (`status` in `tedium.toml`). The `master`
  ruleset requires `gate` and a PR; only the tedium App may bypass it.
- **`review-settled` is off: always green (owner ruling, 2026-10-18).**
  The status still posts on every non-fork PR head, so any repo or
  ruleset that names it keeps reporting, but `bin/review-settled` no
  longer judges reviews or threads and never waits: it posts `success`
  ("review-settled is off ... always green"). It was not in this repo's
  `pr_status` or ruleset before either. The decision code
  (`lib/review-settled.mjs`, `decide` in `bin/review-settled`) is kept and
  tested; `main()` names the one line that turns it back on. The agentic
  reviewer is OCR on Demand, summoned with a `/ocr` PR comment (this repo
  carries the caller); Copilot and Codex review only when a HUMAN fires
  the trigger, never an agent (gates skill, Reviewer Selection). Callers pinned
  to an older tds-utils commit keep the old verdict until they bump.
- **Reviewers** (who may `r+`) are the repo's direct collaborators with
  push, synced by tedium. An agent acting under a reviewer's token is a
  reviewer.
- **Agents act as `9atatimer-bot`, never as the owner** (tds-internal#285).
  The `CODEOWNERS` catch-all needs the owner's approval on every PR, and
  GitHub refuses self-approval, so a PR an agent opens as `9atatimer` can
  never be approved. Start laptop sessions with `bin/claude-as-bot`: the
  bot's token as `GH_TOKEN` (the login Keychain once `bin/seed-bot-token`
  has seeded it, else `TDS_BOT_GH_TOKEN_REF`, else the 1Password item
  tagged `agents-gh-bot`), GitHub over HTTPS only, commits under the bot's
  name. Seeded, neither it nor `asbot` asks 1Password. To run one command
  as the bot from any session, use `bin/asbot <cmd>`. Cloud sessions get
  the same by connecting claude.ai's GitHub integration as the bot.
  - The Keychain is first because the variable cannot be trusted to be
    unset. Long-running processes keep the environment they started
    with: on 2026-11-10 tmux servers, omp, the `op` daemon and ChatGPT
    still carried an `op://` value, so every session they started used
    1Password and prompted, while the agent's own shell showed the
    variable unset (PR#768). A variable unset in your shell says nothing
    about another session's; `ps -E -p <pid>` shows what a process
    inherited. A fast local source must come before one that prompts.
  - Merging here ships nothing: `asbot` and `claude-as-bot` change on the
    machine only at `bin/tds-release`, and a session started before it
    keeps the old `PATH` copy.
- **`gate` is the only name to add to.** A new CI job goes into `gate`'s
  `needs`; a job outside it cannot block a landing. It also takes
  `needs: changes` and a scope in `.github/scripts/changed-scopes.sh`: on a
  PR, `dist-ci.yml` runs only the jobs the diff can affect (a docs-only PR
  runs none), and `gate` counts a skipped job as a pass. A push runs
  everything, so the staging commit is always fully gated. Never a
  `paths:` filter: a workflow that does not run never reports `gate`.
- **`hold` label** keeps a PR out of the queue. `tedium dryrun` builds it
  on `tedium/try` without landing.
- **CODEOWNERS** covers every path (`*`, tds-internal#285): every
  landing needs a human owner's approval before tedium lands it. Agents
  open PRs as `9atatimer-bot` so the owner can approve; a PR the owner
  authored can never clear the check and is merged by hand.
- **`tedium/merge` and `tedium/try` are the bot's build branches**: never
  protect them, never commit to them, never base work on them.
- **Closing keywords do not fire when tedium lands.** `Closes #N` in the
  PR body links the issue (`closed_by_pull_requests` lists the merged PR),
  but the issue stays open: observed on PRs #356 and #357, 2026-09-29.
  After tedium merges, close the issue by hand with a comment naming the
  PR.
- Merging to `master` deploys nothing here -- `bin/tds-release` is a
  separate step, run by the owner or by an agent the owner tells to run it
  in the session -- which is why this repo is first in the go-live rollout.
