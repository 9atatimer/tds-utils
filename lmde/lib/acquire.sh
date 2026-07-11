#!/usr/bin/env bash
# acquire.sh -- library for the `lmde acquire` verb: install the agent-agnostic
# clai + ast-mcp npm packages from GitHub Packages (npm.pkg.github.com), latest
# by default with an optional --pins override, FAIL-OPEN at every step.
#
# Usage:       Sourced by bin/lmde (not executable on its own). Strict mode
#              (`set -euo pipefail`) is owned by the sourcing script, mirroring
#              lmde/components/mcp/lib.sh. Because bin/lmde runs under `set -e`,
#              EVERY fallible call below is guarded (if/|| context) and every
#              flow function returns 0 on all degrade paths -- a bare failing
#              command must never kill bin/lmde before the warn-and-exit-0 logic.
#
# Supply-chain stance: packages are installed from GitHub Packages at the chosen
# version; npm verifies every tarball against the registry-published integrity
# hash and published versions are immutable, so the gate is the version choice
# plus npm's built-in integrity -- never curl|sh, never integrity-disabling
# flags. Auth is GH_AI_TOOLS_PAT, a CLASSIC PAT with read:packages.

# --- Constants ---

ACQUIRE_REGISTRY="https://npm.pkg.github.com"
ACQUIRE_SCOPE="@nine-at-a-time-media"
ACQUIRE_SHARE_ROOT="${HOME}/.local/share/tds-utils/acquire"
ACQUIRE_BIN_DIR="${HOME}/.local/bin"
ACQUIRE_STATE_DIR="${HOME}/.local/state/tds-utils/acquire"
ACQUIRE_PREFIX="${ACQUIRE_SHARE_ROOT}/_npm"

# acquire_pkg_table -- the package manifest, whitespace columns read in a
# while-loop (NOT a declare -A, for macOS bash 3.2). Columns:
#   shortname  npm_name  bin  pin_var
acquire_pkg_table() {
    cat <<'EOF'
clai @nine-at-a-time-media/clai clai CLAI_VERSION
ast-mcp @nine-at-a-time-media/ast-mcp ast-mcp AST_MCP_VERSION
EOF
}

# --- Logging ---

acquire_note() { echo "[lmde acquire] $*" >&2; }

# --- Domain (pure; no I/O, deterministic, always return 0) ---

# pins_lookup <file> <var> -- echo the value of KEY=<var> from a --pins file
# (last assignment wins), stripped of surrounding quotes/whitespace. An absent
# file, absent key, empty value, or the UNSET sentinel all float -> echo "".
pins_lookup() {
    local file="$1" var="$2" line val
    [ -n "${file}" ] || { echo ""; return 0; }
    [ -f "${file}" ] || { echo ""; return 0; }
    line="$(grep -E "^[[:space:]]*${var}=" "${file}" 2>/dev/null | tail -n1)" || line=""
    if [ -z "${line}" ]; then echo ""; return 0; fi
    val="${line#*=}"
    # Trim leading then trailing whitespace.
    val="${val#"${val%%[![:space:]]*}"}"
    val="${val%"${val##*[![:space:]]}"}"
    # Strip a single layer of surrounding double or single quotes.
    case "${val}" in
        \"*\") val="${val#\"}"; val="${val%\"}" ;;
        \'*\') val="${val#\'}"; val="${val%\'}" ;;
    esac
    if [ -z "${val}" ] || [ "${val}" = "UNSET" ]; then echo ""; return 0; fi
    # The literal "latest" (any case) is a FLOAT sentinel, not a concrete pin:
    # collapse it to "" so the caller resolves the real version via the registry
    # and stamps that concrete version -- never the word "latest" (which would
    # otherwise stamp==target forever and freeze the package on one release).
    case "${val}" in
        [Ll][Aa][Tt][Ee][Ss][Tt]) echo ""; return 0 ;;
    esac
    echo "${val}"
    return 0
}

# resolve_version <requested> <latest> -- the pinned <requested> when it carries
# a real value, else <latest>, else "" (nothing resolvable -> unreachable).
resolve_version() {
    local requested="$1" latest="$2"
    if [ -n "${requested}" ] && [ "${requested}" != "UNSET" ]; then
        echo "${requested}"; return 0
    fi
    if [ -n "${latest}" ]; then echo "${latest}"; return 0; fi
    echo ""; return 0
}

# --- Adapters (I/O) ---

# write_acquire_npmrc <dir> -- write an ephemeral authed npmrc scoping
# @nine-at-a-time-media to GitHub Packages. Token from GH_AI_TOOLS_PAT (classic
# read:packages). Mode 600 via umask; symlink-guarded. Copied from
# provision.sh's write_npmrc hardening. The caller removes it after the install.
write_acquire_npmrc() {
    local dir="$1" token="${GH_AI_TOOLS_PAT:-}"
    if [ -z "${token}" ]; then
        acquire_note "GH_AI_TOOLS_PAT unset -- need a classic read:packages PAT to install from GitHub Packages"
        return 1
    fi
    mkdir -p "${dir}" || return 1
    local npmrc="${dir}/.npmrc"
    # Refuse to write the token through a symlink or other non-regular file, and
    # remove any pre-existing regular .npmrc first (`>` truncates in place but
    # does not change an existing file's mode; the umask only governs a newly
    # created file). Start fresh either way.
    if [ -L "${npmrc}" ] || { [ -e "${npmrc}" ] && [ ! -f "${npmrc}" ]; }; then
        acquire_note "refusing to write .npmrc: ${npmrc} exists and is not a regular file"
        return 1
    fi
    rm -f "${npmrc}" || return 1
    (
        umask 077
        {
            printf '%s:registry=%s\n' "${ACQUIRE_SCOPE}" "${ACQUIRE_REGISTRY}"
            printf '//npm.pkg.github.com/:_authToken=%s\n' "${token}"
        } > "${npmrc}"
    ) || return 1
}

# npm_view_latest <npm_name> <npmrc> -- echo the registry-latest version of
# <npm_name>, or "" (and return 1) when the registry is unreachable/unauthorized.
# The explicit --registry is required, else npm queries registry.npmjs.org and
# E404s for the private scoped package.
npm_view_latest() {
    local npm_name="$1" npmrc="$2" out rc=0
    out="$(npm view "${npm_name}" version \
        --registry="${ACQUIRE_REGISTRY}" --userconfig "${npmrc}" 2>/dev/null)" || rc=$?
    if [ "${rc}" -ne 0 ]; then echo ""; return 1; fi
    echo "${out}"
    return 0
}

# npm_install_pkg <npm_name> <version> <npmrc> -- install <npm_name>@<version>
# into ACQUIRE_PREFIX (local, not -g). NO integrity-disabling flags: npm's
# registry integrity check is the supply-chain gate. Returns npm's rc.
npm_install_pkg() {
    local npm_name="$1" version="$2" npmrc="$3" rc=0
    npm install --prefix "${ACQUIRE_PREFIX}" --registry="${ACQUIRE_REGISTRY}" \
        --userconfig "${npmrc}" "${npm_name}@${version}" >/dev/null 2>&1 || rc=$?
    return "${rc}"
}

# installed_version <shortname> -- echo the recorded version from the state
# stamp (the trusted currency identity), or "" when none. Never invokes the
# binary (ast-mcp is not guaranteed to answer --version) and never resolves the
# symlink (no readlink -f on BSD/macOS).
installed_version() {
    local shortname="$1" f="${ACQUIRE_STATE_DIR}/${shortname}.version"
    if [ -f "${f}" ]; then cat "${f}" 2>/dev/null; fi
    return 0
}

# write_stamp <shortname> <version> -- record the installed version.
write_stamp() {
    local shortname="$1" version="$2"
    mkdir -p "${ACQUIRE_STATE_DIR}" || return 1
    printf '%s\n' "${version}" > "${ACQUIRE_STATE_DIR}/${shortname}.version" || return 1
}

# link_bin <target> <link> -- create/refresh the stable symlink atomically;
# skip when it already points at target. Copied from lib.sh link_server
# semantics (no readlink -f).
link_bin() {
    local target="$1" link="$2"
    mkdir -p "$(dirname "${link}")" || return 1
    if [ -L "${link}" ] && [ "$(readlink "${link}")" = "${target}" ]; then
        return 0
    fi
    ln -sfn "${target}" "${link}" || return 1
}

# --- Flow ---

# acquire_one <shortname> <npm_name> <bin> <pin_var> <pins_file> <npmrc> --
# reconcile one package to its target version. Implements the currency state
# machine, guarding every fallible call and always returning 0 (fail-open).
acquire_one() {
    local shortname="$1" npm_name="$2" bin="$3" pin_var="$4" pins_file="$5" npmrc="$6"
    local requested latest target installed prefix_bin link

    requested="$(pins_lookup "${pins_file}" "${pin_var}")" || requested=""

    # Only consult the registry when the version is floating (not pinned).
    latest=""
    if [ -z "${requested}" ]; then
        latest="$(npm_view_latest "${npm_name}" "${npmrc}")" || latest=""
    fi

    target="$(resolve_version "${requested}" "${latest}")" || target=""
    installed="$(installed_version "${shortname}")" || installed=""

    prefix_bin="${ACQUIRE_PREFIX}/node_modules/.bin/${bin}"
    link="${ACQUIRE_BIN_DIR}/${bin}"

    # Registry unreachable (a floating package whose latest could not resolve):
    # keep whatever is installed and name what is stale.
    if [ -z "${target}" ]; then
        if [ -n "${installed}" ]; then
            acquire_note "WARNING: ${shortname}: registry unreachable; keeping already-installed ${shortname} ${installed} (may be STALE)"
        else
            acquire_note "WARNING: ${shortname}: registry unreachable and nothing installed -- ${shortname} unavailable this run"
        fi
        return 0
    fi

    # Already current AND the prefix binary is really present: no install; just
    # ensure the symlink is present. If the stamp matches but the binary is gone
    # (share tree wiped, stamp survived), do NOT trust the stamp -- fall through
    # to reinstall so clai/ast-mcp are actually available again.
    if [ -n "${installed}" ] && [ "${installed}" = "${target}" ] && [ -x "${prefix_bin}" ]; then
        acquire_note "${shortname} ${target} already up-to-date; skipping install"
        link_bin "${prefix_bin}" "${link}" \
            || acquire_note "WARNING: ${shortname}: could not refresh symlink ${link}"
        return 0
    fi
    if [ -n "${installed}" ] && [ "${installed}" = "${target}" ]; then
        acquire_note "${shortname} ${target} stamped but ${prefix_bin} is missing; reinstalling"
    fi

    # Install the target version.
    if ! npm_install_pkg "${npm_name}" "${target}" "${npmrc}"; then
        if [ -n "${installed}" ]; then
            acquire_note "WARNING: ${shortname}: npm install of ${target} failed; keeping already-installed ${shortname} ${installed} (may be STALE)"
        else
            acquire_note "WARNING: ${shortname}: npm install of ${target} failed and nothing installed -- ${shortname} unavailable this run"
        fi
        return 0
    fi

    if [ ! -x "${prefix_bin}" ]; then
        acquire_note "WARNING: ${shortname}: npm install reported success but ${prefix_bin} is missing -- ${shortname} unavailable this run"
        return 0
    fi

    if ! link_bin "${prefix_bin}" "${link}"; then
        acquire_note "WARNING: ${shortname}: installed ${target} but could not create symlink ${link}"
        return 0
    fi

    write_stamp "${shortname}" "${target}" \
        || acquire_note "WARNING: ${shortname}: could not write version stamp"
    acquire_note "installed ${shortname} ${target} from GitHub Packages; ${link} -> ${prefix_bin}"
    return 0
}

# acquire_run <pins_file> -- the top-level flow. Checks the token once, builds
# one authed npmrc under a private mktemp dir, reconciles every package in the
# table, removes the npmrc whatever the outcome, and ALWAYS returns 0.
acquire_run() {
    local pins_file="$1"
    local token="${GH_AI_TOOLS_PAT:-}"

    if [ -z "${token}" ]; then
        acquire_note "GH_AI_TOOLS_PAT is unset -- need a CLASSIC PAT with read:packages to install clai + ast-mcp from GitHub Packages (npm.pkg.github.com)."
        acquire_note "Skipping install; keeping whatever is already installed (fail-open)."
        return 0
    fi

    if ! command -v npm >/dev/null 2>&1; then
        acquire_note "npm not on PATH -- cannot install from GitHub Packages; keeping whatever is already installed (fail-open)."
        return 0
    fi

    local npmrc_dir="" npmrc=""
    npmrc_dir="$(mktemp -d "${TMPDIR:-/tmp}/lmde-acquire.XXXXXX")" || npmrc_dir=""
    if [ -z "${npmrc_dir}" ]; then
        acquire_note "could not create a temp dir for the npmrc -- keeping whatever is already installed (fail-open)."
        return 0
    fi
    if ! write_acquire_npmrc "${npmrc_dir}"; then
        acquire_note "could not write an authed npmrc -- keeping whatever is already installed (fail-open)."
        rm -rf "${npmrc_dir}" 2>/dev/null || true
        return 0
    fi
    npmrc="${npmrc_dir}/.npmrc"

    mkdir -p "${ACQUIRE_BIN_DIR}" "${ACQUIRE_STATE_DIR}" 2>/dev/null || true

    local shortname npm_name bin pin_var
    while read -r shortname npm_name bin pin_var; do
        [ -n "${shortname}" ] || continue
        acquire_one "${shortname}" "${npm_name}" "${bin}" "${pin_var}" "${pins_file}" "${npmrc}"
    done < <(acquire_pkg_table)

    # The PAT must never linger on disk.
    rm -f "${npmrc}" 2>/dev/null || true
    rm -rf "${npmrc_dir}" 2>/dev/null || true

    # Installed-but-unresolved warning: acquire never edits a shell rc.
    case ":${PATH}:" in
        *":${ACQUIRE_BIN_DIR}:"*) ;;
        *) acquire_note "note: ${ACQUIRE_BIN_DIR} is not on PATH -- installed clai/ast-mcp will not resolve until it is added (acquire does not edit your shell rc)." ;;
    esac

    return 0
}
