
export PATH=/Users/stumpf/.sg:$PATH

# log-hoarder: terminal session log directory (XDG-conventional).
# Unset or empty to disable logging (diag logs still go to $HOME).
# Uses :- so it can be overridden (e.g. for testing).
export TDS_LOG_DIR="${TDS_LOG_DIR:-$HOME/.local/share/log-hoarder}"
. "$HOME/.cargo/env"

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
