#!/usr/bin/env bash
# statusline.sh -- Claude Code status line.
#
# Prints the git repo root of the session's cwd (relative to $HOME, so repos
# under ~/workplace render as "workplace/..."), colored by working-tree state:
#   green   = clean       (no changes, no untracked files)
#   yellow  = dirty [N]    (tracked changes only; N = offending file count)
#   red     = untracked [N] (files outside git's control present; N = offending count)
# The [N] suffix is the total number of files git reports as not-clean
# (modified + staged + deleted + untracked). A non-git cwd prints the
# directory's basename, dimmed.
#
# Claude Code feeds session context as JSON on stdin; we read the cwd from it
# (falling back to $PWD if the field is absent or jq is unavailable).

input=$(cat)

dir=$(printf '%s' "$input" | jq -r '.cwd // .workspace.current_dir // empty' 2>/dev/null)
[ -z "$dir" ] && dir="$PWD"

esc=$'\033'
green="${esc}[32m"; yellow="${esc}[33m"; red="${esc}[31m"; dim="${esc}[2m"; reset="${esc}[0m"

# Not a git repo -> show the dir name, dimmed, and stop.
root=$(git -C "$dir" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$root" ]; then
  printf '%s%s (not a git repo)%s' "$dim" "$(basename "$dir")" "$reset"
  exit 0
fi

# --porcelain lists tracked changes AND untracked (??) but NOT ignored files,
# so ignored artifacts correctly do NOT count as "outside git's control".
changes=$(git -C "$dir" status --porcelain 2>/dev/null)
count=$(printf '%s\n' "$changes" | grep -c .)     # offending file count (0 when clean)

if [ -z "$changes" ]; then
  color="$green"; suffix=""                        # clean
elif printf '%s\n' "$changes" | grep -q '^??'; then
  color="$red";    suffix=" [$count]"              # untracked present (takes precedence)
else
  color="$yellow"; suffix=" [$count]"              # tracked changes only
fi

# Path relative to $HOME: ~/workplace/naatm/template-tools -> workplace/naatm/template-tools.
rel="${root#"$HOME"/}"

printf '%s%s%s%s' "$color" "$rel" "$suffix" "$reset"
