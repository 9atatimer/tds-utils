---
id: task-088
kind: task
title: "LMDE: NATS in the kind cluster (design record, then component)"
created: 2026-11-14
implements: docs/design/LMDE.DESIGN.md
---

Move the backplane into kind behind ingress-nginx and `*.lmde.localhost` (LMDE.DESIGN section 5).
Decide: in-cluster server versus host NATS through ingress; the auth model; how `gadmin` resolves the bus address inside and outside the cluster; which components move.
Then `lmde/components/nats/`, an image digest in `registry/images.txt`, an ingress registration, and `test/smoketest_lmde_nats/` publishing and subscribing from host and pod.
