# LMDE Component: Ollama Gateway (laptop side)

The laptop half of the Ollama Gateway
([design](../../../docs/design/OLLAMA-GATEWAY.DESIGN.md), issue #363): a
second, sandboxed ollama that an authorized caller off the laptop reaches
through a Cloudflare Access-protected tunnel and the LMDE proxy layer. The
edge (tunnel, DNS, Access, service tokens, 1Password items) is tds-internal
`ops/terraform/ollama-gateway`; its hostname, vaults and item names live
there, not in this public repo.

```
cloudflared (connector)  -> 127.0.0.1:11436  LMDE proxy layer, gateway route
                                             (deadline hop; ../proxy-layer)
                         -> unix socket      hold hop
                         -> 127.0.0.1:11435  external ollama, under
                                             sandbox-exec (this component)

everyday ollama on 127.0.0.1:11434 -- untouched, denied to the sandbox
```

## What is here

- `gateway.env` -- the single source of truth: ports (11435 ollama, 11436
  proxy -- tds-internal mirrors 11436 as `origin_port`), the 90 s deadline,
  the 6 m upstream hold, keep_alive, context length. Each value says why.
- `sandbox/ollama-gateway.sb.in` -- the sandbox profile's template (G4,
  Q7): deny by default, every allow named. `libexec/profile-render.zsh`
  renders it to `sandbox/ollama-gateway.sb` at install, filling the one
  machine-specific block (the kernel's ephemeral port range, see "The
  external ollama") from `sysctl`; the rendered file is not committed.
- `sandbox/ollama-gateway.probe.tsv` -- the G4 conformance table: one row
  per property, with the expectation under the profile (`confined`) and
  without it (`control`). Adding a property to the seam is adding a row.
- `libexec/probe.zsh`, `libexec/keychain-probe.py` -- the G4 probe, the
  confinement-mechanism seam: runs every row of the table, in both modes,
  before every start.
- `libexec/profile-trace.zsh` -- the allow-list apparatus: runs the real
  engine under a candidate profile on a scratch port, drives the gateway's
  workload, and prints every operation the sandbox denied (from the
  unified log) as SBPL. A human runs it after an ollama or macOS upgrade
  and iterates until the workload passes with an empty trace.
- `libexec/launch-ollama.zsh` -- runs the probe before every start, then
  `ollama serve` under the profile; refuses (exit 78) rather than start
  unconfined. `--probe-only` runs the two probe passes with the same
  parameters, prints their rows and exits 0 or 78 without starting ollama
  (what the tds-internal G6 smoketest calls on a live laptop).
- `libexec/launch-connector.zsh`, `connector/config.yml` -- cloudflared
  with the run token from the login Keychain.
- `route/` -- the gateway's route for the LMDE proxy layer: the deadline
  hop, the 507 deadline answer, the hold hop.
- `seed-tunnel-token.zsh` -- copies the run token from 1Password into the
  Keychain. A human runs it; an agent never does.
- `setup.sh` / `healthcheck.sh` -- the LMDE component contract
  (`lmde install ollama-gateway`, `lmde status`).
- `launchd/*.plist.in` -- LaunchAgent templates; `setup.sh` renders the
  absolute paths.

## The external ollama

- `ollama serve` on `127.0.0.1:11435`, `HOME` = the gateway tree's
  `home/`, `OLLAMA_MODELS` = the everyday store, with `OLLAMA_NOPRUNE=1`,
  `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_KEEP_ALIVE=2m` (Q3),
  `OLLAMA_CONTEXT_LENGTH=32768`, `OLLAMA_NO_CLOUD=1`, flash attention and a
  q8_0 KV cache like the everyday instance, and a scrubbed environment.
- The sandbox denies by default. Readable: the OS's own trees (`/System`,
  `/usr`, the cryptex, `/private/etc`, a few `/Library` and `/private/var/db`
  subtrees, never `/usr/local`), the Homebrew kegs the engine links against
  (its own, `mlx`, `mlx-c`), the gateway tree and the store; writable: the
  gateway `home/` only. Nothing else under `$HOME`, nothing under `/private/tmp`, the
  user's TMPDIR tree or the rest of the Homebrew prefix. Executable: the
  engine's keg and the system's own binaries, with `/usr/bin/security`,
  `/bin/launchctl` and `/usr/bin/open` denied outright, and the keychain,
  launchd and LaunchServices mach services denied so a copied binary
  fails too. Network: listen on loopback; outbound only to the kernel's
  ephemeral loopback ports, where the engine's own runner listens (ollama
  cannot pin that port, and SBPL has no port ranges and lets no deny
  narrow a wildcard allow, so the render lists each port). Every
  well-known loopback port, 11434 and 11436 included, is out of reach
  outbound. Bind is still a loopback wildcard, because a second per-port
  block exceeds the size sandbox_apply accepts; a compromised engine could
  bind a well-known port while its real listener is down (deferred). The
  GPU is reached through two named IOKit user-client classes, not a
  blanket allow.
  The allow-list was derived with `profile-trace.zsh` until the workload
  (model load, `/v1/models`, a completion) passed with an empty trace.
- The probe, before every start, runs every row of
  `sandbox/ollama-gateway.probe.tsv` twice. Unconfined (`control`), each
  row must be reachable, so no confined pass can succeed vacuously.
  Confined, each `deny` row on a file, exec, connect or listen must be
  observed as a sandbox denial (EPERM, never "no such file", "connection
  refused" or "address in use"): reading the file canary
  `~/.local/state/ollama-gateway-probe/canary`, writing the store, the
  installed launchers, `/private/tmp` and the Homebrew prefix, listing
  the user's TMPDIR, executing `launchctl` and `open`, connecting to
  11434, to the proxy's port and off the host; while the gateway home
  must stay writable and the engine's own port bindable. The daemon rows observe the daemon's
  refusal instead: the keychain canary `lmde.ollama-gateway.probe-canary`
  must be found unconfined through `/usr/bin/security` and the Security
  framework and not found confined, and the LaunchServices mach service
  must be reachable unconfined and refused confined, from a binary the
  profile does not deny by path. Both canaries hold the literal
  `not-a-secret`.
- What the engine can still reach: loopback services bound to a port in
  the kernel's ephemeral range (Docker Desktop's, an editor's language
  server), because its runner lives there. Bind local control APIs to
  unix sockets or well-known ports, never to ephemeral ones.
- The probe never reads the keychain canary's secret (Issue#441): both
  means look the item up by its attributes only (`/usr/bin/security
  find-generic-password -s`, no `-w`), which evaluates neither its access
  list nor its partition list, so it needs no authorization. Confined,
  the item cannot even be found, so the run token beside it cannot be
  read (G4).
- The probe never raises a Keychain dialog: the Security framework check
  runs with Keychain UI switched off, and `/usr/bin/security`, which has
  no such switch, is tried only after that check found the canary
  without one. A lookup refused for want of a dialog fails the control
  pass naming the fix.
- A failed probe: the launcher logs the failed checks and exits 78;
  launchd retries every 30 s; the gateway is DEGRADED until it passes.

## The connector

- `cloudflared tunnel --protocol http2 --no-autoupdate --loglevel info run
  --token-file /dev/fd/N`, with `HOME` and `--config` inside the gateway
  tree so it never falls back to `~/.cloudflared` (which holds another
  tunnel on this laptop).
- The run token: Keychain item service `lmde.ollama-gateway.tunnel-token`,
  account `ollama-gateway`, read at launch, handed over a pipe. No token:
  exit 78 naming the item.
- `setup.sh` installs the connector's LaunchAgent DISABLED while no token
  is seeded, so it neither crash-loops nor starts at login.
- Seeding, once the edge is applied (a human, at a terminal, with the
  1Password desktop app unlocked; the reference is in the tds-internal
  record):

```
lmde/components/ollama-gateway/seed-tunnel-token.zsh op://<vault>/<item>/<field>
launchctl enable gui/$(id -u)/com.tds.lmde.ollama-gateway.connector
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tds.lmde.ollama-gateway.connector.plist
```

## The caller contract this side owns

- HTTP 507 is the deadline answer: no first byte from ollama within 90 s
  (typically a cold load). It is the only response the gateway marks
  retryable; the load keeps going, so retry after `retry-after` seconds.
- Every answer from the route carries `X-LMDE-Route: ollama-gateway`.
- ollama down: HTTP 503 from the route at once (G5).
- Not covered by the deadline: a NON-streaming completion whose generation
  takes longer than the deadline also gets 507, and so would every retry.
  Stream (`"stream": true`) for long generations.

Operating it (install, release, re-deriving the allow-list, diagnosis):
`docs/ops/ollama-gateway.md`.

## Install, operate, remove

The runbook -- ship, verify, roll back, debug, gotchas, known gaps -- is
[docs/ops/ollama-gateway.md](../../../docs/ops/ollama-gateway.md); the
as-built is [docs/arch/ollama-gateway/](../../../docs/arch/ollama-gateway/ARCHITECTURE.md).

- Install: `lmde install proxy-layer` and `lmde install ollama-gateway`
  (or each `setup.sh`), in either order. Re-run the gateway's install
  after a change to the kernel's ephemeral port range (`sysctl
  net.inet.ip.portrange`), since the rendered profile lists it.
- After an ollama or macOS upgrade, re-derive the allow-list:
  `libexec/profile-trace.zsh --model <small model>` and fold any new
  denial the workload needs into the template, with a comment saying
  which step wanted it.
- Health: `lmde status` / `lmde doctor`, or `healthcheck.sh`. The Q8 drift
  check (an allow-listed request through the tunnel must reach the route,
  identified by its header) runs when `OLLAMA_GATEWAY_EDGE_URL` and the
  consumer credential variables are set -- see the header of
  `healthcheck.sh`; typically through `op run` with an env file kept in
  tds-internal.
- Logs: `~/Library/Logs/ollama-gateway/{ollama,connector}.log`.
- LaunchAgents (in `~/Library/LaunchAgents/`):
  - `com.tds.lmde.ollama-gateway.ollama`
  - `com.tds.lmde.ollama-gateway.connector`
- Stop one: `launchctl bootout gui/$(id -u)/<label>`; start it again:
  `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/<label>.plist`.
- Remove: `setup.sh uninstall` (leaves the run token; it prints the
  command to delete it).

## Requirements

- macOS with `sandbox-exec`; Homebrew `ollama`, `cloudflared`, `haproxy`;
  `/usr/bin/python3` (Command Line Tools) for the Security-framework probe.
- The external ollama reads the everyday store but never writes it, so it
  needs the store in the layout its own version expects. When Homebrew
  upgrades ollama past a store-layout change, the external instance fails
  `GET /v1/models` ("mkdir .../manifests-v2: operation not permitted")
  until the everyday ollama has run the new version once.
