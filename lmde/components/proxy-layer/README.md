# LMDE Component: Proxy Layer

The one local reverse proxy every laptop service with a public port sits
behind (HAProxy, Adopt in `lmde/TECH_RADAR.md`). It centralizes the
per-route deadline, throttling and payload limits so no service grows its
own ([Ollama Gateway design](../../../docs/design/OLLAMA-GATEWAY.DESIGN.md),
Deadline proxy; Key Decisions Q12). First tenant: the Ollama Gateway's
deadline route. Planned next: OTLP ingest (`docs/design/LMDE.DESIGN.md`
section 3.4) and the chores webhooks.

## Layout

Installed under `~/.local/share/lmde-proxy`:

- `haproxy.cfg` -- global settings and the defaults every route inherits.
  Logs errors, timeouts and aborts only (request line and timings, never a
  body).
- `libexec/launch-proxy.zsh` -- exports each `routes/*.env`, validates the
  whole configuration, then execs HAProxy in the foreground.
- `routes/` -- one set of files per tenant, installed by that tenant's
  `setup.sh`:
  - `<tenant>.cfg` -- the route. One loopback TCP listener per route
    (Q12), so each tunnel's `origin_port` maps to exactly one route.
  - `<tenant>.env` -- POSIX sh assignments the route reads as `${VAR}`.
  - anything else the route references (errorfiles), named `<tenant>.*`.
- `run/` -- the layer's unix sockets (mode 700), for hops that must never
  be a TCP port.

The launcher exports `LMDE_PROXY_ROOT`, `LMDE_PROXY_ROUTES` and
`LMDE_PROXY_RUN` for routes to reference.

## Install, operate, remove

Runbook: [docs/ops/ollama-gateway.md](../../../docs/ops/ollama-gateway.md)
(the layer's only tenant today); as-built:
[docs/arch/proxy-layer/](../../../docs/arch/proxy-layer/ARCHITECTURE.md).

- Install: `lmde install proxy-layer` (or `setup.sh`). Tenants install their
  routes independently and restart the layer when it is loaded.
- LaunchAgent: `com.tds.lmde.proxy-layer`, logs in
  `~/Library/Logs/lmde-proxy/haproxy.log`; restarts after an unsuccessful
  exit (no routes or an invalid configuration refuses with exit 78).
- Restart after editing a route:
  `launchctl kickstart -k gui/$(id -u)/com.tds.lmde.proxy-layer`.
- Stop: `launchctl bootout gui/$(id -u)/com.tds.lmde.proxy-layer`.
- Remove: `setup.sh uninstall` (routes stay for their tenants).
