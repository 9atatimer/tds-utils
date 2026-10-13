# Ollama Gateway -- runbook

Operating the laptop side of the Ollama Gateway: the sandboxed external
ollama, its cloudflared connector, and its route on the LMDE proxy layer.

- Reference (files, contract, values): `lmde/components/ollama-gateway/README.md`,
  `lmde/components/proxy-layer/README.md`.
- As-built: `docs/arch/ollama-gateway/ARCHITECTURE.md`,
  `docs/arch/proxy-layer/ARCHITECTURE.md`.
- Design: `docs/design/OLLAMA-GATEWAY.DESIGN.md` (APPROVED).
- The edge (tunnel, DNS, Access, tokens) is tds-internal
  `ops/terraform/ollama-gateway`; a human applies it there.
- The first caller's runbook: `docs/ops/ocr-review.md`.

---

## Ship

One stage, production (`ollama.api9.com`): one laptop, one model store,
so there is no nonprod (design Key Decisions Q1). The stand-in for nonprod
is the offline suites, run by hand on macOS before merging (no CI job runs
them: Issue#456): they drive the real `sandbox-exec` and a real HAProxy
against fakes.

```
bash test/smoketest_lmde_ollama_gateway/run_all.sh
bash test/smoketest_lmde_proxy_layer/run_all.sh
```

- Merge to `master`, then `bin/tds-release` (the human's step).
- Then, from a shell whose `lmde` is the release worktree's, reinstall
  whichever component the release touched:

  ```
  lmde install proxy-layer
  lmde install ollama-gateway
  ```

  `setup.sh` COPIES the component into `~/.local/share/`; a release alone
  changes nothing that runs. Either order works; each restarts what it
  owns.
- First install on a machine only: a human seeds the run token, with the
  1Password desktop app unlocked, then loads the connector (the
  `op://` reference is in the tds-internal edge record, not here):

  ```
  lmde/components/ollama-gateway/seed-tunnel-token.zsh op://<vault>/<item>/<field>
  launchctl enable gui/$(id -u)/com.tds.lmde.ollama-gateway.connector
  launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.tds.lmde.ollama-gateway.connector.plist
  ```

  An agent never runs the seeding script.

## Verify

- `lmde status` (or `lmde/components/ollama-gateway/healthcheck.sh`).
  Green: `external-ollama: OK`, `deadline-proxy: OK (127.0.0.1:11436,
  HTTP 200)`, and exit 0. `edge` is SKIPPED unless configured.
- The origin-port drift check through the edge: the same healthcheck with
  `OLLAMA_GATEWAY_EDGE_URL` and the consumer credential's four variables
  set, typically under `op run` with an env file kept in tds-internal (the
  header of `healthcheck.sh` names them). Green: `edge: OK (the tunnel
  reaches the deadline proxy, HTTP 200)`.
- End to end: tds-internal `scripts/ollama-gateway/smoketest.sh`, run by a
  human from the tds-internal root. Green: PASS on all six checks
  (uncredentialed refusal, credentialed model list, the `X-LMDE-Route`
  header, the 404 catch-all on two paths, a clean plan). It was PASS 6/6
  on 2026-10-13.
- After any restart, `~/Library/Logs/ollama-gateway/ollama.log` shows
  `launch-ollama: probe passed under ...` then `starting ... serve`.

## Roll back

- To an earlier version: `bin/tds-release -f <sha>` (human), then
  `lmde install proxy-layer` and `lmde install ollama-gateway` again.
- Off the road at once: `launchctl bootout
  gui/$(id -u)/com.tds.lmde.ollama-gateway.connector`. The edge then
  answers 530 to every credentialed request. `bootout` lasts until the
  next login; add `launchctl disable` with the same target to keep it off.
- Remove: `lmde/components/ollama-gateway/setup.sh uninstall` (agents,
  tree, canaries, route; restarts the layer) and
  `lmde/components/proxy-layer/setup.sh uninstall` (the layer; routes
  stay for their tenants).
- Not undone by any of these: the run token in the Keychain (`setup.sh
  uninstall` prints the delete command), the edge (tds-internal), and the
  model store (the gateway never writes it).

## Debug

| Where | What is there |
|---|---|
| `~/Library/Logs/ollama-gateway/ollama.log` | the launcher's preflight and probe lines (`ok <check>` / `FAIL <check>: <why>`), then ollama's own log, one `[GIN]` line per request |
| `~/Library/Logs/ollama-gateway/connector.log` | cloudflared: tunnel registration, connection errors |
| `~/Library/Logs/lmde-proxy/haproxy.log` | errors, timeouts and aborts only; a normal request is not logged; never a body |
| `launchctl print gui/$(id -u)/<label>` | state and last exit code; 78 is a refused start |

What a caller's status code means, outermost first:

| Answer | From | Meaning |
|---|---|---|
| 302, 403 without `X-LMDE-Route` | Cloudflare Access | missing or invalid credential |
| 404 without `X-LMDE-Route` | tunnel ingress | path not allow-listed |
| 530 | Cloudflare | no connector (laptop asleep or offline, connector stopped) |
| 502 | cloudflared | nothing listens on 127.0.0.1:11436 (proxy layer down) |
| 503 with `X-LMDE-Route` | the route | ollama not listening (a refused probe, a crash) |
| 507 with `X-LMDE-Route` | the route | no first byte within 90 s; retry after `retry-after` |
| 403 with `X-LMDE-Route` | ollama | a non-loopback `Host` reached ollama (Issue#444; the route rewrites it) |
| 2xx with `X-LMDE-Route` | ollama | the answer |

## Gotchas

- **Keychain dialogs.** Never change a Keychain item's access in place: it
  prompts. `setup.sh` deletes and recreates the probe's canary on every
  install. A control pass failing for want of a dialog is fixed by
  re-running `setup.sh`. The connector still reads the run token with
  `/usr/bin/security`, which can prompt if the keychain is locked or the
  item does not trust it (Issue#442); re-seed with `seed-tunnel-token.zsh`,
  which writes the item so `/usr/bin/security` reads it without a prompt.
- **ollama upgrades.** The external ollama reads the store read-only, so
  after a Homebrew upgrade past a store-layout change it lists no models
  until the everyday ollama has run the new version once. A new version
  that stats a new path outside the allow-list also lists no models
  (Issue#443): `ollama.log` shows `operation not permitted`.
- **`Host`.** ollama answers 403 to any non-loopback `Host`. Any new route
  to an ollama rewrites `Host`, as this one does.
- **Non-streaming completions longer than 90 s always get 507**, on every
  retry: the deadline is HAProxy's inactivity timeout. Stream.
- **`keep_alive` is 2 m**, so a review that starts later cold-loads the
  model. From a cold OS cache that can take past the deadline: the caller
  sees 507 and retries; the held load completes.
- **`~/.cloudflared` belongs to another tunnel.** The connector runs with
  its own `HOME` and `--config`; never run `cloudflared` by hand against
  the default config for this tunnel.
- **Ports.** 11436 is mirrored by hand in tds-internal (`origin_port`);
  change both together and run the edge check. 11435 already bound makes
  the launcher refuse rather than start beside it. The route's 503 and
  507 are mirrored in `lib/ocr-review/gateway.mjs`; change both in one PR.
- **Transport is pinned to http2**: QUIC over IPv6 fails on this network.

## Known gaps

- The silent-connector bound (Q6), the G5 bounds through the edge
  (stopped connector, stopped proxy layer), and G1 from a cold OS cache
  are not yet measured: task-046.
- The connector's Keychain read can prompt under launchd: Issue#442.
- The sandbox admits metadata reads of `$HOME` and `~/.ollama`, outside
  G4's allow-list: Issue#455 (owner decision).
- Nothing records which commit is installed under `~/.local/share/`.
- The component suites run in no CI job: Issue#456.
- Logs only: no metrics or traces reach LMDE observability.
- The caller holds the gateway credential: Issue#365.
