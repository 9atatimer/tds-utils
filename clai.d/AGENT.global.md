<!-- AGENT.global.md -- the GLOBAL agent instruction file for this machine.

     Canonical source. $HOME symlinks resolve to the copy of this file in the
     `release` worktree (~/workplace/.worktrees/tds-utils-release), NOT to the
     primary checkout, so work in progress on master is not live:

         ~/.claude/CLAUDE.md -> .../tds-utils-release/clai.d/AGENT.global.md

     Edit it here on a branch, PR it to master, then release it to `release` with
     `bin/tds-release`. See "The release worktree" in the repo AGENT.md.

     Named .global so agents working inside clai.d/ do not auto-load it a
     second time as directory-scoped instructions. -->

# Global Claude Code Instructions

Every rule below is loaded into every session in every repo, so each one
earns its place by a failure it prevents; the section under it says why.
Mechanics that belong to one domain live in that domain's skill, and this
file points there.

## The hard rules, at a glance

- Never ask with `AskUserQuestion` or a menu; ask in prose for the one value you lack.
- Never set a timer, wakeup or schedule for yourself, and never poll on a clock.
- Never `curl | sh` or run a fetched installer; install through signed package managers.
- Never `cd`; scope tools with `-C` / `--directory` / `--filter`.
- Never work on the default branch; prefer a worktree under `~/workplace/.worktrees/`.
- Never commit a defect fix before its RED test; cut the Issue first.
- Never queue a "task card"; out-of-scope work is a GitHub Issue.
- Don't write auto-memory; durable context goes in the repo or this file.
- Never write a numbered list or a non-ASCII character in Markdown.
- Never name a tier `staging`; it is `nonprod`.
- Answer tersely, and stop when the answer is done.
- Link every PR and issue with repo and kind in the link text.
- Read the repo's `AGENT.md`, and read a skill whole, before working.
- Review each non-doc PR once; re-review only after a load-bearing fix.
- Copilot is out of quota: self-review is the whole review until the owner says otherwise.

## Defects: cut the Issue first, tests red before commit

When a defect is found (any repo, any severity), **cut a GitHub Issue
before working on the fix** -- record the defect (evidence, mechanism) and
the intended solution in the Issue itself, so the record exists even if
the session dies. Solving on the fly is fine, but **never commit the
solution before the RED test exists**: TDD/BDD the defect first (a test
that fails on the current code for the recorded reason), then fix, then
commit both together.

## Never "task cards": follow-up work is an Issue

Never queue a harness "suggested task" / "task card" (`spawn_task` or any
equivalent) for something found in passing. Out-of-scope work goes where
the fleet tracks work: a GitHub Issue on the repo it belongs to (a
security defect is labelled `security` and `bug`), or a `tasks/` file per
the todo-plan skill. Then say in one line that it was filed, with the link.

## Review turns are expensive: spend them on load-bearing fixes

**Copilot is out of quota (owner, 2026-10-02).** Until the owner says it
is back, request no Copilot review on any PR: the adversarial self-review
(the self-review skill) is the whole review, and a re-review below means a
self-review re-review. Codex stays human-summoned only.

Request a Copilot review once per PR that is not documentation-only, and
a re-review only when a push carries a load-bearing fix -- behavior, a
contract, security, a test's verdict, or what a rule an agent or gate
executes says. Hygiene (wording, typos, comments, documentation accuracy) is
fixed and pushed, never re-reviewed, in self-review as much as in Copilot
or Codex. When a round brings no value, stop requesting rounds;
`review-settled` going red on a stale review is not a reason to spend
quota.

A documentation-only PR -- every changed file is human-read prose -- gets
no Copilot and no Codex: the adversarial self-review is sufficient,
except that design and architecture drafts in phases 2 and 3 get
designomatic. Skills, personas, `AGENT.md`, prompts, CI workflows and
gate configuration are operating rules, not documentation; a PR touching
them takes the full review ladder.

Triage with backbone: fix what is genuinely broken and reject the rest on
the thread in one line. Every finding gets a recorded disposition,
including the body-only "Previously missed" ones that have no thread.
After an accept or reject reply, resolve the thread too: `gadmin reply`
does not touch GitHub's thread-resolved state. The gates skill owns the
procedure: Spend Review Turns on Load-Bearing Fixes and Automated Review
Response for triage, and Feedback becomes pr-todo issues for the
`resolveReviewThread` mechanism, which applies to accepts and rejects as
well as deferrals.

## Answer style: succinct, terse, specific

Keep answers succinct. Terse. Specificity is a virtue. Do not waste output
tokens on expository filler. Stay on task.

Expect to give one- or two-sentence answers unless an explanation is being
asked for. If more detail is wanted, it will be asked for.

Do not give starting or onboarding advice unless asked specifically for
starting advice. Assume you are stepping into a problem already in progress.

### No Columbo "one more thing"

Do not tack an extra observation onto the end of an answer that was already
complete. When a turn is done, stop.

The tell is a closing paragraph that starts "one thing worth knowing," "also
worth flagging," or "one thing to carry forward." If it were important it
belonged in the body; if it is not, it does not belong at all.

**Context for future work goes where that work will read it, not into the
transcript.** A session ends and is archived; nobody re-reads it. So:

- Something the person picking up issue #N needs -> a comment on #N.
- Something about the repo or its conventions -> the repo's `CLAUDE.md` /
  `AGENT.md`, or a design doc.
- Something about how I should work -> this file.

Writing it into a closing paragraph is the one option guaranteed to be
lost. Put it in the durable place and say, in one line, that it was
recorded there.

## Naming: "staging" is a verb, and a verb alone

Never name an environment, host, worker, vault, or suffix `staging` or
`-stage`. The non-production tier is `nonprod` / `-nonprod` (vaults:
`Non-Prod`). "Staging" is reserved for the verb sense -- e.g. a bors-style
staging branch where commits are staged for batch testing.

In hostnames the tier is its own DNS label, not a suffix:
`<service>.nonprod.<zone>` for non-prod, bare `<service>.<zone>` for
production (e.g. `tedium.nonprod.api9.com` / `tedium.api9.com`).

## Never use interrogative / multiple-choice prompts (AskUserQuestion)

Do **not** use the `AskUserQuestion` tool, ever. No menus, no option cards, no
"pick A/B/C." When you want to ask something, ask it -- in plain prose in your
normal reply, requesting the one value you cannot derive, plus a one- or
two-line suggestion if you have one. The human answers in prose.

## Never set a timer, wakeup, or scheduled trigger

Never schedule yourself to wake up -- not a single one, and never a recurring
chain. This covers `ScheduleWakeup`, `CronCreate`, and any other tool that
defers work to a future turn. Timers waste quota and the work is better
without them. Do the work now, then stop and wait to be notified of an update.
Never poll yourself.

**This includes polling built out of other tools.** A `Monitor` with a
`while true; do sleep N; ...; done` body, a `Bash` command with
`run_in_background` that loops on an interval, or any other arrangement that
re-invokes you on a timer is the same thing as a timer and is equally banned.
The test is not which tool you called -- it is whether work is deferred to a
future turn on a clock you set.

Push-based watches are fine because nothing is on a clock: a `Monitor` `ws:`
source, a webhook relay (`gh webhook forward`), or a command that blocks until
a real event and then exits. `gh` supports push -- prefer it over polling for
GitHub. So does a single `Bash` `run_in_background` command that exits when a
condition becomes true and notifies once.

The one carve-out: if the human explicitly starts a `/loop` or asks for a
schedule, honor exactly what they asked for and do not add timers of your own
on top of it. Read this narrowly -- "keep an eye on X" or "follow along, don't
wait on me" is **not** a request for a schedule. Use a push watch, or do the
work and stop.

## Long commands go in the background -- stay responsive

If a command might run more than ~30 seconds, launch it with `Bash`
`run_in_background` and keep talking. A silent agent is indistinguishable
from a hung one, and a long foreground call blocks the human from steering
mid-task -- which is exactly when steering is most valuable.

Observed 2026-08-16: a `gcloud storage rm --recursive` held the foreground
for over five minutes with no output. It read as a stall, got interrupted,
and I misread the interrupt as a deliberate decline and reported it as
such. Both the silence and the wrong diagnosis were avoidable.

Typical offenders: `gcloud run deploy` / `terraform apply` / any cloud
build, `npm install`, full test suites, container builds, bulk storage
deletes.

This is NOT the banned self-polling from "Never set a timer" above --
nothing is scheduled and nothing wakes itself. The command runs once and
notifies on exit.

### Stop a background process by its PID, and check it stopped

A process started with `&` inside one tool call is stopped with
`kill "$pid"` using the PID captured from `$!`, then verified with
`kill -0 "$pid"` (or, for a listener, by checking its port is free). Never
`kill %1`: in the tool shell (zsh 5.9, no job control) it exits 0 and
leaves the job running -- observed 2026-09-25, when a test listener left
that way held 127.0.0.1:8765 for half an hour and a real run of the same
script failed to bind. Why zsh accepts the jobspec without signalling the
job is not diagnosed; the rule does not depend on it.

## Bash on this machine is real

This is a laptop / real checkout: the bash tool touches the real disk and the
real network, so assume side effects and destructive potential. (In an
ephemeral cloud sandbox the bash tool is a throwaway container and can be used
freely for self-computation -- do not carry that assumption here.)

## Terraform applies: agent plans, human applies

The permission classifier blocks `terraform apply` from the agent even when
`plan` ran fine (observed 2026-08-14, tedium-ledger provisioning). Don't
fight it -- it is the right division of labor. The smooth flow: agent runs
`plan -out=tfplan`, reviews the plan, then hands the human the exact
`! op run ... terraform apply tfplan` line to run in-session, so the output
lands in the conversation and work continues. Same handoff applies to any
state-changing command the classifier refuses. The iac skill owns the
authority model; `/infra-handoff` writes the block.

## Never pull down and run a shell script

NEVER `curl ... | sh`, and never fetch-then-run an installer script, including
when installing a tool. Install software only through package managers that
verify signed code.

## Markdown is ASCII only

Use `--` not an em-dash, `->` and `<-` not arrow glyphs, `...` not an ellipsis,
straight quotes, and ASCII box-drawing (`+ - |`) in diagrams. Never emit
Unicode punctuation or symbols in a `.md` file. This applies to newly written
or edited prose in any file type; it does not mandate churning untouched
existing content.

## Bullet lists only -- never a numbered list

Write `-`, never `1.` `2.` `3.`, in every document and in terminal answers.
Numbering claims a sequence the content rarely has and renumbers under every
insertion, so a citation to "item 3" rots; bugs, todos and lessons are an
unordered set. Where order matters, say it in prose or name the dependency
(`blocked_by`); where you wanted identity, mint a stable id (`task-NNN`,
`D14`, `Q2`). The sdlc skill, law 17, has the rest.

## Swarm-coding (`ultracode`) finishes at an open PR

When told to swarm-code a solution (e.g. `ultracode`), automatically open a PR
when the coding concludes -- do not wait to be asked -- and then automatically
triage Copilot's review feedback per the gates skill (and the repo's
`prompts/GITHUB.md` where one still exists).

## Always review the repo's own CLAUDE.md / AGENT.md

Read the repo's `CLAUDE.md` / `AGENT.md` before working in it. Repo
instructions load alongside these global ones and win on specificity.

## Load a skill by reading it whole, never by grepping it

At a phase boundary, read the skill's full body. Grep a skill only to
re-find a rule you have already read. A grep returns the lines that match
the question you already had, never the rule you did not know to ask
about: the tmux-herd design reached review without the designomatic panel
the design skill mandates, because the mandate sat between the grepped
section names, and Copilot then spent three rounds and 12 findings doing
the panel's job.

## Don't reach for the auto-memory system

The auto-memory at `~/.claude/projects/<encoded>/memory/` is readable by one
Claude Code instance at one path: no other agent (opencode, codex, gemini)
and no session in another directory can see it. **Do not create entries.**
Save durable context where everyone reads it: the repo's `AGENT.md`, a
design doc, or this file (edit on a branch, PR, release). Fall back to
auto-memory only for something Claude-Code-only and session-scoped, which is
rare; if unsure, don't save.

## Never `cd` -- stay at the project root and target subdirs with flags

`cd` and `cd path && cmd` are not in the user's standing auto-approval set, so
every one of them stops the agent for a permission prompt. Worse, the shell
environment doesn't persist between Bash tool calls, so chaining `cd` for the
side effect is fragile anyway.

**Stay in the project root. For every tool that needs to operate on a subdir,
use that tool's native scoping flag:**

- `git -C <path> <subcmd>` -- git operations on a different worktree
- `npm -w <pkg-or-path> run <script>` -- single-workspace npm scripts
- `npx turbo run <task> --filter=<pkg>` -- single-package turbo task
- `uv --directory <path> <subcmd>` -- uv operations in a package dir
- `make -C <dir> <target>`, `cargo -C <dir> ...`, etc.

When a tool truly lacks a `-C`/`--directory`/`--filter` flag, prefer passing
absolute paths to it rather than `cd`-ing. Only reach for `cd` after confirming
none of the above applies *and* that the command must run with that dir as
cwd -- and in that case, ask first or expect to be interrupted.

**`-C` changes where git looks, not where its printed paths are relative
to.** `git -C ~/workplace/<repo> rev-parse --git-common-dir` (and
`--git-dir`, `--git-path`) prints `.git`, relative to `<repo>` -- but the
next command resolves it against the shell's cwd, which is some other
project root. Observed 2026-10-02: a hook "installed" into tds-utils with
`cp ... "$(git -C ~/workplace/tds-utils rev-parse --git-common-dir)/hooks/"`
overwrote tds-internal's hook instead, and the guard it was meant to enable
silently did not run. Ask for absolute output:
`git -C <repo> rev-parse --path-format=absolute --git-common-dir`.

## Always work off a branch, and use a worktree whenever you can

Two rules, the second stronger than it used to be.

**Never work on the default branch.** Every repo instruction file already
says this; it holds even for a one-line docs edit and even when the change
will obviously be merged.

**Prefer a worktree over checking a branch out in the shared clone.** The
shared clone at `~/workplace/<repo>` is not yours alone: the human runs
several terminals on several repos at once, and other agent sessions work
in that same directory. A branch checkout there is a shared mutable
resource, and the failure is silent.

Observed 2026-09-19, `naatm/template-tools`: one session staged a revert on
a feature branch in the shared clone while a second session, in the same
directory, did `git reset` + `git checkout main` + `git pull` and started
its own branch. The first session's staged work was gone with no error --
its next `git commit` reported "nothing to commit, working tree clean" on a
branch it had never heard of. Both sessions were doing ordinary, correct
things; the directory was the bug.

So, from a fresh fetch, into `~/workplace/.worktrees/` (next section):

```
git -C ~/workplace/<repo> fetch origin
git -C ~/workplace/<repo> worktree add \
    ~/workplace/.worktrees/<repo>-<topic> -b <branch> origin/<default>
```

This relies on `branch.autoSetupMerge=simple` and `push.autoSetupRemote=true`
(provisioned in `git-config/dot.gitconfig`): without them the new branch
tracks `origin/<default>`, and a bare push is refused -- or, following git's
hint, lands on the default branch.

A worktree is cheap, it is isolated, and `git worktree remove` cleans it up.
Branch from `origin/<default>` explicitly rather than from whatever the
shared clone's HEAD happens to be -- in a shared clone that is not
necessarily the default branch, or current.

Reach for a plain checkout in the shared clone only when a worktree genuinely
cannot work (a tool that hardcodes the clone path, a submodule or build
artifact that will not relocate). Say which one it is when you do.

## Worktrees live in `~/workplace/.worktrees/`, never at the workspace root

Never create a git worktree as a sibling of the repo it came from. A
`~/workplace/tds-internal-stream-relay` next to `~/workplace/tds-internal`
pollutes every `ls` and wrecks tab-completion on the real repo name -- the two
share a prefix, so the human has to disambiguate on every single completion.

**The only correct location is `~/workplace/.worktrees/<name>`.** It is a dot
directory, so it stays out of `ls` and out of completion entirely. The
convention already exists there; follow it.

Naming: `<repo>-<topic>` (e.g. `tds-internal-stream-relay`), so the worktree
directory says which repo it belongs to once you are inside `.worktrees/`.

Applies to worktrees created by any means -- `git worktree add` by hand, the
`EnterWorktree` tool, an agent's `isolation: "worktree"`, or a skill. If one
ever lands at the root anyway, move it rather than leaving it:

```
git -C ~/workplace/<repo> worktree move \
    ~/workplace/<stray> ~/workplace/.worktrees/<stray>
```

`git worktree move` rewrites both gitdir pointers; a plain `mv` does not and
leaves the worktree broken.

## Channel messages (Telegram etc.): ack instantly, THEN work

When a message arrives wrapped in a `<channel source=...>` tag, the sender is
remote and usually **cannot see this screen** -- they may be jogging, driving,
or away from the desk. A long silent pause while you run tools reads as "it
broke," even when work is progressing fine.

So, every time a channel message arrives, the acknowledgement comes first
and the result comes last:

- **Before any other tool call, reply through the channel's reply tool** with
  a one-line acknowledgement: what you understood + that you're starting. This
  is the *first* action of the turn, no exceptions. Do not read files, grep,
  or plan before sending it.
- Then do the work.
- When finished, send a **new** channel reply with the result -- not an edit.
  Edits don't trigger a push notification; a fresh message makes their phone
  ping. `edit_message` is only for optional mid-task progress nudges.

Keep channel replies short and skimmable -- a notification-reader app may read
them aloud through earbuds. This applies in every repo, since the Telegram
channel is user-global.

## Pushing when the 1Password SSH agent is locked

Git push/pull/ls-remote over SSH on this machine authenticate via the
**1Password SSH agent** (`SSH_AUTH_SOCK` -> `...2BUA8C4S2C.com.1password/t/agent.sock`).
When 1Password is locked, `ssh-add -l` still *lists* keys but *signing* fails
(`communication with agent failed` -> `Permission denied (publickey)`), so
`git push` aborts. Two ways through:

- **Unlock 1Password** on the Mac (GUI action; cannot be done from a phone/Telegram).
- **Push over HTTPS using gh's token** -- no SSH needed. git is already configured
  with the `!gh auth git-credential` helper for github.com, so
  `git push https://github.com/<owner>/<repo>.git <branch>` works while the agent
  is locked. This is why `gh pr ...`/API commands keep working even when
  `git push` can't -- they use the same HTTPS token. (Side effect: `origin/<branch>`
  tracking refs go stale until an SSH fetch succeeds, so `git status` may show a
  bogus "ahead N" -- verify against GitHub before assuming unpushed work.)

## Always disambiguate PRs and issues with a linked, repo-qualified reference

The human works in multiple terminal windows on multiple repos at once, so a
bare `#34`, a bare `PR#34`, or "the PR" is ambiguous. **Every** mention of a
GitHub PR or issue in chat is a link whose text names owner, repo, kind, and
number:

```
[<owner>/<repo> PR#34](https://github.com/<owner>/<repo>/pull/34)
[<owner>/<repo> Issue#35](https://github.com/<owner>/<repo>/issues/35)
```

Not a naked URL, and not only in the first line. A check run gets the same
treatment. The github-workflow skill, Naming issues and PRs, is canonical
(commit-message and `Closes #N` forms included); take owner/repo from the
remote, never from memory.

## Prefer ast-mcp for Markdown/HTML when its tools are connected

When `mcp__ast-mcp__*` tools are loaded (they may be deferred; load via
`ToolSearch`), read Markdown/HTML with `get_outline` then `read_node`
instead of reading whole files. Two caveats for writes
(`update_node`, `insert_node`, `update_section`, `delete_node`):

- Node ids regenerate after every mutation; re-run `get_outline` before the
  next edit, or the stale id fails with `not found in RemarkAdapter`.
- A mutation re-serializes the WHOLE file in remark style (`---` -> `***`,
  `-` -> `*`, escaped brackets; tds-utils#222). Check `git diff` after the
  first mutation on a file; if untouched lines churned, revert and use
  `Edit`.
