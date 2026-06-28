#!/usr/bin/env bash
# lib.sh -- Shared helpers for the LMDE MCP component (install + Desktop wiring).
#
# Purpose:     Owns installation of pinned MCP server release tarballs into
#              versioned prefixes, the stable $HOME/.local/bin symlink, the
#              initialize-handshake health check, and registration of servers
#              into the Claude DESKTOP config (the one agent clai cannot wire).
# Usage:       Sourced by mcp/setup.sh and mcp/healthcheck.sh; not executable
#              on its own.
# Note:        Strict mode is intentionally NOT set here -- the sourcing
#              script owns `set -euo pipefail`.

# --- Shared state ---

MCP_SHARE_ROOT="${HOME}/.local/share/tds-utils/mcp"
MCP_BIN_DIR="${HOME}/.local/bin"
CLAUDE_DESKTOP_CONFIG="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"

# --- Logging ---

log() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S%z')] [mcp] $*"
}

# --- Install ---

# install_one_server <name> <version> <release_tag> <repo> <bin> -- ensure the
# pinned tarball is installed into a versioned prefix and the stable symlink
# points at it. Idempotent: a present versioned prefix is left untouched and
# only the symlink is refreshed.
install_one_server() {
    local name="$1"
    local version="$2"
    local tag="$3"
    local repo="$4"
    local bin="$5"

    local prefix="${MCP_SHARE_ROOT}/${name}/${version}"
    local installed_bin="${prefix}/bin/${bin}"
    local link="${MCP_BIN_DIR}/${bin}"

    if [[ -x "${installed_bin}" ]]; then
        log "${name} ${version} already installed at ${prefix}; skipping download."
        link_server "${installed_bin}" "${link}"
        return 0
    fi

    if ! command -v gh >/dev/null 2>&1; then
        log "ERROR: gh not found; cannot download ${name} ${version} from ${repo}." >&2
        return 1
    fi
    if ! command -v npm >/dev/null 2>&1; then
        log "ERROR: npm not found; cannot install ${name} ${version}." >&2
        return 1
    fi

    local tmp
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/mcp-${name}.XXXXXX")"
    # shellcheck disable=SC2064
    trap "rm -rf '${tmp}'" RETURN

    log "Downloading ${name} ${version} tarball from ${repo} (${tag})..."
    if ! gh release download "${tag}" --repo "${repo}" \
            --pattern '*.tgz' --dir "${tmp}"; then
        log "ERROR: gh release download failed for ${tag} in ${repo}." >&2
        return 1
    fi

    local tarball
    tarball="$(find "${tmp}" -maxdepth 1 -name '*.tgz' -print | head -n 1)"
    if [[ -z "${tarball}" ]]; then
        log "ERROR: no .tgz artifact found in release ${tag}." >&2
        return 1
    fi

    log "Installing ${name} ${version} into ${prefix}..."
    mkdir -p "${prefix}"
    if ! npm install -g --prefix "${prefix}" "${tarball}"; then
        log "ERROR: npm install failed for ${tarball}." >&2
        return 1
    fi

    if [[ ! -x "${installed_bin}" ]]; then
        log "ERROR: expected binary ${installed_bin} not produced by install." >&2
        return 1
    fi

    link_server "${installed_bin}" "${link}"
    log "Installed ${name} ${version}; ${link} -> ${installed_bin}"
}

# link_server <target> <link> -- create/refresh the stable symlink atomically.
link_server() {
    local target="$1"
    local link="$2"
    mkdir -p "$(dirname "${link}")"
    # -h on the existing link: only skip when it already points at target.
    if [[ -L "${link}" && "$(readlink "${link}")" == "${target}" ]]; then
        return 0
    fi
    ln -sfn "${target}" "${link}"
}

# healthcheck_server <bin> -- run the MCP initialize handshake against the
# stable symlink and return 0 if the response identifies the server.
healthcheck_server() {
    local bin="$1"
    local cmd="${MCP_BIN_DIR}/${bin}"

    if [[ ! -e "${cmd}" ]]; then
        log "healthcheck: ${cmd} is missing." >&2
        return 1
    fi

    local request response timeout_bin
    request='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"lmde","version":"0"}}}'

    # `timeout` is GNU coreutils, NOT part of the macOS/BSD base userland
    # (Homebrew ships it as `gtimeout`). Resolve a binary up front and run the
    # handshake unwrapped when neither exists, rather than mis-reporting a
    # healthy server as dead because the pipeline failed on a missing command.
    timeout_bin="$(command -v timeout 2>/dev/null || command -v gtimeout 2>/dev/null || true)"
    if [[ -z "${timeout_bin}" ]]; then
        log "healthcheck: no timeout/gtimeout found; running handshake unwrapped." >&2
    fi

    response="$(printf '%s\n' "${request}" \
        | ${timeout_bin:+"${timeout_bin}" 10} "${cmd}" 2>/dev/null)" || true

    if [[ "${response}" == *'"name":"'"${bin}"'"'* ]]; then
        return 0
    fi
    return 1
}

# register_claude_desktop <bin> -- add/refresh .mcpServers["<bin>"] in the
# Claude Desktop config with the canonical absolute command and a node-bearing
# env.PATH (Desktop is a GUI app and lacks nvm node on PATH). Idempotent;
# preserves all other keys via temp-file + validate + atomic mv.
register_claude_desktop() {
    local bin="$1"
    local cmd="${MCP_BIN_DIR}/${bin}"
    local config="${CLAUDE_DESKTOP_CONFIG}"

    if ! command -v jq >/dev/null 2>&1; then
        log "register_claude_desktop: jq not found; skipping Desktop registration." >&2
        return 0
    fi
    if [[ ! -f "${config}" ]]; then
        log "register_claude_desktop: ${config} absent; skipping Desktop registration." >&2
        return 0
    fi

    local node_path node_bin_dir
    node_path="$(command -v node 2>/dev/null || true)"
    if [[ -z "${node_path}" ]]; then
        log "register_claude_desktop: node not on PATH; skipping (Desktop needs node env)." >&2
        return 0
    fi
    node_bin_dir="$(dirname "${node_path}")"
    local env_path="${node_bin_dir}:/usr/local/bin:/usr/bin:/bin"

    local tmp
    tmp="$(mktemp "${config}.XXXXXX")"
    # shellcheck disable=SC2064
    trap "rm -f '${tmp}'" RETURN

    jq --arg name "${bin}" --arg cmd "${cmd}" --arg path "${env_path}" '
        .mcpServers = (.mcpServers // {}) |
        .mcpServers[$name] = {
            "command": $cmd,
            "args": [],
            "env": { "PATH": $path }
        }
    ' "${config}" > "${tmp}"

    if ! jq empty "${tmp}" >/dev/null 2>&1; then
        log "ERROR: produced invalid JSON for ${config}; leaving original intact." >&2
        return 1
    fi

    mv -f "${tmp}" "${config}"
    log "Registered ${bin} in Claude Desktop config (env.PATH pinned to ${node_bin_dir})."
}
