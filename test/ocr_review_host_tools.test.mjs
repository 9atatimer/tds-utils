// test/ocr_review_host_tools.test.mjs -- OCR on Demand, the review job's
// host-tools check (docs/design/OCR-ON-DEMAND.DESIGN.md: State Machine,
// FAILED from AUTHORIZED; Key Decisions, runner tools row; tds-utils#446).
// Which of git, unzip, gpg and op the runner has decides whether the
// 1Password CLI is installed and which missing tool fails the run.
// Pure: values in, values out. No network.
// Run: node --test test/ocr_review_host_tools.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { HOST_TOOLS, checkHostTools, describeHostTools } from '../lib/ocr-review/host-tools.mjs';

const has = (...tools) => Object.fromEntries(HOST_TOOLS.map((tool) => [tool, tools.includes(tool)]));

test('the check covers exactly git, unzip, gpg and op', () => {
  assert.deepEqual([...HOST_TOOLS].sort(), ['git', 'gpg', 'op', 'unzip']);
});

test('the pool image (op baked in) passes and installs nothing', () => {
  // Given a runner with op on PATH, When checked, Then op is used as is.
  assert.deepEqual(checkHostTools(has('git', 'unzip', 'gpg', 'op')), { ok: true, installOp: false, missing: [] });
});

test('with op on the runner, gpg and unzip are not needed', () => {
  assert.deepEqual(checkHostTools(has('git', 'op')), { ok: true, installOp: false, missing: [] });
});

test('a GitHub-hosted runner (gpg and unzip, no op) passes and installs op', () => {
  assert.deepEqual(checkHostTools(has('git', 'unzip', 'gpg')), { ok: true, installOp: true, missing: [] });
});

test('no op and no gpg fails runner-tool-missing naming gpg (the #446 runner)', () => {
  assert.deepEqual(checkHostTools(has('git', 'unzip')), {
    ok: false,
    installOp: true,
    missing: ['gpg'],
    cause: 'runner-tool-missing',
    detail: 'gpg',
  });
});

test('every missing tool the chosen path needs is named, in check order', () => {
  assert.equal(checkHostTools(has('git')).detail, 'unzip, gpg');
  assert.equal(checkHostTools(has()).detail, 'git, unzip, gpg');
});

test('git is needed even when op is on the runner', () => {
  assert.deepEqual(checkHostTools(has('unzip', 'gpg', 'op')), {
    ok: false,
    installOp: false,
    missing: ['git'],
    cause: 'runner-tool-missing',
    detail: 'git',
  });
});

test('over every combination: op decides the install, git is always needed, gpg and unzip only for the install', () => {
  for (let mask = 0; mask < 2 ** HOST_TOOLS.length; mask += 1) {
    const present = Object.fromEntries(HOST_TOOLS.map((tool, i) => [tool, Boolean(mask & (1 << i))]));
    const check = checkHostTools(present);
    const label = JSON.stringify(present);
    assert.equal(check.installOp, !present.op, label);
    assert.equal(check.missing.includes('git'), !present.git, label);
    for (const tool of ['gpg', 'unzip']) assert.equal(check.missing.includes(tool), !present.op && !present[tool], `${tool} ${label}`);
    assert.ok(!check.missing.includes('op'), `op is installed, never missing: ${label}`);
    assert.equal(check.ok, check.missing.length === 0, label);
    if (!check.ok) {
      assert.equal(check.cause, 'runner-tool-missing', label);
      assert.equal(check.detail, check.missing.join(', '), label);
    }
  }
});

test('the report line says, for each tool, whether the runner has it', () => {
  assert.equal(describeHostTools(has('git', 'unzip', 'op')), 'git present, unzip present, gpg missing, op present');
});
