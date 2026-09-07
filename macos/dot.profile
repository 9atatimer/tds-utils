# The following lines were added by Docker Desktop to add commands to your PATH.
[[ -d "$HOME/.docker/bin" ]] && export PATH="$PATH:$HOME/.docker/bin"
# End of Docker Desktop section.

export PATH=/Users/stumpf/.sg:$PATH
. "$HOME/.cargo/env"

# per brew google-cloud-sdk instructions:
source "$(brew --prefix)/share/google-cloud-sdk/path.zsh.inc"
source "$(brew --prefix)/share/google-cloud-sdk/completion.zsh.inc"

. "$HOME/.local/bin/env"
