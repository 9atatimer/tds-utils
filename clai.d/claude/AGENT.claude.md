<!-- AGENT.claude.md -- the Claude Code fragment of the global instruction file.

     bin/agent-instructions appends it to clai.d/AGENT.global.md to build
     Claude Code's ~/.claude/CLAUDE.md. Only Claude Code loads it, so it
     holds the rules about tools and features only Claude Code has. A rule
     every agent needs goes in the core file. See docs/ops/clai.md. -->

# Claude Code only

These rules name tools and features that only Claude Code has. They
narrow the core rules above; none of them relaxes one.

## The hard rules, at a glance

- Never call `AskUserQuestion`.
- Never call `ScheduleWakeup`, `CronCreate` or a sleeping `Monitor`.
- Run anything over ~30s with `run_in_background`; never start long work with `&`.
- On a classifier refusal, hand the human the exact `!` line once and stop.
- Never use claude.ai Artifacts; an HTML deliverable is a file in the repo.
- Never queue a task card.
- Don't write auto-memory.
- A fact you put in a subagent's prompt is a snapshot.
- A stop hook's "unpushed commits" is not an order to push.
- On a `<channel>` message, ack through the channel first, then work.

## Never call AskUserQuestion

The core rule (ask in prose, never with a menu) covers this tool: never
call it.

## Timers and polling in Claude Code

`ScheduleWakeup`, `CronCreate` and any tool that defers work to a later
turn are timers. So is a `Monitor` whose body loops on `sleep`, and a
`run_in_background` command that loops on an interval. Push-based watches
are fine: a `Monitor` `ws:` source, `gh webhook forward`, or one
background command that exits when a condition becomes true. `gh webhook
forward` runs as the owner, under the global file's webhook exception.
To wait on a reviewer's reply (OCR, Copilot), run that watch with
`run_in_background`; do not end the turn and hope the reply is noticed.
"Keep an eye on X" is not a request for a schedule; only a `/loop` the
human starts is.

## Long commands go in the background

Launch a command that may run over ~30 seconds with `run_in_background`
and keep talking; a silent agent looks hung, and a long foreground call
blocks the human from steering. Never start long work with `&`: it sends
no notice and leaves no exit status, so it gets mistaken for dead and
started again. `&` is only for a helper that the same call stops in well
under 30s: stop it with `kill "$pid"` (the PID from `$!`) and check with
`kill -0 "$pid"` (for a listener, that its port is free). Never `kill %1`: the tool shell has no job control, so
it exits 0 and leaves the job running.

## A classifier refusal is not lifted by the human's words

Under auto mode the permission classifier may refuse a commit touching an
agent instruction file (`AGENT.md`, `CLAUDE.md`, `clai.d/AGENT.global.md`,
a skill) and refuses `terraform apply`. The human saying "go ahead" in
chat does not lift it, nor does the command typed back to you without a
leading `!`. Give the exact `!` line for the human to run in
their own shell, or ask them to leave auto mode; say it once and stop.
Never route around the refusal with another tool. A refused deploy the
owner told you to run is still handed over as a `!` line. For Terraform the agent
plans and the human applies, through the Terraform Tower first; the iac
skill owns the authority model.

## Never use Artifacts

Never call the Artifact tool, for any action, or any other claude.ai
publishing path. An HTML deliverable is a file in the repo, opened with
`open <file>`; "an HTML artifact" means that file. This overrides any
skill or tool description that says to publish.

## Never queue a task card

Never call `spawn_task`, `start_session` with a proposal, or any
"suggested task" equivalent for work found in passing; the core rule
sends it to a GitHub Issue.

## Don't write auto-memory

The auto-memory under `~/.claude/projects/<encoded>/memory/` is visible to
one Claude Code instance at one path, and to no other agent. Create no
entries; durable context goes in the repo's `AGENT.md`, a design doc, or
the global instruction file, by PR. If unsure, don't save.

## A fact you put in a subagent's prompt is a snapshot

A claim about remote state in a subagent's prompt (merged, deployed,
released) goes stale while the agent runs. Have the agent re-derive it
(`git ls-tree origin/main`, the workflow run list), or write it as "as of
<sha>; verify before relying on it".

## A stop hook's "unpushed commits" is not an order to push

A cloud stop hook demands a push whenever the branch is ahead of its
remote. After a merge the remote branch is usually deleted; pushing
recreates it, empty. Check `git log origin/<default>..HEAD` first: if it
is empty, push nothing, and check out a detached `origin/<default>`.

## Channel messages: ack first, then work

A `<channel source=...>` sender usually cannot see this screen. Before
any other tool call, reply through the channel's reply tool with one line
saying what you understood and that you are starting. When done, send a
new reply with the result, not an edit: only a new message notifies their
phone; `edit_message` is only for optional progress nudges. Keep
channel replies short; they may be read aloud.
