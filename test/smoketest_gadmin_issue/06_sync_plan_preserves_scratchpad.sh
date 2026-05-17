#!/usr/bin/env bash
# 06_sync_plan_preserves_scratchpad.sh — applyAutogen replaces only the
# block between sentinels; scratchpad before/after is byte-identical.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

# --- Flow --------------------------------------------------------------------

main() {
    require_node

    local PLAN_PATH="${SMOKE_TMP}/TODO_PLAN.md"
    local PLAN_SYNC_MODULE="${GADMIN_ADMIN_DIR}/issue-plan-sync.mjs"

    cat > "${PLAN_PATH}" <<'EOF'
# TODO_PLAN.md

<!-- gadmin:autogen:start -->
old autogen content that should be replaced
<!-- gadmin:autogen:end -->

## Scratchpad (preserved)

- handwritten note 1
- handwritten note 2

```code
preserved block
```

end of file.
EOF

run_node --input-type=module -e "
import { readFileSync, writeFileSync } from 'node:fs';
import { buildAutogenContent, applyAutogen, syncPlanFile } from '${PLAN_SYNC_MODULE}';

const path = '${PLAN_PATH}';
const before = readFileSync(path, 'utf-8');
const issues = [
  { number: 12, title: 'fix the thing', state: 'open',
    labels: [{ name: 'P1' }, { name: 'subsystem:gadmin' }] },
  { number: 13, title: 'less urgent thing', state: 'open',
    labels: [{ name: 'P2' }, { name: 'subsystem:gadmin' }, { name: 'blocked-by:#12' }] },
  { number: 14, title: 'terminal cleanup', state: 'open',
    labels: [{ name: 'P0' }, { name: 'subsystem:terminal' }, { name: 'claimed-by:claude-A' }] },
];

syncPlanFile(path, issues, { generatedAt: '2026-05-17T00:00:00Z' });
const after = readFileSync(path, 'utf-8');

// Sentinels still present, exactly once each
const startCount = (after.match(/<!-- gadmin:autogen:start -->/g) || []).length;
const endCount   = (after.match(/<!-- gadmin:autogen:end -->/g) || []).length;
if (startCount !== 1 || endCount !== 1) {
  console.error('sentinels duplicated or missing:', { startCount, endCount });
  process.exit(1);
}

// Old autogen content must be gone
if (after.includes('old autogen content that should be replaced')) {
  console.error('old autogen content not replaced');
  process.exit(1);
}

// Scratchpad lines must be byte-identical
for (const line of ['## Scratchpad (preserved)', 'handwritten note 1', 'handwritten note 2', 'preserved block', 'end of file.']) {
  if (!after.includes(line)) {
    console.error('scratchpad line missing:', line);
    process.exit(1);
  }
}

// Autogen must contain the issues, priority-sorted
if (!after.includes('#12 P1 fix the thing')) {
  console.error('issue 12 line missing'); process.exit(1);
}
if (!after.includes('#13 P2 less urgent thing')) {
  console.error('issue 13 line missing'); process.exit(1);
}
if (!after.includes('blocked-by: #12')) {
  console.error('blocked-by annotation missing'); process.exit(1);
}
if (!after.includes('claimed-by: claude-A')) {
  console.error('claimed-by annotation missing'); process.exit(1);
}

// Subsystems present
if (!after.includes('### subsystem: gadmin')) {
  console.error('gadmin subsystem heading missing'); process.exit(1);
}
if (!after.includes('### subsystem: terminal')) {
  console.error('terminal subsystem heading missing'); process.exit(1);
}

// Inserting into a doc WITHOUT sentinels must insert them
const docNoSentinels = '# Heading\\n\\nsome existing scratchpad text.\\n';
const inserted = applyAutogen(docNoSentinels, 'BLOCK');
if (!inserted.includes('<!-- gadmin:autogen:start -->') || !inserted.includes('<!-- gadmin:autogen:end -->')) {
  console.error('failed to insert sentinels into doc that lacked them');
  process.exit(1);
}
if (!inserted.includes('some existing scratchpad text')) {
  console.error('scratchpad lost when inserting sentinels');
  process.exit(1);
}

console.log('sync-plan preserves scratchpad ok');
"
}

main "$@"
