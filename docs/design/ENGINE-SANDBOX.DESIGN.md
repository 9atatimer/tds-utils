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
engine's allow-list, and its hardening, stays its own.

---

## Goals

- **G1 One mechanism, many engines.** Every engine the LMDE confines starts
  through the same launcher and the same probe. Confining a new engine
  means writing its policy; it adds no launcher or probe code.
- **G2 Never unconfined.** Before every start of an engine, the probe runs
  under that engine's policy. If any assertion fails, the engine is not
  started, and the launcher exits non-zero with a message naming the engine
  and the failed assertion. There is no fallback to running unconfined.
- **G3 Protected trees are unreachable.** No engine, nor any process it
  spawns, can read or write any **protected tree** -- `~/.ssh`, AI tool
  credentials (`~/.claude`, `~/.codex`, `~/.config/gh`), 1Password data, and
  the rest of the machine-wide baseline -- nor anything under `$HOME`
  outside its own allow-list.
- **G4 Protected secrets are unretrievable.** A secret not reached by path
  (a Keychain item) is protected for **every** engine once any LMDE
  component puts it on the machine, by every means of retrieval the
  baseline lists for it.
- **G5 The probe proves something.** Every assertion is preceded by a
  positive control outside the policy -- the canary is readable there, the
  secret is retrievable there -- so a missing canary or an unseeded secret
  can never make an assertion pass.
- **G6 Engines cannot shape their own confinement.** The policies, the
  generated profiles and the canaries live outside every engine's
  allow-list.
- **G7 Allow-lists and hardening are per engine.** Changing one engine's
  allow-list or hardening changes no other engine's confinement (Todd,
  2026-10-03: "We can harden both separately"). The baseline is shared and
  only ever grows.

---

## Non-Goals

- **The hardening passes.** Denying network, loopback reach and writes to
  an engine's own trees is each engine's later work, recorded in that
  engine's design. This component carries the rule types; it does not
  decide when an engine adopts them.
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
|    reads the baseline + the engine's policy   (outside every         |
|    generates the profile                       engine's allow-list)  |
|    positive controls, unconfined:                                    |
|      each canary readable?  each present secret retrievable?        |
|    probe, under the policy   --(ConfinerPort)-->  mechanism          |
|      confinement in effect? each canary unreadable and unwritable?   |
|      each present secret unretrievable, by every listed means?       |
|    verdict decided -> confined: exec the engine under the policy     |
|                    -> refused:  exit non-zero, naming the assertion  |
+----------------------------------------------------------------------+
   |                                  |
   v                                  v
 external ollama                    decision arena
 (allow-list: gateway config        (allow-list: arena tree)
  tree, model store)

 Baseline, policies and assertions are the core, in the problem's
 language. The mechanism (sandbox-exec today) is the one edge.
```

---

## Design

### Baseline

Owned by this component, inherited by every policy, never relaxed by one.

| Field | Meaning |
|---|---|
| Protected trees | Trees under `$HOME` no engine may read or write, each with a canary: the `$HOME` root, `~/.ssh`, `~/.claude`, `~/.codex`, `~/.config/gh`, 1Password data, and any tree a component adds |
| Protected secrets | Every secret any LMDE component keeps outside a path, each with every means of retrieving it. First entry: the Ollama Gateway's connector run token, by the Security framework and `/usr/bin/security` |
| Rule | A component that puts a credential on the machine adds it to the baseline in the same change |

### Engine policy

Data, one per engine, owned by that engine's component.

| Field | Meaning |
|---|---|
| Engine name | Appears in every verdict and refusal message |
| Allow-list | The trees under `$HOME` the engine may touch, typically its own tree (also its `HOME`) and the store it serves from. Never a protected tree |
| Hardening rules | Optional: deny outbound network, limit loopback, make an allow-listed tree read-only. Empty in the first cut for every engine |

### Launcher

| Responsibility | Details |
|---|---|
| Probe before every start | Each time launchd starts the engine, not once at install |
| Decide before exec | The verdict is reached before the engine command runs, so a fake confiner can assert it and a refused command never starts |
| Refuse, loudly | Any failed assertion: no start, non-zero exit, a message naming the engine and the assertion |
| Start confined | On a passing probe, execs the engine under the same profile the probe ran under |
| Outside the engine's reach | Reads baseline and policy, and writes the generated profile, only outside every engine's allow-list (G6) |
| No engine knowledge | Knows policies and engine commands, nothing about ollama, MLX or any engine's protocol |

### Probe

The probe's assertions are the confinement guarantee and the
confinement-mechanism seam (carried over from the gateway): a successor to
`sandbox-exec` only has to pass the same probe.

| Assertion | Positive control (unconfined) | Pass when (under the policy) |
|---|---|---|
| Confinement in effect | -- | The mechanism reports the profile applied to the probe process |
| Each protected tree | Its canary is readable and writable | Its canary can be neither read nor written |
| Each protected secret | Retrievable by at least one listed means | Every listed means fails |
| Each hardening rule | Per rule | Per rule, when the policy has any (none in the first cut) |

A canary whose positive control fails refuses the start: canaries are this
component's own files. A secret absent outside the policy has nothing to
protect under that name; the verdict records it as `absent` -- never as a
pass -- and the start proceeds.

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
| An engine starts confined | `launch_confined(baseline: Baseline, policy: EnginePolicy, engine: EngineCommand, *, confiner: ConfinerPort) -> LaunchVerdict` | ConfinerPort | Given every positive control and assertion passes, When launchd starts the engine, Then the verdict is `confined` and the engine runs under the profile |
| A reachable protected tree refuses | (same use case; error path) | ConfinerPort | Given a policy whose profile admits `~/.ssh`, When the engine is started, Then the verdict is `refused(protected tree: ~/.ssh)` and the engine command never runs |
| A retrievable secret refuses | (same use case; error path) | ConfinerPort | Given a protected secret retrievable under the policy by one listed means, When the engine is started, Then the verdict is `refused(secret: <name>, <means>)` |
| A secret one engine introduced is denied to every engine | (same use case) | ConfinerPort | Given the gateway's run token in the baseline, When the arena is probed, Then the run token is unretrievable from the arena |
| A missing canary never passes | (same use case; error path) | ConfinerPort | Given a protected tree's canary is absent, When the engine is started, Then the verdict is `refused(canary missing: <tree>)` |
| An absent secret is reported, not passed | (same use case) | ConfinerPort | Given a baseline secret not present on the machine, When the engine is started, Then the verdict lists it as `absent` and the start proceeds |
| No confinement refuses | (same use case; error path) | ConfinerPort | Given a mechanism that cannot apply the profile, When the engine is started, Then the verdict is `refused(confinement not in effect)` |
| One engine's hardening leaves another alone | `launch_confined`, per engine | ConfinerPort | Given two engines, When one gains a hardening rule, Then the other's profile and verdict are unchanged |
| A new engine needs no launcher code | `launch_confined` with a new `EnginePolicy` | ConfinerPort | Given a policy for an engine the launcher has never seen, When it is started, Then it is confined with no change to launcher or probe |

---

## State Machine

Per engine, as launchd drives it.

```
             launchd start                  verdict: confined
 +---------+ ------------> +---------+ ------------------> +---------+
 | STOPPED |               | PROBING |                     | RUNNING |
 +---------+ <------------ +---------+                     +---------+
      ^     verdict: refused    |                               |
      |    (launcher exits)     |                               |
      +------------------------- launchd relaunch <-------------+
                                (throttled)        engine exits
```

| From | To | Trigger | Condition |
|---|---|---|---|
| STOPPED | PROBING | launchd starts the launcher | At login, or a relaunch after exit |
| PROBING | RUNNING | Verdict `confined` | The engine is exec'd under the profile |
| PROBING | STOPPED | Verdict `refused` | Launcher exits non-zero; launchd relaunches under its own throttle, rerunning the probe |
| RUNNING | STOPPED | The engine exits or crashes | launchd relaunches; the probe runs again |

A transient failure clears on a relaunch. A persistent one -- a macOS update
weakening `sandbox-exec` -- holds the engine down until a human fixes the
policy or plugs a successor in at the probe seam. The last verdict is
readable by the engine's own status surface (each engine's design).

---

## Data Model

No database.

```
baseline (this component; outside every allow-list)
+-- protected trees     path + canary path, per tree
+-- protected secrets   name + every means of retrieval, per secret

engine policy (the engine's component; outside every allow-list)
+-- engine name
+-- allow-list          trees under $HOME
+-- hardening rules     optional, per engine

launch verdict (per start)
+-- engine name
+-- outcome             confined | refused(assertion)
+-- absent secrets      listed, never counted as passes
```

---

## Data Warehouse

Nothing is ledgered. A verdict is an exit status and a message in the
engine's launchd log; each engine's design surfaces its own last verdict.

---

## Security Considerations

- **What the sandbox stops.** An engine compromised by a hostile prompt,
  image or model file cannot read or write a protected tree, cannot reach
  anything under `$HOME` outside its allow-list, and cannot retrieve a
  protected secret by any listed means -- including secrets another engine
  depends on.
- **What it does not stop until an engine hardens** (accepted per engine,
  as in the Ollama Gateway): outbound network, reach to other loopback
  services (including other engines), reads and writes outside `$HOME`, and
  writes to the engine's own allow-listed trees. An engine whose own tree
  holds code it runs must therefore verify that code before every start
  (the Decision Arena does).
- **The probe is the guarantee, not the profile text,** and the positive
  controls are what make a passing probe mean something.
- **Confinement inputs are out of reach.** An engine that could write its
  policy, its profile or a canary could loosen its next confinement; G6
  keeps all three outside every allow-list.
- **A shared mechanism is a shared failure.** One macOS change that breaks
  `sandbox-exec` downs every confined engine at once. That is the intended
  failure: down, never unconfined.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Sandbox as its own component | Extracted from the Ollama Gateway's external ollama; the gateway and the Decision Arena both use it | Todd, 2026-10-03: "DDD the sandbox concept from ollama so we can DRY". A second confined engine made the duplication concrete |
| What is per engine | The allow-list and the hardening rules | Todd, 2026-10-03: "We can harden both separately" |
| What is machine-wide | Protected trees and protected secrets, in one baseline every policy inherits | A credential belongs to the machine, not to the engine that introduced it; per-engine secrets would let the arena read the gateway's run token |
| Probe positive controls | Every assertion is preceded by an unconfined control | Without it, a missing canary or unseeded secret passes the probe |
| Confinement-mechanism axis | Seam = the probe's assertions, behind `ConfinerPort`; `sandbox-exec` is the first adapter | Carried from the gateway: `sandbox-exec` is deprecated, and a successor need only pass the same probe |
| Probe timing | Before every start, not once at install | A macOS update can weaken confinement between starts |
| Refusal behavior | Down, never unconfined | Carried from the gateway's G4 |
| First-cut scope | Protected trees and secrets; everything else may be broad | Carried from the gateway's first-cut ruling (Todd, 2026-10-02) |
| Radar: `sandbox-exec` | Trial, as the Ollama Gateway proposed | Apple-deprecated; Trial until a supported successor is chosen or it survives a macOS major update |

---

## Open Questions

- **Q1 The name.** "Engine Sandbox" is the working name. Confirm it or
  choose another.

---

## Rejections

- **A copy of the profile and probe per engine.** Two copies of a security
  control drift; the DRY ruling exists to prevent that.
- **Secrets named per engine.** Leaves every credential readable by every
  engine that did not think to name it.
- **One policy for every engine.** Couples each engine's hardening to every
  other's; Todd's ruling is to harden separately.
- **A single canary.** Proves one path is denied; a profile that admits
  `~/.ssh` and denies only the canary would pass.
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
  ollama is the first engine, and its run token the first protected secret.
- [Decision Arena](./DECISION-ARENA.DESIGN.md) -- the second engine.
- [LMDE](./LMDE.DESIGN.md) -- the platform, and the launchd pattern.
- [Chores](./CHORES.DESIGN.md) -- a likely later engine.
