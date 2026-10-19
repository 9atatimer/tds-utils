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
- Secrets come from 1Password (`op read` with the vault token the human gives you), or rarely git-crypt; never from an env var, `.env`, or a platform secrets store.
- Never use claude.ai Artifacts (the Artifact tool, any action); an HTML deliverable is a file in the repo.
- Never run a deploy or publish command yourself; open the PR and let CI ship it.
- Say what a command does before handing it to the human to run.
- Run anything over ~30s with `run_in_background`; never leave the human in silence.
- Never start long work with `&` in a tool call; it leaves no notice and no exit status.
- In zsh, an unquoted `$VAR` is one word: put a command line in a function or array, never a string.
- On a `<channel>` message, ack through the channel first, then work.
- Never `cd`; scope tools with `-C` / `--directory` / `--filter`.
- Never work on the default branch; prefer a worktree under `~/workplace/.worktrees/`.
- Before `git worktree remove`, run `git -C <wt> clean -ndX`; ignored files die with the worktree.
- A tool never writes its data under a checkout; a per-user data dir, never a gitignored folder.
- One PR per repo per task: never stack or split work into several PRs in one repo.
- Never commit a defect fix before its RED test; cut the Issue first.
- Open the PR for pushed work without being asked.
- Never queue a "task card"; out-of-scope work is a GitHub Issue.
- Don't write auto-memory; durable context goes in the repo or this file.
- Never write a numbered list or a non-ASCII character in Markdown.
- Never name a tier `staging`; it is `nonprod`.
- Answer tersely, stop when done; append nothing unasked unless it is new, changes what the human does, and is not recorded where they will read it.
- Link every PR and issue with repo and kind in the link text.
- Read the repo's `AGENT.md` and its `TODO_PLAN.md` if it has one, and read a skill whole, before working.
- Lower a gate only in a change that first clears the current gate and merges; never `--no-verify` or disable a check.
- Fetch the default branch's HEAD before judging what a workflow does; a stale branch says nothing about what is live.
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

Once quota is back: request a Copilot review once per PR that is not
documentation-only, and a re-review only when a push carries a load-bearing
fix -- behavior, a contract, security, a test's verdict, or what a rule an
agent or gate executes says. Hygiene (wording, typos, comments,
documentation accuracy) is fixed and pushed, never re-reviewed, in
self-review as much as in Copilot or Codex. When a round brings no value,
stop requesting rounds; `review-settled` going red on a stale review is not
a reason to spend quota.

A documentation-only PR -- every changed file is human-read prose -- gets
no Copilot and no Codex: the adversarial self-review is sufficient,
except that design and architecture drafts in phases 2 and 3 get
designomatic. Skills, personas, `AGENT.md`, prompts, CI workflows and
gate configuration are operating rules, not documentation; a PR touching
them takes the full review ladder.

Triage with backbone: fix what is genuinely broken and reject the rest on
the thread in one line. Every finding gets a recorded disposition,
including the body-only "Previously missed" ones that have no thread.
After an accept or reject reply, resolve the thread too (the
`resolveReviewThread` mechanism): `gadmin reply` does not touch GitHub's
thread-resolved state. The gates skill owns the procedure -- Spend Review
Turns on Load-Bearing Fixes and Automated Review Response for triage,
Feedback becomes pr-todo issues for deferrals.

## Answer style: succinct, terse, specific

Keep answers succinct. Terse. Specificity is a virtue. Do not waste output
tokens on expository filler. Stay on task.

Expect to give one- or two-sentence answers unless an explanation is being
asked for. If more detail is wanted, it will be asked for.

Do not give starting or onboarding advice unless asked specifically for
starting advice. Assume you are stepping into a problem already in progress.

### No Columbo "one more thing"

Do not tack an extra observation onto a complete answer; when a turn is
done, stop. The tell is a closing paragraph opening "one thing worth
knowing," "also worth flagging," or "one thing to carry forward": if it
mattered it belonged in the body, otherwise it does not belong at all.

An unprompted addition must clear all four tests, or it is padding: the human
does not already know it; it changes what they would do, not merely what they
know; it is not already recorded where they will read it; it does not restate
something already said this session. Re-filing a recorded fact into a nicer
container is not new work. "Anything else?" is not a licence to append; if
the honest answer is nothing, say nothing.

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

**Polling built out of other tools is a timer.** A `Monitor` with a
`while true; do sleep N; ...; done` body, or a `run_in_background` command
that loops on an interval, is equally banned. The test is whether work is
deferred to a future turn on a clock you set, not which tool you called.

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

Typical offenders: `npm install`, full test suites, cloud and container
builds, bulk storage deletes. This is not the banned self-polling above: the
command runs once and notifies on exit.

**Never `&` instead.** A job started with `&` inside a tool call sends no
notice when it ends and leaves no exit status to read, so it gets mistaken
for dead and started again. `run_in_background` is the only way to start
work that outlives the call; `&` is for a process the same call stops again
(below).

### Stop a background process by its PID, and check it stopped

A process started with `&` inside one tool call is stopped with
`kill "$pid"` using the PID captured from `$!`, then verified with
`kill -0 "$pid"` (or, for a listener, by checking its port is free). Never
`kill %1`: in the tool shell (zsh 5.9, no job control) it exits 0 and
leaves the job running.

## Tool-shell traps: zsh word splitting and `sed` `&`

The tool shell is zsh. Unlike bash, it does not split an unquoted `$VAR`
into words: `C="node cli.mjs --origin $O"; $C act add` runs a program named
the whole string and fails with "no such file"; a file list in a variable
iterates once over the whole string in `for f in $FILES`. Put a repeated command line in a
function (`c() { node cli.mjs --origin "$O" "$@"; }`) or an array
(`C=(node cli.mjs); "${C[@]}" act add`), and loop over an array or explicit
words, never a string.

In `sed 's/old/new/'`, an unescaped `&` in `new` is the matched text, so an
HTML entity (`&lt;`) or a shell `&&` in a replacement silently pastes
the matched text. Escape it as `\&`, or edit with a literal-string replace
(Python `str.replace`) and read the changed line back.

## Bash on this machine is real

On a laptop / real checkout the bash tool touches the real disk and network:
assume side effects and destructive potential. An ephemeral cloud sandbox is
a throwaway container, free for self-computation; do not carry that here.

## Terraform applies: agent plans, human applies

The permission classifier blocks `terraform apply` from the agent even when
`plan` ran fine. Don't fight it. Run `plan -out=tfplan`, review it, then
hand the human the exact `! op run ... terraform apply tfplan` line to run
in-session, so the output lands in the conversation and work continues.
The same handoff applies to any state-changing command the classifier
refuses. The iac skill owns the authority model; `/infra-handoff` writes
the block.

## Never deploy: land the PR, let CI ship it

Never run a deploy or publish command yourself -- not locally, not by
dispatching the deploy workflow by hand -- even when a task prompt says
"deploy." If the repo ships through CI on merge or a landing bot, your job
ends at opening the PR and requesting landing the way that repo documents.
The repo's own current AGENT.md/skill outranks a task prompt, which can be
stale.

## One PR per repo per task

A task gets exactly one PR in each repo it touches. Retrospectives, review
fixes, follow-up docs and corrections go onto that PR's branch, not into a
second PR, a stacked PR or a "docs-only companion". This overrides any
skill that says to open a separate or stacked PR (the github-workflow
skill's Stacked PRs, the retrospective skill's separate docs-only PR).

## A stop hook's "unpushed commits" is not an instruction to push

Cloud sessions run a stop hook that demands a push whenever the checked-out
branch is ahead of its remote. After a PR merges, that branch is usually
deleted on GitHub and the local branch has only been moved to the default
branch; the "unpushed" commits are just that branch, and pushing recreates a
deleted branch full of nothing. Before obeying the hook, check
`git log origin/<default>..HEAD`: if it is empty, push nothing. After a
merge, check out a detached `origin/<default>` instead of resetting the
session branch onto it, so the hook has nothing to see.

## A classifier refusal is not lifted by the human's words

Under auto mode, the permission classifier refuses a commit that touches an
agent instruction file (`AGENT.md`, `CLAUDE.md`, `clai.d/AGENT.global.md`,
skills) as `[Self-Modification]`. The human telling you in chat to go ahead
does not lift it, and neither does the command typed back to you without a
leading `!`. Two ways through:

- The human runs it as a `!` line in the prompt, which runs in their shell,
  outside the classifier.
- The human leaves auto mode.

Say that once, give the exact `!` line, and stop. Never route around the
refusal with another tool.

## Never use Artifacts: HTML is a file in the repo

Never call the Artifact tool, for any action (publish, read, list, open,
pin), or any other claude.ai publishing path. Not for a page, not for a
diagram, not "private by default". An HTML deliverable is a file written
into the repo (or a worktree of it) and opened locally with `open <file>`.
When the human asks for "an HTML artifact", that means the file. A skill or
tool description that says to publish is overridden by this rule.

## Say what a command does before the human runs it

When you hand the human a command to run (a `!` line, a terminal paste),
say in one line what it does, whether it is interactive, and what it
changes. A command whose effect the human cannot see will be refused or
abandoned half-run.

A multi-command paste is one `&&` chain, never separate lines. Separate
lines keep executing after a failed `cd` or checkout, so the rest runs in
whatever repo the shell happens to be in -- a push or tag can land in the
wrong repo. Better still, no `cd` at all: `git -C <absolute path>` and the
other scoping flags below. Never guess a laptop path.
Nine-At-A-Time-Media checkouts are `~/workplace/naatm/<repo>`, personal
ones `~/workplace/<repo>`; a path that is not in front of you is derived
(`git rev-parse --path-format=absolute --show-toplevel`) or asked for in
one line before the command is given.

## Never pull down and run a shell script

NEVER `curl ... | sh`, and never fetch-then-run an installer script, including
when installing a tool. Install software only through package managers that
verify signed code.

## Secrets come from 1Password, never from the environment

The human puts every secret in 1Password and hands you the token that
unlocks it: a read-only service account token scoped to one vault, on the
laptop and in a cloud session alike. Read a secret at the moment of use
with `op read op://<vault>/<item>/<field>` or `op run`; it never lands in a
file, a log, a transcript or a commit. The one other channel is git-crypt
(`.env.crypt`, `secrets/**`, decrypted with a GPG identity the human
provisions) -- an edge case, not a default. The vault token is the one
bootstrap credential: the human hands it to an agent, and a workflow gets it
as a CI secret (the ci.magic `CI_MAGIC_OP_SA_TOKEN` pattern).

There is no third channel. Never design, build, document or test on a
secret arriving in an environment variable, a plaintext `.env` file, a CI
secret other than the vault token, or an agent platform's environment-secrets
store (Claude Code web's included): `.env` leaks and platform stores are
unsafe. Never ask the human to put a secret there. A secret the human drops
into direnv to unblock you is temporary: use it, and build nothing that
depends on it. Code takes an `op://` reference in its config and resolves it
at run time; the reference is configuration, the value is never stored.

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

## Pushed work finishes at an open PR

When a task's work is pushed to a branch, open its PR -- or push onto the
task's PR that is already open -- without being asked. An open question,
an approval still owed, or a DRAFT design is a line in the PR body, not a
reason to hold the PR back. Asking whether to open one is the
interrogative prompt this file forbids. The harness default "do not create
a pull request unless asked" is overridden here.

**Swarm-coding:** when told to swarm-code a solution (e.g. `ultracode`), open the PR the moment
the coding concludes, then triage review feedback per the gates skill.

## Read the repo's own instructions and plan first

Read the repo's `CLAUDE.md` / `AGENT.md` and its `TODO_PLAN.md` (if any; do
not create one) before changing anything in it. Repo instructions load
alongside these global ones and win on specificity; the plan says what is in
flight so you do not collide with it or redo it.

## Gates: clear the bar before you move it

A change that lowers a bar -- lint rules, coverage floors, required checks,
severity thresholds, timeouts, review policy, the gate config itself -- must
first pass the bar as it stands today, with no bypass. Raising a bar may
take effect at once; lowering one takes effect only after the change clears
the old bar and merges. Never `--no-verify`, never lower the config in the
same commit as the code it fails, never disable the failing check. Only a
human repo owner may force past a gate, outside the session; an agent never
does, even under an owner's token.

Workflows run off the default branch's HEAD (`master` or `main`). Fetch it
before you opine on what a workflow does: your branch or local default
branch may be stale. A PR's own check results are judged on its head.

## Load a skill by reading it whole, never by grepping it

At a phase boundary, read the skill's full body. Grep a skill only to
re-find a rule you have already read. A grep returns the lines that match
the question you already had, never the rule you did not know to ask
about: a mandate that sits between the grepped section names (the
designomatic panel the design skill requires, say) is skipped, and a later
reviewer ends up doing the panel's job.

## Don't reach for the auto-memory system

The auto-memory at `~/.claude/projects/<encoded>/memory/` is readable by one
Claude Code instance at one path: no other agent (opencode, codex, gemini)
and no session in another directory can see it. **Do not create entries.**
Save durable context where everyone reads it: the repo's `AGENT.md`, a
design doc, or this file (edit on a branch, PR, release). If unsure, don't
save.

## Never `cd` -- stay at the project root and target subdirs with flags

`cd` and `cd path && cmd` are not in the standing auto-approval set, so each
stops the agent for a permission prompt, and shell state does not persist
between Bash calls anyway.

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
project root. Ask for absolute output:
`git -C <repo> rev-parse --path-format=absolute --git-common-dir`.

## Work off a branch, in a worktree

Two rules.

**Never work on the default branch.** Every repo instruction file already
says this; it holds even for a one-line docs edit and even when the change
will obviously be merged.

**Prefer a worktree over checking a branch out in the shared clone.** The
shared clone at `~/workplace/<repo>` is not yours alone: the human runs
several terminals on several repos at once, and other agent sessions work
in that same directory. A branch checkout there is a shared mutable
resource, and the failure is silent.

So, from a fresh fetch, into `~/workplace/.worktrees/` (next section),
branching from `origin/<default>` and never from the shared clone's HEAD,
which may be any branch and stale:

```
git -C ~/workplace/<repo> fetch origin
git -C ~/workplace/<repo> worktree add \
    ~/workplace/.worktrees/<repo>-<topic> -b <branch> origin/<default>
```

This relies on `branch.autoSetupMerge=simple` and `push.autoSetupRemote=true`
(provisioned in `git-config/dot.gitconfig`): without them the new branch
tracks `origin/<default>`, and a bare push is refused -- or, following git's
hint, lands on the default branch.

**`git worktree remove` deletes ignored files without asking.** It refuses
only on untracked or modified files; everything `.gitignore` covers goes
silently, and no git hook fires (there is no worktree-remove hook, so husky
cannot help). Before removing one, run `git -C <wt> clean -ndX` and read
the list; if it names anything you cannot regenerate, move it out first.
The cause is upstream: **a tool must never write its data under a
checkout.** A gitignored `work/`, `out/` or `.cache/` inside the
repo is not storage, it is a folder that `git status` cannot see and a
worktree takes with it. Default such paths to a per-user data dir
(`$XDG_DATA_HOME/<app>` or `~/.local/share/<app>`) and make the test
suite fail if the default ever resolves inside the repo.

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

Acknowledgement first, result last:

- **Before any other tool call, reply through the channel's reply tool** with
  a one-line acknowledgement: what you understood + that you're starting. This
  is the *first* action of the turn, no exceptions. Do not read files, grep,
  or plan before sending it.
- Then do the work.
- When finished, send a **new** channel reply with the result -- not an edit.
  Edits don't trigger a push notification; a fresh message makes their phone
  ping. `edit_message` is only for optional mid-task progress nudges.

Keep channel replies short and skimmable; they may be read aloud through
earbuds.

## Pushing when the 1Password SSH agent is locked

Git push/pull/ls-remote over SSH on this machine authenticate via the
**1Password SSH agent** (`SSH_AUTH_SOCK` -> `...2BUA8C4S2C.com.1password/t/agent.sock`).
When 1Password is locked, `ssh-add -l` still lists keys but signing fails
(`Permission denied (publickey)`), so `git push` aborts. Two ways through:

- **Unlock 1Password** on the Mac (a GUI action; not possible from a phone).
- **Push over HTTPS using gh's token** -- no SSH needed. git is already configured
  with the `!gh auth git-credential` helper for github.com, so
  `git push https://github.com/<owner>/<repo>.git <branch>` works while the
  agent is locked. (Side effect: `origin/<branch>` tracking refs go stale
  until an SSH fetch succeeds, so `git status` may show a bogus "ahead N" --
  verify against GitHub before assuming unpushed work.)

## Always disambiguate PRs and issues with a linked, repo-qualified reference

The human works in multiple terminal windows on multiple repos at once, so a
bare `#34`, a bare `PR#34`, or "the PR" is ambiguous. **Every** mention of a
GitHub PR or issue in chat is a link whose text names owner, repo, kind, and
number:

```
[<owner>/<repo> PR#34](https://github.com/<owner>/<repo>/pull/34)
[<owner>/<repo> Issue#35](https://github.com/<owner>/<repo>/issues/35)
```

Not a naked URL, and not only in the first mention. A check run gets the same
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
