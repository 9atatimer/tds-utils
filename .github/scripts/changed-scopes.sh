#!/usr/bin/env bash
# changed-scopes.sh -- which dist-ci jobs a change needs to run.
#
# dist-ci.yml runs every job behind an `if:` on these outputs, so a job a
# change cannot affect is SKIPPED, which `gate` counts as a pass. A
# per-workflow `paths:` filter cannot do this: a filtered-out run never
# reports `gate` at all, and an absent required check hangs tedium.
#
# Usage:
#   changed-scopes.sh classify      # file list on stdin -> outputs
#   changed-scopes.sh pr            # the files HEAD^2 adds to HEAD^1
#                                   # (the PR's merge commit)
#   changed-scopes.sh all           # every scope true (push, unknown)
#
# Output: one `<scope>=true|false` line per scope on stdout, appended to
# $GITHUB_OUTPUT when set. The rules below are the ONLY place the scopes
# live. Every doubt resolves toward running MORE:
#
#   - a gate file (this script, its test, dist-ci.yml) runs everything;
#   - a file under dynomark/, chores/ or adherence/ runs that tree's
#     jobs, whatever its extension (dynomark/contract/README.md is itself
#     checked);
#   - a shell file anywhere (by extension or shebang) runs smoketests,
#     whose syntax sweep covers every tracked shell file;
#   - Markdown elsewhere and docs/**/*.html run nothing;
#   - anything else runs smoketests and shellcheck.
#
# Bash 3.2-safe on purpose (no associative arrays): the smoketests'
# syntax sweep parses it under macOS /bin/bash.

set -euo pipefail

# --- Scope table -------------------------------------------------------------

SCOPES="smoketests shellcheck chores adherence dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e"

GATE_FILES=".github/workflows/dist-ci.yml .github/scripts/changed-scopes.sh test/smoketest_changed_scopes.sh"

# --- Action functions --------------------------------------------------------

is_gate_file() {
    local file="$1" g
    for g in ${GATE_FILES}; do
        [ "${file}" = "${g}" ] && return 0
    done
    return 1
}

is_shell_file() {
    local file="$1" line
    case "${file}" in
        *.sh | *.bash | *.zsh) return 0 ;;
    esac
    [ -f "${file}" ] || return 1
    line="$(head -n 1 "${file}" 2>/dev/null | LC_ALL=C tr -d '\0' || true)"
    case "${line}" in
        '#!'*bash* | '#!'*zsh*) return 0 ;;
    esac
    return 1
}

is_inert() {
    local file="$1"
    case "${file}" in
        dynomark/* | chores/* | adherence/*) return 1 ;;
        *.md) return 0 ;;
        docs/*.html) return 0 ;;
    esac
    return 1
}

# The scopes one file needs, space-separated; "all" for a gate file.
scopes_for() {
    local file="$1" out=""
    if is_gate_file "${file}"; then
        echo "all"
        return 0
    fi
    case "${file}" in
        dynomark/contract/*) out="dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e" ;;
        dynomark/daemon/*) out="dynomark-daemon dynomark-e2e" ;;
        dynomark/extension/*) out="dynomark-extension dynomark-e2e" ;;
        dynomark/e2e/*) out="dynomark-e2e" ;;
        dynomark/*) out="dynomark-contract dynomark-daemon dynomark-extension dynomark-e2e" ;;
        chores/*) out="chores" ;;
        adherence/*) out="adherence" ;;
        *) is_inert "${file}" || out="smoketests shellcheck" ;;
    esac
    if is_shell_file "${file}"; then
        out="${out} smoketests"
    fi
    echo "${out}"
}

emit() {
    local line="$1"
    echo "${line}"
    if [ -n "${GITHUB_OUTPUT:-}" ]; then
        echo "${line}" >>"${GITHUB_OUTPUT}"
    fi
}

emit_all() {
    local scope
    for scope in ${SCOPES}; do
        emit "${scope}=true"
    done
}

# --- Flow functions ----------------------------------------------------------

classify() {
    local file hits=" " s scope
    while IFS= read -r file; do
        [ -n "${file}" ] || continue
        for s in $(scopes_for "${file}"); do
            if [ "${s}" = "all" ]; then
                emit_all
                return 0
            fi
            hits="${hits}${s} "
        done
    done
    for scope in ${SCOPES}; do
        case "${hits}" in
            *" ${scope} "*) emit "${scope}=true" ;;
            *) emit "${scope}=false" ;;
        esac
    done
}

classify_pr() {
    local files
    if ! git rev-parse --verify --quiet HEAD^2 >/dev/null; then
        echo "changed-scopes: HEAD is not a merge commit; running everything" >&2
        emit_all
        return 0
    fi
    # --no-renames: a move lists its old path too, so moving a file out of
    # a tree still runs that tree's jobs. quotePath off: a non-ASCII path
    # stays unquoted and keeps its tree prefix.
    files="$(git -c core.quotePath=false diff --name-only --no-renames HEAD^1 HEAD)"
    printf '%s\n' "${files}" | classify
}

# --- Main --------------------------------------------------------------------

main() {
    case "${1:-}" in
        classify) classify ;;
        pr) classify_pr ;;
        all) emit_all ;;
        *)
            echo "usage: $0 classify|pr|all" >&2
            exit 2
            ;;
    esac
}

# Run only when executed; the test sources this file.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
