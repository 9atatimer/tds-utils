#!/usr/bin/env bash
# smoketest_macos_apps.sh -- behavioral smoke test for macos/apps/mkmacapp.
#
# Real osacompile, real codesign, real iconutil -- this is a smoke test, so it
# exercises the actual macOS toolchain rather than faking it. Everything is
# built into a throwaway tmpdir; nothing is installed and the Dock is never
# touched (--dock mutates the live Dock, so it is deliberately not covered).
#
# Skips cleanly on non-macOS and when osacompile is unavailable.
#
# Usage: ./test/smoketest_macos_apps.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "${SCRIPT_DIR}")"
MKMACAPP="${REPO_DIR}/macos/apps/mkmacapp"

# --- Test harness ---

TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0
WORKROOT=""

red()   { printf '\033[1;31m%s\033[0m' "$1"; }
green() { printf '\033[1;32m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m'    "$1"; }

assert() {
    local label="$1" condition="$2"
    TESTS_RUN=$((TESTS_RUN + 1))
    if eval "${condition}"; then
        green "  PASS"; printf ' %s\n' "${label}"
        TESTS_PASSED=$((TESTS_PASSED + 1))
    else
        red "  FAIL"; printf ' %s\n' "${label}"
        TESTS_FAILED=$((TESTS_FAILED + 1))
    fi
}

skip() { bold "  SKIP"; printf ' %s\n' "$1"; }

setup()   { WORKROOT="$(mktemp -d "${TMPDIR:-/tmp}/macos-apps-test.XXXXXX")"; }
cleanup() { [ -n "${WORKROOT}" ] && [ -d "${WORKROOT}" ] && rm -rf "${WORKROOT}"; }
trap cleanup EXIT

plist_get() {
    /usr/libexec/PlistBuddy -c "Print :$2" "$1/Contents/Info.plist" 2>/dev/null
}

# --- Fixtures ---

# A minimal but valid .icns, produced the same way a real app's icon.py does.
make_icon() {
    local dest="$1" iconset="${WORKROOT}/fixture.iconset"
    mkdir -p "${iconset}"
    # A 16x16 and 32x32 pair is the smallest set iconutil will accept.
    sips -s format png --resampleHeightWidth 16 16 \
         /System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns \
         --out "${iconset}/icon_16x16.png" >/dev/null 2>&1
    sips -s format png --resampleHeightWidth 32 32 \
         /System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/GenericApplicationIcon.icns \
         --out "${iconset}/icon_16x16@2x.png" >/dev/null 2>&1
    iconutil -c icns "${iconset}" -o "${dest}" 2>/dev/null
}

# --- Tests ---

test_builds_a_bundle() {
    bold "Builds a launchable bundle"; printf '\n'
    local dest="${WORKROOT}/build1" app
    app="${dest}/Smoke Test.app"

    "${MKMACAPP}" --name "Smoke Test" --command 'true' --dest "${dest}" \
        >/dev/null 2>&1

    assert "bundle directory exists" \
        "[ -d '${app}' ]"
    assert "applet executable is present and executable" \
        "[ -x '${app}/Contents/MacOS/applet' ]"
    assert "CFBundleName is the supplied name" \
        "[ \"\$(plist_get '${app}' CFBundleName)\" = 'Smoke Test' ]"
    assert "CFBundleIdentifier is derived from the name" \
        "plist_get '${app}' CFBundleIdentifier | grep -qi 'smoketest'"
}

test_custom_icon_wins() {
    bold "Custom icon outranks the stock applet icon"; printf '\n'
    local dest="${WORKROOT}/build2" icon="${WORKROOT}/fixture.icns" app
    app="${dest}/Iconic.app"

    make_icon "${icon}"
    if [ ! -s "${icon}" ]; then
        skip "could not build a fixture .icns on this system"
        return
    fi

    "${MKMACAPP}" --name "Iconic" --command 'true' --icon "${icon}" \
        --dest "${dest}" >/dev/null 2>&1

    assert "applet.icns is byte-identical to the supplied icon" \
        "cmp -s '${icon}' '${app}/Contents/Resources/applet.icns'"
    assert "stock Assets.car is removed" \
        "[ ! -e '${app}/Contents/Resources/Assets.car' ]"
    assert "CFBundleIconName is absent so applet.icns wins" \
        "[ -z \"\$(plist_get '${app}' CFBundleIconName)\" ]"
    assert "CFBundleIconFile points at applet" \
        "[ \"\$(plist_get '${app}' CFBundleIconFile)\" = 'applet' ]"
}

test_signature_is_valid() {
    bold "Bundle carries a valid ad-hoc signature"; printf '\n'
    local dest="${WORKROOT}/build3" app
    app="${dest}/Signed.app"

    "${MKMACAPP}" --name "Signed" --command 'true' --dest "${dest}" \
        >/dev/null 2>&1

    # This is the regression that matters: leftover xattrs make codesign fail
    # with "resource fork, Finder information, or similar detritus".
    assert "codesign --verify passes on the finished bundle" \
        "codesign --verify --deep '${app}' 2>/dev/null"
}

test_command_is_wired_through() {
    bold "The command runs with the repo bin on PATH"; printf '\n'
    local dest="${WORKROOT}/build4" app marker
    app="${dest}/Wired.app"
    marker="${WORKROOT}/ran.txt"

    "${MKMACAPP}" --name "Wired" --command "touch '${marker}'" \
        --dest "${dest}" >/dev/null 2>&1

    # Run the compiled applet's script rather than double-clicking it.
    osascript "${app}/Contents/Resources/Scripts/main.scpt" >/dev/null 2>&1 || true

    assert "the wrapped command actually executed" \
        "[ -e '${marker}' ]"
    assert "the repo bin directory is on the generated PATH" \
        "osadecompile '${app}/Contents/Resources/Scripts/main.scpt' 2>/dev/null | grep -qF '${REPO_DIR}/bin'"
    assert "no developer home directory is baked into the repo source" \
        "! grep -rqF '/Users/' '${REPO_DIR}/macos/apps/' --include=mkmacapp --include=build"
}

test_usage_errors() {
    bold "Usage errors are reported, not papered over"; printf '\n'
    local dest="${WORKROOT}/build5" status

    status=0; "${MKMACAPP}" --dest "${dest}" >/dev/null 2>&1 || status=$?
    assert "missing --name and --command exits 64" \
        "[ '${status}' -eq 64 ]"

    status=0; "${MKMACAPP}" --name "NoCmd" --dest "${dest}" >/dev/null 2>&1 || status=$?
    assert "missing --command exits 64" \
        "[ '${status}' -eq 64 ]"

    status=0
    "${MKMACAPP}" --name "Ghost" --command 'true' --icon "${WORKROOT}/nope.icns" \
        --dest "${dest}" >/dev/null 2>&1 || status=$?
    assert "a missing --icon file is a hard failure" \
        "[ '${status}' -ne 0 ]"
}

test_clobber_protection() {
    bold "An existing bundle is not silently replaced"; printf '\n'
    local dest="${WORKROOT}/build6" status
    local app="${dest}/Twice.app"

    "${MKMACAPP}" --name "Twice" --command 'true' --dest "${dest}" >/dev/null 2>&1

    status=0
    "${MKMACAPP}" --name "Twice" --command 'true' --dest "${dest}" \
        >/dev/null 2>&1 || status=$?
    assert "rebuilding over an existing bundle fails without --force" \
        "[ '${status}' -ne 0 ]"

    status=0
    "${MKMACAPP}" --name "Twice" --command 'true' --dest "${dest}" --force \
        >/dev/null 2>&1 || status=$?
    assert "--force replaces it" \
        "[ '${status}' -eq 0 ] && [ -d '${app}' ]"
}

test_flip_monitor_app() {
    bold "The flip-monitor app builds from its own build script"; printf '\n'
    local build="${REPO_DIR}/macos/apps/flip-monitor/build"
    local dest="${WORKROOT}/build7" app
    app="${dest}/Flip Monitor.app"

    assert "flip-monitor/build is executable" \
        "[ -x '${build}' ]"
    assert "flip-monitor/icon.icns is committed" \
        "[ -s '${REPO_DIR}/macos/apps/flip-monitor/icon.icns' ]"

    "${build}" --dest "${dest}" >/dev/null 2>&1

    assert "it produces a Flip Monitor bundle" \
        "[ -d '${app}' ]"
    assert "it wraps monctl flip, not the mc shell alias" \
        "osadecompile '${app}/Contents/Resources/Scripts/main.scpt' 2>/dev/null | grep -qF 'monctl flip'"
}

# --- Flow ---

run_all() {
    printf '\n'; bold "smoketest_macos_apps"; printf '\n\n'

    test_builds_a_bundle;        printf '\n'
    test_custom_icon_wins;       printf '\n'
    test_signature_is_valid;     printf '\n'
    test_command_is_wired_through; printf '\n'
    test_usage_errors;           printf '\n'
    test_clobber_protection;     printf '\n'
    test_flip_monitor_app;       printf '\n'

    printf 'ran %d, passed %d, failed %d\n' \
        "${TESTS_RUN}" "${TESTS_PASSED}" "${TESTS_FAILED}"
    [ "${TESTS_FAILED}" -eq 0 ]
}

main() {
    if [ "$(uname -s)" != "Darwin" ]; then
        skip "not macOS -- mkmacapp builds Apple bundles"
        exit 0
    fi
    if ! command -v osacompile >/dev/null 2>&1; then
        skip "osacompile not available"
        exit 0
    fi
    if [ ! -x "${MKMACAPP}" ]; then
        red "  FAIL"; printf ' macos/apps/mkmacapp is missing or not executable\n'
        exit 1
    fi

    setup
    run_all
}

main "$@"
