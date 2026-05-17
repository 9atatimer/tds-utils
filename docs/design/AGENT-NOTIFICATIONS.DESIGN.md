# AGENT-NOTIFICATIONS.DESIGN.md

> **Status:** DRAFT
> **Date:** 2026-05-17
> **Authors:** Todd Stumpf
> **Depends on:** [CLAI.DESIGN.md](../../CLAI.DESIGN.md)

---

## Overview

When a coding agent (Claude Code, Codex, Gemini CLI, etc.) blocks for user
input -- a permission prompt, a clarifying question, end-of-turn -- the user
has no signal outside that terminal. This design wires each agent's own
runtime hook system to publish lifecycle events into a local NATS bus, and
makes `goldfish` (and a new zsh RPROMPT segment) consume that bus so the user
sees at-a-glance which sessions are waiting on them.

---

## Goals

1. **Low-latency signal.** RPROMPT reflects an agent transitioning to
   `waiting` within 1s of the agent firing its `Notification` hook, without
   blocking prompt rendering on the hot path.
2. **Fast aggregate view.** `goldfish` renders a `WAITING` column from a
   single localhost NATS KV query in under 50ms wall-clock.
3. **Idempotent install.** First `clai <agent>` invocation per machine
   installs the per-agent notification hooks; subsequent invocations are
   no-ops. Re-running never duplicates hook entries.
4. **Graceful degradation.** If `nats-server` is not reachable, `clai-emit`
   falls back to filesystem markers under `$XDG_STATE_HOME/goldfish/waiting/`
   with no loss of RPROMPT functionality. NATS is an optimization, not a
   hard dependency.
5. **Per-agent coverage.** v1 covers `claude`, `codex`, `gemini`, `opencode`,
   `cursor-agent` -- every agent in `goldfish/config.json` except `aider`.
6. **Reversible.** A single command (`clai-emit --uninstall <agent>`) removes
   every hook entry this system installs, restoring the agent's pre-install
   settings file.

---

## Non-Goals

- **Aider support.** Aider has no notification hook system. Out of scope;
  punted to a future tmux-capture-pane watcher if ever needed.
- **Cross-host state.** v1 is single-machine. NATS leaf-node federation
  between laptop and desktop is a future consideration, not a v1 deliverable.
- **Event history / replay.** State is last-write-wins in KV. Subjects carry
  fire-and-forget events; we do not promise durability or replay.
- **Mid-tool-call telemetry.** We emit only lifecycle transitions
  (running / waiting / exited), not per-tool-call events.
- **Multi-user.** Single `$HOME`, single NATS daemon, single KV bucket.
- **Agents launched outside `clai`.** A `claude` invoked directly (not via
  `clai claude`) will not get `CLAI_SESSION_ID` and its hook commands will
  fall back to a degraded mode. We don't intercept `exec` of agents we did
  not launch.

---

## Architecture Overview

```
+----------+   exec    +---------+   hooks    +-----------+
|  clai    |---------->|  agent  |----------->| clai-emit |
| (pre:    |  mints    | (claude,|  fire on   |  (helper) |
|  install |  session, | codex,  |  Notif./   +-----+-----+
|  hooks)  |  exports  | gemini, |  Stop/etc. |     |
+----------+  env vars | etc.)   |            |     v
                       +---------+      +----------+----------+
                                        | nats-server (local) |
                                        |  - KV: agent_state  |
                                        |  - subj: agent.*.*  |
                                        +----------+----------+
                                                   |
              +------------------------------------+--------+
              |                                             |
              v                                             v
   +----------+----------+                       +----------+----------+
   |     goldfish        |                       |  goldfish-prompt    |
   |  (table view, on    |                       |  (zsh RPROMPT seg., |
   |   demand: kv get)   |                       |   via zsh-async)    |
   +---------------------+                       +---------------------+

   fallback (when NATS unreachable):
       clai-emit ----> ~/.local/state/goldfish/waiting/<session>.json
       goldfish    ---> scan that dir
```

---

## Design

### Subsystem 1: clai.d hook installers

Per-agent pre-stage scripts under `clai.d/<agent>/pre/20-install-nats-hooks`.
Each script is idempotent and edits that agent's settings file via `jq` with
atomic-tmpfile-rename, the same pattern as `10-disable-cloudflare-mcp`.

#### Responsibilities

| Responsibility | Details |
|----------------|---------|
| Detect settings file path | Per-agent: claude -> `~/.claude/settings.json`; codex/gemini/opencode/cursor-agent paths recorded in a `clai.d/<agent>/pre/20-install-nats-hooks.conf` sibling file |
| Ensure hook entries present | `Notification` (state=waiting), `Stop` (state=idle), `UserPromptSubmit` (state=running), `SessionStart` (state=running), `SessionEnd` (state=exited) |
| Bake command form | Each hook command is `clai-emit --agent <agent> --session "$CLAI_SESSION_ID" --state <state>`; references env vars exported by clai |
| Idempotency | If a matching entry already exists for the same command, do nothing. Never duplicate. |
| Backup-on-first-install | Before first edit, copy `<settings>.json` to `<settings>.json.clai-orig` (only if `.clai-orig` does not already exist). |

#### Hook contract per agent

| Agent | Settings path | Notification stage | Idle stage | Run stage | Notes |
|-------|---------------|--------------------|------------|-----------|-------|
| claude | `~/.claude/settings.json` | `Notification` | `Stop` | `UserPromptSubmit`, `SessionStart` | Hook command has `$CLAI_SESSION_ID` in its argv; `SessionEnd` -> exited |
| codex | TBD (open question) | TBD | TBD | TBD | Per-agent installer in v1 only if its hook system matches the model |
| gemini | TBD | TBD | TBD | TBD | Per-agent installer in v1 only if its hook system matches the model |
| opencode | TBD | TBD | TBD | TBD | Same |
| cursor-agent | TBD | TBD | TBD | TBD | Same |

The "TBD" rows here are tracked as an open question. The design accommodates
per-agent variation by giving each its own pre-hook installer and its own
config file; the only contract that crosses agents is "the hook command must
call `clai-emit`".

### Subsystem 2: CLAI_SESSION_ID minting

`clai` mints a UUIDv4 for every launch and exports it into the agent's
environment before `exec`:

```
CLAI_SESSION_ID=$(uuidgen | tr A-Z a-z)
CLAI_AGENT=<agent>
export CLAI_SESSION_ID CLAI_AGENT
```

Hook commands installed in agent settings files reference these via shell
substitution. The agent's own session UUID (where one exists) is not used,
because:

- Not all agents expose one to hooks.
- We need a single identity owned by the launcher, valid across the agent's
  full lifetime.
- `$PPID` is wrong: reused, and not the agent process itself.

### Subsystem 3: clai-emit

A small zsh script in `bin/clai-emit`. Single entry point for every hook in
every agent. Single place to centralize the NATS-or-fallback logic, the
event-payload schema, and timeouts.

#### CLI

```
clai-emit --agent <name> --session <uuid> --state <state> [--cwd <path>] [--pid <int>]
clai-emit --uninstall <agent>
```

States: `running`, `waiting`, `idle`, `exited`.

#### Behavior

| Step | Action |
|------|--------|
| 1 | Build event payload (JSON: agent, session, state, since, cwd, pid). |
| 2 | If `nats-server` reachable on `127.0.0.1:4222` within 200ms: `nats kv put agent_state <agent>.<session> <payload>` and `nats publish agent.<agent>.<session>.state <payload>`. Return. |
| 3 | Otherwise: write `$XDG_STATE_HOME/goldfish/waiting/<agent>.<session>.json` atomically (tmp + rename) if state==waiting; remove the file for any other state. |
| 4 | Never block the agent. Hard ceiling: 250ms total wall-clock; exceeding it logs a single line to `$XDG_STATE_HOME/goldfish/clai-emit.log` and exits 0. |

`clai-emit` exits 0 in all non-fatal cases. The agent must never see a hook
failure from this layer.

### Subsystem 4: NATS configuration

NATS is installed as part of the lmde toolchain (alongside Caddy, dnsmasq,
1Password, Ollama) and managed by launchd on macOS. JetStream is enabled --
required for KV.

#### Bucket

```
bucket name:   agent_state
storage:       file
ttl:           24h  (stale sessions self-expire)
history:       1     (only current state matters)
max_value_size:1KB
```

#### Subjects

```
agent.<agent>.<session>.state    last-write-wins, mirrored into KV
agent.<agent>.<session>.event    fire-and-forget lifecycle events
agent.<agent>.<session>.meta     set-once at session start (cwd, pid, repo)
```

Goldfish subscribes / queries `agent.*.*.state` and the `agent_state` KV.
Future consumers (Slack notifier, tmux statusbar, iOS notifier) attach to
the same root.

### Subsystem 5: Filesystem fallback

When NATS is unreachable, `clai-emit` writes JSON markers under
`$XDG_STATE_HOME/goldfish/waiting/`. Filename pattern:

```
<agent>.<session>.json
```

File content matches the NATS KV value. Files for non-waiting states are
removed. `goldfish` always reads both sources and merges, with NATS winning
on conflict (NATS is fresher than a stale fallback file from before the
daemon started).

### Subsystem 6: goldfish integration

`goldfish/shell.py` gains a `read_agent_state()` adapter:

| Try | Source | Behavior |
|-----|--------|----------|
| 1 | `nats kv ls agent_state --json` (200ms timeout) | Parse all entries, build `{session_id: AgentState}`. |
| 2 | Read `$XDG_STATE_HOME/goldfish/waiting/*.json` | Merge into the same map; NATS entries win on conflict. |

`goldfish/core.py` gains a `WAITING` column rendered next to `AGENTS`,
showing a count of waiting sessions per repo. The existing `running_agents()`
process-scan stays -- it answers "is the process alive?" -- but the
`waiting` count comes from this new state source.

### Subsystem 7: goldfish-prompt (RPROMPT)

A new zsh function sourced from `macos/dot.zshrc`, integrated with the
existing `RPROMPT` chain (which today includes only `uv_env_prompt`).

| Step | Action |
|------|--------|
| Init | `async_init` once at shell start. Register a worker `goldfish_prompt_worker`. |
| precmd | If state cache older than 2s, fire `async_job` running `goldfish-prompt` (a new bin script that wraps subsystem 6's reader and emits a single styled string). |
| Callback | On `async_job` completion, store the rendered string in `_GOLDFISH_RPROMPT` and call `zle reset-prompt`. |
| RPROMPT | `RPROMPT='${_GOLDFISH_RPROMPT}$(uv_env_prompt)'`. |

When zero sessions are waiting, the segment is empty (no visual noise).
Otherwise it renders something like `[!2]` colored yellow, where 2 is the
waiting count. Click-through is not a goal -- the segment is informational.

---

## State Machine

Per-session lifecycle, from clai's POV:

```
              +---------+
              |  BORN   |   (clai exec'd the agent; no events yet)
              +----+----+
                   |  SessionStart hook fires
                   v
              +----+----+
       +----->| RUNNING |<-------+
       |      +----+----+        |
       |           |  Notification hook fires
       |           v             |
       |      +----+----+        |
       |      | WAITING |--------+
       |      +----+----+   UserPromptSubmit / Stop -> running
       |           |
       |           |  agent exits or SessionEnd hook fires
       v           v
              +----+----+
              | EXITED  |
              +---------+
```

| From | To | Trigger | Hook fired |
|------|-----|---------|------------|
| BORN | RUNNING | `clai` execs agent, SessionStart fires | `SessionStart` |
| RUNNING | WAITING | Agent blocks for input or permission | `Notification` |
| WAITING | RUNNING | User responds (prompt submit) | `UserPromptSubmit` |
| WAITING | RUNNING | Agent's turn resumes (Stop fires, then next turn begins) | `Stop` then `UserPromptSubmit` |
| RUNNING | EXITED | Agent process exits | `SessionEnd` (or absence detected by TTL) |
| WAITING | EXITED | Agent killed mid-prompt | TTL expiry (24h) or process-absence sweeper |

A 30-second sweeper inside `goldfish` removes KV entries whose recorded `pid`
is no longer alive, catching abnormal exits without waiting for the 24h TTL.

---

## Data Model

### NATS KV bucket `agent_state`

```
key:    "<agent>.<session>"
value:  JSON {
          agent:   string,    -- "claude" | "codex" | "gemini" | ...
          session: string,    -- UUIDv4, the CLAI_SESSION_ID
          state:   string,    -- "running" | "waiting" | "idle" | "exited"
          since:   string,    -- ISO8601 timestamp of last transition
          cwd:     string,    -- agent's working directory at hook fire
          pid:     int,       -- agent process PID (best-effort)
        }
```

### Filesystem fallback

```
$XDG_STATE_HOME/goldfish/waiting/<agent>.<session>.json
                                             (same JSON shape as KV value)
```

### Settings-file edits (per-agent)

Each agent's settings file is the source of truth for its hook config. The
`clai.d` installer records a single line in
`$XDG_STATE_HOME/clai/installed-hooks.json`:

```
{
  "claude": {
    "settings_path": "/Users/stumpf/.claude/settings.json",
    "installed_at": "2026-05-17T..."
  },
  ...
}
```

Used by `--uninstall` to find which file to revert.

---

## Security Considerations

- **NATS bind address.** `nats-server` listens on `127.0.0.1:4222` only.
  No remote access. The launchd plist hardcodes the bind address.
- **No secrets in events.** Event payloads carry only state, session UUID,
  cwd, and PID. No tokens, no prompt content, no tool arguments.
- **User-owned files.** All settings-file edits, KV writes, and fallback
  files are owned by the invoking user. No setuid, no privilege escalation.
- **Atomic settings edits.** Hook installers write to a temp file and
  rename, never edit in place. A crashed installer leaves the settings file
  intact.
- **JetStream store on local disk only.** No off-machine replication.
- **TTL bounds stale-state risk.** 24h KV TTL means a missed exit cannot
  haunt the RPROMPT forever.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where agents emit from | Their own runtime hooks, not `clai` | Mid-session events; `clai` pre-stage cannot fire after `exec` |
| State representation | NATS JetStream KV (`agent_state`) | "Is session X waiting now?" is last-write-wins; KV models that directly |
| Transport for events | NATS subjects (`agent.*.*.state`) | Future consumers (Slack, iOS, statusbar) attach for free |
| Session identity | `CLAI_SESSION_ID=$(uuidgen)` injected by clai | `$PPID` is reused; per-agent native session IDs vary or are absent |
| Hook command form | Shell, references `$CLAI_SESSION_ID`, `$CLAI_AGENT` | Uniform across agents whose hook engine runs shell |
| Hook installer location | `clai.d/<agent>/pre/20-install-nats-hooks` | Override-by-filename gives per-project escape, same pattern as cloudflare-mcp |
| Fallback transport | `$XDG_STATE_HOME/goldfish/waiting/` JSON files | Works without NATS (first boot, CI, daemon crashed); zero new deps |
| RPROMPT update | `zsh-async` worker + `zle reset-prompt` | Goldfish-prompt read is local but not free; never block prompt render |
| Cleanup of stale state | 24h KV TTL + 30s PID-absence sweeper in goldfish | Bounded staleness without requiring a perfect SessionEnd path |
| Aider | Out of scope | No hook system; tmux-capture-pane fallback deferred |

---

## Open Questions

1. **Per-agent hook coverage.** Which of codex / gemini / opencode /
   cursor-agent expose a hook system that can run shell commands on
   notification-equivalent events? Each needs verification before its
   installer can be written. Until verified, v1 ships `claude` only and
   the others remain in the design's scope but unimplemented.
2. **NATS install path.** Is `nats-server` installed via Homebrew + a
   hand-rolled launchd plist in `macos/`, or is there an existing lmde
   convention for adding daemons that this should follow?
3. **JetStream storage location.** `$XDG_DATA_HOME/nats/` is the obvious
   pick. Confirm vs. wherever the existing lmde daemons (Ollama, etc.) put
   their state.
4. **clai-emit fallback latency.** Should NATS reachability be probed every
   call (simpler, ~5ms overhead per event) or cached for the lifetime of
   the session (faster but stales on daemon restart)?
5. **`clai`-not-on-PATH agents.** What is the expected behavior when a user
   runs `claude` directly (not via `clai claude`)? The hooks are still
   installed in `~/.claude/settings.json`, but `$CLAI_SESSION_ID` is unset.
   Options: (a) the hook command no-ops gracefully; (b) `clai-emit`
   synthesizes a session from `$PPID + $$`. Lean toward (a) for v1.
6. **Linux parity.** macOS uses launchd; Linux would need systemd-user. Is
   Linux RPROMPT integration part of v1, or macOS-only initially? (The repo
   is cross-platform per CLAUDE.md.)

---

## Rejections

- **Pure-filesystem solution, no NATS.** Rejected: lmde is gaining other
  event consumers (notifier, statusbar, future iOS app); files are a
  fallback, not the primary substrate.
- **A "wrap" stage in `clai`.** Keep `clai` alive as the agent's parent and
  pump signals from there. Rejected: breaks the existing exec-and-step-aside
  contract, complicates pty handling, duplicates work the agent's own hook
  engine already does.
- **`$PPID` as session key.** Rejected: reused after agent exit, not durable
  across the session lifetime, ambiguous when the agent forks.
- **`/proc/<pid>/wchan` polling as primary signal.** Rejected: cannot
  distinguish "blocked on user input" from "blocked on network/disk". Noisy.
  Kept on the table only as a last-resort fallback for future non-hooked
  agents -- not in v1.
- **Subjects only, no KV.** Rejected: forces every consumer (including
  `goldfish` on a cold read) to maintain its own state from an event stream.
  KV is the right primitive for "what is true right now".
- **One settings.json fragment shipped per agent, sourced via include.**
  Rejected: agents do not uniformly support include-style settings
  composition; jq-edit of the agent's own file is portable and matches the
  existing `10-disable-cloudflare-mcp` pattern.
- **Agents emit directly to NATS without `clai-emit`.** Rejected: centralizes
  the schema, retry, and fallback logic in one place; agent hook lines stay
  short and stable.

---

## Future Considerations

- **Aider via tmux-capture-pane watcher.** A small daemon polls the agent's
  tmux pane, pattern-matches the aider prompt marker, and emits to NATS via
  `clai-emit`. Deferred -- aider usage is rare and the marker is fragile.
- **Cross-host NATS leaf nodes.** Laptop and desktop run leaf-node NATS,
  share a parent; a `waiting` agent on one machine surfaces in the RPROMPT
  on the other. Requires auth and a clear topology decision.
- **Slack / Discord notifier.** A small subscriber on
  `agent.*.*.state` posts to a private channel when state transitions to
  `waiting` and stays there longer than N minutes.
- **iOS / Apple Watch notifier.** Same shape as Slack notifier, different
  delivery channel. Wants the cross-host work first.
- **log-hoarder cross-link.** Each session emits its tmux pane ID in `meta`
  so `goldfish` can deep-link from the WAITING column into the live pane log.
- **Event replay UI.** A `goldfish --history` view that reads JetStream
  stream history (not KV) for "what did I work on last week".
- **Linux systemd-user integration.** Mirror the launchd setup for Linux
  hosts that run the same toolchain.

---

## Related Documents

- [CLAI.DESIGN.md](../../CLAI.DESIGN.md) -- The hook framework that owns
  installation of these per-agent notification hooks.
- [LOG-HOARDER.DESIGN.md](./LOG-HOARDER.DESIGN.md) -- Sibling local-daemon
  infra; informs the launchd-managed daemon convention used here.
- `goldfish/core.py`, `goldfish/shell.py` -- The consumers that grow a new
  `read_agent_state()` adapter and a `WAITING` column.
