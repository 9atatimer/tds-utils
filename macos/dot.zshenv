
export PATH=/Users/stumpf/.sg:$PATH

# log-hoarder: set this to your terminal log directory.
# Example: export TDS_LOG_DIR="$HOME/logs/terminal"
# Leave unset to disable logging (a warning banner will appear in each session).
export TDS_LOG_DIR=""
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
