# ast-mcp: make the server available to cloud/kind-sandboxed agents (Cowork)

> **STATUS: DRAFT** -- not yet filed. **Target repo undecided**
> (`9atatimer/ai-tools` vs `tds-utils`). Decide owner before opening.

## Summary

The host rollout installs `ast-mcp` (release `ast-mcp-v0.1.0`) as a versioned,
PATH-resolved binary and wires it into every **Mac-local** agent:

- LMDE owns the install: download the pinned release tarball, `npm install -g`
  into `~/.local/share/tds-utils/mcp/ast-mcp/0.1.0/`, symlink
  `~/.local/bin/ast-mcp`, health-check the JSON-RPC handshake, and register the
  server in **Claude Desktop**.
- clai owns the wiring for the four clai agents (Claude Code, codex, opencode,
  agy), each pointed at the canonical absolute command
  `/Users/stumpf/.local/bin/ast-mcp` at launch.

Every one of those consumers resolves the server through the **host filesystem
and host PATH**. That is exactly what a **kind/Cowork-sandboxed agent cannot
see.** This issue tracks the Phase-2 follow-on: surfacing `ast-mcp` to
sandboxed agents.

## Why the host install does not cover sandboxed agents

Per the residency rule in [`lmde/LMDE.md`](../../../LMDE.md):

> Components reachable by kind-sandboxed coding agents must run inside (or be
> exposed into) the kind cluster. Mac-local agents can hit either side;
> sandboxed agents only see what the cluster surfaces, so anything they consume
> needs an in-cluster path.

`ast-mcp` is currently a host-edge component: a binary on `~/.local/bin` with a
`#!/usr/bin/env node` shebang that depends on the host's nvm `node`. A
kind/Cowork-sandboxed agent has neither that filesystem path nor that PATH, so
the canonical `command = "/Users/stumpf/.local/bin/ast-mcp"` invocation is
unreachable from inside the sandbox. As the server's audience widens to include
sandboxed agents, LMDE's own rule says to plan its move into (or exposure into)
the cluster.

## Scope

- **In scope:** make the pinned `ast-mcp-v0.1.0` server reachable by
  kind/Cowork-sandboxed coding agents, using the same version that the host
  rollout pins (no drift between host and sandbox).
- **Out of scope (already shipped by the host rollout):** host install,
  symlink, health check, Claude Desktop registration, and the four clai-agent
  hooks. This is a *follow-on*, not a replacement.

## Options to explore

1. **Bake the pinned release into the sandbox image.** Add the
   `nine-at-a-time-media-ast-mcp-*.tgz` release artifact (or a vendored install
   of it) into the Cowork/kind sandbox base image so each sandboxed agent gets a
   local `ast-mcp` plus a compatible `node`, with no host dependency. Pin to the
   exact release tag so host and sandbox stay in lockstep; re-bake on version
   bumps.
   - Pro: hermetic, offline-friendly, mirrors the host's "pinned version"
     posture and the local-registry supply-chain stance.
   - Con: image rebuild on every `ast-mcp` bump; node toolchain baked per image.

2. **Surface the server into the kind cluster.** Run `ast-mcp` as an
   in-cluster service (e.g. a Deployment/Service fed from the local pinned
   registry on `localhost:5001`) and have sandboxed agents reach it over the
   cluster network instead of via a binary on PATH. This may require the server
   to support a network transport (the host path uses stdio JSON-RPC), so
   confirm transport support before committing.
   - Pro: single shared instance; matches the residency rule's "expose into the
     cluster" path; no per-image node toolchain.
   - Con: needs a network transport + an in-cluster config story for agents;
     more moving parts than baking a binary.

## Acceptance criteria (sketch)

- A kind/Cowork-sandboxed agent can complete the `initialize` JSON-RPC
  handshake against `ast-mcp` and receive a response containing
  `"name":"ast-mcp"` (same health check the host install uses).
- The sandbox-side server is the **same pinned version** as the host
  (`ast-mcp-v0.1.0`); no version drift.
- The host rollout (clai hooks + Claude Desktop) is left unchanged.

## References

- `lmde/LMDE.md` -- Residency: in-kind vs. on the host.
- `lmde/components/mcp/` -- host install/registration component (Phase 1).
- Release: `ast-mcp-v0.1.0` in `9atatimer/ai-tools` (private; needs `gh` auth).
