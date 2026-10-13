# Ollama Gateway, laptop side -- as-built

What is deployed, not what was designed. Living; edit it when a release
changes the component.

- Design: [OLLAMA-GATEWAY.DESIGN.md](../../design/OLLAMA-GATEWAY.DESIGN.md)
  (APPROVED; the authority for intent). Open drift: Issue#455.
- Runbook: [docs/ops/ollama-gateway.md](../../ops/ollama-gateway.md).
- Diagram: [ollama-gateway.html](./ollama-gateway.html).
- Source: `lmde/components/ollama-gateway/`; its route runs on the
  [LMDE proxy layer](../proxy-layer/ARCHITECTURE.md).
- The edge (tunnel, DNS, Access application and policy, service tokens,
  1Password items) is tds-internal `ops/terraform/ollama-gateway`; its
  as-built lives there. Public hostname: `ollama.api9.com`.

## Deployment

- Runs on the owner's laptop (macOS, M1 Max, 64 GB), as two LaunchAgents
  of its own plus a route on the proxy layer's. Live since 2026-10-13; verified end to end through
  `ollama.api9.com` by tds-internal's `scripts/ollama-gateway/smoketest.sh`
  (PASS 6/6: uncredentialed refusal, credentialed model list, the
  `X-LMDE-Route` drift header, the ingress catch-all's 404 on `/api/tags`
  and `/v1/models/x`, a clean terraform plan).
- Installed by `lmde install ollama-gateway` (`setup.sh`), which COPIES the
  component from the checkout `lmde` runs from into
  `~/.local/share/ollama-gateway` (mode 700) and the route into
  `~/.local/share/lmde-proxy/routes/`. A `bin/tds-release` does not
  reinstall it; nothing records which commit is installed.
- Runtime dependencies: Homebrew `ollama` (0.40.3 at bring-up),
  `cloudflared`, `haproxy`; `/usr/bin/sandbox-exec`; `/usr/bin/python3`
  (Command Line Tools; `ctypes` only) for the Security-framework probe; the
  login Keychain; the everyday model store `~/.ollama/models`, populated
  only by the everyday ollama.
- Telemetry: logs only, `~/Library/Logs/ollama-gateway/{ollama,connector}.log`
  and the proxy layer's `~/Library/Logs/lmde-proxy/haproxy.log`. No
  metrics, no traces.

## Components

| Component | Responsibility | Source | LaunchAgent |
|---|---|---|---|
| External ollama launcher | Preflight, the G4 probe (control, then confined), then `ollama serve` under `sandbox-exec`; exit 78 instead of an unconfined start | `libexec/launch-ollama.zsh` | `com.tds.lmde.ollama-gateway.ollama` |
| G4 probe | The confinement assertions that gate every start | `libexec/probe.zsh`, `libexec/keychain-probe.py` | -- (run by the launcher) |
| Sandbox profile | The Seatbelt policy for the probe and for ollama | `sandbox/ollama-gateway.sb` | -- |
| Connector launcher | Reads the run token from the Keychain, execs `cloudflared` with it on a pipe | `libexec/launch-connector.zsh`, `connector/config.yml` | `com.tds.lmde.ollama-gateway.connector` |
| Gateway route | The deadline hop, the 507 answer, the hold hop | `route/ollama-gateway.cfg`, `route/ollama-gateway.deadline.http`, `gateway.env` | served by `com.tds.lmde.proxy-layer` |
| Token seeding | Copies the run token from 1Password into the Keychain; a human runs it | `seed-tunnel-token.zsh` | -- |
| Install, health | `lmde install` / `lmde status` contract | `setup.sh`, `healthcheck.sh` | -- |

The everyday ollama (`127.0.0.1:11434`, its LaunchAgent, its config) is
not part of the component; nothing here touches it (G8, smoketest 12).

## Tuned values

| Value | Setting | Where | Why (as the code says) |
|---|---|---|---|
| External ollama port | `127.0.0.1:11435` | `gateway.env` | never 11434; the launcher refuses 11434 and a port already bound |
| Proxy (route) port | `127.0.0.1:11436` | `gateway.env` | tds-internal mirrors it by hand as `origin_port`; the healthcheck's edge check catches drift |
| Deadline | `90s` | `gateway.env` -> route `timeout server` | Cloudflare's proxy read timeout is 100 s; 10 s left for tunnel and edge |
| Deadline answer | HTTP `507 Model Not Ready`, `retry-after: 20`, JSON error `code: model_not_ready` | `route/ollama-gateway.deadline.http` | the only retryable answer; distinct from every other 5xx |
| Hold | `6m` | `gateway.env` -> hold hop `timeout server` | above ollama's 5 m `OLLAMA_LOAD_TIMEOUT`, so ollama gives up first |
| `OLLAMA_KEEP_ALIVE` | `2m` | `gateway.env` | Q3: unload promptly after a review |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | `launch-ollama.zsh` | the one-loaded-model bound |
| `OLLAMA_CONTEXT_LENGTH` | `32768` | `gateway.env` | ollama 0.40 sizes the default from VRAM (256k here), making the KV cache rival the weights |
| Other ollama env | `OLLAMA_NOPRUNE=1`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `HOME=<tree>/home`, `TMPDIR=<tree>/home/tmp`, `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, everything else scrubbed (`env -i`) | `launch-ollama.zsh` | no store pruning (G8); no cloud; KV cache like the everyday instance |
| Connector | `cloudflared tunnel --config <tree>/connector/config.yml --no-autoupdate --protocol http2 --loglevel info run --token-file /dev/fd/N`, `HOME=<tree>/connector` | `launch-connector.zsh` | QUIC over IPv6 fails on this network; never fall back to `~/.cloudflared` (another tunnel) |
| LaunchAgents | `RunAtLoad`, `KeepAlive` on unsuccessful exit, `ThrottleInterval` 30 s | `launchd/*.plist.in` | G7; a refused start (78) retries every 30 s |
| Refusal exit | 78 (`EX_CONFIG`) | both launchers | -- |
| Healthcheck timeouts | 15 s local, 30 s through the edge | `healthcheck.sh` | -- |

## Seams in the code

- **Confinement mechanism: the G4 probe.** `probe.zsh control` (unconfined)
  must find both canaries; `probe.zsh confined` (under the profile, with
  ollama's parameters) must see a sandbox denial (EPERM, not "no such
  file" or "connection refused") for: reading the file canary
  `~/.local/state/ollama-gateway-probe/canary`; finding the Keychain
  canary (service `lmde.ollama-gateway.probe-canary`) through the Security
  framework and through `/usr/bin/security`; connecting to
  `127.0.0.1:11434`; writing the model store; writing the installed
  launchers. The store must still be readable. `sandbox-exec` plus
  `sandbox/ollama-gateway.sb` is today's only implementation behind it.
- **Keychain lookups are attribute-only** in the probe: it finds the canary
  item and never reads its secret, with Security-framework user
  interaction switched off first and `/usr/bin/security` tried only after
  a dialog-free framework lookup (Issue#441). The connector, by contrast,
  reads the run token's secret with `/usr/bin/security
  find-generic-password -w` (Issue#442: can still prompt).
- **Credential header names come from the item**, never the code: the
  healthcheck's edge check takes header names and values from
  `OLLAMA_GATEWAY_CLIENT_{ID,SECRET}{,_HEADER}` and feeds them to curl on
  stdin.
- **`gateway.env` is the single source** for ports, deadline, hold,
  keep_alive and context length; every value can be overridden from the
  environment (the tests do; launchd sets none).
- No seam for the edge vendor on this side: the connector is `cloudflared`.

## Entry points (the use-case surface)

| Behavior | Entry point | Composition root |
|---|---|---|
| Start the external ollama confined, or refuse | `launch-ollama.zsh`: `load_config`, `preflight`, `run_probe`, `start_ollama` | `com.tds.lmde.ollama-gateway.ollama` plist |
| Hold the tunnel open | `launch-connector.zsh` `main` | `com.tds.lmde.ollama-gateway.connector` plist |
| Answer before the deadline; hold the load | `route/ollama-gateway.cfg` | the proxy layer's `launch-proxy.zsh` |
| Install / uninstall | `setup.sh` `do_install` / `do_uninstall` | `lmde install ollama-gateway` |
| Health and origin-port drift | `healthcheck.sh`: `external-ollama`, `deadline-proxy`, `edge` | `lmde status`, `lmde doctor` |
| Seed the run token | `seed-tunnel-token.zsh` | a human at a terminal |

## Flows

A request, in evaluation order:

```
caller -- HTTPS, credential headers --> Cloudflare Access   302 / 403
  -> tunnel, remotely managed ingress: exactly /v1/chat/completions
     and /v1/models; anything else                           404
     (no connector)                                          530
  -> cloudflared (http2) on the laptop
  -> 127.0.0.1:11436  deadline hop (nothing listening: 502 from the connector)
       X-LMDE-Route: ollama-gateway on every answer
       no first byte within 90 s                             507
  -> unix@~/.local/share/lmde-proxy/run/ollama-gateway.sock  hold hop
       no abortonclose; Host rewritten to 127.0.0.1:11435
       ollama not listening                                  503
       held up to 6 m after the caller is gone
  -> 127.0.0.1:11435  external ollama under sandbox-exec      ollama's answer
```

A start of the external ollama: launchd runs `launch-ollama.zsh`;
preflight checks `sandbox-exec`, the profile, the gateway home, the store,
that the port is not 11434 and not already bound, and that `ollama` is on
PATH; then the probe runs unconfined, then confined; then `exec
sandbox-exec -f <profile> -D ... /usr/bin/env -i ... ollama serve`. Any
failure exits 78 and launchd retries in 30 s; the gateway is DEGRADED
until the probe passes.

A start of the connector: read the token from the Keychain (service
`lmde.ollama-gateway.tunnel-token`, account `ollama-gateway`); a missing
or malformed token exits 78 naming the item; else `exec cloudflared` with
the token on `/dev/fd/N`. `setup.sh` installs this agent disabled until the
token is seeded.

## The sandbox profile as built

Over `(allow default)`: deny all file reads and writes under `$HOME`;
allow metadata of `$HOME` itself (literal); allow reads of the gateway
tree and writes only to its `home/`; allow reads of the model store and
metadata (literal) of its parent; deny writes to the store; deny outbound
TCP to port 11434; deny exec of `/usr/bin/security`; deny mach lookups of
`com.apple.SecurityServer`, `com.apple.securityd`, `com.apple.secd` and
`com.apple.security.*`.
Everything outside `$HOME` stays broad (the hardening pass).

## Built but not designed

Recorded here as fact; recording is not approval.

- Metadata reads of `$HOME` and `~/.ollama`, outside G4's allow-list:
  drift, Issue#455.
- `X-LMDE-Route: ollama-gateway` on every response: the Q8 drift check's
  mechanism (Key Decisions Q8 leaves the mechanism to code).
- The `Host` rewrite to loopback (Issue#444): ollama's DNS-rebinding guard
  answers 403 to the public hostname.
- Probe checks beyond G4's two: loopback to 11434 and store writes (Q7),
  and the launchers' directory unwritable; the gateway tree read-only
  except `home/`. Narrower than the design's text, which delegates the
  profile's text to code.
- Engine parameters the design does not name: context length, flash
  attention, KV cache type, `OLLAMA_NO_CLOUD`.

## Radar reality

| Tech | Ring (`lmde/TECH_RADAR.md`) | Used for |
|---|---|---|
| Ollama | Adopt | the external engine |
| cloudflared | Adopt (2026-10-12) | the connector |
| sandbox-exec | Adopt (2026-10-12) | confinement, gated by the probe |
| HAProxy | Adopt (2026-10-03) | the proxy layer and this route |
| Python 3 | Adopt | the Security-framework probe (stdlib `ctypes`) |
| 1Password CLI | Adopt | token seeding only, by a human |

## Lessons the shape taught

- **A probe that proves reachability by reading a secret needs
  authorization, and under launchd that is a dialog storm.** Reading the
  canary's data from `/usr/bin/python3` asked the user on every relaunch;
  `security add-generic-password -A` widens the access list but not the
  partition list, so with UI off the read became errSecAuthFailed and the
  gateway stayed DEGRADED (Issue#441). Prove reachability by attributes;
  recreate a Keychain item rather than change its access in place (that
  prompts). The connector's secret read is the remaining exposure
  (Issue#442).
- **ollama is not a passive file reader or a passive HTTP server.** 0.40.3
  lstats every ancestor of `OLLAMA_MODELS` and drops every manifest it
  cannot (Issue#443); it answers 403 to a non-loopback `Host` (Issue#444).
  The allow-list sandbox and the proxy in front each broke G1 while every
  offline test passed.
- **ollama aborts a load whose requester disconnects.** A deadline proxy
  that only times out would cancel the load the caller's retry needs, so
  the route is two hops: the deadline hop answers 507 and hangs up; the
  hold hop, on a unix socket the tunnel can never be pointed at, keeps
  the upstream request open for 6 m.
- **The deadline is an inactivity timeout.** HAProxy's `timeout server`
  also fires on a non-streaming completion that takes longer than 90 s,
  on every retry; callers must stream (OCR on Demand sets
  `"stream": true`).
- **`keep_alive` 2 m means a cold load per review.** Reviews minutes apart
  each pay one (the pilot's green run did).
- **The external ollama cannot migrate the store.** It reads the store
  read-only, so after a Homebrew upgrade past a store-layout change it
  fails `GET /v1/models` until the everyday ollama has run the new version
  once.
- **Values mirrored by hand across the repo boundary.** 11436 is mirrored
  in tds-internal (the edge check detects drift); 503 and 507 are mirrored
  in `lib/ocr-review/gateway.mjs` (nothing checks them).
