#!/usr/bin/env bash
# fetch-model.sh — populate /models from the bucket, or HF -> bucket once.
#
# THE GUARANTEE: Hugging Face is hit only to populate the bucket. Every node
# after the first cold start pulls weights from the bucket (a cache hit).
#
# Environment (injected by the orchestrator via the appliance):
#   MODEL_ID          e.g. zai-org/GLM-5.2
#   QUANT             int4 | fp8
#   MODEL_BUCKET_URI  rclone remote:path, e.g. r2:remvllm-weights/models/zai-org__GLM-5.2/int4
#   RCLONE_CONFIG_*   rclone remote config (R2/S3 endpoint + creds)
#   HF_TOKEN          Hugging Face token (only used on a cache miss)
set -euo pipefail

MODEL_DIR="/models/current"

# --- Action functions --------------------------------------------------------

bucket_has_weights() {
    # Probe the bucket and distinguish three cases:
    #   reachable + non-empty -> cache HIT  (return 0)
    #   reachable + empty     -> cache MISS (return 1 -> HF fallback)
    #   unreachable / misconfigured -> FATAL (exit 1)
    # The fatal case is the point: if we silently treated an unreachable bucket
    # as a miss, we'd re-download from HF and break the "HF only once" guarantee.
    local listing errfile
    errfile="$(mktemp)"
    if listing="$(rclone lsf "${MODEL_BUCKET_URI}" 2>"${errfile}")"; then
        rm -f "${errfile}"
        [[ -n "${listing}" ]]
    else
        echo "fatal: weight bucket ${MODEL_BUCKET_URI} is unreachable/misconfigured" >&2
        echo "       (refusing to fall back to Hugging Face; fix bucket access and retry)" >&2
        cat "${errfile}" >&2 || true
        rm -f "${errfile}"
        exit 1
    fi
}

pull_from_bucket() {
    echo "cache HIT: pulling weights from ${MODEL_BUCKET_URI}"
    rclone copy --transfers 16 --checkers 32 "${MODEL_BUCKET_URI}" "${MODEL_DIR}"
}

download_from_hf() {
    if [[ -z "${HF_TOKEN:-}" ]]; then
        echo "fatal: HF_TOKEN is not set; cannot download ${MODEL_ID} from Hugging Face" >&2
        echo "       (set HF_TOKEN, or pre-populate the weight bucket so this is a cache hit)" >&2
        exit 1
    fi
    echo "cache MISS: downloading ${MODEL_ID} from Hugging Face (one time only)"
    HF_HUB_ENABLE_HF_TRANSFER=1 \
        huggingface-cli download "${MODEL_ID}" --local-dir "${MODEL_DIR}" --token "${HF_TOKEN}"
}

populate_bucket() {
    echo "populating bucket so HF is never hit again: ${MODEL_BUCKET_URI}"
    rclone copy --transfers 16 --checkers 32 "${MODEL_DIR}" "${MODEL_BUCKET_URI}"
}

# --- Flow / Main -------------------------------------------------------------

main() {
    mkdir -p "${MODEL_DIR}"
    if bucket_has_weights; then
        pull_from_bucket
    else
        download_from_hf
        populate_bucket
    fi
    echo "${MODEL_DIR}"
}

main "$@"
