# .zshrc -- interactive shells only. Everything here is either slow, chatty,
# or meaningless without a terminal: runtime-manager shell functions,
# completion, history, prompt, tmux. Anything an agent-spawned `zsh -c` needs
# belongs in .zshenv instead -- see the contract at the top of that file.

# --- Runtime managers (these mutate PATH; keep them above tds_path_apply) ---

# nvm: .zshenv already put the default node toolchain on PATH statically, by
# reading $NVM_DIR/alias/default. Sourcing the script here is what makes `nvm`
# itself -- `nvm use`, `nvm install`, `nvm ls` -- exist as a shell function.
# It costs ~450ms, which is why only real terminals pay it.
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"

# pyenv: .zshenv already put $PYENV_ROOT/shims on PATH statically. This adds
# the `pyenv` shell function (pyenv shell, pyenv activate, rehash).
if (( $+commands[pyenv] )); then
    eval "$(pyenv init -)"
    if [[ -d "$PYENV_ROOT/plugins/pyenv-virtualenv" ]]; then
        eval "$(pyenv virtualenv-init -)"
    fi
fi

# direnv magic
if (( $+commands[direnv] )); then
    eval "$(direnv hook zsh)"
fi

# Restore the canonical ordering. Both managers above prepend their own
# entries; tds_path_apply is idempotent, so this simply puts everything back
# in rank. The ordering itself lives in .zshenv and is never restated here.
if (( $+functions[tds_path_apply] )); then
    tds_path_apply
fi

# --- History ---
# This has to live HERE, not in .zshenv: /etc/zshrc hard-sets HISTFILE,
# HISTSIZE and SAVEHIST, and it runs after ~/.zshenv but before ~/.zshrc, so
# anything set in .zshenv is overwritten before the user ever sees it.
HISTSIZE=999999999
SAVEHIST=999999999
HISTFILE="$HOME/.zsh_history"
setopt HIST_IGNORE_ALL_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_REDUCE_BLANKS
# Don't want this:
#setopt SHARE_HISTORY
# Trying this:
setopt INC_APPEND_HISTORY_TIME
setopt INC_APPEND_HISTORY
setopt EXTENDED_HISTORY
setopt HIST_SAVE_NO_DUPS

# --- Completion ---
# Every fpath contribution first, then exactly ONE compinit, then anything
# that calls compdef. The Homebrew site-functions directory used to arrive via
# brew's environment eval and its fpath line; now that .zshenv sets the
# Homebrew variables statically, it has to be added explicitly or every
# Homebrew-shipped completion silently disappears.
if [[ -n "${HOMEBREW_PREFIX:-}" && -d "$HOMEBREW_PREFIX/share/zsh/site-functions" ]]; then
    fpath=( "$HOMEBREW_PREFIX/share/zsh/site-functions" $fpath )
fi
if [[ -d "$HOME/.docker/completions" ]]; then
    fpath=( "$HOME/.docker/completions" $fpath )
fi

autoload -Uz compinit && compinit

# Sourcegraph
if [[ -f "$HOME/.sourcegraph/sg.zsh_autocomplete" ]]; then
    PROG=sg source "$HOME/.sourcegraph/sg.zsh_autocomplete"
fi

# Grubsta completion
if [[ -f "$HOME/workplace/lab54/grubsta/scripts/completions/grubsta-completions.zsh" ]]; then
    source "$HOME/workplace/lab54/grubsta/scripts/completions/grubsta-completions.zsh"
fi

# 1Password CLI completion and aliases.
# To regenerate the cached completion file after upgrading the 'op' CLI, run:
#   op completion zsh > ~/workplace/tds-utils/macos/dot.op-completion
# The agent/vscode guard is deliberate -- loading this under those hosts trips
# macOS TCC prompts. See TODO_PLAN.md "Lessons Learned".
if (( $+commands[op] )); then
    if [[ -z "${ANTIGRAVITY_AGENT:-}" && -z "${CLAI_AGENT:-}" && "${TERM_PROGRAM:-}" != "vscode" ]]; then
        if [[ -f "$HOME/.op-completion" ]]; then
            source "$HOME/.op-completion"
        elif [[ -f "$HOME/.tds/dist/current/macos/dot.op-completion" ]]; then
            source "$HOME/.tds/dist/current/macos/dot.op-completion"
        elif [[ -f "$HOME/.tds/release/macos/dot.op-completion" ]]; then
            source "$HOME/.tds/release/macos/dot.op-completion"
        elif [[ -f "$HOME/workplace/tds-utils/macos/dot.op-completion" ]]; then
            source "$HOME/workplace/tds-utils/macos/dot.op-completion"
        fi
    fi
fi

# --- Prompt ---

# Define the base prompt
prompt_base='%D{%H:%M:%S} %n@%m:%2~ %# '

# Check if the user is root and adjust color
if [[ $(id -u) -eq 0 ]]; then
    PROMPT="%F{red}${prompt_base}%f"
else
    PROMPT="${prompt_base}"
fi

# UV environment indicator on the RHS of the zsh prompt
setopt prompt_subst

function uv_env_prompt() {
  if [[ -n "$VIRTUAL_ENV" ]]; then
    if [[ "$VIRTUAL_ENV" == *".uv/env/"* ]]; then
      local env_name=$(basename "$VIRTUAL_ENV")
      echo "%F{cyan}(uv:$env_name)%f"
    fi
  fi
}

RPROMPT='$(uv_env_prompt)'

# --- Interactive conveniences ---

# for gpg stuff
export GPG_TTY=$(tty)

# we want wildcard for ec alias, so define it as a function:
ec() {
    emacsclient -n "$@"
}

# Source aliases
if [[ -f "$HOME/.alias" ]]; then
    source "$HOME/.alias"
fi

# log-hoarder: semantic search widget (ctrl-x s). Same tier order as PATH --
# dist install, then the release worktree, then the live dev checkout last
# (issues #202, #235).
if [[ -f "$HOME/.tds/dist/current/macos/dot.zsh_log_search" ]]; then
    source "$HOME/.tds/dist/current/macos/dot.zsh_log_search"
elif [[ -f "$HOME/.tds/release/macos/dot.zsh_log_search" ]]; then
    source "$HOME/.tds/release/macos/dot.zsh_log_search"
elif [[ -f "$HOME/workplace/tds-utils/macos/dot.zsh_log_search" ]]; then
    source "$HOME/workplace/tds-utils/macos/dot.zsh_log_search"
fi

# ~/.tds-local overlay: device-owned config loads last (work overlays etc.);
# core ships the hook, the device owns the content. Stays above the tmux
# exec block -- nothing below that runs in a normal terminal.
if [[ -f "$HOME/.tds-local/zshrc" ]]; then
    source "$HOME/.tds-local/zshrc"
fi

# --- Main (must stay last: exec replaces this shell) ---

# log-hoarder: auto-launch tmux for each new terminal window.
# NOTHING BELOW THIS BLOCK RUNS in a normal terminal. tmux's shell is login
# AND interactive, so .zshenv -> path_helper -> .zprofile -> .zshrc all run a
# second time; that is why tds_path_apply has to be idempotent.
if [[ -o interactive ]] && [[ -z "$TMUX" ]]; then
    exec tmux new-session
fi
