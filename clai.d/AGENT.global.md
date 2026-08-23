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

## Defects: cut the Issue first, tests red before commit

When a defect is found (any repo, any severity), **cut a GitHub Issue
before working on the fix** -- record the defect (evidence, mechanism) and
the intended solution in the Issue itself, so the record exists even if
the session dies. Solving on the fly is fine, but **never commit the
solution before the RED test exists**: TDD/BDD the defect first (a test
that fails on the current code for the recorded reason), then fix, then
commit both together.

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

## Resolve the review thread when you accept or reject it

An accept/reject reply on a PR review comment is only half the job:
`gadmin reply` does not touch GitHub's thread-resolved state. After every
accept or reject reply, also resolve that sub-thread via the GraphQL
`resolveReviewThread` mutation (thread node ids come from the
`reviewThreads` query, matched by first comment `databaseId`). The
github-workflow skill documents this mechanism for deferred threads; it
applies to accepts and rejects too.

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
state-changing command the classifier refuses.

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

## Swarm-coding (`ultracode`) finishes at an open PR

When told to swarm-code a solution (e.g. `ultracode`), automatically open a PR
when the coding concludes -- do not wait to be asked -- and then automatically
triage Copilot's review feedback according to the repo's `GITHUB.md`
instructions.

## Always review the repo's own CLAUDE.md / AGENT.md

Read the repo's `CLAUDE.md` / `AGENT.md` before working in it. Repo
instructions load alongside these global ones and win on specificity.

## Don't reach for the auto-memory system

The project-scoped auto-memory at `~/.claude/projects/<encoded>/memory/` is
readable only by this Claude Code instance tied to that path. Other AI agents
(opencode, codex, gemini, cursor, aider, etc.) cannot read those files. A
fresh Claude session in a different working directory cannot either. Notes
saved there are effectively private to one process.

**Default: do not create new auto-memory entries.** When something is worth
saving, prefer locations that other agents and future sessions can read:

- `<repo>/CLAUDE.md` or `<repo>/AGENT.md` -- version-controlled with the
  project, visible to every agent that walks the repo for instructions.
- `clai.d/AGENT.global.md` in tds-utils (this file) -- the global agent
  instructions, reaching every agent on this machine via the `release` worktree
  and surviving every session. Edit on a branch, PR, then release to `release`.
- A design doc in the repo (`docs/design/...`, `packages/*/docs/...`) -- for
  durable decisions, with rationale, that anyone can read.

Only fall back to the auto-memory system when the rule is genuinely
Claude-Code-only, session-scoped, and inappropriate for any of the above --
which is rare. If unsure, don't save. Smaller memory state is better than a
sprawling private garden no one else can see.

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

## Worktrees live in `~/workplace/.worktrees/`, never at the workspace root

Never create a git worktree as a sibling of the repo it came from. A
`~/workplace/tds-internal-stream-relay` next to `~/workplace/tds-internal`
pollutes every `ls` and wrecks tab-completion on the real repo name -- the two
share a prefix, so the human has to disambiguate on every single completion.

**The only correct location is `~/workplace/.worktrees/<name>`.** It is a dot
directory, so it stays out of `ls` and out of completion entirely. The
convention already exists there; follow it.

```
git -C ~/workplace/<repo> worktree add \
    ~/workplace/.worktrees/<repo>-<topic> <branch>
```

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

So, every time a channel message arrives:

1. **Before any other tool call, reply through the channel's reply tool** with
   a one-line acknowledgement: what you understood + that you're starting. This
   is the *first* action of the turn, no exceptions. Do not read files, grep,
   or plan before sending it.
2. Then do the work.
3. When finished, send a **new** channel reply with the result -- not an edit.
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

## Always disambiguate PRs and issues by full URL

The human works in multiple terminal windows on multiple repos at once, so a
bare `#34` or "the PR" is ambiguous. When reporting on a GitHub PR, issue, or
check run, include the **full URL** (e.g.
`https://github.com/<owner>/<repo>/pull/<n>`) in the first line of the update.
The repo's `gh` config or the branch's upstream remote tells you the
owner/repo; never guess from memory.

## Prefer ast-mcp for Markdown/HTML when its tools are connected

ast-mcp is a token-efficient navigation/RAG tool for Markdown and HTML, and as
of 0.3.2 it is fully read **and** write capable (tds-utils#73 fixed in
9atatimer/ai-tools#75; verified live 2026-07-11).

When the `mcp__ast-mcp__*` tools are available this session:

- **Read / navigate** with `get_outline`, then `read_node` for only the node(s)
  you need, instead of `Read`-ing whole `.md`/`.html` files or `grep`-ing for
  line ranges.
- **Edit in place** with `update_node`, `insert_node`, `update_section`, and
  `delete_node`.

One caveat, empirically confirmed: **node IDs are document-state-derived and
regenerate after every mutation.** Re-run `get_outline` before the next edit
rather than reusing an ID from an earlier outline -- a stale anchor fails with
`not found in RemarkAdapter`.

A second caveat (2026-08-14, tds-utils#222): **a mutation re-serializes the
WHOLE file in remark canonical style**, not just the edited node -- `---`
becomes `***`, `_em_` becomes `*em*`, `-` bullets become `*`, literal
brackets get escaped. On any file not already in that style the churn swamps
the real change and violates repo formatting rules. Until fixed: use ast-mcp
freely for READS, but check `git diff` after the first mutation on a file --
if it churned untouched lines, revert and use plain `Edit` instead.

When the tools aren't loaded (they may be deferred -- load via `ToolSearch`) or
the file isn't Markdown/HTML, just use `Read`/`Edit`/`Write` as normal.
