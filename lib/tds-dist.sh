#!/usr/bin/env bash
# tds-dist.sh -- shared parser and checks for .pkg / .manifest data files.
#
# Sourced by bin/tds-export, bin/tds-install, and test/smoketest_tds_dist.sh.
# Contract (docs/design/ENV-DISTRIBUTION.DESIGN.md): these files are DATA,
# never code. One KEY=VALUE per line; keys match [A-Z_]+; values are literal
# strings (one pair of surrounding double quotes stripped; no expansion, no
# substitution, no escapes); list values are whitespace-separated; a line
# whose first non-blank character is '#' is a comment; any other line shape
# is a parse error that aborts the run. Duplicate keys are a parse error.
#
# Bash 3.2 compatible (macOS /bin/bash): no associative arrays, no mapfile.

# --- Action functions ---

# tds_dist_parse <file>
# Validate <file> and print canonical KEY=VALUE lines (quotes stripped).
# Parse errors go to stderr with file:line; returns nonzero on any error.
tds_dist_parse() {
    local file="$1"
    if [ ! -f "${file}" ]; then
        echo "tds-dist: no such file: ${file}" >&2
        return 1
    fi
    awk '
        /^[[:space:]]*$/ { next }                 # blank
        /^[[:space:]]*#/ { next }                 # comment
        {
            if ($0 !~ /^[A-Z_]+=/) {
                printf "%s:%d: not KEY=VALUE: %s\n", FILENAME, FNR, $0 > "/dev/stderr"
                bad = 1; next
            }
            eq = index($0, "=")
            key = substr($0, 1, eq - 1)
            val = substr($0, eq + 1)
            if (val ~ /\t/) {
                printf "%s:%d: tab in value\n", FILENAME, FNR > "/dev/stderr"
                bad = 1; next
            }
            nq = gsub(/"/, "\"", val)             # count double quotes
            if (nq == 2 && val ~ /^".*"$/ && length(val) >= 2) {
                val = substr(val, 2, length(val) - 2)
            } else if (nq != 0) {
                printf "%s:%d: unbalanced or interior quotes\n", FILENAME, FNR > "/dev/stderr"
                bad = 1; next
            }
            if (key in seen) {
                printf "%s:%d: duplicate key %s\n", FILENAME, FNR, key > "/dev/stderr"
                bad = 1; next
            }
            seen[key] = 1
            printf "%s=%s\n", key, val
        }
        END { exit bad ? 1 : 0 }
    ' "${file}"
}

# tds_dist_get <file> <key>
# Print the value of <key> in <file>. Returns 1 if the key is absent
# (an empty value counts as present). Parse errors propagate as failure.
tds_dist_get() {
    local file="$1" key="$2" parsed
    parsed="$(tds_dist_parse "${file}")" || return 1
    printf '%s\n' "${parsed}" | awk -v k="${key}" '
        index($0, k "=") == 1 { print substr($0, length(k) + 2); found = 1 }
        END { exit found ? 0 : 1 }
    '
}

# tds_dist_require <file> <key>
# Like tds_dist_get but a missing key is a hard error naming the file.
tds_dist_require() {
    local file="$1" key="$2" val
    if ! val="$(tds_dist_get "${file}" "${key}")"; then
        echo "tds-dist: ${file}: required key ${key} missing" >&2
        return 1
    fi
    printf '%s\n' "${val}"
}

# tds_dist_path_claimed <path> <pkgfile>
# Return 0 if <path> equals, or lies under, one of <pkgfile>'s PATHS entries.
tds_dist_path_claimed() {
    local path="$1" pkg="$2" p
    for p in $(tds_dist_get "${pkg}" PATHS 2>/dev/null || true); do
        p="${p%/}"
        case "${path}" in
            "${p}" | "${p}"/*) return 0 ;;
        esac
    done
    return 1
}

# --- Flow functions ---

# tds_dist_check_ownership <pkgfile> [...]
# Assert exclusive path ownership across packages: a repo path may be
# claimed by at most one package's PATHS, and no claim may nest under
# another package's claim (that would make "path belonging to a denied
# package" ambiguous). Prints each conflict; returns nonzero on any.
tds_dist_check_ownership() {
    local pkg name p claims="" conflicts=0
    for pkg in "$@"; do
        name="$(tds_dist_require "${pkg}" NAME)" || return 1
        for p in $(tds_dist_get "${pkg}" PATHS 2>/dev/null || true); do
            p="${p%/}"
            claims="${claims}${p} ${name}
"
        done
    done
    # Pairwise check: exact duplicates and prefix-nesting across owners.
    # (Sort-adjacency misses nesting when other names sort between a
    # directory and its children; the registry is small, O(n^2) is fine.)
    conflicts=$(printf '%s' "${claims}" | awk '
        { paths[NR] = $1; owners[NR] = $2 }
        END {
            for (i = 1; i <= NR; i++) {
                for (j = i + 1; j <= NR; j++) {
                    if (owners[i] == owners[j]) continue
                    if (paths[i] == paths[j]) {
                        printf "duplicate claim: %s (%s, %s)\n", \
                            paths[i], owners[i], owners[j] > "/dev/stderr"
                        bad++
                    } else if (index(paths[j], paths[i] "/") == 1) {
                        printf "nested claim: %s (%s) under %s (%s)\n", \
                            paths[j], owners[j], paths[i], owners[i] > "/dev/stderr"
                        bad++
                    } else if (index(paths[i], paths[j] "/") == 1) {
                        printf "nested claim: %s (%s) under %s (%s)\n", \
                            paths[i], owners[i], paths[j], owners[j] > "/dev/stderr"
                        bad++
                    }
                }
            }
            print bad + 0
        }
    ')
    [ "${conflicts}" -eq 0 ]
}
