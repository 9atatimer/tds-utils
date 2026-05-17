#!/usr/bin/env node
/**
 * gadmin/admin/issue-grammar.mjs
 *
 * Wire format for /gadmin command comments on GitHub Issues.
 *
 * Coding agents are append-only: they POST a command comment, then exit.
 * The laptop-pinned aggregator consumes these comments in order and is the
 * sole writer of canonical Issue state (body, labels, state). Comments
 * without the /gadmin preamble are treated as human discussion and ignored.
 *
 * Command-comment format (case-sensitive keys, one op per line except
 * edit-body which is a fenced block):
 *
 *   /gadmin tx=<id> agent=<id> [assume-version=<prev-tx>]
 *   priority: P1
 *   add-label: blocked-by:#42
 *   remove-label: claimed-by:claude-A
 *   claim:
 *   release:
 *   close: completed
 *   reopen:
 *   edit-title: New title here
 *   edit-body: |
 *     multi
 *     line
 *     body
 *
 * Apply-receipt format (posted by aggregator as a reply comment):
 *
 *   /gadmin-applied tx=<id> status=ok
 *   /gadmin-applied tx=<id> status=rejected reason=already-claimed-by:claude-A
 */

import { randomUUID } from 'node:crypto';

export const COMMAND_PREAMBLE = '/gadmin';
export const APPLIED_PREAMBLE = '/gadmin-applied';

export const OP_KINDS = new Set([
  'priority',
  'add-label',
  'remove-label',
  'claim',
  'release',
  'close',
  'reopen',
  'edit-title',
  'edit-body',
]);

const FLAG_OPS = new Set(['claim', 'release', 'reopen']);

/**
 * Generate a sortable transaction id. NOT a standards UUIDv7 — this is a
 * custom `<base36-ms-since-epoch>-<12-hex>` string built from a v4 UUID's
 * random half. The time prefix makes lexical sort approximate chronological
 * order, which is enough for client-side ordering hints; the aggregator
 * authoritatively orders by GitHub comment created_at.
 *
 * If a true UUIDv7 is later needed (e.g. for interop), replace this with
 * the standards form and bump the on-the-wire `tx=` token format. Existing
 * tx ids stored in tx_log remain valid since the column is opaque text.
 */
export function newTxId() {
  const t = Date.now().toString(36).padStart(9, '0');
  const r = randomUUID().replace(/-/g, '').slice(0, 12);
  return `${t}-${r}`;
}

function parsePreamble(line) {
  if (!line.startsWith(COMMAND_PREAMBLE)) return null;
  const rest = line.slice(COMMAND_PREAMBLE.length).trim();
  const pairs = {};
  for (const tok of rest.split(/\s+/).filter(Boolean)) {
    const eq = tok.indexOf('=');
    if (eq < 0) return null;
    pairs[tok.slice(0, eq)] = tok.slice(eq + 1);
  }
  if (!pairs.tx || !pairs.agent) return null;
  return {
    tx: pairs.tx,
    agent: pairs.agent,
    assumeVersion: pairs['assume-version'],
  };
}

/**
 * Parse a comment body. Returns:
 *   { tx, agent, assumeVersion?, ops: [{ kind, value? }, ...] }
 * or null if this is not a /gadmin command comment.
 *
 * Lines inside an `edit-body: |` fenced block (indented by at least one
 * whitespace, plus blank lines) are absorbed as body content. The first
 * non-indented non-blank line after the block terminates it and is parsed
 * as the next op. Unknown op kinds, malformed preambles, and value/flag
 * mismatches all cause a parse failure (returns null) so the aggregator
 * can flag malformed commands rather than partially apply them.
 */
export function parseCommand(body) {
  if (typeof body !== 'string') return null;
  const lines = body.replace(/\r\n/g, '\n').split('\n');
  // Find preamble line (first line starting with /gadmin); ignore leading
  // blank lines so callers can include a friendly preface above.
  let i = 0;
  while (i < lines.length && lines[i].trim() === '') i++;
  if (i >= lines.length) return null;
  const head = parsePreamble(lines[i].trim());
  if (!head) return null;
  i++;

  const ops = [];
  while (i < lines.length) {
    const raw = lines[i];
    const line = raw.trimEnd();
    if (line.trim() === '') { i++; continue; }
    const colon = line.indexOf(':');
    if (colon < 0) return null;
    const kind = line.slice(0, colon).trim();
    let value = line.slice(colon + 1).trim();
    if (!OP_KINDS.has(kind)) return null;

    if (kind === 'edit-body' && value === '|') {
      // Collect indented block; stop at first non-indented non-blank line.
      i++;
      const collected = [];
      while (i < lines.length) {
        const bl = lines[i];
        if (bl === '' || /^\s/.test(bl)) {
          collected.push(bl.replace(/^ {2}/, ''));
          i++;
        } else {
          break;
        }
      }
      // Trim trailing blank lines for stable round-trips.
      while (collected.length && collected[collected.length - 1] === '') {
        collected.pop();
      }
      ops.push({ kind, value: collected.join('\n') });
      continue;
    }

    if (FLAG_OPS.has(kind)) {
      if (value !== '') return null;
      ops.push({ kind });
    } else {
      if (value === '') return null;
      ops.push({ kind, value });
    }
    i++;
  }

  if (ops.length === 0) return null;
  return { tx: head.tx, agent: head.agent, assumeVersion: head.assumeVersion, ops };
}

/**
 * Format a command object as a comment body. Round-trips with parseCommand
 * for all op shapes including multi-line edit-body.
 */
export function formatCommand(cmd) {
  if (!cmd || typeof cmd !== 'object') {
    throw new TypeError('formatCommand requires a command object');
  }
  if (!cmd.tx || !cmd.agent) {
    throw new TypeError('formatCommand requires tx and agent fields');
  }
  if (!Array.isArray(cmd.ops) || cmd.ops.length === 0) {
    throw new TypeError('formatCommand requires at least one op');
  }

  const headParts = [COMMAND_PREAMBLE, `tx=${cmd.tx}`, `agent=${cmd.agent}`];
  if (cmd.assumeVersion) {
    headParts.push(`assume-version=${cmd.assumeVersion}`);
  }
  const out = [headParts.join(' ')];

  for (const op of cmd.ops) {
    if (!OP_KINDS.has(op.kind)) {
      throw new TypeError(`unknown op kind: ${op.kind}`);
    }
    if (op.kind === 'edit-body') {
      out.push('edit-body: |');
      for (const ln of String(op.value ?? '').split('\n')) {
        out.push(`  ${ln}`);
      }
      continue;
    }
    if (FLAG_OPS.has(op.kind)) {
      out.push(`${op.kind}:`);
      continue;
    }
    out.push(`${op.kind}: ${op.value}`);
  }

  return out.join('\n');
}

/**
 * Parse a /gadmin-applied receipt. Returns { tx, status, reason? } or null.
 */
export function parseApplied(body) {
  if (typeof body !== 'string') return null;
  const firstLine = body.replace(/\r\n/g, '\n').split('\n')[0].trim();
  if (!firstLine.startsWith(APPLIED_PREAMBLE)) return null;
  const rest = firstLine.slice(APPLIED_PREAMBLE.length).trim();
  const pairs = {};
  for (const tok of rest.split(/\s+/).filter(Boolean)) {
    const eq = tok.indexOf('=');
    if (eq < 0) return null;
    pairs[tok.slice(0, eq)] = tok.slice(eq + 1);
  }
  if (!pairs.tx || !pairs.status) return null;
  return {
    tx: pairs.tx,
    status: pairs.status,
    reason: pairs.reason,
  };
}

export function formatApplied(tx, status, reason) {
  const parts = [APPLIED_PREAMBLE, `tx=${tx}`, `status=${status}`];
  if (reason) parts.push(`reason=${reason}`);
  return parts.join(' ');
}

// CLI self-test: `node issue-grammar.mjs` runs round-trip checks.
if (import.meta.url === `file://${process.argv[1]}`) {
  const samples = [
    { tx: 't1', agent: 'a', ops: [{ kind: 'priority', value: 'P1' }] },
    { tx: 't2', agent: 'a', ops: [{ kind: 'claim' }, { kind: 'add-label', value: 'subsystem:gadmin' }] },
    { tx: 't3', agent: 'a', assumeVersion: 'p0', ops: [{ kind: 'close', value: 'completed' }] },
    {
      tx: 't4', agent: 'a',
      ops: [{ kind: 'edit-body', value: 'line1\nline2\n\nline4' }],
    },
  ];
  let ok = 0;
  for (const s of samples) {
    const got = parseCommand(formatCommand(s));
    if (JSON.stringify(got) !== JSON.stringify(s)) {
      console.error('round-trip mismatch:', { in: s, out: got });
      process.exit(1);
    }
    ok++;
  }
  console.log(`grammar self-test ok (${ok}/${samples.length})`);
}
