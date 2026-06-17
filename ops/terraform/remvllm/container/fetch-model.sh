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
    # rclone lsf returns the listing; non-empty => cache hit.
    [[ -n "$(rclone lsf "${MODEL_BUCKET_URI}" 2>/dev/null)" ]]
}

pull_from_bucket() {
    echo "cache HIT: pulling weights from ${MODEL_BUCKET_URI}"
    rclone copy --transfers 16 --checkers 32 "${MODEL_BUCKET_URI}" "${MODEL_DIR}"
}

download_from_hf() {
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
