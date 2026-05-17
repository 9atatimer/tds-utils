#!/usr/bin/env bash
# 04_aggregator_apply_logic.sh — exercise applyOpsToState in isolation.
# No network, no SQLite. Pure label/state transitions.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./config.sh
source "${SCRIPT_DIR}/config.sh"

# --- Flow --------------------------------------------------------------------

main() {
    require_node

    run_node --input-type=module -e "
import { applyOpsToState } from '${GADMIN_AGGREGATOR}';

function freshState(extra = {}) {
  return {
    title: 't', body: 'b',
    labels: new Set(extra.labels || []),
    state: extra.state || 'open',
    state_reason: extra.state_reason || null,
  };
}

let fails = 0;
function check(name, cond, detail) {
  if (!cond) {
    console.error('FAIL', name, detail || '');
    fails++;
  }
}

// priority replaces existing P*
{
  const s = freshState({ labels: ['P2', 'subsystem:gadmin'] });
  const r = applyOpsToState(s, [{ kind: 'priority', value: 'P0' }], 'a');
  check('priority replace.reject-null', r.reject === null, r);
  check('priority replace.has-P0', s.labels.has('P0'));
  check('priority replace.no-P2', !s.labels.has('P2'));
  check('priority replace.keeps-other', s.labels.has('subsystem:gadmin'));
}

// invalid priority value is rejected and does not mutate state
{
  const s = freshState({ labels: ['P2'] });
  const r = applyOpsToState(s, [{ kind: 'priority', value: 'not-a-priority' }], 'a');
  check('priority invalid.reject-truthy', typeof r.reject === 'string', r);
  check('priority invalid.no-bad-label', !s.labels.has('not-a-priority'));
  check('priority invalid.keeps-P2', s.labels.has('P2'));
}

// claim adds claimed-by:<agent>
{
  const s = freshState();
  const r = applyOpsToState(s, [{ kind: 'claim' }], 'claude-A');
  check('claim.reject-null', r.reject === null);
  check('claim.label', s.labels.has('claimed-by:claude-A'));
}

// second claim by different agent rejected
{
  const s = freshState({ labels: ['claimed-by:claude-A'] });
  const r = applyOpsToState(s, [{ kind: 'claim' }], 'claude-B');
  check('claim conflict.reject-truthy', typeof r.reject === 'string');
  check('claim conflict.no-B-label', !s.labels.has('claimed-by:claude-B'));
  check('claim conflict.keeps-A', s.labels.has('claimed-by:claude-A'));
}

// same agent re-claim is idempotent (not rejected)
{
  const s = freshState({ labels: ['claimed-by:claude-A'] });
  const r = applyOpsToState(s, [{ kind: 'claim' }], 'claude-A');
  check('claim idempotent.reject-null', r.reject === null);
  check('claim idempotent.label', s.labels.has('claimed-by:claude-A'));
}

// release removes all claim labels
{
  const s = freshState({ labels: ['claimed-by:claude-A', 'P1'] });
  const r = applyOpsToState(s, [{ kind: 'release' }], 'whoever');
  check('release.reject-null', r.reject === null);
  check('release.no-claim', ![...s.labels].some((l) => l.startsWith('claimed-by:')));
  check('release.keeps-P1', s.labels.has('P1'));
}

// close + reopen toggle state
{
  const s = freshState();
  applyOpsToState(s, [{ kind: 'close', value: 'completed' }], 'a');
  check('close.state', s.state === 'closed');
  check('close.reason', s.state_reason === 'completed');
  applyOpsToState(s, [{ kind: 'reopen' }], 'a');
  check('reopen.state', s.state === 'open');
  check('reopen.reason-null', s.state_reason === null);
}

// edit-title / edit-body mutate fields
{
  const s = freshState();
  applyOpsToState(s, [
    { kind: 'edit-title', value: 'new title' },
    { kind: 'edit-body',  value: 'new\\nbody' },
  ], 'a');
  check('edit.title', s.title === 'new title');
  check('edit.body',  s.body === 'new\\nbody');
}

// add-label / remove-label
{
  const s = freshState({ labels: ['blocked-by:#42'] });
  applyOpsToState(s, [
    { kind: 'add-label',    value: 'blocked-by:#99' },
    { kind: 'remove-label', value: 'blocked-by:#42' },
  ], 'a');
  check('addremove.added',  s.labels.has('blocked-by:#99'));
  check('addremove.removed', !s.labels.has('blocked-by:#42'));
}

if (fails) {
  console.error('aggregator apply tests:', fails, 'failure(s)');
  process.exit(1);
}
console.log('aggregator apply tests ok');
"
}

main "$@"
