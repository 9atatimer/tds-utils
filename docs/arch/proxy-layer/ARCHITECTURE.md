# LMDE proxy layer -- as-built

What is deployed, not what was designed. Living.

- Authority: the [Ollama Gateway design](../../design/OLLAMA-GATEWAY.DESIGN.md),
  Deadline proxy, and its Key Decisions Q10 and Q12. The layer has no
  design record of its own.
- Source: `lmde/components/proxy-layer/` (its README is the operator's
  reference).
- Tenants today: one, the Ollama Gateway's route
  ([as-built](../ollama-gateway/ARCHITECTURE.md)). The OTLP ingest route
  and the chores webhooks are planned, not built.

## Deployment

- Runs on the owner's laptop as the LaunchAgent `com.tds.lmde.proxy-layer`:
  HAProxy in the foreground (`-db`), supervised by launchd (no daemon
  mode, no master-worker, no stats socket). Live since 2026-10-13.
- Installed by `lmde install proxy-layer` (`setup.sh`), which copies
  `haproxy.cfg` and `libexec/` into `~/.local/share/lmde-proxy` and
  renders the plist. Tenants install their own routes into
  `~/.local/share/lmde-proxy/routes/` and restart the layer when it is
  loaded. Uninstall leaves routes for their tenants.
- Runtime dependency: Homebrew `haproxy`.
- Logs: `~/Library/Logs/lmde-proxy/haproxy.log` -- errors, timeouts and
  aborts only (`option dontlog-normal`): request line and timings, never a
  body (Q10).

## Components and layout

| Path under `~/.local/share/lmde-proxy` | What |
|---|---|
| `haproxy.cfg` | `global` and the `defaults` every route inherits |
| `libexec/launch-proxy.zsh` | exports `LMDE_PROXY_ROOT`, `LMDE_PROXY_ROUTES`, `LMDE_PROXY_RUN`; sources every `routes/*.env` with export on; `haproxy -c` over the layer config plus every route; then execs `haproxy -db` |
| `routes/<tenant>.cfg` | a tenant's route: one loopback TCP listener (Q12) |
| `routes/<tenant>.env` | POSIX sh assignments the route reads as `${VAR}` |
| `routes/<tenant>.*` | anything else the route references (errorfiles) |
| `run/` (mode 700) | the layer's unix sockets, for hops that must never be a TCP port |

## Tuned values

| Value | Setting | Where |
|---|---|---|
| `mode` | `http` | `haproxy.cfg` defaults |
| `timeout connect` | `2s` | defaults |
| `timeout http-request` | `30s` | defaults |
| `timeout client` | `10m` | defaults |
| `timeout server` | `10m` (a route overrides it: the gateway's 90 s deadline and 6 m hold) | defaults |
| Logging | `log stderr format raw daemon info`, `option httplog`, `option dontlog-normal` | `haproxy.cfg` |
| File descriptors | soft and hard `NumberOfFiles` 8192 | plist |
| Restart | `RunAtLoad`, `KeepAlive` on unsuccessful exit, `ThrottleInterval` 10 s | plist |
| Refusal | exit 78 with no routes, no `haproxy`, or an invalid configuration | `launch-proxy.zsh` |

No throttle and no payload cap is set (Q12).

## Seams in the code

- **A route is a file set**, named by its tenant, that the launcher
  discovers by glob. Adding a tenant changes no layer file.
- **One loopback listener per route** (Q12), so each tunnel's
  `origin_port` maps to exactly one route.
- **The tenant owns its values**: the layer exports `routes/<tenant>.env`
  to HAProxy's environment, and the route reads them as `${VAR}`.

## Built but not designed

Recorded as fact: the `defaults` timeouts above (Q12 sets no throttle or
payload cap, and these are neither, but `timeout http-request 30s` does
bound how long a request's headers may take to arrive), and the 8192
descriptor limit.

## Lessons the shape taught

- **launchd's default descriptor limit is a hidden connection cap.** At
  256 descriptors HAProxy sizes itself to about 100 connections, a cap Q12
  does not set; each gateway request holds four descriptors across its two
  hops. The plist raises the limit (PR#440, test 07 of
  `test/smoketest_lmde_proxy_layer`).
- **Environment-variable routes keep tenants independent of the layer.**
  The gateway's `gateway.env` is both its launcher's config and its
  route's (installed as `routes/ollama-gateway.env`), so one file holds
  each value.
