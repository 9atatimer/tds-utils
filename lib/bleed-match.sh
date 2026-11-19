#!/usr/bin/env bash
# bleed-match.sh -- the denylist matcher shared by bin/bleed-guard and
# bin/tds-public.
#
# Sourced, never run. One matcher, so the commit-time guard and the publish
# step cannot disagree about what a hit is. A caller sets LC_ALL=C before
# using it (byte semantics for awk; see bin/bleed-guard).
#
# resolve_denylist        print the denylist path:
#                         $TDS_BLEED_DENYLIST -> git config bleedguard.denylist
#                         (--type=path) -> ~/workplace/tds-internal/ops/bleed-denylist
# match_records <list>    read "path<TAB>line<TAB>text" records on stdin; print
#                         one report line per (record, entry) hit, naming the
#                         entry by its line in the denylist, never its text
# match_records_counted <list> <countfile>  match_records, plus the number of
#                         path-name records and records the matcher read
# redact_lines <list>     read lines on stdin; print them with every denylist
#                         entry, in any case, replaced by [redacted]
#
# Portability: bash 3.2 / BSD-safe.

DEFAULT_DENYLIST="${HOME:-}/workplace/tds-internal/ops/bleed-denylist"

# The awk shared by match_records and redact_lines: load the entries of the
# denylist named by -v list= (blank lines and # lines skipped, whitespace
# trimmed, entries lowercased, each tagged with its line number) and define
# redact(s), s with every entry, in any case, replaced by [redacted].
BLEED_AWK_COMMON='
    BEGIN {
        n = 0
        while ((getline raw < list) > 0) {
            lineno++
            sub(/^[ \t]+/, "", raw); sub(/[ \t\r]+$/, "", raw)
            if (raw == "" || substr(raw, 1, 1) == "#") continue
            n++; entry[n] = tolower(raw); where[n] = lineno
        }
        close(list)
    }
    function redact(s,    i, low, at, out) {
        for (i = 1; i <= n; i++) {
            out = ""; low = tolower(s)
            while ((at = index(low, entry[i])) > 0) {
                out = out substr(s, 1, at - 1) "[redacted]"
                s = substr(s, at + length(entry[i])); low = substr(low, at + length(entry[i]))
            }
            s = out s
        }
        return s
    }
'

resolve_denylist() {
    local path="${TDS_BLEED_DENYLIST:-}"
    [ -n "${path}" ] || path="$(git config --type=path --get bleedguard.denylist 2>/dev/null || true)"
    [ -n "${path}" ] || path="${DEFAULT_DENYLIST}"
    printf '%s\n' "${path}"
}

# _match_run <denylist> <countfile> -- the matcher. With a count file it also
# writes "<path-name records> <records>" there when the input ends.
_match_run() {
    awk -v list="$1" -v countfile="$2" "${BLEED_AWK_COMMON}"'
        {
            total++
            tab1 = index($0, "\t"); path = substr($0, 1, tab1 - 1); rest = substr($0, tab1 + 1)
            tab2 = index(rest, "\t"); line = substr(rest, 1, tab2 - 1); text = tolower(substr(rest, tab2 + 1))
            if (line == 0) names++
            shown = redact(path)
            for (i = 1; i <= n; i++) {
                if (index(text, entry[i]) == 0) continue
                if (line == 0) printf "%s: file name matches denylist entry at line %d\n", shown, where[i]
                else           printf "%s:%s: matches denylist entry at line %d\n", shown, line, where[i]
            }
        }
        END { if (countfile != "") printf "%d %d\n", names, total > countfile }
    '
}

# match_records <denylist> -- read records on stdin; print one report line per
# (record, entry) hit, naming the entry by its line in the denylist file.
match_records() { _match_run "$1" ""; }

# match_records_counted <denylist> <countfile> -- match_records, and write
# "<path-name records> <records>" to <countfile>, so a caller can prove the
# matcher saw everything it fed.
match_records_counted() { _match_run "$1" "$2"; }

# redact_lines <denylist> -- read lines on stdin; print each with every entry
# replaced by [redacted].
redact_lines() {
    awk -v list="$1" "${BLEED_AWK_COMMON}"'{ print redact($0) }'
}
