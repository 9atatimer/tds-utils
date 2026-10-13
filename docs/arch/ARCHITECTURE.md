# tds-utils -- as-built index

What is deployed right now, as fact. `docs/design/` holds what was
intended and is frozen at APPROVED; this tree is living and holds nothing
that has not shipped (the architecture skill, folder law). Each topic's
`ARCHITECTURE.md` is the detail for agents; its `.html` is the at-a-glance
view for humans; the two must agree.

Coverage: this tree starts with the Ollama Gateway and OCR on Demand
release (2026-10-13). Components that shipped earlier (the dotfiles and
release worktree, chores, Dynomark, log-hoarder, the dist tools, the other
LMDE components) have no as-built yet; their absence here says nothing
about whether they are deployed.

## Inventory

| Component | What it is | Source | Runs where | As-built |
|---|---|---|---|---|
| Ollama Gateway, laptop side | A second ollama under `sandbox-exec`, reached by authorized callers through Cloudflare Access, a cloudflared tunnel and the proxy layer | `lmde/components/ollama-gateway/` | the owner's laptop, LaunchAgents | [ollama-gateway/](./ollama-gateway/ARCHITECTURE.md) |
| LMDE proxy layer | HAProxy: the one local front door for laptop services with a public port; one route per tenant | `lmde/components/proxy-layer/` | the owner's laptop, LaunchAgent | [proxy-layer/](./proxy-layer/ARCHITECTURE.md) |
| OCR on Demand | A reusable GitHub Actions workflow that runs Open Code Review over a PR on demand, with completions from the gateway | `.github/workflows/ocr-review.yml`, `bin/ocr-review`, `lib/ocr-review/`, `bin/seed-ocr-review`, `bin/ocr-review-stats` | adopting repos' Actions: the caller's `CI_RUNS_ON` pool, else GitHub-hosted | [ocr-review/](./ocr-review/ARCHITECTURE.md) |

Outside this repo: the gateway's edge (tunnel, DNS, Access, service
tokens, 1Password items) is tds-internal `ops/terraform/ollama-gateway`,
and the runner pool's image is tds-internal
`services/ci-runner-pool/`. Their as-builts live there.

## How they connect

```
adopting repo  -- /ocr or dispatch -->  OCR on Demand (Actions runner)
                                          | HTTPS, Access headers from 1Password
                                          v
                               ollama.api9.com (Cloudflare Access, tunnel)
                                          | cloudflared, http2
                                          v
                               proxy layer route 127.0.0.1:11436
                                          | unix socket hold hop
                                          v
                               sandboxed ollama 127.0.0.1:11435
```

## Cross-cutting friction

- **Values mirrored by hand across boundaries.** The route port 11436 is
  mirrored in tds-internal as the tunnel's `origin_port` (the gateway
  healthcheck's edge check and tds-internal's smoketest detect drift). The
  route's 503 and 507 are mirrored in `lib/ocr-review/gateway.mjs`
  `GATEWAY_STATUS`; nothing checks that pair.
- **Installed by copy.** The laptop components run from copies under
  `~/.local/share/` that `lmde install` makes; `bin/tds-release` moves the
  release worktree but does not reinstall them, and nothing records which
  commit is installed.
- **Two pins per adopter.** An OCR on Demand caller pins the workflow and
  the step code separately (Issue#453).
- **The runner pool's 10-minute container ceiling** bounds the review
  job (9 min), which must hold a cold-model probe of up to about 7.5 min.

## Radar reality

| Tech | Ring | Radar | Used by |
|---|---|---|---|
| Ollama | Adopt | `lmde/TECH_RADAR.md` | gateway |
| cloudflared | Adopt | `lmde/TECH_RADAR.md` | gateway |
| sandbox-exec | Adopt | `lmde/TECH_RADAR.md` | gateway |
| HAProxy | Adopt | `lmde/TECH_RADAR.md` | proxy layer |
| 1Password CLI | Adopt | `lmde/TECH_RADAR.md` | token seeding; OCR on Demand's credentials |
| Python 3, Node.js | Adopt | `lmde/TECH_RADAR.md` | the Keychain probe; `bin/ocr-review` |
| Open Code Review | Trial | the fleet tech-radar skill | OCR on Demand -- the row scopes it to the self-review adapter only (finding; see [ocr-review/](./ocr-review/ARCHITECTURE.md)) |
