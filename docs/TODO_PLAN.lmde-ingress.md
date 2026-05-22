# LMDE Ingress (ingress-nginx) Implementation TODO Plan

> **Status:** Implemented -- pending human bootstrap
> **Created:** 2026-05-22
> **Design:** [LMDE-OBSERVABILITY.DESIGN.md](design/LMDE-OBSERVABILITY.DESIGN.md)
> **Branch:** `claude/feat/lmde-ingress-nginx`

---

## Goal

Make Grafana reachable at `grafana.lmde.localhost` through the chain
`Caddy -> ingress-nginx -> Grafana Service`, replacing the rejected istio
approach, and establish the reusable `*.{cluster}.localhost` host-ingress
pattern in the `networking/` component.

## Implementation Notes

- This is infrastructure-as-code: the artifacts are shell + YAML, not
  unit-testable code. Static verification is `bash -n` (and `shellcheck`)
  on every script. The live acceptance gate is the smoke test, run
  against a real cluster.
- `(RED)`/`(GREEN)` commit markers do not apply here; commit per phase.
- The implementing agent did NOT run the live bootstrap (cluster
  create/delete, helm, Caddy mutation). A human runs and verifies it --
  see the Human Bootstrap Checklist below.

## Resuming After Compact Amnesia

1. `git log --oneline -12` -- see which phase commits landed.
2. Match the last commit to a phase below; continue from the next.
3. `bash -n` any script left mid-edit.
4. The design doc is the spec; this plan is sequence only.

---

## Phases

### P0 -- Purge istio  [DONE]

istio artifacts deleted; `setup.sh` istio calls removed.
Commit: `feat(observability): source networking lib and deploy dashboards in setup`
(the istio code was uncommitted, so its removal produced no diff).

### P1 -- Registry: pin ingress-nginx images  [DONE]

Controller + `kube-webhook-certgen` images digest-pinned in `images.txt`.
Commit: `feat(registry): pin ingress-nginx controller images`

### P2 -- kind config: open the ingress door  [DONE]

`kind-config.yaml.tpl`: dropped the `3000` mapping, added
`80 <-> 127.0.0.1:32100`, added the `ingress-ready=true` node label.
Commit: `feat(lmde): open the ingress-nginx host port in kind config`

### P3 -- networking component: ingress-nginx + Caddy helper  [DONE]

Vendored kind ingress-nginx manifest (images retagged to the local
registry); `ingress-nginx/setup.sh`; `lib.sh` `register_cluster_vhost`;
`networking/README.md`.
Commits: `feat(networking): add ingress-nginx install component`,
`feat(networking): add register_cluster_vhost Caddy helper`

### P4 -- observability: route Grafana  [DONE]

`specs/grafana/ingress.yaml` routes `grafana.lmde.localhost`; `setup.sh`
installs the controller after the cluster and registers the route after
Grafana is up.
Commits: `feat(observability): add Grafana ingress route`,
`feat(observability): wire ingress-nginx into the bootstrap`

### P5 -- verify  [DONE]

`test/smoketest_lmde_observability/02_verify_grafana_vhost.sh`.
Commit: `test(lmde): smoke-test the Grafana vhost`

---

## Definition of Done

- [x] All scripts pass `bash -n` and `shellcheck -S warning`.
- [x] Every phase committed on `claude/feat/lmde-ingress-nginx`.
- [x] No istio references remain in shipped code or config (the design
      doc Rejections and this plan record the removal).
- [ ] HUMAN GATE: `setup.sh` runs clean; `grafana.lmde.localhost` serves
      the Grafana login page; the smoke test passes.

## Notes / Discoveries

- `specs/grafana/values.yaml` already used the local registry
  (`image.registry: localhost:5001`) and a `ClusterIP` service, so the
  ingress work needed no change there. Its dashboard-sidecar edits are
  committed alongside the dashboards feature.
- The istio bootstrap was entirely uncommitted, so purging it produced
  no deletion diff; only the previous agent's non-istio `setup.sh`
  additions (networking-lib sourcing, `deploy_dashboards`) survived into
  a commit.
- `register_cluster_vhost` assumes the Caddy server is named `srv0`
  (Caddy's default). If the host Caddy uses a different server name,
  the route lands on a new conflicting `srv0` -- verify during bootstrap.

## Human Bootstrap Checklist (morning)

1. Confirm host port `32100` is free: `lsof -nP -iTCP:32100 -sTCP:LISTEN`.
2. Confirm the Caddy admin API is up: `curl -s localhost:2019/config/ | head -c 80`.
3. (Optional) delete the stray default `kind` cluster: `kind delete cluster --name kind`.
4. Run `lmde/components/observability/setup.sh`.
5. Watch for the `ingress-nginx` controller pod Ready and Grafana Running.
6. Browse `https://grafana.lmde.localhost`.
7. Run `test/smoketest_lmde_observability/02_verify_grafana_vhost.sh`.
