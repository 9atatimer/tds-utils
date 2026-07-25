# .zprofile -- login shells only, and specifically AFTER macOS has had its say.
#
# /etc/zprofile evaluates `/usr/libexec/path_helper -s`. path_helper rebuilds
# PATH from /etc/paths and /etc/paths.d with those system directories FIRST,
# appending the PATH it inherited after them. That silently demotes everything
# .zshenv established -- most damagingly $HOMEBREW_PREFIX/bin, which sinks
# below /bin, so `#!/usr/bin/env bash` starts resolving Apple Bash 3.2. Bash
# 3.2 has no `readarray`, which is what aborted the clai pre-hook (issue #176).
#
# zsh always sources ~/.zshenv before /etc/zprofile, in the same process, so
# tds_path_apply is already defined by the time we get here. The ordering is
# NOT restated in this file: one definition, three call sites, no drift.

# --- Main ---

if (( $+functions[tds_path_apply] )); then
    tds_path_apply
fi

# Homebrew's info pages. `man` needs nothing -- manpath(1) derives its search
# path from PATH -- and brew's own environment eval likewise emits no MANPATH
# when MANPATH is unset, so setting one here would be a deviation, not a fix.
if [[ -n "${HOMEBREW_PREFIX:-}" ]]; then
    export INFOPATH="$HOMEBREW_PREFIX/share/info:${INFOPATH:-}"
fi
