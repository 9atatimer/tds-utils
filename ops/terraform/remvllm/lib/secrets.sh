#!/usr/bin/env bash
# secrets.sh — 1Password (op) secret resolution for remvllm.
#
# Secrets are read at runtime and piped into terraform/ssh/the appliance. They
# are never written to disk.
# Prerequisites: 1Password CLI (`op`) authenticated.
# Side effects: shells out to `op read`.

# --- Action functions --------------------------------------------------------

# Resolve a single op:// reference, no trailing newline.
secrets_read() {
    local ref="$1"
    [[ -n "${ref}" ]] || { echo "error: empty op:// reference" >&2; return 1; }
    op read "${ref}" --no-newline
}

# Resolve the active provider's API token (e.g. REMVLLM_SPHERON_OP_TOKEN).
secrets_provider_token() {
    local var="REMVLLM_${REMVLLM_PROVIDER^^}_OP_TOKEN"
    secrets_read "${!var:-}"
}

secrets_provider_ssh_key() {
    local var="REMVLLM_${REMVLLM_PROVIDER^^}_OP_SSH_KEY"
    secrets_read "${!var:-}"
}

secrets_provider_ssh_pubkey() {
    local var="REMVLLM_${REMVLLM_PROVIDER^^}_OP_SSH_PUBKEY"
    secrets_read "${!var:-}"
}

secrets_hf_token()        { secrets_read "${REMVLLM_OP_HF_TOKEN:-}"; }
secrets_bucket_access()   { secrets_read "${REMVLLM_OP_BUCKET_ACCESS_KEY:-}"; }
secrets_bucket_secret()   { secrets_read "${REMVLLM_OP_BUCKET_SECRET_KEY:-}"; }
secrets_bucket_endpoint() { secrets_read "${REMVLLM_OP_BUCKET_ENDPOINT:-}"; }

# --- Flow functions ----------------------------------------------------------

# Verify `op` is available and authenticated; actionable error if not.
secrets_preflight() {
    if ! command -v op >/dev/null 2>&1; then
        echo "error: 1Password CLI (op) not found. Install: brew install 1password-cli" >&2
        return 1
    fi
    if ! op account list >/dev/null 2>&1; then
        echo "error: op is not signed in. Run: eval \"\$(op signin)\"" >&2
        return 1
    fi
}
