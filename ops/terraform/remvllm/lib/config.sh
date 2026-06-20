#!/usr/bin/env bash
# config.sh — layered configuration loader for remvllm.
#
# Precedence (lowest to highest): remvllm.conf < remvllm.local.conf < environment.
# Prerequisites: bash 5.2+.
# Side effects: exports REMVLLM_* variables into the environment.

# --- Action functions --------------------------------------------------------

# Snapshot every REMVLLM_* variable EXPORTED in the environment, so it can be
# re-applied after the conf files load (environment wins). Only exported scalars
# count as environment overrides — internal array tables (compgen -v) are skipped
# by using compgen -e. Echoes "NAME=VALUE" lines, one per variable.
config_env_snapshot() {
    local name
    while IFS= read -r name; do
        printf '%s=%s\n' "${name}" "${!name-}"
    done < <(compgen -e 2>/dev/null | grep -E '^REMVLLM_' || true)
}

# --- Flow functions ----------------------------------------------------------

# Load config from <ops_dir>, honoring precedence. The environment snapshot is
# captured BEFORE sourcing the conf files and re-applied AFTER, so any REMVLLM_*
# set in the environment overrides both files.
config_load() {
    local ops_dir="$1"
    local main_conf="${ops_dir}/remvllm.conf"
    local local_conf="${ops_dir}/remvllm.local.conf"

    local snapshot
    snapshot="$(config_env_snapshot)"

    if [[ -f "${main_conf}" ]]; then
        # shellcheck disable=SC1090
        source "${main_conf}"
    else
        echo "error: missing ${main_conf}" >&2
        return 1
    fi
    if [[ -f "${local_conf}" ]]; then
        # shellcheck disable=SC1090
        source "${local_conf}"
    fi

    # Re-apply environment overrides (highest precedence).
    local line name value
    while IFS= read -r line; do
        [[ -n "${line}" ]] || continue
        name="${line%%=*}"
        value="${line#*=}"
        printf -v "${name}" '%s' "${value}"
    done <<< "${snapshot}"

    # Export scalars for child processes (terraform, ssh, etc.). Internal array
    # tables (e.g. the sizing tables) cannot be exported and are skipped.
    local v
    while IFS= read -r v; do
        case "$(declare -p "${v}" 2>/dev/null)" in
            "declare -A"*|"declare -a"*) continue ;;
        esac
        export "${v?}"
    done < <(compgen -v | grep -E '^REMVLLM_' || true)
}
