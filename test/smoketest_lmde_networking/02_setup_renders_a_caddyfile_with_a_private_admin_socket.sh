#!/usr/bin/env bash
# 02_setup_renders_a_caddyfile_with_a_private_admin_socket.sh
# Given the networking component's Caddyfile template, When setup.sh
# installs it into a (fake) Homebrew etc, Then the rendered Caddyfile puts
# the admin API on a unix socket under the component's run dir with mode
# 0600 and names no TCP admin address, the run dir exists with mode 0700,
# and `caddy adapt` accepts the result (skipped when caddy is absent).
# The real /opt/homebrew/etc and the running Caddy are never touched.

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    fixture_setup
    local etc="${WORK}/etc" home="${WORK}/home" out caddyfile
    mkdir -p "${etc}" "${home}"
    out="$(env -i HOME="${home}" PATH="/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin" \
        LMDE_NETWORKING_CADDY_ETC="${etc}" LMDE_NETWORKING_NO_RESTART=1 \
        /bin/bash "${SETUP}" install 2>&1)" || fail "setup.sh install failed: ${out}"
    caddyfile="${etc}/Caddyfile"
    [[ -f "${caddyfile}" ]] || fail "no Caddyfile rendered into ${etc}"
    local text
    text="$(cat "${caddyfile}")"
    assert_contains "${text}" "admin unix/${home}/.local/share/lmde-networking/run/caddy-admin.sock|0600" "admin on the component's socket, mode 0600"
    assert_not_contains "${text}" "2019" "no TCP admin address"
    [[ -d "${home}/.local/share/lmde-networking/run" ]] || fail "run dir not created"
    [[ "$(stat -f '%Lp' "${home}/.local/share/lmde-networking/run")" == "700" ]] || fail "run dir is not mode 0700"
    if command -v caddy >/dev/null 2>&1; then
        caddy adapt --config "${caddyfile}" >/dev/null 2>&1 || fail "caddy adapt rejected the rendered Caddyfile"
    fi
    assert_contains "${out}" "Caddyfile" "setup reports what it installed"
}

main "$@"
