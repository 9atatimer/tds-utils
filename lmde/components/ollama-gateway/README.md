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
- `sandbox/ollama-gateway.sb` -- the sandbox profile (G4, Q7).
- `libexec/probe.zsh`, `libexec/keychain-probe.py` -- the G4 probe, the
  confinement-mechanism seam.
- `libexec/launch-ollama.zsh` -- runs the probe before every start, then
  `ollama serve` under the profile; refuses (exit 78) rather than start
  unconfined.
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
- The sandbox, first cut: under `$HOME` only the gateway tree (read; its
  `home/` read-write) and the store (read-only) are reachable; loopback to
  11434 is denied; `/usr/bin/security` and the keychain daemons' mach
  services are denied. Outside `$HOME` it is broad (hardening pass).
- The probe, before every start: unconfined, both canaries must be
  reachable; confined, each of these must be a sandbox denial (EPERM):
  reading the file canary `~/.local/state/ollama-gateway-probe/canary`,
  retrieving the keychain canary `lmde.ollama-gateway.probe-canary`
  through `/usr/bin/security` and through the Security framework,
  connecting to 11434, writing the store, writing the installed launchers.
  Both canaries hold the literal `not-a-secret`.
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

## Install, operate, remove

- Install: `lmde install proxy-layer` and `lmde install ollama-gateway`
  (or each `setup.sh`), in either order.
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
