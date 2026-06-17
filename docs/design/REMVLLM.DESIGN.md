# remvllm — Remote vLLM Orchestrator (GLM-5.2 endpoint)

> **Status:** Design / Pre-Implementation
> **Created:** 2026-06-17
> **Location:** `ops/terraform/remvllm/`
> **Entry Point:** `bin/remvllm`
> **Sister to:** [REMOLLAMA.DESIGN.md](./REMOLLAMA.DESIGN.md)

---

## Overview

`remvllm` is the sister tool to `remollama`. Where `remollama` runs Ollama on a
single GPU, `remvllm` provisions a **multi-GPU spot node**, serves a large
open-weight model with **vLLM**, and exposes an **OpenAI-compatible API** on
`localhost` via SSH tunnel. The first-class target is **GLM-5.2** — a 744B-param
MoE (~40B active, 1M context, MIT license, weights at `zai-org/GLM-5.2`) that is
far too large for Ollama-on-one-GPU.

Two hard constraints drive the design:

1. **Cheapest possible per hour.** Spot/preemptible instances by default, lowest
   viable quant by default, cheapest GPU that fits. Preemption is acceptable.
2. **Download the weights from Hugging Face exactly once.** Weights are cached in
   an object bucket (Cloudflare **R2** by default — zero egress). Every node pulls
   from the bucket; HF is only ever hit to *populate* the cache.

---

## Goals

1. **One-command endpoint** — `remvllm run glm-5.2` yields an OpenAI-compatible
   API at `localhost:<port>` speaking `/v1/chat/completions`.
2. **Cheapest by default** — the sizer picks the lowest-cost spot config that fits
   the chosen quant; `remvllm sizes` shows the cost matrix.
3. **HF downloaded once** — after the first cold start, all weights come from the
   bucket. Verifiable: a second cold start makes zero HF requests.
4. **Selectable GPU and quant** — `--gpu` and `--quant` override the auto pick;
   invalid combos (won't fit in VRAM) are refused with an actionable message.
5. **Preemption-tolerant** — a reclaimed spot node is detected on the next `run`
   and re-provisioned cheaply (weights already in the bucket).
6. **Belt-and-suspenders spend control** — client TTL watchdog + server idle
   watchdog, inherited from the remollama model.

---

## Non-Goals

- **Replacing remollama** — remollama stays the right tool for small models on one
  GPU. remvllm is for big MoE models that need tensor + expert parallelism.
- **Training / fine-tuning** — inference serving only.
- **Multi-user / shared serving** — single operator, SSH-tunnel access only.
- **Guaranteeing availability** — spot nodes get reclaimed; that is the accepted
  trade for price. We optimize fast recovery, not zero downtime.

---

## Architecture Overview

```
+------------------------------------------------------------------+
|  CLI Layer                                     bin/remvllm        |
|  Parse args, load config, dispatch to orchestration               |
+------------------------------------------------------------------+
|  Orchestration Layer                           lib/               |
|  Lifecycle, state, TTL, sizing, model-cache sync, SSH tunnels      |
+------------------------------------------------------------------+
|  Provisioning Layer                            modules/<provider> |
|  Terraform — one module per cloud provider                        |
|  Contract: "get me N GPUs of type T on a SPOT node, with podman"  |
+------------------------------------------------------------------+
|  Runtime Layer                                 container/         |
|  The remvllm appliance container                                  |
|  fetch-model + vLLM + sshd + watchdog — identical everywhere      |
+------------------------------------------------------------------+
                              |
                              v
+------------------------------------------------------------------+
|  Object bucket (R2 default / S3)   models/<sanitized-id>/         |
|  Write-once weight cache. HF is hit only to populate it.          |
+------------------------------------------------------------------+
```

`remvllm` deliberately reuses remollama's module/lib/container/state shape. The
differences are concentrated in three places: the **engine** (vLLM, not Ollama),
the **sizer** (multi-GPU, cost-driven), and the **model cache** (bucket-backed).

---

## Design

### Sizing Layer (`lib/sizing.sh`) — the penny-pincher

The sizer answers: *given a quant and (optionally) a GPU type, what is the
cheapest spot configuration that fits, and will it fit at all?*

It is data-driven from tunable tables (prices are spot $/hr estimates, Spheron,
2026-06 — easy to edit as the market moves):

| GPU | VRAM/GPU | Spot $/hr | On-demand $/hr |
|-----|----------|-----------|----------------|
| a100 | 80 GB | 0.66 | 1.10 |
| h100 | 80 GB | 1.43 | 2.53 |
| h200 | 141 GB | 1.77 | 4.84 |
| b200 | 180 GB | 2.99 | 5.50 |

| Quant | Required VRAM (weights + KV/activation overhead, estimate) |
|-------|------------------------------------------------------------|
| int4 (AWQ) | ~430 GB |
| fp8 | ~860 GB |

Algorithm:

1. `count = smallest valid tensor-parallel size in {1,2,4,8} such that
   count * vram_per_gpu >= required_vram`. (TP is constrained to powers of two so
   it divides GLM-5's attention-head count.)
2. If no valid TP fits, that (quant, gpu) combo is **rejected**.
3. `cost = count * spot_price`.
4. `auto` mode evaluates every GPU type and returns the minimum-cost fit.

Worked results from the tables above:

| Quant | Cheapest pick | Count | TP | Est. spot $/hr |
|-------|---------------|-------|----|----------------|
| **int4** (default) | **a100** | 8 | 8 | **~5.28** |
| fp8 | h200 | 8 | 8 | ~14.16 |

`--gpu a100 --quant fp8` is correctly refused (8×80 GB = 640 GB < 860 GB).

### Model Cache (`lib/modelcache.sh` + `container/fetch-model.sh`)

The cache key sanitizes the model id: `zai-org/GLM-5.2` → `zai-org__GLM-5.2`.
The bucket URI is `${REMVLLM_BUCKET_URL%/}/models/<key>/`.

On node bootstrap, `fetch-model.sh`:

1. Probe the bucket for `models/<key>/`.
2. **Hit:** `rclone copy` (R2/S3 via `rclone` or `aws --endpoint-url`) bucket →
   local model dir. No HF traffic.
3. **Miss:** `hf download <model-id>` → local, then **upload** to the bucket to
   populate it for every future node. HF is touched this once.

Because re-provisioning after a spot preemption is a cache *hit*, recovery is a
fast bucket pull, not a multi-hundred-GB HF re-download. This is what makes
"cheapest, even if we get booted" practical.

### Provisioning Layer (`modules/spheron/`)

Terraform module honoring the provider-agnostic contract (same as remollama, plus
multi-GPU + spot):

| Direction | Field | Notes |
|-----------|-------|-------|
| In | `gpu_type`, `gpu_count` | from the sizer |
| In | `spot` (default `true`), `max_price` | cheapest-first |
| In | `container_image`, `ssh_public_key`, `provider_token`, `env_vars` | |
| Out | `host`, `ssh_port`, `instance_id` | |

cloud-init installs podman + nvidia-container-toolkit and runs the appliance.

### Runtime Layer (`container/`)

| Service | Purpose |
|---------|---------|
| `fetch-model.sh` | Populate the model dir from bucket (or HF→bucket) before serve |
| `vllm serve` | OpenAI-compatible API on `:8000` (`--tensor-parallel-size`, `--enable-expert-parallel`) |
| `sshd` | Tunnel access |
| `watchdog` | Server-side idle → self-destruct |

### CLI (`bin/remvllm`)

```
remvllm run <recipe>  [--gpu <type>] [--quant fp8|int4] [--ttl <min>] [--no-spot]
remvllm stop          # close tunnel; node lives until TTL / preemption
remvllm destroy       # terraform destroy now
remvllm status        # node state, TTL, recipe, cost estimate
remvllm sizes [--quant q]   # print the cost matrix and the auto pick
remvllm cache <recipe>      # warm the bucket from HF without serving
remvllm list-recipes
```

---

## State Machine

```
+--------+   run (cache miss)   +-------------+   serve ready   +---------+
| ABSENT |--------------------->| PROVISIONING|---------------->| RUNNING |
+--------+                      +-------------+                 +---------+
    ^   ^                                                        |  |   |
    |   |  destroy / TTL expiry / preemption detected            |  |   |
    |   +--------------------------------------------------------+  |   |
    |                          stop (tunnel only)                   |   |
    +---------------------------------------------------------------+   |
    |                    spot preemption (node gone)                    |
    +-------------------------------------------------------------------+
```

| From | To | Trigger | Condition |
|------|----|---------|-----------|
| ABSENT | PROVISIONING | `run` | no live node in state |
| PROVISIONING | RUNNING | vLLM `/health` ok | tunnel established |
| RUNNING | ABSENT | `destroy` / TTL / preemption | idle or user action |
| RUNNING | RUNNING | `run` | warm reconnect, extend TTL |

---

## Data Model — `state/<hostname>/state.json`

```
state.json
+-- instance_id      provider instance id
+-- provider         "spheron"
+-- host / ssh_port  tunnel target
+-- gpu_type/count    sized config
+-- quant            "int4" | "fp8"
+-- recipe           "glm-5.2"
+-- spot             bool
+-- est_cost_hr      number (USD)
+-- created_at / ttl_expires_at
+-- tunnel_pid / status
```

`state/` is `.gitignore`d, partitioned per hostname.

---

## Security Considerations

- **Transport** — SSH tunnel only; vLLM binds to localhost on the remote, exposed
  to the laptop over the tunnel. Only port 22 reachable.
- **Secrets** — provider token, SSH keys, **bucket credentials**, and the HF token
  come from 1Password (`op`) at runtime; never written to disk.
- **Bucket** — private bucket, scoped credentials. Weights are public (MIT) but the
  credential is not.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Engine | vLLM | Documented GLM-5 recipe; native OpenAI API; TP + expert parallel for MoE |
| Default quant | int4 (AWQ) | Cheapest fit; 1–3% coding regression accepted for price |
| Default GPU | auto → cheapest | Penny-pinching is the explicit requirement |
| Spot | on by default | Cheapest per hour; preemption acceptable |
| Weight cache | R2 default | Zero egress beats S3 on repeated multi-hundred-GB pulls |
| HF policy | populate-once | Bucket hit on every node after the first cold start |
| Tool shape | sister to remollama | Reuse module/lib/container/state skeleton; engine/sizer/cache differ |

---

## Open Questions

1. **Exact TP/head divisibility for GLM-5.2** — TP is constrained to {1,2,4,8};
   confirm against the published config before first real run.
2. **Quant artifact source** — pull a prebuilt AWQ/FP8 checkpoint, or quantize once
   and cache the quantized weights in the bucket? Caching quantized is cheaper to
   serve and smaller to pull. Leaning: cache the quantized artifact under a distinct
   key.
3. **vLLM cold-load time** — large MoE load + KV warmup can exceed the SSH-probe
   window; health-poll budget may need raising.

## Rejections

- **Ollama / llama.cpp** — wrong engine for a 744B MoE at long context; no native
  expert parallelism, weaker throughput.
- **Single "big GPU" instance** — no single GPU holds the model even at int4
  (~430 GB > 141 GB H200). Multi-GPU is mandatory.
- **S3 as default cache** — egress fees on repeated cold pulls defeat the
  penny-pinching goal; R2 egress is free.
- **On-demand instances by default** — 2–3× the spot price for a workload that
  explicitly tolerates preemption.

## Future Considerations

- **SGLang** as an alternate engine (`--enable-moe-ep`) behind the same recipe.
- **WireGuard/Tailscale** instead of SSH tunnel if it becomes a bottleneck.
- **Shared lib with remollama** once remollama is actually built.

## Related Documents

- [REMOLLAMA.DESIGN.md](./REMOLLAMA.DESIGN.md) — the single-GPU Ollama sister tool
