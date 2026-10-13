#!/usr/bin/env bash
# 11_seed_refuses_anything_but_a_human_session.sh
# Given anything other than a human at a terminal with an interactive op
# session -- no terminal, a 1Password service-account token in the
# environment, a reference that is not op://, a failed op read, or a value
# that is not a run token -- When the seeding script runs, Then it exits
# non-zero, writes nothing to the keychain and prints no value (Q9).

set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/config.sh"

main() {
    require_macos
    fixture_setup
    install_fake_op
    local out status

    status=0
    out="$(env -i HOME="${FAKE_HOME}" PATH="${FAKE_BIN}:/usr/bin:/bin" OLLAMA_GATEWAY_KEYCHAIN="${KEYCHAIN}" \
        /bin/zsh -f "${SEED}" "${FAKE_REF}" < /dev/null 2>&1)" || status=$?
    [[ "${status}" -ne 0 ]] || fail "must refuse without a terminal"
    assert_contains "${out}" "terminal" "no-terminal refusal says why"

    out="$(SEED_EXTRA_ENV="OP_SERVICE_ACCOUNT_TOKEN=ops_fake" run_seed_tty "${FAKE_REF}")"
    assert_contains "${out}" "OP_SERVICE_ACCOUNT_TOKEN" "service-account refusal names the variable"

    out="$(run_seed_tty "not-a-reference")"
    assert_contains "${out}" "op://" "bad reference refusal"

    out="$(SEED_EXTRA_ENV="OP_FAKE_FAIL=1" run_seed_tty "${FAKE_REF}")"
    assert_contains "${out}" "op read failed" "op failure refusal"

    install_fake_op "not a token; has spaces"
    out="$(run_seed_tty "${FAKE_REF}")"
    assert_contains "${out}" "not a tunnel run token" "malformed value refusal"
    assert_not_contains "${out}" "has spaces" "malformed value never printed"

    assert_eq "$(keychain_token)" "" "nothing was written to the keychain"
}

main "$@"
