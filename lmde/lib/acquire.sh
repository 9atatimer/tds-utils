#!/usr/bin/env bash
# acquire.sh -- library for the `lmde acquire` verb: install the agent-agnostic
# clai + ast-mcp + git-mirror + skills + gadmin npm packages from GitHub Packages
# (npm.pkg.github.com), latest by default with an optional --pins override,
# FAIL-OPEN at every step.
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
# Where UNSCOPED dependencies of the fleet packages come from. GitHub Packages
# serves only scoped packages for the configured owner, so it can never be the
# default registry for an install that has to resolve a dependency tree.
ACQUIRE_PUBLIC_REGISTRY="https://registry.npmjs.org/"
ACQUIRE_SCOPE="@nine-at-a-time-media"
ACQUIRE_SHARE_ROOT="${HOME}/.local/share/tds-utils/acquire"
ACQUIRE_BIN_DIR="${HOME}/.local/bin"
ACQUIRE_STATE_DIR="${HOME}/.local/state/tds-utils/acquire"
ACQUIRE_PREFIX="${ACQUIRE_SHARE_ROOT}/_npm"
# Where DATA packages (bin column "-") get their convention symlink: the
# lmde->clai boundary contract path (tds-utils docs/design/LMDE.DESIGN.md,
# section 2.3).
ACQUIRE_DATA_LINK_ROOT="${HOME}/.local/lib/node_modules"
# The FLEET pins shipped inside the skills payload (SANDBOX-LIFECYCLE.DESIGN.md
# D1): with no explicit --pins, the executable packages take their pins from
# here -- a reviewed template-tools file that reaches every surface via the
# same floating acquire that delivers the skills. Resolution order per
# package: explicit --pins argument > this file > float to registry latest.
ACQUIRE_FLEET_PINS="${ACQUIRE_DATA_LINK_ROOT}/${ACQUIRE_SCOPE}/skills/pins.env"

# acquire_pkg_table -- the package manifest, whitespace columns read in a
# while-loop (NOT a declare -A, for macOS bash 3.2). Columns:
#   shortname  npm_name  bin  pin_var
# A bin of "-" marks a DATA package: it ships no binary; presence is the
# package directory itself, and the symlink lands under
# ACQUIRE_DATA_LINK_ROOT/<npm_name> instead of ACQUIRE_BIN_DIR.
#
# gadmin is the one row whose bin name is not its npm name: the package is
# @nine-at-a-time-media/admin and it ships `gadmin`. Shortname follows the bin
# (so the stamp is gadmin.version and the warnings read "gadmin"), because
# gadmin is what an agent looks for on PATH.
acquire_pkg_table() {
    cat <<'EOF'
clai @nine-at-a-time-media/clai clai CLAI_VERSION
ast-mcp @nine-at-a-time-media/ast-mcp ast-mcp AST_MCP_VERSION
git-mirror @nine-at-a-time-media/git-mirror git-mirror GIT_MIRROR_VERSION
skills @nine-at-a-time-media/skills - SKILLS_VERSION
gadmin @nine-at-a-time-media/admin gadmin ADMIN_VERSION
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

# is_data_pkg <bin> -- whether the table's bin column carries the "-" sentinel
# marking a data-only package (no binary ships; the artifact is the package
# directory itself).
is_data_pkg() { [ "$1" = "-" ]; }

# effective_pins <explicit_pins_file> -- resolve the pins file the EXECUTABLE
# rows use (D1): the explicit --pins argument when one was given, else the
# fleet pins inside the acquired skills payload when present, else "" (float).
# The skills row itself never uses the fleet pins (self-reference: it would be
# pinning itself from the payload it is installing); callers pass it the
# explicit file only.
effective_pins() {
    local explicit="${1:-}"
    if [ -n "${explicit}" ]; then echo "${explicit}"; return 0; fi
    if [ -f "${ACQUIRE_FLEET_PINS}" ]; then echo "${ACQUIRE_FLEET_PINS}"; return 0; fi
    echo ""
    return 0
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
            # Default registry FIRST, scope mapping second: the scoped fleet
            # packages come from GitHub Packages, everything they depend on
            # (unscoped, e.g. admin's `octokit`) comes from npmjs.
            #
            # This line does NOT outrank an ambient NPM_CONFIG_REGISTRY -- an
            # npmrc sits below the environment in npm's precedence, which is
            # why npm_install_pkg asserts the same default on the command
            # line. Keep it anyway: it makes this npmrc self-describing and
            # gives any future caller that omits the flag a sane default
            # rather than npm's ambient one.
            printf 'registry=%s\n' "${ACQUIRE_PUBLIC_REGISTRY}"
            printf '%s:registry=%s\n' "${ACQUIRE_SCOPE}" "${ACQUIRE_REGISTRY}"
            printf '//npm.pkg.github.com/:_authToken=%s\n' "${token}"
        } > "${npmrc}"
    ) || return 1
}

# purge_npmrc <npmrc> <npmrc_dir> -- remove the ephemeral authed npmrc and its
# temp dir; if the token file survives a failed rm, blank its contents and warn
# so the PAT can never linger on disk. EVERY acquire_run exit path routes its
# cleanup through here, so the "PAT never lingers" guarantee holds uniformly
# (not just on the happy path).
purge_npmrc() {
    local npmrc="$1" npmrc_dir="$2"
    rm -f "${npmrc}" 2>/dev/null || true
    rm -rf "${npmrc_dir}" 2>/dev/null || true
    if [ -n "${npmrc}" ] && [ -e "${npmrc}" ]; then
        : > "${npmrc}" 2>/dev/null || true
        acquire_note "warning: could not remove the ephemeral npmrc (${npmrc}); blanked it so the PAT is not left on disk"
    fi
    return 0
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
#
# --registry points at the PUBLIC registry here, not the private one -- the
# opposite of npm_view_latest, and load-bearing. --registry sets the DEFAULT
# registry for the whole install, which is what governs how UNSCOPED
# DEPENDENCIES resolve; GitHub Packages serves only scoped packages for the
# configured owner. @nine-at-a-time-media/admin depends on the unscoped
# `octokit`, so pointing the default at GitHub Packages made npm 404 on that
# dependency, and the fail-open path silently left gadmin uninstalled.
#
# It must be the COMMAND-LINE flag, not just the npmrc line: npm's config
# precedence is command line > environment > npmrc > builtin default, so an
# ambient NPM_CONFIG_REGISTRY in the sandbox outranks anything the npmrc says.
# Only the flag actually pins it.
#
# The private scoped package still routes correctly because --registry sets the
# default only -- the npmrc's @nine-at-a-time-media:registry mapping is a
# separate key and wins for that scope. See PR #187 review.
npm_install_pkg() {
    local npm_name="$1" version="$2" npmrc="$3" rc=0
    npm install --prefix "${ACQUIRE_PREFIX}" \
        --registry="${ACQUIRE_PUBLIC_REGISTRY}" \
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
# semantics (no readlink -f). Works for directory targets too (ln -sfn), so
# data packages reuse it for their convention symlink -- BUT a real
# (non-symlink) directory already sitting at <link> is refused: `ln -sfn`
# treats a directory-valued LINK_NAME as a target directory and would nest
# the new link INSIDE it (e.g. skills/skills), silently leaving consumers on
# the stale directory. The directory is not acquire's to delete; the caller
# warns and skips the stamp so the next run retries.
link_bin() {
    local target="$1" link="$2"
    mkdir -p "$(dirname "${link}")" || return 1
    if [ -L "${link}" ] && [ "$(readlink "${link}")" = "${target}" ]; then
        return 0
    fi
    if [ ! -L "${link}" ] && [ -d "${link}" ]; then
        acquire_note "WARNING: ${link} exists as a real directory (not a symlink); refusing to link through it -- remove or migrate it by hand"
        return 1
    fi
    ln -sfn "${target}" "${link}" || return 1
}

# artifact_present <bin> <artifact> -- whether the package's observable
# artifact is really on disk: an executable prefix binary for bin packages, or
# the package directory's package.json for data packages.
artifact_present() {
    local bin="$1" artifact="$2"
    if is_data_pkg "${bin}"; then
        [ -f "${artifact}/package.json" ]
    else
        [ -x "${artifact}" ]
    fi
}

# --- Flow ---

# acquire_one <shortname> <npm_name> <bin> <pin_var> <pins_file> <npmrc> --
# reconcile one package to its target version. Implements the currency state
# machine, guarding every fallible call and always returning 0 (fail-open).
acquire_one() {
    local shortname="$1" npm_name="$2" bin="$3" pin_var="$4" pins_file="$5" npmrc="$6"
    local requested latest target installed artifact link

    requested="$(pins_lookup "${pins_file}" "${pin_var}")" || requested=""

    # Only consult the registry when the version is floating (not pinned).
    latest=""
    if [ -z "${requested}" ]; then
        latest="$(npm_view_latest "${npm_name}" "${npmrc}")" || latest=""
    fi

    target="$(resolve_version "${requested}" "${latest}")" || target=""
    installed="$(installed_version "${shortname}")" || installed=""

    # Bin packages: artifact is the prefix binary, linked into ACQUIRE_BIN_DIR.
    # Data packages: artifact is the installed package dir, linked at the
    # boundary convention path under ACQUIRE_DATA_LINK_ROOT.
    if is_data_pkg "${bin}"; then
        artifact="${ACQUIRE_PREFIX}/node_modules/${npm_name}"
        link="${ACQUIRE_DATA_LINK_ROOT}/${npm_name}"
    else
        artifact="${ACQUIRE_PREFIX}/node_modules/.bin/${bin}"
        link="${ACQUIRE_BIN_DIR}/${bin}"
    fi

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

    # Already current AND the artifact is really present: no install; just
    # ensure the symlink is present. If the stamp matches but the artifact is
    # gone (share tree wiped, stamp survived), do NOT trust the stamp -- fall
    # through to reinstall so the package is actually available again.
    if [ -n "${installed}" ] && [ "${installed}" = "${target}" ] && artifact_present "${bin}" "${artifact}"; then
        acquire_note "${shortname} ${target} already up-to-date; skipping install"
        link_bin "${artifact}" "${link}" \
            || acquire_note "WARNING: ${shortname}: could not refresh symlink ${link}"
        return 0
    fi
    if [ -n "${installed}" ] && [ "${installed}" = "${target}" ]; then
        acquire_note "${shortname} ${target} stamped but ${artifact} is missing; reinstalling"
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

    if ! artifact_present "${bin}" "${artifact}"; then
        acquire_note "WARNING: ${shortname}: npm install reported success but ${artifact} is missing -- ${shortname} unavailable this run"
        return 0
    fi

    if ! link_bin "${artifact}" "${link}"; then
        acquire_note "WARNING: ${shortname}: installed ${target} but could not create symlink ${link}"
        return 0
    fi

    write_stamp "${shortname}" "${target}" \
        || acquire_note "WARNING: ${shortname}: could not write version stamp"
    acquire_note "installed ${shortname} ${target} from GitHub Packages; ${link} -> ${artifact}"
    return 0
}

# acquire_run <pins_file> -- the top-level flow. Checks the token once, builds
# one authed npmrc under a private mktemp dir, reconciles every package in the
# table, removes the npmrc whatever the outcome, and ALWAYS returns 0.
acquire_run() {
    # Optional under set -u, mirroring check_run: always invoked with an arg
    # today, but hardened so a bare acquire_run floats instead of crashing.
    local pins_file="${1:-}"
    local token="${GH_AI_TOOLS_PAT:-}"

    if [ -z "${token}" ]; then
        acquire_note "GH_AI_TOOLS_PAT is unset -- need a CLASSIC PAT with read:packages to install the fleet packages from GitHub Packages (npm.pkg.github.com)."
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
        purge_npmrc "${npmrc_dir}/.npmrc" "${npmrc_dir}"
        return 0
    fi
    npmrc="${npmrc_dir}/.npmrc"

    # Refuse to install through a symlinked or non-directory install prefix --
    # npm --prefix would then write THROUGH the link, outside the intended tree.
    # Fail-open: drop the token, skip installs, keep whatever is already there.
    if [ -L "${ACQUIRE_PREFIX}" ] || { [ -e "${ACQUIRE_PREFIX}" ] && [ ! -d "${ACQUIRE_PREFIX}" ]; }; then
        acquire_note "refusing to install: ${ACQUIRE_PREFIX} is a symlink or non-directory -- keeping whatever is already installed (fail-open)."
        purge_npmrc "${npmrc}" "${npmrc_dir}"
        return 0
    fi

    mkdir -p "${ACQUIRE_BIN_DIR}" "${ACQUIRE_STATE_DIR}" 2>/dev/null || true

    # Two passes (SANDBOX-LIFECYCLE.DESIGN.md D1). Pass 1: the skills DATA
    # package alone, using only the EXPLICIT pins (skills never pins itself
    # from the payload being installed). Pass 2: everything else, with the
    # pins resolved AFTER skills landed -- explicit --pins > fleet pins from
    # the (now-current) payload > float.
    local shortname npm_name bin pin_var
    while read -r shortname npm_name bin pin_var; do
        [ "${shortname}" = "skills" ] || continue
        acquire_one "${shortname}" "${npm_name}" "${bin}" "${pin_var}" "${pins_file}" "${npmrc}"
    done < <(acquire_pkg_table)

    local exec_pins
    exec_pins="$(effective_pins "${pins_file}")" || exec_pins="${pins_file}"
    if [ -z "${pins_file}" ] && [ -n "${exec_pins}" ]; then
        acquire_note "using fleet pins from the skills payload (${exec_pins})"
    fi

    while read -r shortname npm_name bin pin_var; do
        [ -n "${shortname}" ] || continue
        [ "${shortname}" = "skills" ] && continue
        acquire_one "${shortname}" "${npm_name}" "${bin}" "${pin_var}" "${exec_pins}" "${npmrc}"
    done < <(acquire_pkg_table)

    # The PAT must never linger on disk (see purge_npmrc).
    purge_npmrc "${npmrc}" "${npmrc_dir}"

    # Installed-but-unresolved warning: acquire never edits a shell rc.
    case ":${PATH}:" in
        *":${ACQUIRE_BIN_DIR}:"*) ;;
        *) acquire_note "note: ${ACQUIRE_BIN_DIR} is not on PATH -- installed clai/ast-mcp/gadmin will not resolve until it is added (acquire does not edit your shell rc)." ;;
    esac

    return 0
}

# --- Check (advisory currency; report-only, NEVER installs, ALWAYS exits 0) ---
#
# `lmde acquire --check` honors the same --pins file acquire would (the sandbox
# passes sandbox/pins.env; with no --pins every package floats) and asks GitHub
# Packages what the latest is, printing a short colored advisory for anything
# behind. It is meant to ride alongside git commands, so it is purely
# advisory: a package that is current prints nothing, an unreachable registry or
# missing token prints a warning, and EVERY path returns 0 -- it must never fail
# the command it accompanies. Under normal operation a checked-in pin and the
# installed stamp are at-or-behind the registry latest -- pins.env holds
# published versions and a stamp records a previously-resolved one -- so
# "differs from latest" is a good-enough proxy for "behind" and no semver
# comparator is needed. This is an expectation, not a hard guarantee: a pin set
# ahead of latest (an unpublished or typo'd version) is a misconfiguration
# acquire would fail to install, and --check would simply surface it as
# differing rather than prove an ordering.

# check_paint <enabled> <sgr> <text> -- echo <text> wrapped in the ANSI SGR
# color <sgr> (e.g. 31 red, 33 amber) when <enabled> is "1", else bare. Pure.
check_paint() {
    local enabled="$1" sgr="$2" text="$3"
    if [ "${enabled}" = "1" ]; then
        printf '\033[1;%sm%s\033[0m' "${sgr}" "${text}"
    else
        printf '%s' "${text}"
    fi
}

# check_one <shortname> <npm_name> <pin_var> <pins_file> <npmrc> <color> --
# classify one package's currency and print ONE advisory line only when it is
# behind. Current -> silent (stdout). Registry unreachable for this package ->
# a stderr warning, nothing on stdout. A checked-in pin behind latest -> AMBER
# (deliberate pin, newer available). A floating package whose installed stamp is
# behind latest -> RED (something meant to track latest is silently stale).
# ALWAYS returns 0. (The package table's `bin` column is unused here -- unlike
# acquire_one, a report-only check never touches a binary -- so check_run reads
# it into `_bin` and does not pass it.)
check_one() {
    local shortname="$1" npm_name="$2" pin_var="$3" pins_file="$4" npmrc="$5" color="$6"
    local requested latest installed

    requested="$(pins_lookup "${pins_file}" "${pin_var}")" || requested=""
    latest="$(npm_view_latest "${npm_name}" "${npmrc}")" || latest=""

    if [ -z "${latest}" ]; then
        acquire_note "WARNING: ${shortname}: registry unreachable -- cannot check for updates"
        return 0
    fi

    if [ -n "${requested}" ]; then
        if [ "${requested}" != "${latest}" ]; then
            check_paint "${color}" 33 \
"[lmde] ${shortname}: pinned ${requested}, latest ${latest} -- newer version available; bump ${pin_var} in ${pins_file}"
            printf '\n'
        fi
        return 0
    fi

    installed="$(installed_version "${shortname}")" || installed=""
    if [ -n "${installed}" ] && [ "${installed}" != "${latest}" ]; then
        check_paint "${color}" 31 \
"[lmde] ${shortname}: floating, installed ${installed}, latest ${latest} -- STALE; re-run lmde acquire"
        printf '\n'
    fi
    return 0
}

# check_run <pins_file> -- advisory currency check across the package table.
# Needs the same authed npmrc as acquire to read the private registry; a missing
# token or npm warns (stderr) and returns 0. Emits color only when stdout is a
# real terminal and NO_COLOR is unset or empty (per the NO_COLOR spec: a
# present, non-empty NO_COLOR disables color; NO_COLOR= does not). Builds one
# ephemeral npmrc, checks every
# package, purges the npmrc whatever the outcome, and ALWAYS returns 0.
check_run() {
    # Optional under set -u: a bare check_run must float (no pins), never crash
    # on an unbound $1 -- consistent with this verb's fail-open contract.
    local pins_file="${1:-}"
    local token="${GH_AI_TOOLS_PAT:-}"

    if [ -z "${token}" ]; then
        acquire_note "GH_AI_TOOLS_PAT unset or empty -- cannot query GitHub Packages; advisory update check skipped."
        return 0
    fi
    if ! command -v npm >/dev/null 2>&1; then
        acquire_note "npm not on PATH -- advisory update check skipped."
        return 0
    fi

    local color=""
    if [ -z "${NO_COLOR:-}" ] && [ -t 1 ]; then color="1"; fi

    local npmrc_dir="" npmrc=""
    npmrc_dir="$(mktemp -d "${TMPDIR:-/tmp}/lmde-check.XXXXXX")" || npmrc_dir=""
    if [ -z "${npmrc_dir}" ]; then
        acquire_note "could not create a temp dir for the npmrc -- advisory update check skipped."
        return 0
    fi
    if ! write_acquire_npmrc "${npmrc_dir}"; then
        acquire_note "could not write an authed npmrc -- advisory update check skipped."
        purge_npmrc "${npmrc_dir}/.npmrc" "${npmrc_dir}"
        return 0
    fi
    npmrc="${npmrc_dir}/.npmrc"

    # Mirror acquire_run's D1 resolution so the advisory reflects what acquire
    # would actually do: the skills row checks against the explicit pins only;
    # the executable rows check against explicit > fleet > float.
    local exec_pins
    exec_pins="$(effective_pins "${pins_file}")" || exec_pins="${pins_file}"

    local shortname npm_name _bin pin_var row_pins
    while read -r shortname npm_name _bin pin_var; do
        [ -n "${shortname}" ] || continue
        row_pins="${exec_pins}"
        [ "${shortname}" = "skills" ] && row_pins="${pins_file}"
        check_one "${shortname}" "${npm_name}" "${pin_var}" "${row_pins}" "${npmrc}" "${color}"
    done < <(acquire_pkg_table)

    purge_npmrc "${npmrc}" "${npmrc_dir}"
    return 0
}
