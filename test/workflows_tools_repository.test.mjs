// test/workflows_tools_repository.test.mjs -- where the three published
// reusable workflows fetch their tool code from (tds-utils Issue#829).
//
// An outside caller gets the tools from the public 9atatimer/workflows
// (the default); this repository's own callers name this repository, so a
// change to the engine or a checker is judged by that change before it lands.
// Read as text, what a reviewer would check by eye, made mechanical. No
// network.
// Run: node --test test/workflows_tools_repository.test.mjs

import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(ROOT, path), 'utf8');
const code = (text) =>
  text
    .split('\n')
    .filter((line) => !/^\s*#/.test(line))
    .join('\n');

const PUBLISHED = ['ocr-review', 'review-settled', 'adherence'];
const WORKFLOW = Object.fromEntries(PUBLISHED.map((n) => [n, read(`.github/workflows/${n}.yml`)]));
const PUBLIC_REPO = '9atatimer/workflows';
const PUBLIC_BRANCH = 'main';
// How many checkouts of the tools each workflow makes.
const TOOLS_CHECKOUTS = { 'ocr-review': 3, 'review-settled': 1, adherence: 1 };

/** The lines of one workflow_call input, from its key to the next input. */
function inputBlock(text, name) {
  const all = code(text).split('\n');
  const start = all.findIndex((l) => l === `      ${name}:`);
  if (start < 0) return null;
  const out = [];
  for (const l of all.slice(start + 1)) {
    if (/^ {0,6}\S/.test(l)) break;
    out.push(l);
  }
  return out.join('\n');
}

for (const name of PUBLISHED) {
  test(`${name}: declares tools_repository, a string defaulting to ${PUBLIC_REPO}`, () => {
    const input = inputBlock(WORKFLOW[name], 'tools_repository');
    assert.ok(input, 'declares the input');
    assert.match(input, /type: string/);
    assert.match(input, /required: false/);
    assert.match(input, new RegExp(`default: ${PUBLIC_REPO}$`, 'm'));
  });

  test(`${name}: every repository it checks out names the input, none names tds-utils`, () => {
    const body = code(WORKFLOW[name]);
    const repos = body.match(/^\s+repository:.*$/gm) ?? [];
    assert.equal(repos.length, TOOLS_CHECKOUTS[name], 'one repository: per tools checkout');
    for (const line of repos) assert.equal(line.trim(), 'repository: ${{ inputs.tools_repository }}');
    assert.doesNotMatch(body, /9atatimer\/tds-utils/);
  });

  test(`${name}: a tools_ref default is a branch ${PUBLIC_REPO} has`, () => {
    const input = inputBlock(WORKFLOW[name], 'tools_ref');
    assert.ok(input, 'declares tools_ref');
    const dflt = input.match(/default: (\S+)/);
    if (dflt) assert.equal(dflt[1], PUBLIC_BRANCH);
    assert.doesNotMatch(input, /master/);
  });

  test(`${name}: its header shows a caller outside this repository the public repository, never tds-utils`, () => {
    const comments = WORKFLOW[name]
      .split('\n')
      .filter((l) => /^\s*#/.test(l))
      .join('\n');
    assert.doesNotMatch(comments, /9atatimer\/tds-utils\/\.github/);
    assert.doesNotMatch(comments, /@master/);
  });
}

test('review-settled and adherence headers name the public reusable workflow a caller uses', () => {
  for (const name of ['review-settled', 'adherence']) {
    assert.match(WORKFLOW[name], new RegExp(`uses: ${PUBLIC_REPO}/\\.github/workflows/${name}\\.yml@`), name);
  }
});

test('review-settled: the one tools_ref default is no longer master', () => {
  assert.match(inputBlock(WORKFLOW['review-settled'], 'tools_ref'), /default: main$/m);
});

// --- This repository's own callers keep the tools in this repository ------------

test('review-settled-caller: fetches the checker from this repository, at the PR head as before', () => {
  const caller = code(read('.github/workflows/review-settled-caller.yml'));
  assert.match(caller, /uses: \.\/\.github\/workflows\/review-settled\.yml/);
  assert.match(caller, /^\s+tools_repository: \$\{\{ github\.repository \}\}$/m);
  assert.match(caller, /tools_ref: \$\{\{ github\.event\.pull_request\.head\.sha \|\| 'master' \}\}/);
});

test('dist-ci adherence-judge: fetches the engine from this repository, at the PR head as before', () => {
  const dist = read('.github/workflows/dist-ci.yml');
  const start = dist.indexOf('\n  adherence-judge:');
  assert.ok(start > 0, 'has the adherence-judge job');
  const rest = dist.slice(start + 1);
  const next = rest.slice(1).search(/^ {2}[a-z][a-z-]*:/m);
  const job = rest.slice(0, next < 0 ? undefined : next + 1);
  assert.match(job, /uses: \.\/\.github\/workflows\/adherence\.yml/);
  assert.match(job, /^\s+tools_repository: \$\{\{ github\.repository \}\}$/m);
  assert.match(job, /tools_ref: \$\{\{ github\.event\.pull_request\.head\.sha \|\| github\.sha \}\}/);
});

test('ocr-review-caller (live): when it names tools_repository, it names this repository', () => {
  // Its `uses:` pins a tds-utils commit; the input exists only from the
  // commit that adds it, so the live caller takes the line with its next pin.
  const live = code(read('.github/workflows/ocr-review-caller.yml'));
  const line = live.match(/^\s+tools_repository:\s*(.*)$/m);
  if (line) assert.equal(line[1].trim(), '${{ github.repository }}');
});

// --- Templates and examples for other repositories ------------------------------

test('ocr-review caller template: uses the public repository, passes no tools_repository', () => {
  const tpl = code(read('docs/ocr-review-caller.yml'));
  assert.match(tpl, new RegExp(`uses: ${PUBLIC_REPO}/\\.github/workflows/ocr-review\\.yml@[0-9a-f]{40}`));
  assert.doesNotMatch(tpl, /tools_repository/);
  assert.doesNotMatch(tpl, /9atatimer\/tds-utils/);
});

test('ocr-review caller template: its comments say both SHAs are one 9atatimer/workflows commit', () => {
  const tpl = read('docs/ocr-review-caller.yml');
  assert.match(tpl, /9atatimer\/workflows/);
  assert.doesNotMatch(tpl, /tds-utils (commit|master)/);
});
