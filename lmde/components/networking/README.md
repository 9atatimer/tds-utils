# LMDE Component: Networking

## Overview

Owns the host edge of LMDE cluster ingress: it makes in-cluster HTTP services
reachable from the laptop at stable `*.{cluster}.localhost` vhosts. See
[LMDE.DESIGN.md](../../../docs/design/LMDE.DESIGN.md), section 4 (Host
ingress), for the full design.

## The Pattern

```
*.{cluster}.localhost -> Caddy -> ingress-nginx (in {cluster}) -> Service -> pod
```

- **Caddy** (host) terminates TLS and reverse-proxies a cluster's wildcard
  vhost to that cluster's ingress port on `127.0.0.1`.
- **ingress-nginx** (in each cluster) routes by `Host` header to the target
  `Service`. Pod churn is absorbed by the Service; no reconfiguration.

## Pieces

- `setup.sh` -- installs Caddy's configuration: renders `caddy/Caddyfile.in`
  into Homebrew's `/opt/homebrew/etc/Caddyfile` with the admin API on the
  component's unix socket (`~/.local/share/lmde-networking/run/caddy-admin.sock`,
  mode 0600, run dir 0700) and restarts the Homebrew service. A human runs
  it once per laptop and after a Caddy reinstall.
- `lib.sh` -- sourced helper library. `register_cluster_vhost <alias> <port>`
  adds or updates the Caddy route for `*.{alias}.localhost`;
  `unregister_cluster_vhost <alias>` removes it. Every admin call goes
  through `caddy_api`, over the socket.
- `ingress-nginx/` -- the in-cluster controller: a vendored kind-provider
  manifest plus `setup.sh`, which applies it and waits for the rollout.

## Conventions

- **Vhost scheme:** `*.{cluster}.localhost`. `.localhost` resolves to
  loopback with no dnsmasq configuration.
- **Ingress ports:** `3210X`, where `X` is the cluster index (`0`-`9`).
  Drawn from the Kubernetes NodePort range (`30000`-`32767`): clear of common
  dev ports, below the Linux ephemeral floor (`32768`). The observability
  cluster is index `0`, hence `32100`.
- **Caddy assumption:** routes are added to Caddy server `srv0` (the default
  server name Caddy assigns), via the admin API on the component's unix
  socket. The API is unauthenticated and can make the proxy serve any file
  this account can read, so it is never on a TCP port (Issue#465).

## Usage

`setup.sh install` puts Caddy on its socket. `lib.sh` is sourced by a
cluster's `setup.sh`; `ingress-nginx/setup.sh` is invoked during that
bootstrap once the cluster exists. Tests: `test/smoketest_lmde_networking/`
(a fake admin API on a unix socket; nothing real is touched).
