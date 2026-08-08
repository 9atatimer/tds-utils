# .zshenv -- read by EVERY zsh, including the noninteractive, nonlogin shells
# that GUI applications and coding agents spawn (`zsh -c ...`). Those shells
# source this file and nothing else, so the toolchain has to be established
# here (issue #169). See issue #176 for why that alone is not sufficient.
#
# The three-file contract:
#   .zshenv   -- this file. Static, silent, fork-free environment plus THE
#                canonical PATH ordering. No runtime-manager startup, no
#                completions, no output of any kind: this file runs when zsh
#                is acting as a script interpreter, so a single stray line on
#                stdout corrupts whatever captured that script.
#   .zprofile -- login shells only. Re-applies the ordering defined here,
#                because macOS /etc/zprofile runs /usr/libexec/path_helper
#                AFTER this file and demotes everything it prepended.
#   .zshrc    -- interactive shells only: runtime managers, completion,
#                history, prompt, tmux.
#
# The ordering is stated exactly ONCE, in tds_path_apply below. .zprofile and
# .zshrc re-invoke that function rather than restating any part of it, so the
# three files cannot drift apart.

# --- Environment ---

# log-hoarder: terminal session log directory (XDG-conventional).
# Unset or empty to disable logging (diag logs still go to $HOME).
# Uses :- so it can be overridden (e.g. for testing).
export TDS_LOG_DIR="${TDS_LOG_DIR:-$HOME/.local/share/log-hoarder}"

# Language-runtime roots. Setting the variables is free; starting the managers
# is not, so that happens in .zshrc. Both must be unconditional: the PATH
# block below derives directories from them, so gating them on the tool
# already being resolvable would be circular.
export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
export PYENV_ROOT="${PYENV_ROOT:-$HOME/.pyenv}"

# ast-mcp: dynamically resolve AST_MCP_BIN path based on environment if unset
if [[ -z "${AST_MCP_BIN:-}" ]]; then
    if [[ "${CLAUDE_CODE_REMOTE:-}" == "true" ]]; then
        export AST_MCP_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.ast-mcp/node_modules/.bin/ast-mcp"
    else
        export AST_MCP_BIN="$HOME/.local/bin/ast-mcp"
    fi
fi

# 1Password SSH agent. Only when the caller has not supplied one: agent
# forwarding, `ssh -A`, a CI harness and a test rig all export their own
# socket, and clobbering it strands the caller with no way to sign.
export SSH_AUTH_SOCK="${SSH_AUTH_SOCK:-$HOME/Library/Group Containers/2BUA8C4S2C.com.1password/t/agent.sock}"

# Homebrew, resolved by a builtin test rather than by asking brew. These are
# exactly the three variables brew's own environment eval exports; the rest of
# its output is PATH (handled below), fpath (handled in .zshrc) and INFOPATH
# (handled in .zprofile). Apple Silicon first, Intel fallback.
#
# NB: do not name that eval literally in this file. test/smoketest_shell_env.sh
# greps the raw text of .zshenv for heavy-init markers, so even a comment
# mentioning it fails the suite.
if [[ -x /opt/homebrew/bin/brew ]]; then
    export HOMEBREW_PREFIX=/opt/homebrew
    export HOMEBREW_CELLAR=/opt/homebrew/Cellar
    export HOMEBREW_REPOSITORY=/opt/homebrew
elif [[ -x /usr/local/bin/brew ]]; then
    export HOMEBREW_PREFIX=/usr/local
    export HOMEBREW_CELLAR=/usr/local/Cellar
    export HOMEBREW_REPOSITORY=/usr/local/Homebrew
fi

# --- Action functions ---

# Resolve the bin directory of nvm's default node WITHOUT starting nvm.
# Sourcing nvm's loader costs ~456ms, which every agent-spawned shell would pay;
# the answer is one file read away. `read` is a builtin and the redirect is not
# a subshell, so this forks nothing. Result in $REPLY; anything that does not
# land on a real directory yields nothing at all -- no bogus PATH entry, no
# output.
#
# $NVM_DIR/alias/default holds either a version or the name of another alias,
# so follow a few hops. nvm is INCONSISTENT about the "v" prefix between those
# two forms, which is the trap here:
#     alias/default     -> "24.18.0"      bare, when set by `nvm alias default`
#     alias/lts/*       -> "lts/krypton"  another alias name
#     alias/lts/krypton -> "v24.18.0"     v-prefixed, written by nvm itself
# Directory names are always v-prefixed. So strip any leading "v" before adding
# one back, or the common `nvm alias default 'lts/*'` setup resolves correctly
# and is then thrown away against a nonexistent "vv24.18.0".
#
# `read` is deliberately NOT guarded with `|| return 0`: zsh's read reports
# failure on EOF-before-delimiter, so an alias file with no trailing newline
# fails the read while still populating $version correctly. The emptiness check
# on the next line is the real guard.
tds_nvm_default_bin() {
    emulate -L zsh
    local root="${NVM_DIR:-$HOME/.nvm}" name=default version hop dir
    REPLY=""
    for hop in 1 2 3 4; do
        [[ -r "$root/alias/$name" ]] || return 0
        read -r version < "$root/alias/$name"
        [[ -n "$version" ]] || return 0
        dir="$root/versions/node/v${version#v}/bin"
        if [[ -d "$dir" ]]; then
            REPLY="$dir"
            return 0
        fi
        name="$version"
    done
    return 0
}

# --- Flow functions ---

# THE canonical PATH ordering. Called from here, from .zprofile (after
# path_helper) and from .zshrc (after the runtime managers prepend their own
# entries). Idempotent by construction: managed entries are subtracted from
# wherever they currently sit and re-seated, so repeated calls converge on the
# same PATH instead of stacking. That matters because .zshrc execs tmux, whose
# shell walks .zshenv -> /etc/zprofile -> .zprofile -> .zshrc all over again.
#
# Directories that do not exist are dropped, which keeps PATH short and lets
# this same file work on a machine without antigravity, windsurf or nvm.
#
# Ordering rationale, front to back:
#   .local/bin        uv-installed tools (clai, ast-mcp, ...). Must outrank
#                     tds-utils/bin: clone-audit exists in both and the
#                     uv-installed copy is the current one.
#   antigravity,      editor CLIs. GUI-spawned agents get only this file.
#   windsurf
#   pyenv shims       pyenv global is 3.12.4; Homebrew ships python3 3.14.6.
#                     Shims must outrank Homebrew or an agent gets a different
#                     interpreter than the terminal does.
#   node default bin  `claude` is an npm global scoped to that node version
#                     alone; Homebrew's node does not carry it.
#   go/bin            `go install` target (goimports and friends).
#   tds-utils/bin     this repo's scripts (lmde, goldfish, orgmarks, ...).
#   Homebrew bin,     GNU bash 5.x (readarray), gh, uv, git, tmux, direnv, op,
#   Homebrew sbin     pyenv, go. MUST outrank /bin -- that is issue #176.
#   <inherited PATH>  in a login shell this is path_helper's block:
#                     /usr/local/bin, /usr/bin, /bin, /usr/sbin, /sbin, the
#                     cryptex entries. Kept verbatim; never hand-rolled.
#   .cargo/bin, .sg   deliberately last; nothing in them needs to shadow.
tds_path_apply() {
    emulate -L zsh
    # -g is load-bearing: a bare `typeset -U path` would create a FUNCTION
    # LOCAL `path`, the assignment below would evaporate on return, and this
    # function would silently become a no-op.
    typeset -gU path PATH
    local d REPLY
    local -a want_head want_tail head tail managed

    tds_nvm_default_bin

    # tds bin: the installed environment (~/.tds/dist/current) owns PATH
    # once it exists; the dev checkout is only a pre-migration fallback,
    # so branch switches there stop leaking into live shells (issue #202).
    local -a tds_bin
    if [[ -d "$HOME/.tds/dist/current/bin" ]]; then
        tds_bin=( "$HOME/.tds/dist/current/bin" )
    else
        tds_bin=( "$HOME/workplace/tds-utils/bin" )
    fi

    want_head=(
        "$HOME/.local/bin"
        "$HOME/.antigravity/antigravity/bin"
        "$HOME/.codeium/windsurf/bin"
        "$PYENV_ROOT/shims"
        "$REPLY"
        "$HOME/go/bin"
        $tds_bin
        "${HOMEBREW_PREFIX:+$HOMEBREW_PREFIX/bin}"
        "${HOMEBREW_PREFIX:+$HOMEBREW_PREFIX/sbin}"
    )
    want_tail=(
        "$HOME/.cargo/bin"
        "$HOME/.sg"
    )

    for d in $want_head; do [[ -n "$d" && -d "$d" ]] && head+=( "$d" ); done
    for d in $want_tail; do [[ -n "$d" && -d "$d" ]] && tail+=( "$d" ); done
    managed=( $head $tail )

    # ${path:|managed} is zsh array subtraction: every current entry this
    # function does NOT own, in its current order. In a login shell that is
    # precisely path_helper's freshly built system block.
    path=( $head ${path:|managed} $tail )
}

# --- Main ---

tds_path_apply

# Note: ~/.cargo/env and ~/.local/bin/env are deliberately NOT sourced here.
# Each is a `case ":$PATH:" in` shim whose entire effect is to PREPEND one
# directory, and both directories appear above in their intended positions.
# Sourcing either could only pull an entry out of rank.
