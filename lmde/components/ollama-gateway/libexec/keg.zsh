# keg.zsh -- the one rule for which keg the gateway's engine runs from,
# sourced by launch-ollama.zsh, keg-watch.zsh and healthcheck.sh so the
# three can never disagree about it (Issue#709).
#
# The keg is the tree the resolved `ollama` binary lives in (<keg>/bin/ollama,
# with the real binary and its runner under <keg>/libexec): the one tree the
# sandbox profile lets the engine exec from (OLLAMA_KEG). A Homebrew upgrade
# installs a new keg and deletes the old one under a running engine, whose
# runner then fails to exec; so the launcher records the keg it granted, and
# the watcher and the healthcheck compare that record with this rule.

# ollama_keg -- the keg of the `ollama` on PATH; fails if there is none.
ollama_keg() {
    local bin
    bin="$(whence -p ollama)" || return 1
    print -r -- "${bin:A:h:h}"
}

# engine_keg_record <tree> -- the file holding the keg the running engine
# was started from.
engine_keg_record() {
    print -r -- "$1/run/engine.keg"
}

# recorded_engine_keg <tree> -- the keg the running engine was started
# from; fails if none is recorded.
recorded_engine_keg() {
    local record
    record="$(engine_keg_record "$1")"
    [[ -s "${record}" ]] || return 1
    print -r -- "$(<"${record}")"
}
