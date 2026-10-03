# Engine Sandbox

> **Status:** DRAFT  
> **Date:** 2026-10-03  
> **Authors:** Todd Stumpf, Claude (Opus 5.5)  
> **Depends on:** [LMDE](./LMDE.DESIGN.md)  
> **Origin:** extracted from [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md), External ollama; issue #382

---

## Overview

The Engine Sandbox is the LMDE component that runs an **engine** -- a
laptop process that handles untrusted input, such as an inference server
reading prompts, images and model files -- so that it cannot read the
user's credentials, and that refuses to start it at all when that
confinement is not in effect. It was the Ollama Gateway's sandbox for the
external ollama; it is extracted so the gateway and the
[Decision Arena](./DECISION-ARENA.DESIGN.md) share one mechanism (Todd,
2026-10-03: "DDD the sandbox concept from ollama so we can DRY"), while each
engine's policy, and its hardening, stays its own.

---

## Goals

- **G1 One mechanism, many engines.** Every engine the LMDE confines starts
  through the same launcher and the same probe. Confining a new engine
  means writing its confinement policy; it adds no launcher or probe code.
- **G2 Never unconfined.** Before every start of an engine, the probe runs
  under that engine's policy. If any assertion fails, the engine is not
  started, and the launcher exits non-zero with a message naming the
  failed assertion. There is no fallback to running unconfined.
- **G3 The home directory is an allow-list.** An engine, and every process
  it spawns, can read or write under `$HOME` only within the trees its
  policy names. Everything else under `$HOME` -- `~/.ssh`, AI tool
  credentials (`~/.claude`, `~/.codex`, `~/.config/gh`), 1Password data --
  is denied. Asserted by the probe: a canary file under `$HOME`, outside
  every allow-listed tree, is unreadable.
- **G4 Named secrets are unretrievable.** A policy can name secrets that
  are not reached by path (a Keychain item, for example) together with
  every means of retrieving them. The probe attempts each means under the
  policy, and each must fail.
- **G5 Policies are independent.** Changing one engine's policy -- its
  trees, its secrets, or its hardening -- changes no other engine's
  confinement. Each engine is hardened on its own schedule (Todd,
  2026-10-03).

---

## Non-Goals

- **The hardening pass.** Denying network, loopback reach and store writes
  is each engine's own later work, recorded in that engine's design. This
  component carries the rules; it does not decide when an engine adopts
  them.
- **Confining trusted vendor daemons.** The cloudflared connector and the
  LMDE proxy layer are signed vendor binaries on loopback and stay
  unconfined in the first cut (Ollama Gateway, Key Decisions).
- **Linux.** The first mechanism is macOS-only, like the engines it
  confines.
- **Resource limits.** Memory and CPU contention between engines is
  operational, not confinement (Todd, 2026-10-03).

---

## Architecture Overview

```
 launchd (LaunchAgent per engine, restart on crash)
   |
   v
+--------------------- Engine Sandbox (tds-utils LMDE) ----------------+
|  launcher                                                            |
|    reads the engine's ConfinementPolicy                              |
|    runs the probe under the policy  --(ConfinerPort)-->  mechanism   |
|      canary outside the allow-list unreadable?                       |
|      every named secret unretrievable, by every listed means?        |
|    all pass  -> exec the engine under the policy                     |
|    any fail  -> exit non-zero, naming the failed assertion           |
+----------------------------------------------------------------------+
   |                                  |
   v                                  v
 external ollama                    decision arena
 (policy: gateway config tree,      (policy: arena config tree,
  model store; run token denied)     weights dir)

 Policies and probe assertions are the core, in the problem's language.
 The mechanism (sandbox-exec today) is the one edge, behind ConfinerPort.
```

---

## Design

### Confinement policy

A policy is data, one per engine, owned by that engine's component and
read by the launcher.

| Field | Meaning |
|---|---|
| Engine name | Which engine this confines; appears in every refusal message |
| Home allow-list | The trees under `$HOME` the engine may touch. Typically its own config tree (also its `HOME`) and the store it serves from |
| Named secrets | Secrets not reached by path, each with every means of retrieval to deny and to probe (for the gateway: the run token, by the Security framework and `/usr/bin/security`) |
| Hardening rules | Optional, per engine: deny outbound network, limit loopback, make a tree read-only. Empty in the first cut for every engine |

### Launcher

| Responsibility | Details |
|---|---|
| Probe before every start | Runs the probe under the policy each time launchd starts the engine, not once at install |
| Refuse, loudly | Any failed assertion: no start, non-zero exit, a message naming the engine and the assertion |
| Start confined | On a passing probe, execs the engine under the same policy the probe ran under |
| No engine knowledge | Knows policies and engine commands, nothing about ollama, MLX or any engine's protocol |

### Probe

The probe's assertions are the confinement guarantee, and the
confinement-mechanism seam (carried over from the gateway's Key
Decisions): a successor to `sandbox-exec` only has to pass the same probe.

| Assertion | Pass when |
|---|---|
| Confinement in effect | The mechanism reports the policy applied to the probe process |
| Home allow-list holds | A canary file under `$HOME`, outside every allow-listed tree, cannot be read |
| Each named secret is unretrievable | Every listed means of retrieving it fails |
| Each hardening rule holds | Per rule, when the policy has any (none in the first cut) |

### Mechanism (ConfinerPort)

`sandbox-exec` with a generated profile is the first adapter. The 2026-10-02
spike (issue #363) showed GPU inference under it for ollama: Metal found,
models read, completions served, `~/.ssh` and `~/.ollama/id_ed25519`
denied. Apple has deprecated `sandbox-exec`; if an update removes or weakens
it, the probe fails, and every engine stays down rather than running
unconfined.

---

## Behaviors and Interfaces

| Behavior | Use case (signature) | Ports it needs | Given / When / Then |
|---|---|---|---|
| An engine starts confined | `launch_confined(policy: ConfinementPolicy, engine: EngineCommand, *, confiner: ConfinerPort) -> LaunchVerdict` | ConfinerPort | Given a policy whose probe passes, When launchd starts the engine, Then the verdict is `confined` and the engine runs under the policy |
| A readable canary refuses the start | (same use case; error path) | ConfinerPort | Given a policy whose allow-list admits the canary, When the engine is started, Then the verdict is `refused(home allow-list)` and the engine command never runs |
| A retrievable secret refuses the start | (same use case; error path) | ConfinerPort | Given a named secret one of whose means succeeds under the policy, When the engine is started, Then the verdict is `refused(secret: <name>, <means>)` |
| No confinement refuses the start | (same use case; error path) | ConfinerPort | Given a mechanism that cannot apply the policy, When the engine is started, Then the verdict is `refused(confinement not in effect)` |
| One engine's policy change leaves another alone | `launch_confined` for each engine | ConfinerPort | Given two engines' policies, When one gains a hardening rule, Then the other's probe and confinement are unchanged |

---

## State Machine

Per engine, as launchd drives it.

```
             launchd start                  probe passes
 +---------+ ------------> +---------+ ------------------> +---------+
 | STOPPED |               | PROBING |                     | RUNNING |
 +---------+ <------------ +---------+                     +---------+
      ^       probe fails       |                               |
      |    (launcher exits)     |                               |
      +------------------------- launchd relaunch <-------------+
                                (throttled)        engine exits
```

| From | To | Trigger | Condition |
|---|---|---|---|
| STOPPED | PROBING | launchd starts the launcher | At login, or a relaunch after exit |
| PROBING | RUNNING | Every assertion passes | The engine is exec'd under the policy |
| PROBING | STOPPED | Any assertion fails | Launcher exits non-zero; launchd relaunches under its own throttle, rerunning the probe |
| RUNNING | STOPPED | The engine exits or crashes | launchd relaunches; the probe runs again |

A transient failure clears on a relaunch. A persistent one -- a macOS update
weakening `sandbox-exec` -- holds the engine down until a human fixes the
policy or plugs a successor in at the probe seam.

---

## Data Model

No database. One policy per engine, declared in that engine's component
(see Confinement policy for its fields), and one probe implementation
shared by all.

---

## Data Warehouse

Nothing is ledgered. A refusal is an exit status and a message in the
engine's launchd log; the engine's own design decides whether its state is
surfaced elsewhere.

---

## Security Considerations

- **What the sandbox stops.** An engine compromised by a hostile prompt,
  image or model file cannot read credentials under `$HOME` outside its
  allow-list, nor retrieve any named secret by a probed means.
- **What it does not stop until an engine hardens** (accepted per engine,
  as in the Ollama Gateway): outbound network, reach to other loopback
  services, reads and writes outside `$HOME`, and writes to the engine's
  own allow-listed trees.
- **The probe is the guarantee, not the profile text.** A policy is never
  trusted because of what it says; it is trusted because the probe passed
  under it, before this start.
- **A shared mechanism is a shared failure.** One macOS change that breaks
  `sandbox-exec` downs every confined engine at once. That is the intended
  failure: down, never unconfined.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Sandbox as its own component | Extracted from the Ollama Gateway's external ollama; the gateway and the Decision Arena both use it | Todd, 2026-10-03: "DDD the sandbox concept from ollama so we can DRY". A second confined engine made the duplication concrete |
| Per-engine policy | Each engine owns its policy; the launcher and probe are shared | Todd, 2026-10-03: "We can harden both separately" |
| Confinement-mechanism axis | Seam = the probe's assertions, behind `ConfinerPort`; `sandbox-exec` is the first adapter | Carried from the gateway: `sandbox-exec` is deprecated, and a successor need only pass the same probe |
| Probe timing | Before every start, not once at install | A macOS update can weaken confinement between starts |
| Refusal behavior | Down, never unconfined | Carried from the gateway's G4; an engine handling untrusted input must not run open |
| Load-bearing first-cut scope | `$HOME` allow-list and named secrets; everything else may be broad | Carried from the gateway's first-cut ruling (Todd, 2026-10-02) |

---

## Open Questions

- **Q1 The name.** "Engine Sandbox" is the working name. Confirm it or
  choose another.

---

## Rejections

- **A copy of the profile and probe per engine.** Two copies of a security
  control drift; the DRY ruling exists to prevent that.
- **One policy shared by every engine.** Couples each engine's hardening to
  every other's; Todd's ruling is to harden separately.
- **Docker as the mechanism.** Docker on macOS has no Metal GPU, so every
  engine here would fall back to CPU.
- **Probing once at install.** Confinement can change under a running
  install (an OS update); only a per-start probe sees it.

---

## Future Considerations

- **Per-engine hardening passes**, each in its engine's design: the
  gateway's (its Future Considerations) and the arena's (issue #401).
- **A supported successor to `sandbox-exec`**, plugged in at the probe
  seam.
- **More engines.** The chores design names sandbox profiles for chores
  that run untrusted code (`CHORES.DESIGN.md`, Future Considerations); each
  would be a new policy.

---

## Related Documents

- [Ollama Gateway](./OLLAMA-GATEWAY.DESIGN.md) -- origin; the external
  ollama is the first engine.
- [Decision Arena](./DECISION-ARENA.DESIGN.md) -- the second engine.
- [LMDE](./LMDE.DESIGN.md) -- the platform, and the launchd pattern.
- [Chores](./CHORES.DESIGN.md) -- a likely later engine.
