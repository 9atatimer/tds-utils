#!/usr/bin/env bash
# syntax_sweep.sh -- parse-check every git-tracked shell file in the repo.
#
# The same gate runs locally and in CI (.github/workflows/dist-ci.yml):
#   - files whose first line is a bash shebang  -> /bin/bash -n
#   - files whose first line is a zsh shebang   -> zsh -n
#   - the extensionless zsh dotfiles (no shebang of their own,
#     sourced by zsh at startup)                -> zsh -n
#   - the extensionless bash/sh dotfiles        -> /bin/bash -n
#
# /bin/bash is pinned deliberately: on macOS `env bash` resolves to
# Homebrew bash 5, which would silently stop parse-testing the 3.2
# dialect this repo must keep working on stock macOS. On Linux /bin/bash
# is the distro bash; CI's macos leg asserts /bin/bash IS 3.2 first.
#
# Only GIT-TRACKED files are swept (git ls-files -z). Never sweep the
# live tree: untracked caches (e.g. emacs/dot.emacs.d/.cache) contain
# shebang-lookalikes that must not be parsed.
#
# Usage: bash test/syntax_sweep.sh   (any cwd; repo root is self-detected)
# Exit:  0 when every file parses, 1 when any check fails.

set -euo pipefail

# Extensionless zsh dotfiles: sourced by zsh, no shebang first line, so
# the shebang scan cannot classify them. Keep in sync with macos/.
ZSH_DOTFILES="macos/dot.zshenv macos/dot.zprofile macos/dot.zshrc \
macos/dot.alias macos/dot.env macos/dot.zsh_log_search macos/dot.op-completion"

# Extensionless bash-family dotfiles: sourced by bash (or POSIX sh), no
# usable shebang (dot.prompts carries a fake '#!/usr/bash' for emacs
# formatting), so the shebang scan cannot classify these either.
BASH_DOTFILES="bash/dot.bashrc bash/dot.prompts bash/dot.bashrc.ubuntu_original \
macos/dot.bashrc macos/dot.profile emacs/dot.emacs.d/dot.emacs_bash"

# --- Action functions ---

# Repo root from this script's own location, so any cwd works.
find_repo_root() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    git -C "${script_dir}" rev-parse --show-toplevel
}

# First line of a file (empty for unreadable/empty files, never fatal).
# tr strips NUL bytes so binary tracked files (icons, archives) neither
# match a shebang pattern nor make bash 5's command substitution warn.
first_line() {
    local file="$1"
    head -n 1 "${file}" 2>/dev/null | LC_ALL=C tr -d '\0' || true
}

# Is <rel> listed in the whitespace-separated <list>?
in_dotfile_list() {
    local rel="$1" list="$2" candidate
    for candidate in ${list}; do
        if [ "${rel}" = "${candidate}" ]; then
            return 0
        fi
    done
    return 1
}

# Run one parse check, print a per-file verdict, return its status.
check_file() {
    local checker="$1" rel="$2" file="$3"
    if ${checker} -n "${file}" 2>&1; then
        printf 'ok    %-14s %s\n' "${checker} -n" "${rel}"
        return 0
    fi
    printf 'FAIL  %-14s %s\n' "${checker} -n" "${rel}"
    return 1
}

# --- Flow functions ---

# Walk the tracked file list, classify by first line (or dotfile list),
# parse-check each hit. Reports counts; nonzero when anything failed.
sweep_tracked_files() {
    local root="$1"
    local rel file line checked=0 failed=0
    while IFS= read -r -d '' rel; do
        file="${root}/${rel}"
        [ -f "${file}" ] || continue
        line="$(first_line "${file}")"
        case "${line}" in
            '#!/bin/bash'* | '#!/usr/bin/bash'* | '#!/usr/bin/env bash'*)
                checked=$((checked + 1))
                check_file /bin/bash "${rel}" "${file}" || failed=$((failed + 1))
                ;;
            '#!/bin/zsh'* | '#!/usr/bin/zsh'* | '#!/usr/bin/env zsh'*)
                checked=$((checked + 1))
                check_file zsh "${rel}" "${file}" || failed=$((failed + 1))
                ;;
            *)
                if in_dotfile_list "${rel}" "${ZSH_DOTFILES}"; then
                    checked=$((checked + 1))
                    check_file zsh "${rel}" "${file}" || failed=$((failed + 1))
                elif in_dotfile_list "${rel}" "${BASH_DOTFILES}"; then
                    checked=$((checked + 1))
                    check_file /bin/bash "${rel}" "${file}" || failed=$((failed + 1))
                fi
                ;;
        esac
    done < <(git -C "${root}" ls-files -z)

    printf '\nsyntax sweep: %d files checked, %d failed\n' \
        "${checked}" "${failed}"
    [ "${failed}" -eq 0 ]
}

# --- Main ---

main() {
    local root
    root="$(find_repo_root)"
    sweep_tracked_files "${root}"
}

main "$@"
