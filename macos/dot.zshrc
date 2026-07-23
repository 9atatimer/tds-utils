export PATH="/Users/stumpf/workplace/tds-utils/bin:$PATH"

# Go-installed tools (go install puts binaries in ~/go/bin)
export PATH="$HOME/go/bin:$PATH"

# NVM magic
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"
autoload -Uz compinit && compinit
PROG=sg source /Users/stumpf/.sourcegraph/sg.zsh_autocomplete

# pyenv magic
if command -v pyenv 1>/dev/null 2>&1; then
    export PYENV_ROOT="$HOME/.pyenv"
    eval "$(pyenv init -)"
    if [ -d "${PYENV_ROOT}/plugins/pyenv-virtualenv" ]; then
        eval "$(pyenv virtualenv-init -)"
    fi
fi

# direnv magic
eval "$(direnv hook zsh)"

# 1Password Integration
# Setting the socket to the verified Website-installation path
export SSH_AUTH_SOCK=~/Library/Group\ Containers/2BUA8C4S2C.com.1password/t/agent.sock

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

. "$HOME/.local/bin/env"

# Added by Windsurf
export PATH="/Users/stumpf/.codeium/windsurf/bin:$PATH"

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

# Path updates
export PATH="/Users/stumpf/.antigravity/antigravity/bin:$PATH"

# Normalize PATH: collapse duplicate entries, and put ~/.local/bin (the
# uv-installed tools — clai, designomatic, crmagic) ahead of tds-utils/bin
# so the uv-installed tools take precedence. Must stay after every PATH
# mutation above.
typeset -U path
path=("$HOME/.local/bin" $path)

# log-hoarder: semantic search widget (ctrl-x s)
if [[ -f ~/workplace/tds-utils/macos/dot.zsh_log_search ]]; then
    source ~/workplace/tds-utils/macos/dot.zsh_log_search
fi

# log-hoarder: auto-launch tmux for each new terminal window.
# (1Password ENV is inherited by tmux because it is exported above)
if [[ -o interactive ]] && [[ -z "$TMUX" ]]; then
    exec tmux new-session
fi
