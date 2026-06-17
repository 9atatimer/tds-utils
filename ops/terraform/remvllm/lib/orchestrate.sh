#!/usr/bin/env bash
# orchestrate.sh — lifecycle glue for remvllm (provision, connect, teardown).
#
# Sequences the other libs: sizing -> secrets -> terraform -> tunnel -> state.
# This is the integration layer; it shells out to terraform, ssh, and op.
# Prerequisites: terraform, ssh, op, jq, curl.
# Side effects: provisions/destroys cloud infrastructure.

# --- Action functions --------------------------------------------------------

# Echo the terraform working dir for the active provider module.
orchestrate_tf_dir() {
    printf '%s/modules/%s\n' "${REMVLLM_OPS_DIR}" "${REMVLLM_PROVIDER}"
}

# Probe whether the node behind the current state is still alive (spot nodes get
# reclaimed). Returns 0 if reachable over SSH.
orchestrate_node_alive() {
    local host="$1" ssh_port="$2" key_file="$3"
    [[ -n "${host}" ]] || return 1
    ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 -o BatchMode=yes \
        -i "${key_file}" -p "${ssh_port}" "root@${host}" true 2>/dev/null
}

# --- Flow functions ----------------------------------------------------------

# Provision (or reconnect to) a node serving `recipe`, then open the tunnel.
# This is the body of `remvllm run`; it expects config to be loaded and the
# resolved sizing in REMVLLM_PLAN ("gpu count tp cost").
orchestrate_run() {
    local recipe="$1"
    local base="${REMVLLM_STATE_DIR:-${REMVLLM_OPS_DIR}/state}"

    read -r gpu count tp cost <<< "${REMVLLM_PLAN}"

    secrets_preflight

    if state_has_instance "${base}"; then
        local host ssh_port
        host="$(state_read "${base}" host)"
        ssh_port="$(state_read "${base}" ssh_port)"
        if orchestrate_node_alive "${host}" "${ssh_port}" "${REMVLLM_KEY_FILE}"; then
            echo "reconnecting to live ${gpu} x${count} node (${host})"
            orchestrate_extend_ttl "${base}"
            orchestrate_connect "${base}"
            return 0
        fi
        echo "previous node is gone (spot reclaim?) — provisioning fresh"
        state_clear "${base}"
    fi

    echo "provisioning ${count}x ${gpu} spot node for ${recipe} (~\$${cost}/hr) ..."
    orchestrate_provision "${recipe}" "${gpu}" "${count}" "${tp}" "${cost}" "${base}"
    orchestrate_connect "${base}"
}

# terraform apply with sized + secret inputs, then record state.
orchestrate_provision() {
    local recipe="$1" gpu="$2" count="$3" tp="$4" cost="$5" base="$6"
    local tf_dir
    tf_dir="$(orchestrate_tf_dir)"

    terraform -chdir="${tf_dir}" init -input=false >/dev/null
    terraform -chdir="${tf_dir}" apply -input=false -auto-approve \
        -var "gpu_type=${gpu}" \
        -var "gpu_count=${count}" \
        -var "spot=${REMVLLM_SPOT}" \
        -var "provider_token=$(secrets_provider_token)" \
        -var "ssh_public_key=$(secrets_provider_ssh_pubkey)" \
        -var "container_image=${REMVLLM_IMAGE:-ghcr.io/9atatimer/remvllm-appliance:latest}" \
        -var "instance_name=remvllm-${recipe}"

    local host ssh_port instance_id ttl
    host="$(terraform -chdir="${tf_dir}" output -raw host)"
    ssh_port="$(terraform -chdir="${tf_dir}" output -raw ssh_port)"
    instance_id="$(terraform -chdir="${tf_dir}" output -raw instance_id)"
    ttl="$(watchdog_ttl_from_now "${REMVLLM_TTL_MINUTES}")"

    state_write "${base}" \
        instance_id="${instance_id}" provider="${REMVLLM_PROVIDER}" \
        host="${host}" ssh_port="${ssh_port}" \
        gpu_type="${gpu}" gpu_count="${count}" tensor_parallel="${tp}" \
        quant="${REMVLLM_QUANT}" recipe="${recipe}" spot="${REMVLLM_SPOT}" \
        est_cost_hr="${cost}" ttl_expires_at="${ttl}" status="running"
}

# Open the tunnel and wait for the OpenAI-compatible endpoint to answer.
orchestrate_connect() {
    local base="$1"
    local host ssh_port pid
    host="$(state_read "${base}" host)"
    ssh_port="$(state_read "${base}" ssh_port)"

    pid="$(tunnel_open "${host}" "${ssh_port}" \
        "${REMVLLM_LOCAL_PORT}" "${REMVLLM_REMOTE_PORT}" "${REMVLLM_KEY_FILE}")"
    state_write_field "${base}" tunnel_pid "${pid:-null}"

    echo "waiting for vLLM endpoint ..."
    local i
    for i in $(seq 1 120); do
        if tunnel_endpoint_ready "${REMVLLM_LOCAL_PORT}"; then
            echo "ready — OpenAI-compatible API at http://localhost:${REMVLLM_LOCAL_PORT}/v1"
            return 0
        fi
        sleep 5
    done
    echo "error: endpoint did not become ready; check 'remvllm status' / node logs" >&2
    return 1
}

# Merge a single field into existing state (read-modify-write).
state_write_field() {
    local base="$1" field="$2" value="$3"
    local file
    file="$(state_file "${base}")"
    [[ -f "${file}" ]] || { echo "{}" > "${file}"; }
    local tmp
    tmp="$(mktemp)"
    if [[ "${value}" =~ ^-?[0-9]+(\.[0-9]+)?$ || "${value}" == "true" || "${value}" == "false" || "${value}" == "null" ]]; then
        jq ".${field} = ${value}" "${file}" > "${tmp}"
    else
        jq --arg v "${value}" ".${field} = \$v" "${file}" > "${tmp}"
    fi
    mv "${tmp}" "${file}"
}

orchestrate_extend_ttl() {
    local base="$1"
    state_write_field "${base}" ttl_expires_at "$(watchdog_ttl_from_now "${REMVLLM_TTL_MINUTES}")"
}

# Close the tunnel; leave the node to TTL/preemption.
orchestrate_stop() {
    local base="${REMVLLM_STATE_DIR:-${REMVLLM_OPS_DIR}/state}"
    tunnel_kill "$(state_read "${base}" tunnel_pid)"
    state_write_field "${base}" tunnel_pid null
    echo "tunnel closed; node alive until TTL or spot reclaim. 'remvllm destroy' to kill now."
}

# Tear the node down immediately.
orchestrate_destroy() {
    local base="${REMVLLM_STATE_DIR:-${REMVLLM_OPS_DIR}/state}"
    local tf_dir
    tf_dir="$(orchestrate_tf_dir)"
    tunnel_kill "$(state_read "${base}" tunnel_pid)"
    if state_has_instance "${base}"; then
        secrets_preflight
        terraform -chdir="${tf_dir}" destroy -input=false -auto-approve \
            -var "provider_token=$(secrets_provider_token)" >/dev/null
    fi
    state_clear "${base}"
    echo "destroyed."
}
