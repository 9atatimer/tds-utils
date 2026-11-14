#!/usr/bin/env bash
# smoketest_codex_session_cost.sh -- bin/codex-session-cost reports what one
# Codex session cost from its rollout log.
#
# Hermetic: builds small rollout logs with known sizes in a temp dir, and
# points CODEX_HOME there; real session logs are never read.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOOL="$(dirname "${SCRIPT_DIR}")/bin/codex-session-cost"
WORK=""
TESTS_RUN=0
TESTS_FAILED=0

# --- Action functions ---

cleanup() { [[ -n "${WORK}" && -d "${WORK}" ]] && rm -rf "${WORK}"; return 0; }

fail() {
    echo "FAIL: $1"
    TESTS_FAILED=$((TESTS_FAILED + 1))
}

# write_rollout <path> <cwd> <kind> -- a rollout log with a 1000-char AGENTS
# block, a 500-char skills list, three tool calls (design read twice,
# markdown once, one call that reads no skill), and two token counts of which
# the last is the session total. kind "judge" adds the auto-review prompt.
write_rollout() {
    mkdir -p "$(dirname "$1")"
    python3 -I - "$1" "$2" "$3" <<'PY'
import json, sys
path, cwd, kind = sys.argv[1:4]

def item(payload):
    return {"type": "response_item", "payload": payload}

def msg(role, text):
    return item({"type": "message", "role": role,
                 "content": [{"type": "input_text", "text": text}]})

def call(call_id, cmd):
    return item({"type": "custom_tool_call", "call_id": call_id, "name": "exec",
                 "input": json.dumps({"cmd": cmd})})

def out(call_id, n):
    return item({"type": "custom_tool_call_output", "call_id": call_id,
                 "output": "o" * n})

def tokens(inp, cached, outp):
    return {"type": "event_msg", "payload": {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": inp, "cached_input_tokens": cached,
                              "output_tokens": outp}}}}

head = "# AGENTS.md instructions for " + cwd + "\n"
rows = [{"type": "session_meta", "payload": {"id": "s1", "cwd": cwd}}]
if kind == "judge":
    rows.append(msg("developer", "You are judging one planned coding-agent action."))
rows += [
    msg("developer", "<skills_instructions>" + "y" * 479),
    msg("user", head + "x" * (1000 - len(head))),
    call("c1", "sed -n '1,$p' .codex/skills/design/SKILL.md"),
    out("c1", 2000),
    tokens(10, 0, 1),
    call("c2", "wc -l .codex/skills/design/SKILL.md && sed -n '1,$p' "
               "/h/.codex/skills/.system/markdown/SKILL.md"),
    out("c2", 3000),
    call("c3", "ls"),
    out("c3", 100),
    tokens(1000, 900, 50),
]
with open(path, "w") as fh:
    for r in rows:
        fh.write(json.dumps(r) + "\n")
PY
}

# --- Flow functions ---

# Given a main session's rollout log, When codex-session-cost reads it (the
# production invocation: the script by path, the log by path), Then it
# reports the kind, the AGENTS block and skills list sizes, the tool calls and
# their output, each skill's call count with repeats marked, and the token
# totals from the last count.
test_reports_a_main_session() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local log="${WORK}/main.jsonl" out want
    write_rollout "${log}" /w/repo main
    out=$("${TOOL}" "${log}") || fail "main session: non-zero exit"
    for want in \
        'kind: main' \
        'cwd: /w/repo' \
        'agents block: 1000 chars' \
        'skills list: 500 chars' \
        'tool calls: 3, output 5100 chars' \
        'skill calls: 2 calls name a SKILL.md, output 5000 chars' \
        'skill design: 2 calls (repeat)' \
        'skill markdown: 1 call' \
        'tokens: input 1000, cached 900, uncached 100, output 50'; do
        grep -qxF "${want}" <<<"${out}" || fail "main session: missing '${want}' in: ${out}"
    done
}

# Given an auto-review judge session's log, When it is read, Then the kind
# is auto-review.
test_reports_a_judge_session() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local log="${WORK}/judge.jsonl" out
    write_rollout "${log}" /w/repo judge
    out=$("${TOOL}" "${log}") || fail "judge session: non-zero exit"
    grep -qxF 'kind: auto-review' <<<"${out}" || fail "judge session: ${out}"
}

# Given two logs under CODEX_HOME, When --latest runs with and without
# --cwd, Then it reads the newest log, or the newest log for that cwd.
test_latest_picks_newest_log_for_cwd() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local home="${WORK}/codex" out
    write_rollout "${home}/sessions/2026/11/13/rollout-a.jsonl" /w/repo main
    write_rollout "${home}/sessions/2026/11/14/rollout-b.jsonl" /w/other main
    touch -t 202611130900 "${home}/sessions/2026/11/13/rollout-a.jsonl"
    touch -t 202611140900 "${home}/sessions/2026/11/14/rollout-b.jsonl"
    out=$(CODEX_HOME="${home}" "${TOOL}" --latest) || fail "--latest: non-zero exit"
    grep -qxF 'cwd: /w/other' <<<"${out}" || fail "--latest: ${out}"
    out=$(CODEX_HOME="${home}" "${TOOL}" --latest --cwd /w/repo) || fail "--latest --cwd: non-zero exit"
    grep -qxF 'cwd: /w/repo' <<<"${out}" || fail "--latest --cwd: ${out}"
}

# Given a path that does not exist, When codex-session-cost runs, Then it
# exits 2 and names the path.
test_missing_log_is_usage_error() {
    TESTS_RUN=$((TESTS_RUN + 1))
    local out rc=0
    out=$("${TOOL}" "${WORK}/nope.jsonl" 2>&1) || rc=$?
    [[ "${rc}" -eq 2 ]] || fail "missing log: exit ${rc}, want 2"
    grep -qF 'nope.jsonl' <<<"${out}" || fail "missing log: path not named: ${out}"
}

# --- Main ---

main() {
    trap cleanup EXIT INT TERM HUP
    WORK=$(mktemp -d)
    test_reports_a_main_session
    test_reports_a_judge_session
    test_latest_picks_newest_log_for_cwd
    test_missing_log_is_usage_error
    if [[ "${TESTS_FAILED}" -gt 0 ]]; then
        echo "${TESTS_FAILED} failed check(s) in ${TESTS_RUN} tests"
        exit 1
    fi
    echo "PASS: ${TESTS_RUN} tests"
}

main "$@"
