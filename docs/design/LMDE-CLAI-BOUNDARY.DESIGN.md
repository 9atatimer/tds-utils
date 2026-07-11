# LMDE / clai Boundary -- Acquire vs Configure

> **Status:** DRAFT
> **Date:** 2026-07-11
> **Authors:** Claude (from design discussion with Todd)
> **Depends on:** [PROVISION.DESIGN.md](./PROVISION.DESIGN.md),
> [LMDE.md](../../lmde/LMDE.md),
> [CLAI.DESIGN.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md),
> [template-tools#145](https://github.com/nine-at-a-time-media/template-tools/issues/145)

---

## Overview

Today `clai provision` does two jobs that don't belong together: it **acquires**
on-disk artifacts (git-clone the skills tree and MCP catalog, install the
`ast-mcp` binary, bootstrap clai itself) and it **configures** per-agent state
(collate the config layers, emit each agent's dialect, place skills into agent
directories, inject the telemetry environment). Acquisition is agent-agnostic;
configuration is agent-aware. Fusing them in one tool has three costs:

1. It couples clai -- the agent-aware collator -- to network transport and
   supply-chain policy it shouldn't own.
2. It is the exact seam that breaks in the cloud: the acquisition half
   git-clones `template-tools`, and the Claude-web git proxy brokers only the
   session's own repo, so the fetch is unreachable and the whole run degrades
   (see PROVISION.DESIGN.md, and `sandbox/claude-web/setup.sh`'s deferral note).
3. It blurs which tool to reach for when a responsibility moves.

This design splits the two along a single axis and couples the halves as
loosely as possible -- **by convention, not by handoff**.

## The axis

> **If it doesn't matter which agent it is, it's lmde. When it matters which
> agent it is, it's clai.**

- **lmde = Acquire.** Fetch and install on-disk artifacts. Agent-agnostic.
  Owns transport, pins, and supply-chain integrity.
- **clai = Configure.** Collate config from layered sources into each agent's
  on-disk form, and set the launch environment. Agent-aware. Owns nothing about
  where artifacts came from.

The two never call each other and never exchange a data payload. They meet only
at a set of **well-known filesystem locations**: lmde installs there, clai reads
from there. That shared path set is the entire contract.

---

## Goals

1. **Clean concern split** -- Every provisioning responsibility lands wholly in
   Acquire (lmde) or Configure (clai), decided by the agent-agnostic /
   agent-aware test, with no straddlers.
2. **Loose coupling** -- The boundary is a fixed locations convention, not a
   runtime manifest or receipt. Either side can be reimplemented without the
   other changing, as long as the paths hold.
3. **clai is a collator, never a gatekeeper** -- clai combines sources and
   writes the effective per-agent config; it never verifies that a referenced
   artifact is present and never blocks a launch over a missing one. The agent
   manages its own missing server. It may note obviously-dangling references in
   a trailing epilogue when they fall out for free (see Configure), but it
   never blocks.
4. **Cloud parity on acquisition** -- Moving acquisition to lmde puts it on the
   reachable GitHub Packages rail instead of the proxy-blocked git clone, so a
   fresh cloud sandbox provisions the same artifacts a laptop does. (Requires
   template-tools#145; see Dependencies.)
5. **Velocity by default, pins by path** -- Acquire installs every artifact at
   `latest` by default: no pin file to bump on a release, so shipping is one
   publish, not a publish plus a second on-disk edit. `lmde acquire --pins
   <file>` reads versions from that pins file instead; with no `--pins`,
   everything floats to `latest`. The pins file is a passed argument, never
   ambient state to keep current.

## Non-Goals

- **Folding this into the LMDE and CLAI design docs.** That is step two, done
  once the responsibilities have actually moved. This doc only clarifies the
  shuffle; the canonical docs are updated afterward.
- **Cloud telemetry / launcher parity (gap G1).** clai's environment injection
  happens at agent launch, and in the cloud the provider launches the agent
  directly with no clai wrapper. Making cloud telemetry work is a separate,
  orthogonal problem; ENV stays launch-time-only here.
- **A receipt / install manifest between the tools.** Explicitly rejected -- see
  Rejections. The coupling is path convention only.
- **Reworking lmde's platform components** (kind, NATS, Caddy, observability).
  Those are untouched; this only adds an artifact-acquisition capability
  alongside them.

---

## Responsibility split

| Concern | Today | -> Owner |
|---|---|---|
| Fetch skills (`SKILL.md` trees) | clai provision (git-clone) | **lmde** |
| Fetch canonical MCP catalog (`mcp/manifest.json`) | clai provision (git-clone) | **lmde** |
| Install MCP server binaries (`ast-mcp`, ...) | setup.sh / SessionStart hook | **lmde** |
| Install clai itself | lmde (laptop) / provision.sh (cloud) | **lmde** |
| Version pins + supply-chain integrity gate | `pins.env` + provision.sh | **lmde** |
| Collate config layers (catalog <- repo <- user) | clai provision | **clai** |
| Emit per-agent MCP dialects (`.mcp.json`, `~/.codex/config.toml`, `~/.gemini/.../mcp_config.json`, `opencode.json`) | clai provision | **clai** |
| Place / symlink skills into each agent's dir | clai provision | **clai** |
| Register a server at agent scope (`~/.claude.json`) | setup.sh / hook | **clai** |
| ENV / OTel injection at launch | clai launcher | **clai** |

Nothing straddles. The only item that changes shape rather than owner is the
canonical MCP catalog (below).

---

## Contract-by-convention: the locations

The boundary is a small, fixed set of paths **hardcoded in both tools' code** --
no env vars, no config surface, nothing dynamic. If a path ever changes, both
sides change in the same commit. lmde installs to them; clai reads from them.
Neither side passes the other a description of what it did.

| Artifact | Convention path (code constant) | lmde does | clai does |
|---|---|---|---|
| MCP server binaries | `~/.local/bin/<server>` (e.g. `~/.local/bin/ast-mcp`) | installs the binary here | names this path in the emitted config |
| Skills source tree | `~/.cache/clai/template-tools/skills/` (today's staging) | populates one dir per skill here | enumerates it, places/symlinks into each agent's skills dir |
| Canonical MCP catalog | `~/.cache/clai/template-tools/mcp/manifest.json` | writes the fetched catalog file here | reads it as the base collation layer |
| clai | on `$PATH` | installs it | is the runtime |

Two rules make the convention load-bearing:

- **lmde installs to convention or not at all.** An artifact either lands at its
  canonical path or is absent; lmde never invents alternate locations and never
  reports paths back to clai.
- **clai reads convention and never gates.** clai uses whatever is present at
  those paths and emits config regardless. A missing binary still gets named in
  the config it belongs in; a missing skills dir means zero skills placed, not
  an error. clai never stats an artifact to decide whether to proceed with a
  launch.

The `~/.local/bin/<server>` path is already load-bearing today -- the committed
`.mcp.json`, `~/.claude.json`, the `clai.d/*/pre/20-enable-ast-mcp` hooks, and
`install-claude-user.sh` all name `~/.local/bin/ast-mcp`. This design elevates
that de-facto path to a named part of the contract rather than a coincidence.

```
        ACQUIRE (lmde)                         CONFIGURE (clai)
  agent-agnostic, owns transport          agent-aware, owns collation
+------------------------------+        +------------------------------+
| fetch skills  ---------------+--> ~/.cache/clai/template-tools/skills/
| fetch MCP catalog -----------+--> ~/.cache/clai/template-tools/mcp/manifest.json
| install ast-mcp -------------+--> ~/.local/bin/ast-mcp    |         |
| install clai ----------------+--> $PATH                   |         |
| latest by default / --pins   |        |  reads -----------+         |
| (integrity always on)        |        |  collates catalog <- repo clai.d
+------------------------------+        |             <- user clai.d     |
              |                         |  emits per-agent dialects     |
     no call, no payload                |  places skills into agent dirs|
     only the paths below               |  injects OTel env at launch   |
              v                         |  + trailing oddities epilogue |
   ~/.cache/clai/..., ~/.local/bin/       +------------------------------+
```

---

## Acquire (lmde)

lmde gains an **artifact-acquisition capability** distinct from its existing
platform components. Platform components (kind, NATS, Caddy, dnsmasq, the
observability stack) are laptop-only and stay exactly as they are. The
acquisition capability is **cloud-portable**: it is the subset of lmde a sandbox
can and should run.

- **Transport is uniform: GitHub Packages (npm).** Binaries already ship this
  way post-#98/#101. Skills and the MCP catalog ship the same way once
  template-tools#145 lands, so acquisition is one reachable rail in both
  environments -- no git clone, so no cloud proxy block.
- **Versioning: `latest` by default, pins by path.** Acquire installs every
  artifact at `latest` unless invoked as `lmde acquire --pins <file>`, which
  reads versions from that pins file. No `--pins` -> no pinning; the pins file is
  a passed argument, never ambient state to keep current. npm **registry
  integrity is always on** either way -- every tarball is verified against the
  registry hash -- so `--pins` governs *which version*, never *whether it's
  tamper-checked*. clai holds no pins at all.
- **Supply-chain note (conscious tradeoff).** `latest`-by-default means a
  publish to the private registry propagates to every consumer on the next
  acquire, without the pinned-version review gate PROVISION.DESIGN.md's #72
  stance relied on. Accepted for development velocity; `--pins <file>` restores
  that gate when wanted. Mitigation meanwhile: `template-tools` is private with
  protected `main`, and integrity verification still blocks in-transit
  tampering.
- **Idempotent, honest degradation.** lmde already has `install / sync / status
  / doctor`; acquisition reuses that shape. A fetch that cannot reach the
  registry uses whatever is already installed and warns naming what is stale --
  it never blocks the session (the fail-open stance from PROVISION.DESIGN.md's
  state machine, now owned by lmde).

The surface is a new **`lmde acquire`** verb -- a clear name for the
cloud-portable subset, distinct from the platform-component `lmde install` /
`sync` verbs.

## Configure (clai)

clai keeps everything agent-aware and loses everything about acquisition.

- **Collate, don't fetch.** clai's inputs are the canonical MCP catalog (at its
  convention path), the repo layer (`<repo>/clai.d/`), and the user layer
  (`~/clai.d/`). It merges them closest-wins exactly as the overlay walk does
  today, and reads the skills tree by listing its convention dir. No network.
- **Emit each agent's dialect.** The per-agent emitters are unchanged; they now
  read the catalog from the convention path instead of a freshly cloned tree.
- **Place skills per agent.** Symlink on the laptop, copy in ephemeral
  sandboxes, into each agent's skills directory -- the placement map stays in
  clai (it is inherently agent-aware).
- **Inject ENV at launch.** The telemetry environment (per-agent enable vars +
  `repo=` / airframe resource attributes) is unchanged and stays launch-time.
- **Never gate.** Per Goal 3: emit config that references convention paths
  whether or not the artifact is there yet. clai is a collator.
- **Trailing oddities epilogue.** clai never probes for problems, but emitting
  config already means touching every convention path it references; when one is
  plainly absent, it collects the dangling reference and prints a short epilogue
  at the end of the run. A zero-effort byproduct of work already done, not a
  validation pass -- no dangling refs, no epilogue. It aids debugging a
  misconfigured box without making clai a gatekeeper.

`clai provision` therefore narrows to "configure from the conventional
locations." `clai refresh` (= `provision --report`) is unchanged in spirit.

## The canonical MCP catalog (naming)

The file today called `mcp/manifest.json` is renamed in prose to the **canonical
MCP catalog** to avoid colliding with the rejected "install manifest/receipt."
It is not a handoff between tools -- it is inert config *data* (profiles + server
definitions) that lmde **acquires** like any other artifact and clai **reads**
as the base layer under `repo` and `user` `clai.d`. Same file, unambiguous role.

---

## Sandbox reflow

The cloud wrapper stops being a clai-bootstrap-and-fetch and becomes
acquire-then-configure:

```
BEFORE
  env-setup  (setup.sh)          install ast-mcp only; DEFER provisioning
  session    (session-start.sh)  provision.sh: npm-install clai, `clai provision`
                                   +- git-clone of template-tools BLOCKED -> DEGRADED

AFTER
  env-setup  (setup.sh)          lmde acquire  -> skills, catalog, ast-mcp, clai
                                   (all via GitHub Packages -- reachable)
  session    (session-start.sh)  clai provision -> collate + emit + place
                                   (reads convention paths -- offline, no clone)
```

- `sandbox/provision.sh`'s bootstrap-and-fetch dissolves: the install half moves
  into `lmde acquire`; the configure half is a plain `clai provision`.
- The laptop path is symmetric and already close: LMDE (platform install) puts
  clai and artifacts in place; a `clai.d` pre-hook / SessionStart runs
  `clai provision`. The refactor just makes the artifact acquisition an explicit
  lmde responsibility on both sides.
- The three-way `session-start.sh` branch simplifies: it only ever needs to run
  `clai provision` (configure); acquisition happened in the setup/platform
  stage.

---

## Dependencies

- **template-tools#145 (skills + catalog as an npm package)** is a hard
  prerequisite for cloud acquisition parity. Until it lands, `lmde acquire`
  falls back to git-clone on the laptop (where it works) and the cloud stays on
  today's degraded behavior. The split is still worth doing before #145 -- it
  just doesn't unblock the cloud until #145 ships.

---

## Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Split axis | Agent-agnostic acquire (lmde) vs agent-aware configure (clai) | One test decides every responsibility; matches Todd's framing |
| Coupling mechanism | Contract-by-convention (fixed paths) | Loose coupling; either side reimplementable; no runtime handoff to keep in sync |
| Acquisition surface | `lmde acquire` verb | Cloud-portable subset, named distinct from platform `lmde install`/`sync` |
| Locations contract | Hardcoded in both tools' code | Nothing dynamic; a path change is one lockstep commit |
| Staging location | Keep today's `~/.cache/clai/template-tools/` | No churn to the existing clone/symlink layout |
| Receipt / install manifest | Rejected | clai needs none of what it offered (path is convention, version+currency are Acquire's); it only re-adds tight coupling -- see Rejections |
| clai on missing artifact | Emit anyway; list dangling refs in a trailing epilogue | Collator, not gatekeeper; the epilogue is a zero-effort debug aid |
| Versioning | `latest` by default; `--pins <file>` to pin | Kills the release double-edit; integrity always on; the pins file is a passed argument, not ambient state |
| Transport | GitHub Packages for binaries **and** data (#145) | One reachable rail; kills the cloud git-clone block |
| MCP catalog | Keep the file, rename in prose to "canonical MCP catalog" | It is an acquired config source, not a tool-to-tool handoff |
| lmde in the sandbox | Sandbox runs lmde's cloud-portable acquisition subset | "Rework the sandbox to utilize lmde" -- acquisition is the portable part |
| ENV in cloud | Out of scope (launch-time only) | Orthogonal launcher-parity gap (G1) |

## Open Questions

1. **Dangling-config benignness across agents** -- an emitted config that names
   an absent binary must be inert for codex / agy / opencode as it is for Claude
   Code (Goal 3). The trailing oddities epilogue surfaces these in practice;
   confirm none of the four agents errors on a named-but-missing server rather
   than skipping it.
2. **Pins-file scope** -- `--pins <file>` pins every artifact the file names and
   floats the rest to `latest`; confirm nothing needs pinning that the file
   can't express (e.g. a transitive dep of a floated package).

## Rejections

- **A receipt / install manifest handed from lmde to clai.** Introduced in an
  earlier draft to give clai an artifact's path, version, and a currency check.
  Rejected: the path is a convention (no data needed), and version + currency
  are Acquire's concern, not clai's -- clai emits a config pointing at a path and
  does not care which version sits there or whether it is current. The receipt
  bought clai nothing it needs and re-created the exact tight producer->consumer
  coupling this refactor exists to remove. Contract-by-convention replaces it.
- **clai gating a launch on artifact presence.** clai is a collator, not a
  gatekeeper; a missing server is the agent's problem to report, not clai's to
  block on.
- **Keeping acquisition in clai "because it already works on the laptop."** It
  works on the laptop and is precisely what fails in the cloud; leaving it
  blurs the concern split and keeps clai coupled to transport.

## Related Documents

- [PROVISION.DESIGN.md](./PROVISION.DESIGN.md) -- the current unified design this
  refactor splits; folded in at step two.
- [LMDE.md](../../lmde/LMDE.md) -- the platform contract lmde acquisition joins.
- [CLAI.DESIGN.md](https://github.com/nine-at-a-time-media/template-tools/blob/main/packages/clai/docs/CLAI.DESIGN.md)
  -- the launcher/collator whose provision verb narrows to configure-only.
- `sandbox/claude-web/setup.sh`, `sandbox/provision.sh` -- the wrappers reflowed
  to acquire-then-configure.
