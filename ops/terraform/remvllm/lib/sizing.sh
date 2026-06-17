#!/usr/bin/env bash
# sizing.sh — cost-driven multi-GPU sizing for remvllm.
#
# Purpose: given a quant and (optionally) a GPU type, compute the CHEAPEST spot
#   configuration that fits the model in VRAM, or reject combos that cannot fit.
# Prerequisites: bash 5.2+ (associative arrays), awk.
# Side effects: none. Pure functions; source and call.
#
# All tables are tunable estimates (Spheron spot $/hr, 2026-06). Edit freely as
# the market moves — the logic does not change.

# --- Data tables -------------------------------------------------------------

declare -gA REMVLLM_GPU_VRAM=(     [a100]=80  [h100]=80   [h200]=141  [b200]=180 )
declare -gA REMVLLM_GPU_SPOT=(     [a100]=0.66 [h100]=1.43 [h200]=1.77 [b200]=2.99 )
declare -gA REMVLLM_GPU_ONDEMAND=( [a100]=1.10 [h100]=2.53 [h200]=4.84 [b200]=5.50 )

# Required total VRAM (weights + KV/activation overhead) per quant, in GB.
# Estimates for GLM-5.2 (744B MoE). See REMVLLM.DESIGN.md.
declare -gA REMVLLM_QUANT_VRAM=( [int4]=430 [fp8]=860 )

# Tensor-parallel size is constrained to powers of two so it divides GLM-5's
# attention-head count. Ascending — we want the smallest fit.
REMVLLM_VALID_TP=(1 2 4 8)

# Target-platform ceiling. 4-GPU single-node (NVLink, no cross-node fabric) is
# the sweet spot: easy to schedule on spot, serves inference better than 8-GPU.
# Combos that need more than this are refused unless overridden (--max-gpus).
REMVLLM_MAX_GPUS_DEFAULT=4

# Order GPUs cheapest-first only for tie-breaking; cost still decides.
REMVLLM_GPU_TYPES=(a100 h100 h200 b200)

# --- Action functions --------------------------------------------------------

# Echo the smallest valid tensor-parallel GPU count (<= max_gpus) that fits
# `quant` on `gpu_type`. Returns non-zero (and echoes nothing) if no valid size
# fits within the cap. Internal: the cap is an explicit argument.
sizing_count_within() {
    local quant="$1" gpu="$2" max="$3"
    local vram="${REMVLLM_GPU_VRAM[$gpu]:-}"
    local required="${REMVLLM_QUANT_VRAM[$quant]:-}"
    if [[ -z "${vram}" || -z "${required}" ]]; then
        return 1
    fi
    local tp
    for tp in "${REMVLLM_VALID_TP[@]}"; do
        (( tp > max )) && break
        if (( tp * vram >= required )); then
            printf '%s\n' "${tp}"
            return 0
        fi
    done
    return 1
}

# Public: smallest count that fits within the active GPU cap
# (REMVLLM_MAX_GPUS, default REMVLLM_MAX_GPUS_DEFAULT).
sizing_gpu_count() {
    sizing_count_within "$1" "$2" "${REMVLLM_MAX_GPUS:-${REMVLLM_MAX_GPUS_DEFAULT}}"
}

# Echo cost = count * price for a pricing model (spot|ondemand), 2 decimals.
sizing_cost() {
    local count="$1" gpu="$2" pricing="${3:-spot}"
    local price
    if [[ "${pricing}" == "ondemand" ]]; then
        price="${REMVLLM_GPU_ONDEMAND[$gpu]:-}"
    else
        price="${REMVLLM_GPU_SPOT[$gpu]:-}"
    fi
    [[ -n "${price}" ]] || return 1
    awk -v c="${count}" -v p="${price}" 'BEGIN { printf "%.2f", c * p }'
}

# --- Flow functions ----------------------------------------------------------

# Plan a concrete sizing. Echoes "gpu_type count tp cost" on success.
# Usage: sizing_plan <quant> <gpu_type|auto> [pricing]
sizing_plan() {
    local quant="$1" gpu="${2:-auto}" pricing="${3:-spot}"

    local cap="${REMVLLM_MAX_GPUS:-${REMVLLM_MAX_GPUS_DEFAULT}}"

    if [[ "${gpu}" != "auto" ]]; then
        local count uncapped
        if ! count="$(sizing_gpu_count "${quant}" "${gpu}")"; then
            # Distinguish "over the GPU cap" from "won't fit in VRAM at all".
            if uncapped="$(sizing_count_within "${quant}" "${gpu}" "${REMVLLM_VALID_TP[-1]}")"; then
                echo "error: ${quant} on ${gpu} needs ${uncapped} GPUs, over the ${cap}-GPU cap" >&2
                echo "       raise it with --max-gpus ${uncapped} (or pick a larger-VRAM GPU)" >&2
            else
                echo "error: ${quant} will not fit on any valid GPU count of ${gpu}" >&2
                echo "       (need ${REMVLLM_QUANT_VRAM[$quant]:-?} GB; ${gpu} = ${REMVLLM_GPU_VRAM[$gpu]:-?} GB/GPU, max TP ${REMVLLM_VALID_TP[-1]})" >&2
            fi
            return 1
        fi
        local cost
        cost="$(sizing_cost "${count}" "${gpu}" "${pricing}")"
        printf '%s %s %s %s\n' "${gpu}" "${count}" "${count}" "${cost}"
        return 0
    fi

    # auto: evaluate every GPU type, keep the minimum-cost fit.
    local best_gpu="" best_count="" best_cost=""
    local g count cost
    for g in "${REMVLLM_GPU_TYPES[@]}"; do
        count="$(sizing_gpu_count "${quant}" "${g}")" || continue
        cost="$(sizing_cost "${count}" "${g}" "${pricing}")"
        if [[ -z "${best_cost}" ]] || awk -v a="${cost}" -v b="${best_cost}" 'BEGIN { exit !(a < b) }'; then
            best_gpu="${g}"; best_count="${count}"; best_cost="${cost}"
        fi
    done
    if [[ -z "${best_gpu}" ]]; then
        echo "error: ${quant} does not fit any GPU type within the ${cap}-GPU cap" >&2
        echo "       raise it with --max-gpus (e.g. fp8 GLM-5.2 needs 8), or use int4" >&2
        return 1
    fi
    printf '%s %s %s %s\n' "${best_gpu}" "${best_count}" "${best_count}" "${best_cost}"
}

# Render the full cost matrix for a quant (human-readable). Marks the auto pick
# and flags combos that fit only by exceeding the GPU cap.
sizing_matrix() {
    local quant="$1" pricing="${2:-spot}"
    local cap="${REMVLLM_MAX_GPUS:-${REMVLLM_MAX_GPUS_DEFAULT}}"
    local pick g count cost uncapped
    # `|| true`: when nothing fits the cap, sizing_plan fails; the matrix must
    # still render (showing why), so don't let set -e/pipefail abort here.
    pick="$(sizing_plan "${quant}" auto "${pricing}" 2>/dev/null | awk '{print $1}')" || true
    printf 'quant=%s  pricing=%s  cap=%s GPUs\n' "${quant}" "${pricing}" "${cap}"
    printf '  %-6s %-6s %-6s %-10s\n' GPU COUNT TP "$(printf '$%s/hr' "${pricing}")"
    for g in "${REMVLLM_GPU_TYPES[@]}"; do
        if count="$(sizing_gpu_count "${quant}" "${g}")"; then
            cost="$(sizing_cost "${count}" "${g}" "${pricing}")"
            printf '  %-6s %-6s %-6s %-10s%s\n' \
                "${g}" "${count}" "${count}" "${cost}" \
                "$([[ "${g}" == "${pick}" ]] && printf '  <- cheapest' || true)"
        elif uncapped="$(sizing_count_within "${quant}" "${g}" "${REMVLLM_VALID_TP[-1]}")"; then
            printf '  %-6s %-6s %-6s %-10s\n' "${g}" "-" "-" "needs ${uncapped} (>cap)"
        else
            printf '  %-6s %-6s %-6s %-10s\n' "${g}" "-" "-" "will not fit"
        fi
    done
}
