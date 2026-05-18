#!/usr/bin/env bash
# 01_grammar_roundtrip.sh — parse(format(cmd)) === cmd for every op shape.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

# --- Flow --------------------------------------------------------------------

main() {
    require_node

    run_node --input-type=module -e "
import { parseCommand, formatCommand, newTxId } from '${GADMIN_GRAMMAR}';

const samples = [
  { tx: newTxId(), agent: 'claude-A',
    ops: [{ kind: 'priority', value: 'P0' }] },
  { tx: newTxId(), agent: 'todd-laptop',
    ops: [
      { kind: 'add-label', value: 'subsystem:gadmin' },
      { kind: 'remove-label', value: 'P2' },
      { kind: 'priority', value: 'P1' },
    ] },
  { tx: newTxId(), agent: 'a', ops: [{ kind: 'claim' }] },
  { tx: newTxId(), agent: 'a', ops: [{ kind: 'release' }] },
  { tx: newTxId(), agent: 'a', ops: [{ kind: 'close', value: 'not-planned' }] },
  { tx: newTxId(), agent: 'a', ops: [{ kind: 'reopen' }] },
  { tx: newTxId(), agent: 'a', assumeVersion: 'prev-tx',
    ops: [{ kind: 'edit-title', value: 'Renamed: foo bar baz' }] },
  { tx: newTxId(), agent: 'a',
    ops: [{ kind: 'edit-body', value: 'first line\\nsecond line\\n\\nfourth' }] },
];

let failures = 0;
for (const s of samples) {
  const body = formatCommand(s);
  const back = parseCommand(body);
  if (JSON.stringify(back) !== JSON.stringify(s)) {
    console.error('mismatch:', { wanted: s, got: back, wire: body });
    failures++;
  }
}
if (failures) {
  console.error('grammar round-trip failed:', failures, 'cases');
  process.exit(1);
}
console.log('grammar round-trip ok (' + samples.length + ' cases)');
"
}

main "$@"
