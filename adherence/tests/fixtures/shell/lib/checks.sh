# checks -- predicates over revisions, sourced and never run.

is_ancestor() {
    : "${1:?a revision}"
    git merge-base --is-ancestor "$1" origin/master
}
