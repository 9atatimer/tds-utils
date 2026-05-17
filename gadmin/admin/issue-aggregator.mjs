#!/usr/bin/env node
/**
 * gadmin/admin/issue-aggregator.mjs
 *
 * The single-writer process for the Issues subsystem. Runs as a
 * laptop-pinned long-running process (launchd plist / systemd unit). One
 * aggregator per repo+identity; multiple writers would race on label/state
 * mutations.
 *
 * Loop:
 *   1. fetch new /gadmin command comments since cursor
 *   2. apply each in created_at order to canonical Issue state
 *   3. post /gadmin-applied receipt
 *   4. update SQLite snapshot
 *   5. publish gadmin.events.* on NATS (if available)
 *   6. sleep --interval seconds (default 15)
 *
 * Auth: $GITHUB_TOKEN (falls back to `gh auth token`).
 * Snapshot: --db PATH or $GADMIN_DB (default ~/.gadmin/issues.db).
 * NATS:     --nats-url URL or $NATS_URL (default nats://127.0.0.1:4222;
 *           empty string or "none" disables publishing).
 * CLI flags override the corresponding environment variables.
 *
 * This file is deliberately conservative: polling (not webhook forward),
 * core ops only, no JetStream. Webhook ingress and JetStream are listed
 * out-of-scope for v0 in the design plan.
 */

import { execSync } from 'node:child_process';
import { homedir } from 'node:os';
import { dirname } from 'node:path';
import { mkdirSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';

import {
  parseCommand,
  formatApplied,
  COMMAND_PREAMBLE,
  APPLIED_PREAMBLE,
} from './issue-grammar.mjs';

const GITHUB_API = 'https://api.github.com';
const LOG_PREFIX = '[gadmin-aggregator]';

function logInfo(msg)  { console.log(`${LOG_PREFIX} ${msg}`); }
function logWarn(msg)  { console.error(`${LOG_PREFIX} ${msg}`); }
function logError(msg) { console.error(`${LOG_PREFIX} ${msg}`); }

// ---- args ------------------------------------------------------------------

function parseArgs(argv) {
  // CLI flags override environment defaults.
  const opts = {
    repo: null,
    db: process.env.GADMIN_DB || null,
    interval: 15,
    natsUrl: process.env.NATS_URL ?? null,
    once: false,
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    const next = argv[i + 1];
    switch (a) {
      case '--repo':     opts.repo = next; i++; break;
      case '--db':       opts.db = next; i++; break;
      case '--interval': {
        const n = parseInt(next, 10);
        if (!Number.isFinite(n) || n <= 0) {
          logError(`--interval requires a positive integer, got: ${next}`);
          process.exit(1);
        }
        opts.interval = n;
        i++;
        break;
      }
      case '--nats-url': opts.natsUrl = next; i++; break;
      case '--once':     opts.once = true; break;
      case '--help':
      case '-h':
        usage();
        process.exit(0);
      default:
        logError(`unknown arg: ${a}`);
        usage();
        process.exit(1);
    }
  }
  return opts;
}

function usage() {
  console.log(`Usage: issue-aggregator --repo OWNER/REPO [options]

Options:
  --repo OWNER/REPO    Required.
  --db PATH            SQLite snapshot path (default ~/.gadmin/issues.db).
  --interval SEC       Poll interval seconds (default 15).
  --nats-url URL       NATS server (default nats://127.0.0.1:4222 if reachable;
                       set to "" or "none" to disable publishing).
  --once               Single pass then exit (for testing).
`);
}

// ---- auth ------------------------------------------------------------------

function getToken() {
  if (process.env.GITHUB_TOKEN) return process.env.GITHUB_TOKEN;
  try {
    return execSync('gh auth token', { encoding: 'utf-8' }).trim();
  } catch {
    logError('no GITHUB_TOKEN and `gh auth token` failed');
    process.exit(1);
  }
}

// ---- HTTP ------------------------------------------------------------------

async function ghFetch(endpoint, init = {}) {
  const url = endpoint.startsWith('http') ? endpoint : `${GITHUB_API}${endpoint}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      'Authorization': `Bearer ${getToken()}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      ...(init.headers || {}),
    },
  });
  if (!res.ok) {
    const body = await res.text();
    const err = new Error(`GH ${res.status} ${res.statusText}: ${body}`);
    err.status = res.status;
    throw err;
  }
  const ct = res.headers.get('content-type') || '';
  return { res, body: ct.includes('json') ? await res.json() : await res.text() };
}

async function ghPaginate(endpoint) {
  const out = [];
  let url = endpoint.startsWith('http') ? endpoint : `${GITHUB_API}${endpoint}`;
  if (!url.includes('per_page')) {
    url += url.includes('?') ? '&per_page=100' : '?per_page=100';
  }
  while (url) {
    const { res, body } = await ghFetch(url);
    if (Array.isArray(body)) out.push(...body);
    const link = res.headers.get('link');
    url = null;
    if (link) {
      const m = link.match(/<([^>]+)>;\s*rel="next"/);
      if (m) url = m[1];
    }
  }
  return out;
}

// ---- SQLite ----------------------------------------------------------------

function openDb(path) {
  const resolved = path || `${homedir()}/.gadmin/issues.db`;
  mkdirSync(dirname(resolved), { recursive: true });
  const db = new DatabaseSync(resolved);
  db.exec(`
    CREATE TABLE IF NOT EXISTS issues (
      number          INTEGER PRIMARY KEY,
      state           TEXT,
      title           TEXT,
      body            TEXT,
      labels          TEXT,
      assignees       TEXT,
      last_applied_tx TEXT,
      updated_at      TEXT
    );
    CREATE TABLE IF NOT EXISTS tx_log (
      tx          TEXT PRIMARY KEY,
      issue       INTEGER,
      agent       TEXT,
      comment_id  INTEGER,
      status      TEXT,
      reason      TEXT,
      applied_at  TEXT
    );
    CREATE TABLE IF NOT EXISTS meta (
      key   TEXT PRIMARY KEY,
      value TEXT
    );
  `);
  return db;
}

function getMeta(db, key) {
  const row = db.prepare('SELECT value FROM meta WHERE key = ?').get(key);
  return row ? row.value : null;
}
function setMeta(db, key, value) {
  db.prepare('INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value').run(key, value);
}

function upsertIssue(db, it, lastAppliedTx) {
  db.prepare(`
    INSERT INTO issues(number,state,title,body,labels,assignees,last_applied_tx,updated_at)
    VALUES(?,?,?,?,?,?,?,?)
    ON CONFLICT(number) DO UPDATE SET
      state=excluded.state,
      title=excluded.title,
      body=excluded.body,
      labels=excluded.labels,
      assignees=excluded.assignees,
      last_applied_tx=COALESCE(excluded.last_applied_tx, issues.last_applied_tx),
      updated_at=excluded.updated_at
  `).run(
    it.number,
    it.state,
    it.title || '',
    it.body || '',
    JSON.stringify((it.labels || []).map((l) => l.name || l)),
    JSON.stringify((it.assignees || []).map((a) => a.login)),
    lastAppliedTx,
    it.updated_at || new Date().toISOString(),
  );
}

function logTx(db, { tx, issue, agent, commentId, status, reason }) {
  db.prepare(`
    INSERT OR REPLACE INTO tx_log(tx,issue,agent,comment_id,status,reason,applied_at)
    VALUES(?,?,?,?,?,?,?)
  `).run(tx, issue, agent, commentId, status, reason || null, new Date().toISOString());
}

// ---- NATS ------------------------------------------------------------------

async function maybeNats(natsUrl) {
  if (natsUrl === '' || natsUrl === 'none') return null;
  const url = natsUrl || 'nats://127.0.0.1:4222';
  let nats;
  try {
    nats = await import('nats');
  } catch {
    logWarn('nats package not installed; running without NATS publishing');
    return null;
  }
  try {
    const nc = await nats.connect({ servers: url, timeout: 2000 });
    const sc = nats.StringCodec();
    logInfo(`connected to NATS at ${url}`);
    return {
      publish(subject, payload) {
        try { nc.publish(subject, sc.encode(JSON.stringify(payload))); } catch (e) { logWarn(`nats publish failed: ${e.message}`); }
      },
      close() { try { nc.close(); } catch {} },
    };
  } catch (e) {
    logWarn(`nats connect failed (${e.message}); continuing without`);
    return null;
  }
}

// ---- Apply -----------------------------------------------------------------

const PRIORITY_RE = /^P[0-9]$/;

function applyOpsToState(state, ops, agent) {
  // state: { title, body, labels: Set<string>, state: 'open'|'closed', state_reason }
  for (const op of ops) {
    switch (op.kind) {
      case 'priority':
        if (!PRIORITY_RE.test(op.value || '')) {
          return { reject: `invalid-priority:${op.value}` };
        }
        for (const l of [...state.labels]) {
          if (PRIORITY_RE.test(l)) state.labels.delete(l);
        }
        state.labels.add(op.value);
        break;
      case 'add-label':
        state.labels.add(op.value);
        break;
      case 'remove-label':
        state.labels.delete(op.value);
        break;
      case 'claim': {
        const existing = [...state.labels].find((l) => l.startsWith('claimed-by:'));
        if (existing && existing !== `claimed-by:${agent}`) {
          return { reject: `already-${existing}` };
        }
        state.labels.add(`claimed-by:${agent}`);
        break;
      }
      case 'release':
        for (const l of [...state.labels]) {
          if (l.startsWith('claimed-by:')) state.labels.delete(l);
        }
        break;
      case 'close':
        state.state = 'closed';
        state.state_reason = op.value;
        break;
      case 'reopen':
        state.state = 'open';
        state.state_reason = null;
        break;
      case 'edit-title':
        state.title = op.value;
        break;
      case 'edit-body':
        state.body = op.value;
        break;
    }
  }
  return { reject: null };
}

async function mutateIssueOnGh(owner, repo, number, before, after) {
  // Compute minimal diffs and apply via GH API.
  const patch = {};
  if (after.title !== before.title) patch.title = after.title;
  if (after.body  !== before.body)  patch.body  = after.body;
  if (after.state !== before.state) {
    patch.state = after.state;
    if (after.state === 'closed' && after.state_reason) {
      patch.state_reason = after.state_reason;
    }
  }
  if (Object.keys(patch).length) {
    await ghFetch(`/repos/${owner}/${repo}/issues/${number}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    });
  }

  const added   = [...after.labels].filter((l) => !before.labels.has(l));
  const removed = [...before.labels].filter((l) => !after.labels.has(l));
  if (added.length) {
    await ghFetch(`/repos/${owner}/${repo}/issues/${number}/labels`, {
      method: 'POST',
      body: JSON.stringify({ labels: added }),
    });
  }
  for (const l of removed) {
    try {
      await ghFetch(
        `/repos/${owner}/${repo}/issues/${number}/labels/${encodeURIComponent(l)}`,
        { method: 'DELETE' }
      );
    } catch (e) {
      if (e.status !== 404) throw e;
    }
  }
}

async function postReceipt(owner, repo, issueNumber, tx, status, reason) {
  const body = formatApplied(tx, status, reason);
  await ghFetch(`/repos/${owner}/${repo}/issues/${issueNumber}/comments`, {
    method: 'POST',
    body: JSON.stringify({ body }),
  });
}

// ---- Main loop -------------------------------------------------------------

function extractIssueNumberFromCommentUrl(url) {
  // /repos/:owner/:repo/issues/:n/comments/:id  or  /repos/.../issues/:n
  const m = url.match(/\/issues\/(\d+)/);
  return m ? parseInt(m[1], 10) : null;
}

async function fetchIssueWithLabels(owner, repo, number) {
  const { body: it } = await ghFetch(`/repos/${owner}/${repo}/issues/${number}`);
  return {
    title: it.title || '',
    body: it.body || '',
    labels: new Set((it.labels || []).map((l) => l.name || l)),
    state: it.state,
    state_reason: it.state_reason || null,
    raw: it,
  };
}

async function processComment(ctx, comment) {
  const { owner, repo, db, nats } = ctx;
  const body = comment.body || '';
  if (!body.includes(COMMAND_PREAMBLE)) return; // ignore non-commands quickly
  const cmd = parseCommand(body);
  if (!cmd) return;
  const issueNumber = extractIssueNumberFromCommentUrl(comment.issue_url || comment.html_url || '');
  if (!issueNumber) return;

  // Idempotency: skip if we already logged this tx as applied or rejected.
  const prior = db.prepare('SELECT status FROM tx_log WHERE tx = ?').get(cmd.tx);
  if (prior) return;

  nats?.publish('gadmin.events.command', {
    tx: cmd.tx, agent: cmd.agent, issue: issueNumber, comment_id: comment.id,
  });

  let before;
  try {
    before = await fetchIssueWithLabels(owner, repo, issueNumber);
  } catch (e) {
    logWarn(`fetch issue #${issueNumber} failed: ${e.message}`);
    return;
  }

  // CAS check
  if (cmd.assumeVersion) {
    const row = db.prepare('SELECT last_applied_tx FROM issues WHERE number = ?').get(issueNumber);
    const lastTx = row ? row.last_applied_tx : null;
    if (lastTx && lastTx !== cmd.assumeVersion) {
      await postReceipt(owner, repo, issueNumber, cmd.tx, 'rejected', `version-conflict:last=${lastTx}`);
      logTx(db, { tx: cmd.tx, issue: issueNumber, agent: cmd.agent, commentId: comment.id, status: 'rejected', reason: 'version-conflict' });
      nats?.publish('gadmin.events.rejected', { tx: cmd.tx, issue: issueNumber, reason: 'version-conflict' });
      return;
    }
  }

  const after = {
    title: before.title, body: before.body,
    labels: new Set(before.labels),
    state: before.state, state_reason: before.state_reason,
  };
  const { reject } = applyOpsToState(after, cmd.ops, cmd.agent);
  if (reject) {
    await postReceipt(owner, repo, issueNumber, cmd.tx, 'rejected', reject);
    logTx(db, { tx: cmd.tx, issue: issueNumber, agent: cmd.agent, commentId: comment.id, status: 'rejected', reason: reject });
    nats?.publish('gadmin.events.rejected', { tx: cmd.tx, issue: issueNumber, reason: reject });
    logInfo(`#${issueNumber} tx=${cmd.tx} rejected: ${reject}`);
    return;
  }

  try {
    await mutateIssueOnGh(owner, repo, issueNumber, before, after);
  } catch (e) {
    logWarn(`mutate #${issueNumber} failed: ${e.message}`);
    await postReceipt(owner, repo, issueNumber, cmd.tx, 'rejected', `apply-error:${e.message.slice(0, 80)}`);
    logTx(db, { tx: cmd.tx, issue: issueNumber, agent: cmd.agent, commentId: comment.id, status: 'rejected', reason: 'apply-error' });
    return;
  }

  await postReceipt(owner, repo, issueNumber, cmd.tx, 'ok');
  // Refresh snapshot from GH after mutation.
  const refreshed = await ghFetch(`/repos/${owner}/${repo}/issues/${issueNumber}`);
  upsertIssue(db, refreshed.body, cmd.tx);
  logTx(db, { tx: cmd.tx, issue: issueNumber, agent: cmd.agent, commentId: comment.id, status: 'ok' });
  nats?.publish('gadmin.events.applied', {
    tx: cmd.tx, issue: issueNumber, agent: cmd.agent,
    title: after.title,
    state: after.state,
    labels: [...after.labels].sort(),
  });
  logInfo(`#${issueNumber} tx=${cmd.tx} applied (agent=${cmd.agent})`);
}

async function pollOnce(ctx) {
  const { owner, repo, db } = ctx;
  // Cursor is (created_at, comment_id) — GH `created_at` is second-granularity,
  // so we need a tiebreaker for comments in the same second as the cursor.
  const cursorTs = getMeta(db, 'cursor');
  const cursorId = parseInt(getMeta(db, 'cursor_comment_id') || '0', 10) || 0;
  let endpoint = `/repos/${owner}/${repo}/issues/comments?sort=created&direction=asc&per_page=100`;
  if (cursorTs) endpoint += `&since=${encodeURIComponent(cursorTs)}`;
  const comments = await ghPaginate(endpoint);

  // `since=<iso>` is inclusive at second precision. Accept a comment as fresh
  // if its created_at is strictly past the cursor timestamp, OR same-second
  // but with a higher comment id. Idempotency on tx_log catches anything we
  // happen to re-see.
  const fresh = comments.filter((c) => {
    const ts = c.created_at || '';
    if (!cursorTs) return true;
    if (ts > cursorTs) return true;
    if (ts === cursorTs && (c.id || 0) > cursorId) return true;
    return false;
  });

  // Skip receipts and aggregator's own /gadmin-applied comments to avoid feedback.
  for (const c of fresh) {
    const b = c.body || '';
    if (b.startsWith(APPLIED_PREAMBLE)) continue;
    await processComment(ctx, c);
  }

  if (fresh.length) {
    const newest = fresh[fresh.length - 1];
    setMeta(db, 'cursor', newest.created_at);
    setMeta(db, 'cursor_comment_id', String(newest.id || 0));
  } else if (!cursorTs) {
    setMeta(db, 'cursor', new Date().toISOString());
    setMeta(db, 'cursor_comment_id', '0');
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.repo) { logError('--repo OWNER/REPO is required'); usage(); process.exit(1); }
  const [owner, repo] = opts.repo.split('/');
  if (!owner || !repo) { logError(`invalid --repo: ${opts.repo}`); process.exit(1); }

  const db = openDb(opts.db);
  const nats = await maybeNats(opts.natsUrl);
  const ctx = { owner, repo, db, nats };

  process.on('SIGINT',  () => { logInfo('shutting down'); nats?.close(); db.close(); process.exit(0); });
  process.on('SIGTERM', () => { logInfo('shutting down'); nats?.close(); db.close(); process.exit(0); });

  logInfo(`aggregator started for ${owner}/${repo}, interval=${opts.interval}s, db=${opts.db || '~/.gadmin/issues.db'}`);

  while (true) {
    try {
      await pollOnce(ctx);
    } catch (e) {
      logWarn(`poll failed: ${e.message}`);
    }
    if (opts.once) break;
    await new Promise((r) => setTimeout(r, opts.interval * 1000));
  }
  nats?.close();
  db.close();
}

// Export for tests
export {
  applyOpsToState,
  openDb,
  parseArgs,
  upsertIssue,
  logTx,
  processComment,
};

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((e) => { logError(e.message); process.exit(1); });
}
