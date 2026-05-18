#!/usr/bin/env bash
# 02_grammar_rejects_malformed.sh — parseCommand returns null for non-/gadmin
# comments and malformed commands (unknown op, missing tx, dangling colon).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

# --- Flow --------------------------------------------------------------------

main() {
    require_node

    run_node --input-type=module -e "
import { parseCommand } from '${GADMIN_GRAMMAR}';

const cases = [
  // Plain human discussion — must be ignored.
  'looks good to me',
  '',
  // Preamble present but missing required fields.
  '/gadmin\\npriority: P1',
  '/gadmin tx=abc\\npriority: P1',
  '/gadmin agent=a\\npriority: P1',
  // Unknown op kind.
  '/gadmin tx=1 agent=a\\nbogus-op: yes',
  // Flag op with stray value.
  '/gadmin tx=1 agent=a\\nclaim: nope',
  // Value op missing value.
  '/gadmin tx=1 agent=a\\npriority:',
  // Body must include at least one op.
  '/gadmin tx=1 agent=a',
];

let failed = 0;
for (const body of cases) {
  const got = parseCommand(body);
  if (got !== null) {
    console.error('expected null, got:', got, 'for input:', JSON.stringify(body));
    failed++;
  }
}
if (failed) {
  console.error('grammar negative cases:', failed, 'unexpected non-null parses');
  process.exit(1);
}
console.log('grammar rejects ' + cases.length + ' malformed cases ok');
"
}

main "$@"
