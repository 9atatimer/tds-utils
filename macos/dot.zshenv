export PATH=/Users/stumpf/.sg:$PATH

# log-hoarder: terminal session log directory (XDG-conventional).
# Unset or empty to disable logging (diag logs still go to $HOME).
# Uses :- so it can be overridden (e.g. for testing).
export TDS_LOG_DIR="${TDS_LOG_DIR:-$HOME/.local/share/log-hoarder}"
. "$HOME/.cargo/env"

# ast-mcp: dynamically resolve AST_MCP_BIN path based on environment if unset
if [ -z "${AST_MCP_BIN:-}" ]; then
  if [ "${CLAUDE_CODE_REMOTE:-}" = "true" ]; then
    export AST_MCP_BIN="${CLAUDE_PROJECT_DIR:-$PWD}/.ast-mcp/node_modules/.bin/ast-mcp"
  else
    export AST_MCP_BIN="${HOME}/.local/bin/ast-mcp"
  fi
fi

# --- MIGRATED ENVIRONMENT SETUP (LMDE) ---
# Ensure background agents and GUI shells inherit the full interactive environment.

# Homebrew
eval "$(/opt/homebrew/bin/brew shellenv)"

# Core Tools
export PATH="/Users/stumpf/workplace/tds-utils/bin:$PATH"

# Go-installed tools (go install puts binaries in ~/go/bin)
export PATH="$HOME/go/bin:$PATH"

# NVM magic
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

# pyenv magic
if command -v pyenv 1>/dev/null 2>&1; then
    export PYENV_ROOT="$HOME/.pyenv"
    eval "$(pyenv init -)"
    if [ -d "${PYENV_ROOT}/plugins/pyenv-virtualenv" ]; then
        eval "$(pyenv virtualenv-init -)"
    fi
fi

# 1Password Integration
export SSH_AUTH_SOCK=~/Library/Group\ Containers/2BUA8C4S2C.com.1password/t/agent.sock

# Local bin and Windsurf
. "$HOME/.local/bin/env"
export PATH="/Users/stumpf/.codeium/windsurf/bin:$PATH"

# Path updates
export PATH="/Users/stumpf/.antigravity/antigravity/bin:$PATH"

# Normalize PATH: collapse duplicate entries, and put ~/.local/bin (the
# uv-installed tools — clai, designomatic, crmagic) ahead of tds-utils/bin
# so the uv-installed tools take precedence. Must stay after every PATH
# mutation above.
typeset -U path
path=("$HOME/.local/bin" $path)

# --- END MIGRATED ENVIRONMENT SETUP ---

# History settings need to be in .zshenv to take precedence
HISTSIZE=999999999
SAVEHIST=999999999
HISTFILE=~/.zsh_history
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
