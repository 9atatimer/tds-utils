export PATH="/opt/homebrew/opt/node@16/bin:$PATH"
export PATH="/Users/stumpf/workplace/tds-utils/bin:$PATH"

# NVM magic
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion
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
eval "$(direnv hook zsh)"   # If you use Zsh

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

setopt prompt_subst  # Enable prompt substitution for RPROMPT

# Function to detect UV environment
function uv_env_prompt() {
  # Check if VIRTUAL_ENV is set
  if [[ -n "$VIRTUAL_ENV" ]]; then
    # Check if it's a UV environment (in ~/.uv/env/)
    if [[ "$VIRTUAL_ENV" == *".uv/env/"* ]]; then
      # Extract environment name
      local env_name=$(basename "$VIRTUAL_ENV")
      echo "%F{cyan}(uv:$env_name)%f"
    fi
  fi
}

# Add the UV environment indicator to your RPROMPT
# This assumes you're using Zsh with prompt substitution enabled
RPROMPT='$(uv_env_prompt)'
