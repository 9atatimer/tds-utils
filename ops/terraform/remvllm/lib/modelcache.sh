#!/usr/bin/env bash
# modelcache.sh — bucket-backed weight cache addressing for remvllm.
#
# The guarantee: download the weights from Hugging Face exactly once. These
# helpers compute WHERE the weights live in the bucket; the actual transfer
# (rclone/aws) runs on the node via container/fetch-model.sh, using the same
# key scheme.
# Prerequisites: none (pure string logic).
# Side effects: none.

# --- Action functions --------------------------------------------------------

# Sanitize a model id into a filesystem/bucket-safe key.
#   zai-org/GLM-5.2 -> zai-org__GLM-5.2
modelcache_key() {
    local model_id="$1"
    printf '%s\n' "${model_id//\//__}"
}

# Echo the bucket URI (rclone-style remote:path) for a model id, optionally
# namespaced by quant so a quantized artifact gets its own slot.
#   modelcache_uri r2:weights zai-org/GLM-5.2        -> r2:weights/models/zai-org__GLM-5.2
#   modelcache_uri r2:weights zai-org/GLM-5.2 int4   -> r2:weights/models/zai-org__GLM-5.2/int4
modelcache_uri() {
    local bucket_url="$1" model_id="$2" quant="${3:-}"
    local key
    key="$(modelcache_key "${model_id}")"
    local uri="${bucket_url%/}/models/${key}"
    [[ -n "${quant}" ]] && uri="${uri}/${quant}"
    printf '%s\n' "${uri}"
}
