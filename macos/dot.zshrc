# Environment paths migrated to dot.zshenv

[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
autoload -Uz compinit && compinit
PROG=sg source /Users/stumpf/.sourcegraph/sg.zsh_autocomplete

# pyenv init migrated to dot.zshenv

# direnv magic
eval "$(direnv hook zsh)"

# 1Password Integration migrated to dot.zshenv

# CLI completion and aliases
# To regenerate the cached completion file after upgrading the 'op' CLI, run:
#   op completion zsh > ~/workplace/tds-utils/macos/dot.op-completion
if [[ -o interactive ]] && (( $+commands[op] )); then
    if [[ -z "${ANTIGRAVITY_AGENT:-}" && -z "${CLAI_AGENT:-}" && "${TERM_PROGRAM:-}" != "vscode" ]]; then
        if [[ -f "${HOME}/.op-completion" ]]; then
            source "${HOME}/.op-completion"
        elif [[ -f "${HOME}/workplace/tds-utils/macos/dot.op-completion" ]]; then
            source "${HOME}/workplace/tds-utils/macos/dot.op-completion"
        fi
    fi
fi

# Define the base prompt
prompt_base='%D{%H:%M:%S} %n@%m:%2~ %# '

# Check if the user is root and adjust color
if [[ $(id -u) -eq 0 ]]; then
    PROMPT="%F{red}${prompt_base}%f"
else
    PROMPT="${prompt_base}"
fi

# for gpg stuff
export GPG_TTY=$(tty)

# we want wildcard for ec alias, so define it as a function:
ec() {
    emacsclient -n "$@"
}

# Source aliases
if [ -f "$HOME/.alias" ]; then
    source "$HOME/.alias"
fi

# .local/bin/env and windsurf paths migrated to dot.zshenv

# UV environment indicator of RHS of zsh prompt
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

# Docker CLI completions
fpath=(/Users/stumpf/.docker/completions $fpath)
autoload -Uz compinit
compinit

# Grubsta completion
source ~/workplace/lab54/grubsta/scripts/completions/grubsta-completions.zsh

# Path deduplication and additions migrated to dot.zshenv

# log-hoarder: semantic search widget (ctrl-x s)
if [[ -f ~/workplace/tds-utils/macos/dot.zsh_log_search ]]; then
    source ~/workplace/tds-utils/macos/dot.zsh_log_search
fi

# log-hoarder: auto-launch tmux for each new terminal window.
# (1Password ENV is inherited by tmux because it is exported above)
if [[ -o interactive ]] && [[ -z "$TMUX" ]]; then
    exec tmux new-session
fi
