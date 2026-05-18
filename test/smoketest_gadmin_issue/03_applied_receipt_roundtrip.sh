#!/usr/bin/env bash
# 03_applied_receipt_roundtrip.sh — /gadmin-applied receipts round-trip.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

# --- Flow --------------------------------------------------------------------

main() {
    require_node

    run_node --input-type=module -e "
import { formatApplied, parseApplied } from '${GADMIN_GRAMMAR}';

const cases = [
  { tx: 'tx1', status: 'ok' },
  { tx: 'tx2', status: 'rejected', reason: 'already-claimed-by:claude-A' },
  { tx: 'tx3', status: 'rejected', reason: 'version-conflict' },
];

let failed = 0;
for (const c of cases) {
  const body = formatApplied(c.tx, c.status, c.reason);
  const got = parseApplied(body);
  if (JSON.stringify(got) !== JSON.stringify(c)) {
    console.error('mismatch:', { wanted: c, got, wire: body });
    failed++;
  }
}
// And human comments are ignored.
if (parseApplied('just a regular comment') !== null) {
  console.error('expected null for non-receipt comment');
  failed++;
}
if (failed) {
  console.error('applied receipt round-trip failed:', failed);
  process.exit(1);
}
console.log('applied receipt round-trip ok (' + cases.length + ' cases)');
"
}

main "$@"
