# Ollama Gateway (laptop side) -- runbook

The laptop half of the Ollama Gateway: a second, sandboxed `ollama serve`
that an authorized caller off the laptop reaches through Cloudflare Access,
a cloudflared tunnel and the LMDE proxy layer's deadline route. The edge
(tunnel, DNS, Access, service tokens) is tds-internal
`ops/terraform/ollama-gateway/`; this runbook is the laptop.

- Design: `docs/design/OLLAMA-GATEWAY.DESIGN.md` (APPROVED; Key Decisions
  rows of 2026-10-13 supersede the "first cut" sandbox text).
- Component: `lmde/components/ollama-gateway/` (its README has the file
  map); the route: `lmde/components/proxy-layer/`; the host proxy's
  administration: `lmde/components/networking/`.
- Tests: `test/smoketest_lmde_ollama_gateway/run_all.sh`,
  `test/smoketest_lmde_proxy_layer/`, `test/smoketest_lmde_networking/`.
- First caller: OCR on Demand, `docs/ops/ocr-review.md`.

---

## What runs, and where it comes from

| Piece | Runs as | Config it reads | Installed by |
|---|---|---|---|
| external ollama, `127.0.0.1:11435` | `com.tds.lmde.ollama-gateway.ollama`, under `sandbox-exec` | `~/.local/share/ollama-gateway/` (the gateway tree: launchers, probe, the rendered profile, the probe table, `gateway.env`) | `lmde install ollama-gateway` (`setup.sh`) |
| connector (cloudflared) | `com.tds.lmde.ollama-gateway.connector`, unconfined | the run token in the login Keychain (`lmde.ollama-gateway.tunnel-token`) | the same, enabled once a human seeds the token |
| deadline route, `127.0.0.1:11436` | `com.tds.lmde.proxy-layer` (HAProxy) | `~/.local/share/lmde-proxy/routes/ollama-gateway.*` | the gateway's `setup.sh` installs the route; `lmde install proxy-layer` the layer |
| Caddy (host vhosts, unrelated to the road) | Homebrew `caddy` service | `/opt/homebrew/etc/Caddyfile`, admin API on `~/.local/share/lmde-networking/run/caddy-admin.sock` | `lmde install networking` |

What is live follows the `release` worktree (`AGENT.md`, The Release
Worktree): a merged change reaches the laptop by `bin/tds-release`, then the
component's install.

## Install, upgrade, release

- Fresh laptop: `lmde install proxy-layer`, `lmde install ollama-gateway`,
  then seed the run token (component README, The connector), then
  `lmde install networking` for Caddy's socket.
- After any change to the component lands on `master`:
  `bin/tds-release`, then `lmde install ollama-gateway` again. The install
  re-renders the sandbox profile for this machine, reinstalls the route and
  restarts the external ollama; the connector stays up. Expect the first
  start to take a few seconds longer: the profile lists every ephemeral
  port and compiles on each start.
- After an `ollama` or macOS upgrade: re-derive the allow-list before
  trusting the gateway (below). The engine's keg path changes with every
  ollama version; the launcher derives it from `whence -p ollama`, so a
  new keg needs no edit, but new files the engine reads do.

## The sandbox, and what proves it

The profile is deny-by-default (`sandbox/ollama-gateway.sb.in`); every allow
is named. The launcher never trusts the profile text: before every start it
runs `libexec/probe.zsh` twice over `sandbox/ollama-gateway.probe.tsv`,
unconfined (every row must be reachable, so nothing can pass vacuously) and
under the profile (every `deny` row must be a sandbox denial), and refuses
to start on any failed row. The connector is not sandboxed.

- Re-prove it on a running laptop without restarting the engine:

  ```
  ~/.local/share/ollama-gateway/libexec/launch-ollama.zsh --probe-only
  ```

  Exit 0 and one `ok` line per row in both passes; exit 78 and a `FAIL`
  line naming the row otherwise. tds-internal's G6 smoketest runs this.
- Add a property: one row in the table (`check  confined  control  verb
  target`), then `lmde install ollama-gateway`. The row is the test.

### Re-deriving the allow-list

`libexec/profile-trace.zsh` runs the real engine under a candidate profile
on a scratch port with a scratch HOME, drives the gateway's workload
(version, model list, one completion) and prints every operation the
sandbox denied, for the engine and its runner, as the unified log recorded
them, then as SBPL lines to shape by hand.

```
lmde/components/ollama-gateway/libexec/profile-trace.zsh --model llama3.2:latest
```

- Read the denials. One that the workload needed (a path the new ollama
  reads, a mach service Metal now wants) becomes an allow in the template,
  as a literal or the narrowest subpath, with a comment saying which step
  wanted it. One it did not need (`.CFUserTextEncoding`, `dtracehelper`,
  mDNSResponder, the user's preferences) stays denied.
- Iterate until the completion answers 200 and the trace carries only
  denials the engine does not need. Then run the suite and open the PR; the
  design's Key Decisions row records the shape, not the list.
- The tracer stops the engine it started on exit, interrupt and hangup. If
  it dies some other way (Issue#464), `ps -axo pid,command | grep 'ollama
  serve'` and kill the one whose cwd is the scratch dir.

## Diagnosis

`lmde status` (or the component's `healthcheck.sh`) reports
`external-ollama`, `deadline-proxy` and, with the edge credential in the
environment, `edge`. Logs: `~/Library/Logs/ollama-gateway/{ollama,connector}.log`,
`~/Library/Logs/lmde-proxy/haproxy.log`.

| Symptom | Where to look | What it usually is |
|---|---|---|
| `external-ollama: DEGRADED`, log says `refusing to start` | `ollama.log`, the `FAIL <row>` line above it | the probe refused: a canary missing (`run setup.sh` again), the keychain wanting a dialog (unlock it), or a profile that no longer denies what the row asserts. launchd retries every 30 s; the gateway stays down until the row passes. Never "fix" it by widening the profile without a trace |
| launcher says `refusing to grant the engine <dir>` | `ollama.log` | `ollama` on PATH is a regular file in a shared bin dir, not a Homebrew keg; the launcher will not grant a whole prefix to the engine. Install ollama with Homebrew |
| engine up, completion returns 500 with `operation not permitted` | `ollama.log` (the `srv` lines) | the engine or its runner needs a file or service the profile denies: run the tracer |
| `deadline-proxy: DEGRADED` | `haproxy.log`; `launchctl print gui/$(id -u)/com.tds.lmde.proxy-layer` | the layer is down or another process took 11436 |
| caller gets 507 for 6 minutes | `ollama.log` | a cold model load longer than the caller's retry budget; nothing to fix, re-run |
| `edge: DEGRADED ... DRIFT` | tds-internal module README, Q8 | the edge's origin port reaches some other listener; stop and read that README |
| Caddy vhosts gone after an install | `curl --unix-socket ~/.local/share/lmde-networking/run/caddy-admin.sock http://localhost/config/` | the networking install restarted Caddy; routes are added at cluster bootstrap, so re-run the cluster's setup or `register_cluster_vhost` from `lib.sh` |

## Stop, start, remove

- Take the road down without touching the engine: `launchctl bootout
  gui/$(id -u)/com.tds.lmde.ollama-gateway.connector`. The edge then answers
  530 to callers. Back: `launchctl bootstrap gui/$(id -u)
  ~/Library/LaunchAgents/com.tds.lmde.ollama-gateway.connector.plist`.
- Restart the engine (after an install, or to pick up a rendered profile):
  `launchctl kickstart -k gui/$(id -u)/com.tds.lmde.ollama-gateway.ollama`.
- Remove everything but the run token: `lmde/components/ollama-gateway/setup.sh
  uninstall` (it prints the keychain command for the token).

## What the sandbox does not cover, stated

- Loopback services bound to a port in the kernel's ephemeral range
  (49152-65535) stay reachable from the engine, because its runner lives
  there. Bind local control APIs to unix sockets or well-known ports.
- The engine may bind any loopback port while its real listener is down
  (tds-utils Issue#463): a per-port bind block does not fit the profile
  size `sandbox_apply` accepts.
- The connector runs unconfined and reads the run token from the login
  Keychain, whose ACL admits `/usr/bin/security` without a dialog: any
  unconfined process of this account can read it. The structural fix is a
  dedicated macOS user for the gateway (tds-internal remediation plan,
  phase 4).
