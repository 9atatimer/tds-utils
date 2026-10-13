# Ollama Gateway, laptop side -- as-built

What is deployed, not what was designed. Living; edit it when a release
changes the component.

- Design: [OLLAMA-GATEWAY.DESIGN.md](../../design/OLLAMA-GATEWAY.DESIGN.md)
  (APPROVED; the authority for intent; its Key Decisions rows of
  2026-10-13 supersede the "first cut" sandbox text). Open drift:
  Issue#455.
- Runbook: [docs/ops/ollama-gateway.md](../../ops/ollama-gateway.md).
- Diagram: [ollama-gateway.html](./ollama-gateway.html).
- Source: `lmde/components/ollama-gateway/`; its route runs on the
  [LMDE proxy layer](../proxy-layer/ARCHITECTURE.md).
- The edge (tunnel, DNS, Access application and policy, service tokens,
  1Password items) is tds-internal `ops/terraform/ollama-gateway`; its
  as-built lives there. Public hostname: `ollama.api9.com`.

## Deployment

- Runs on the owner's laptop (macOS, M1 Max, 64 GB), as two LaunchAgents
  of its own plus a route on the proxy layer's. Live since 2026-10-13;
  verified end to end through `ollama.api9.com` by tds-internal's
  `scripts/ollama-gateway/smoketest.sh`: PASS 6/6 at bring-up, and PASS
  7/7 at 2026-10-13T22:28Z once the smoketest's first check became the
  laptop's G4 probe through `launch-ollama.zsh --probe-only` (PR#467);
  the edge checks are the uncredentialed refusal, the credentialed model
  list, the `X-LMDE-Route` drift header, the ingress catch-all's 404 on
  `/api/tags` and `/v1/models/x`, and a clean terraform plan.
- The deny-by-default profile and the table-driven probe (PR#462) are
  installed: the installed tree matches the merged code, and the engine
  starts under the rendered profile with the probe passing.
- Installed by `lmde install ollama-gateway` (`setup.sh`), which COPIES the
  component from the checkout `lmde` runs from into
  `~/.local/share/ollama-gateway` (mode 700), renders the profile there,
  and copies the route into `~/.local/share/lmde-proxy/routes/`. A
  `bin/tds-release` does not reinstall it; nothing records which commit is
  installed.
- Runtime dependencies: Homebrew `ollama` (0.40.3 at bring-up), installed
  as a keg (`<keg>/bin/ollama`, the real binary and its runner under
  `<keg>/libexec`), `cloudflared`, `haproxy`; `/usr/bin/sandbox-exec`;
  `/usr/bin/python3` (Command Line Tools; `ctypes` only) for the
  Security-framework and mach-service probes; the login Keychain; the
  everyday model store `~/.ollama/models`, populated only by the everyday
  ollama.
- Telemetry: logs only, `~/Library/Logs/ollama-gateway/{ollama,connector}.log`
  and the proxy layer's `~/Library/Logs/lmde-proxy/haproxy.log`. No
  metrics, no traces.

## Components

| Component | Responsibility | Source | LaunchAgent |
|---|---|---|---|
| External ollama launcher | Preflight, the G4 probe (control, then confined), then `ollama serve` under `sandbox-exec`; exit 78 instead of an unconfined start. `--probe-only` runs the two probe passes, prints every row and exits 0 or 78 without starting ollama (PR#467) | `libexec/launch-ollama.zsh` | `com.tds.lmde.ollama-gateway.ollama` |
| G4 probe | Runs every row of the conformance table in the mode it is given; the confinement-mechanism seam | `libexec/probe.zsh`, `libexec/keychain-probe.py` (Security framework), `libexec/mach-probe.py` (bootstrap lookup) | -- (run by the launcher) |
| Conformance table | One row per confinement property, with an expectation per mode (PR#462) | `sandbox/ollama-gateway.probe.tsv` | -- |
| Sandbox profile template | The Seatbelt policy for the probe and for ollama, deny by default, with one machine-specific marker (PR#462) | `sandbox/ollama-gateway.sb.in` | -- |
| Profile renderer | Replaces the marker with one outbound allow per port of the kernel's ephemeral range, read from `sysctl`; writes `<tree>/sandbox/ollama-gateway.sb` atomically at install (PR#462) | `libexec/profile-render.zsh` | -- (run by `setup.sh`) |
| Allow-list tracer | Runs the real engine under a candidate profile on a scratch port and HOME, drives version, model list and one completion, and prints every sandbox denial from the unified log, then as SBPL; never edits the profile (PR#462) | `libexec/profile-trace.zsh` | -- (a human runs it) |
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
| Other ollama env | `OLLAMA_NOPRUNE=1`, `OLLAMA_NO_CLOUD=1`, `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `HOME=<tree>/home`, `TMPDIR=<tree>/home/tmp`, `PATH=/usr/bin:/bin:/usr/sbin:/sbin`, everything else scrubbed (`env -i`); cwd `<tree>/home` | `launch-ollama.zsh` | no store pruning (G8); no cloud; KV cache like the everyday instance; `HOME` is the one writable tree |
| Ephemeral outbound range | the kernel's `net.inet.ip.portrange.first`-`last` (49152-65535 here: 16384 rules), one `network-outbound` allow per port | `profile-render.zsh`, at install | the runner listens on a port ollama cannot pin; SBPL has no port ranges and no deny narrows a wildcard allow; the renderer refuses a range starting below 1024 |
| Profile parameters | `USER_HOME`, `GATEWAY_TREE`, `GATEWAY_HOME`, `MODEL_STORE`, `MODEL_STORE_PARENT`, `OLLAMA_KEG` (`whence -p ollama`, resolved, two levels up) | `launch-ollama.zsh` | identical for the probe and for `ollama serve` |
| Connector | `cloudflared tunnel --config <tree>/connector/config.yml --no-autoupdate --protocol http2 --loglevel info run --token-file /dev/fd/N`, `HOME=<tree>/connector` | `launch-connector.zsh` | QUIC over IPv6 fails on this network; never fall back to `~/.cloudflared` (another tunnel) |
| LaunchAgents | `RunAtLoad`, `KeepAlive` on unsuccessful exit, `ThrottleInterval` 30 s | `launchd/*.plist.in` | G7; a refused start (78) retries every 30 s |
| Refusal exit | 78 (`EX_CONFIG`) | both launchers | -- |
| Healthcheck timeouts | 15 s local, 30 s through the edge | `healthcheck.sh` | -- |

## Seams in the code

- **Confinement mechanism: the G4 probe over a table.** `probe.zsh` reads
  `sandbox/ollama-gateway.probe.tsv` (`check  confined  control  verb
  target`) and runs every row in the mode it is given. Expectations:
  `deny` (a sandbox denial observed: EPERM, never "no such file",
  "connection refused" or "address in use"), `permit` (anything but a
  sandbox denial), `allow` (the operation succeeded), `skip` (not
  exercised in this mode). Verbs: read, list, write, exec, connect,
  listen, mach-lookup, keychain-framework, keychain-cli. The launcher runs
  the control pass unconfined (every `control` column must hold, so no
  confined row passes vacuously), then the confined pass under the
  rendered profile with ollama's parameters, before every start, and
  alone with `--probe-only` (what tds-internal's G6 smoketest runs, PR#467).
  Adding a property is adding a row. `sandbox-exec` plus the rendered
  profile is today's only implementation behind it.
- **The rows as built** (18): the file canary
  `~/.local/state/ollama-gateway-probe/canary` unreadable; the store
  listable and unwritable; the installed launchers (`<tree>/libexec`)
  unwritable; the gateway home writable; `/private/tmp`, `/opt/homebrew/bin`
  unwritable; the user's `DARWIN_USER_TEMP_DIR` and `/usr/local`
  unlistable; the Keychain canary (service
  `lmde.ollama-gateway.probe-canary`) not found through the Security
  framework nor through `/usr/bin/security`; `launchctl print` and `open
  -Ra Finder` refused; the LaunchServices mach service refused from
  python (a binary the profile does not deny by path); connect to 11434,
  to the route's 11436 and off the host (`224.0.0.1:9`) refused; listen on
  the engine's own port permitted.
- **The probe proves with canaries, never the run token.** Both canaries
  hold the literal `not-a-secret`; the Keychain rows look the canary up by
  attributes only and never read its secret, with Security-framework user
  interaction switched off first and `/usr/bin/security` tried only after
  a dialog-free framework lookup (Issue#441). The connector, by contrast,
  reads the run token's secret with `/usr/bin/security
  find-generic-password -w` (Issue#442: can still prompt).
- **The profile is a template rendered per machine.** The only
  machine-specific text is the `@EPHEMERAL_OUTBOUND@` block; everything
  else comes from the committed `.sb.in`. The rendered file is not
  committed.
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
| Re-prove confinement on a running laptop | `launch-ollama.zsh --probe-only` | a human, or tds-internal's G6 smoketest |
| Hold the tunnel open | `launch-connector.zsh` `main` | `com.tds.lmde.ollama-gateway.connector` plist |
| Answer before the deadline; hold the load | `route/ollama-gateway.cfg` | the proxy layer's `launch-proxy.zsh` |
| Install / uninstall | `setup.sh` `do_install` / `do_uninstall` | `lmde install ollama-gateway` |
| Health and origin-port drift | `healthcheck.sh`: `external-ollama`, `deadline-proxy`, `edge` | `lmde status`, `lmde doctor` |
| Derive the allow-list | `profile-trace.zsh --model <name>` | a human, after an ollama or macOS upgrade |
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

An install: `setup.sh` copies the launchers, probe, profile template,
conformance table, `gateway.env` and connector config into the gateway
tree; renders the profile for this machine's kernel; creates `home/`
(with `.ollama` and `tmp`); recreates both canaries (the Keychain one
deleted and re-added, never modified in place); installs the route and
restarts the proxy layer if loaded; renders both LaunchAgents and
restarts the external ollama; and restarts the connector if its run
token is seeded, else leaves it disabled.

A start of the external ollama: launchd runs `launch-ollama.zsh`;
`load_config` resolves `ollama` on PATH and its keg. Preflight refuses
(exit 78, naming the reason) when `sandbox-exec`, the rendered profile,
the conformance table, the gateway home or the store is missing; when the
engine port is not 1-65535 or is 11434; when the keg is missing or not a
private keg (one of `/`, `/usr`, `/usr/local`, `/opt`, `/opt/homebrew`,
`/opt/local`, an ancestor of `$HOME`, or a `bin/` holding anything but
`ollama*`); and, except under `--probe-only`, when 11435 is already
bound. Then the probe runs unconfined, then confined (cwd the gateway
home); then `exec sandbox-exec -f <profile> -D ... /usr/bin/env -i ...
ollama serve`. Any failure exits 78 and launchd retries in 30 s; the
gateway is DEGRADED until the probe passes. Profile compilation adds a few
seconds to every start.

A start of the connector: read the token from the Keychain (service
`lmde.ollama-gateway.tunnel-token`, account `ollama-gateway`); a missing
or malformed token exits 78 naming the item; else `exec cloudflared` with
the token on `/dev/fd/N`. `setup.sh` installs this agent disabled until the
token is seeded.

## The sandbox profile as built

`(deny default)`, every allow named (PR#462, Issue#460). In SBPL the last
matching rule wins, so the explicit denials at the end take back part of
an allow above them.

- **Process and kernel**: fork, signals to self and children,
  `sysctl-read`, `system-socket`; the GPU through two IOKit user-client
  classes (`AGXDeviceUserClient`, `IOSurfaceRootUserClient`) and
  `com.apple.MTLCompilerService`; the logging, notification-center and
  opendirectory libinfo mach services.
- **Exec**: the engine's keg (`OLLAMA_KEG`), `/bin`, `/usr/bin`,
  `/usr/libexec`, the Command Line Tools. Nothing under `$HOME`,
  `/private/tmp` or the rest of the Homebrew prefix.
- **Reads**: OS-owned trees that hold no user data (`/System`, `/usr`
  with `/usr/local` taken back, `/bin`, `/sbin`, the cryptex under
  `/private/preboot`, `/private/etc`, `/private/var/db/dyld` and
  `timezone`, `/Library/Frameworks`, `/Library/Preferences/Logging`,
  `/Library/Apple`, the Command Line Tools, `/dev`), plus metadata on the
  path components leading to them; the Homebrew kegs the engine links
  against (its own, `mlx`, `mlx-c`) and metadata on every Cellar path,
  never Homebrew's `etc/` or `var/`.
- **The gateway's own trees**: the gateway tree read-only; `HOME` =
  `<tree>/home`, the only writable tree; the store readable, its writes
  denied explicitly (Q7); metadata only on `$HOME` itself and the store's
  parent (Issue#443, Issue#455). Nothing else under `$HOME`: `~/.ssh`, AI
  tool credentials, 1Password data, `~/.ollama/id_ed25519` and the login
  keychain file are unreachable because nothing allows them.
- **Network**: bind and inbound on loopback (a wildcard); outbound only
  to `localhost:<p>` for each port of the kernel's ephemeral range, where
  the runner lives. Every well-known loopback port, 11434 and 11436
  included, and everything off the host are out of reach outbound.
- **Explicit denials, last**: exec of `/usr/bin/security`,
  `/bin/launchctl` and `/usr/bin/open`; mach lookups of the keychain
  daemons (`com.apple.SecurityServer`, `securityd`, `secd`,
  `security.*`), LaunchServices (`coreservices.launchservicesd`, `lsd.*`)
  and launchd (`xpc.launchd*`), so a copied binary fails too.

The allow-list was derived with `profile-trace.zsh`, round by round, until
the workload (model load, `/v1/models`, a completion) passed with an empty
trace.

Residuals as built:

- The engine may bind any loopback port while the real listener on it is
  down (Issue#463): a second per-port block for bind pushes the compiled
  profile past what `sandbox_apply` accepts.
- Loopback services bound to a port in the ephemeral range stay reachable
  outbound, because the runner lives there.
- Metadata reads of `$HOME` and `~/.ollama` (Issue#455).
- The connector runs unconfined, with the run token in the login
  Keychain, readable by `/usr/bin/security` without a dialog to any
  unconfined process of this account.

Loopback neighbours: Caddy's admin API (the LMDE networking component) is
on the unix socket `~/.local/share/lmde-networking/run/caddy-admin.sock`,
mode 0600, in a 0700 run dir (PR#466, Issue#465); nothing listens on TCP
port 2019. The proxy layer's hold hop is a unix socket too.

## Built but not designed

Recorded here as fact; recording is not approval.

- Metadata reads of `$HOME` and `~/.ollama`, outside G4's allow-list:
  drift, Issue#455.
- `X-LMDE-Route: ollama-gateway` on every response: the Q8 drift check's
  mechanism (Key Decisions Q8 leaves the mechanism to code).
- The `Host` rewrite to loopback (Issue#444): ollama's DNS-rebinding guard
  answers 403 to the public hostname.
- Probe rows beyond G4's two (the file and the Keychain): the table above,
  including the launchers' directory unwritable and the gateway tree
  read-only except `home/`. The design delegates the profile's text to
  code.
- The keg check: the launcher grants the engine exec and read only on a
  private keg and refuses a shared prefix or a home directory.
- The refusals of a bound engine port (lifted under `--probe-only`) and
  of a missing conformance table or gateway home.
- The probe's shape: non-secret canaries in place of the run token, found
  by attributes; the `skip` expectation; `--probe-only`.
- `HOME` = `<tree>/home`, a tree of its own inside the gateway tree, as
  the one writable tree.
- Engine parameters the design does not name: context length, flash
  attention, KV cache type, `OLLAMA_NO_CLOUD`.

## Radar reality

| Tech | Ring (`lmde/TECH_RADAR.md`) | Used for |
|---|---|---|
| Ollama | Adopt | the external engine |
| cloudflared | Adopt (2026-10-12) | the connector |
| sandbox-exec | Adopt (2026-10-12) | confinement, gated by the probe |
| HAProxy | Adopt (2026-10-03) | the proxy layer and this route |
| Python 3 | Adopt | the Security-framework and mach-service probes (stdlib `ctypes`) |
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
- **An allow-list under `$HOME` on top of `(allow default)` is undone by
  any unconfined loopback neighbour.** The first profile denied the home
  directory and allowed everything else, so every local control API on
  loopback stayed reachable; one that is unauthenticated and runs
  unconfined (Caddy's admin API on TCP 2019) can be told to serve any file
  the user can read, and the home-directory deny proved nothing (Issue#460,
  Issue#465). The profile became deny-by-default with outbound loopback
  limited to the ephemeral range (PR#462), and the neighbour moved to a
  0600 unix socket (PR#466).
