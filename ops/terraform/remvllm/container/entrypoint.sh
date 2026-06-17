#!/usr/bin/env bash
# entrypoint.sh — PID 1 supervisor for the remvllm appliance.
#
# Order: install SSH key -> start sshd -> fetch model -> start watchdog ->
# exec vLLM (so vLLM is PID 1's foreground child and signals propagate).
#
# Environment (injected at run time):
#   SSH_PUBLIC_KEY, MODEL_ID, QUANT, MODEL_BUCKET_URI, HF_TOKEN,
#   TENSOR_PARALLEL_SIZE, SERVED_NAME, MAX_MODEL_LEN, EXTRA_ARGS,
#   WATCHDOG_TIMEOUT, REMOTE_PORT
set -euo pipefail

start_sshd() {
    mkdir -p /root/.ssh
    printf '%s\n' "${SSH_PUBLIC_KEY}" > /root/.ssh/authorized_keys
    chmod 700 /root/.ssh
    chmod 600 /root/.ssh/authorized_keys
    /usr/sbin/sshd
}

start_watchdog() {
    WATCHDOG_TIMEOUT="${WATCHDOG_TIMEOUT:-600}" /usr/local/bin/watchdog.sh &
}

quant_args() {
    case "${QUANT:-int4}" in
        int4) printf -- '--quantization awq' ;;
        fp8)  printf -- '--quantization fp8' ;;
        *)    printf '' ;;
    esac
}

serve_vllm() {
    local model_dir
    model_dir="$(/usr/local/bin/fetch-model.sh | tail -n1)"
    # vLLM binds to localhost; the SSH tunnel is the only access path.
    # shellcheck disable=SC2086
    exec python3 -m vllm.entrypoints.openai.api_server \
        --model "${model_dir}" \
        --served-model-name "${SERVED_NAME:-glm-5.2}" \
        --tensor-parallel-size "${TENSOR_PARALLEL_SIZE:-1}" \
        --max-model-len "${MAX_MODEL_LEN:-131072}" \
        --host 127.0.0.1 --port "${REMOTE_PORT:-8000}" \
        $(quant_args) ${EXTRA_ARGS:-}
}

main() {
    start_sshd
    start_watchdog
    serve_vllm
}

main "$@"
