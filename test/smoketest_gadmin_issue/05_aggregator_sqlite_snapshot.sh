#!/usr/bin/env bash
# 05_aggregator_sqlite_snapshot.sh — verify SQLite schema + upsert + tx_log.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

require_node

DB_PATH="${SMOKE_TMP}/snap-$$.db"

run_node --input-type=module --no-warnings -e "
import { openDb, upsertIssue, logTx } from '${GADMIN_AGGREGATOR}';

const db = openDb('${DB_PATH}');

const fakeIssue = {
  number: 42,
  state: 'open',
  title: 'hello',
  body: 'body text',
  labels: [{ name: 'P1' }, { name: 'subsystem:gadmin' }],
  assignees: [{ login: 'todd' }],
  updated_at: '2026-05-17T00:00:00Z',
};

upsertIssue(db, fakeIssue, 'tx-abc');
logTx(db, { tx: 'tx-abc', issue: 42, agent: 'claude-A', commentId: 100, status: 'ok' });

const row = db.prepare('SELECT number, state, title, labels, last_applied_tx FROM issues WHERE number = 42').get();
if (!row) { console.error('issue row missing'); process.exit(1); }
if (row.title !== 'hello') { console.error('title mismatch:', row.title); process.exit(1); }
if (row.last_applied_tx !== 'tx-abc') { console.error('tx mismatch:', row.last_applied_tx); process.exit(1); }
const labels = JSON.parse(row.labels);
if (!labels.includes('P1') || !labels.includes('subsystem:gadmin')) {
  console.error('labels mismatch:', labels);
  process.exit(1);
}

const tx = db.prepare('SELECT status, agent FROM tx_log WHERE tx = ?').get('tx-abc');
if (!tx || tx.status !== 'ok' || tx.agent !== 'claude-A') {
  console.error('tx_log row mismatch:', tx);
  process.exit(1);
}

// Update: priority change should bump last_applied_tx and labels
const fakeIssue2 = { ...fakeIssue, labels: [{ name: 'P0' }, { name: 'subsystem:gadmin' }], title: 'renamed' };
upsertIssue(db, fakeIssue2, 'tx-def');
const row2 = db.prepare('SELECT title, labels, last_applied_tx FROM issues WHERE number = 42').get();
if (row2.title !== 'renamed') { console.error('title update failed:', row2); process.exit(1); }
if (row2.last_applied_tx !== 'tx-def') { console.error('tx update failed:', row2); process.exit(1); }
if (!JSON.parse(row2.labels).includes('P0')) { console.error('label update failed:', row2.labels); process.exit(1); }

console.log('aggregator sqlite snapshot ok');
"
