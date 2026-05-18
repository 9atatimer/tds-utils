#!/usr/bin/env node
/**
 * gadmin/admin/migrate-todo-plan.mjs
 *
 * One-time migration: parse TODO_PLAN.md's "Open Tasks" section and mint
 * a GitHub Issue per `- [ ]` row. Subsystem label derived from the most
 * recent `### Heading`; default priority P2.
 *
 * Usage:
 *   migrate-todo-plan --repo OWNER/REPO [--path TODO_PLAN.md]
 *                     [--apply]            # without --apply, dry-run
 *                     [--start-after ID]   # resume after this Task ID
 *                     [--default-priority P2]
 *
 * Strict-aggregated assumption: this script creates Issues directly (issue
 * creation is the exception in the design — there is no Issue to comment on
 * yet). Subsequent edits should go through the regular gadmin command-
 * comment path.
 */

import { execSync } from 'node:child_process';
import { readFileSync, existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';

const LOG_PREFIX = '[migrate-todo-plan]';
function logInfo(msg)  { console.log(`${LOG_PREFIX} ${msg}`); }
function logWarn(msg)  { console.error(`${LOG_PREFIX} ${msg}`); }
function logError(msg) { console.error(`${LOG_PREFIX} ${msg}`); }

// ---- arg parse -------------------------------------------------------------

function parseArgs(argv) {
  const opts = {
    repo: null, path: null, apply: false,
    startAfter: null, defaultPriority: 'P2',
  };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    switch (a) {
      case '--repo':              opts.repo = argv[++i]; break;
      case '--path':              opts.path = argv[++i]; break;
      case '--apply':             opts.apply = true; break;
      case '--start-after':       opts.startAfter = argv[++i]; break;
      case '--default-priority':  opts.defaultPriority = argv[++i]; break;
      case '--help':
      case '-h':
        console.log(usage());
        process.exit(0);
      default:
        logError(`unknown arg: ${a}`);
        console.log(usage());
        process.exit(1);
    }
  }
  return opts;
}

function usage() {
  return `Usage: migrate-todo-plan --repo OWNER/REPO [options]

Options:
  --repo OWNER/REPO        Target repository (required).
  --path FILE              TODO_PLAN.md path (default: walk up from cwd).
  --apply                  Actually create issues (default: dry-run preview).
  --start-after TASK-ID    Skip tasks up to and including this Task ID.
  --default-priority P2    Default label when no P0/P1 hint is present.
`;
}

// ---- find file -------------------------------------------------------------

function findTodoPlan(startDir) {
  let dir = resolve(startDir);
  while (true) {
    const candidate = join(dir, 'TODO_PLAN.md');
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

// ---- parser ----------------------------------------------------------------

function subsystemFromHeading(heading) {
  // First token, lowercased, simple slug. e.g. "log-hoarder / tmux UX" -> "log-hoarder"
  const first = heading.replace(/^#+\s*/, '').trim().split(/\s+/)[0] || 'misc';
  return first.toLowerCase().replace(/[^a-z0-9_-]/g, '');
}

function extractTitleAndBody(taskBody) {
  // Look for **Title** marker first; lazy match so a single `*` inside
  // inline-code (e.g. `github-*`) doesn't terminate the title early.
  const boldMatch = taskBody.match(/^\*\*(.+?)\*\*\s*[—-]?\s*([\s\S]*)$/);
  if (boldMatch) {
    return { title: boldMatch[1].trim(), body: boldMatch[2].trim() };
  }
  // Otherwise: first sentence as title, rest as body.
  const sentenceMatch = taskBody.match(/^([^.]{1,120})\.\s*([\s\S]*)$/);
  if (sentenceMatch) {
    return { title: sentenceMatch[1].trim(), body: sentenceMatch[2].trim() };
  }
  return { title: taskBody.trim().slice(0, 120), body: '' };
}

/**
 * Parse TODO_PLAN.md, return open tasks under the "Open Tasks" section
 * with subsystem labels derived from `###` headings. Stops at the first
 * `---` horizontal rule after "Open Tasks".
 */
export function parseOpenTasks(markdown) {
  const lines = markdown.replace(/\r\n/g, '\n').split('\n');
  const tasks = [];
  let inOpen = false;
  let subsystem = 'misc';

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^##\s+Open Tasks\b/.test(line)) { inOpen = true; continue; }
    if (!inOpen) continue;
    if (/^---\s*$/.test(line)) break; // exit Open Tasks section
    if (/^##\s+/.test(line)) break;   // next H2 ends Open Tasks too

    const heading = line.match(/^###\s+(.+)$/);
    if (heading) {
      subsystem = subsystemFromHeading(heading[1]);
      continue;
    }

    const openTask = line.match(/^\s*-\s+\[\s\]\s+Task\s+([A-Za-z0-9.]+)\s*:?\s*(.*)$/);
    if (openTask) {
      const id = openTask[1];
      let body = openTask[2];
      // Continuation lines (indented): swallow until next bullet or blank-then-bullet.
      let j = i + 1;
      while (j < lines.length) {
        const nxt = lines[j];
        if (/^\s*-\s+\[/.test(nxt) || /^###\s+/.test(nxt) || /^##\s+/.test(nxt) || /^---\s*$/.test(nxt)) break;
        body += '\n' + nxt;
        j++;
      }
      i = j - 1;
      const { title, body: detail } = extractTitleAndBody(body.trim());
      tasks.push({ id, subsystem, title, body: detail, raw: body.trim() });
    }
  }
  return tasks;
}

// ---- GH writes (via gh CLI) ------------------------------------------------

function ghCreateIssue({ owner, repo, title, body, labels }) {
  const args = [
    'issue', 'create',
    '--repo', `${owner}/${repo}`,
    '--title', title,
    '--body', body || '',
  ];
  for (const l of labels) {
    args.push('--label', l);
  }
  const out = execSync(`gh ${args.map(shellEscape).join(' ')}`, {
    encoding: 'utf-8',
  });
  // gh prints the issue URL on stdout
  return out.trim();
}

function shellEscape(s) {
  if (s === '') return "''";
  if (/^[A-Za-z0-9_\-./@:=]+$/.test(s)) return s;
  return `'${s.replace(/'/g, `'\\''`)}'`;
}

// ---- main ------------------------------------------------------------------

function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.repo) {
    logError('--repo OWNER/REPO is required');
    console.log(usage());
    process.exit(1);
  }
  const [owner, repo] = opts.repo.split('/');
  if (!owner || !repo) {
    logError(`invalid --repo: ${opts.repo}`);
    process.exit(1);
  }
  const path = opts.path || findTodoPlan(process.cwd());
  if (!path || !existsSync(path)) {
    logError(`could not find TODO_PLAN.md (pass --path)`);
    process.exit(1);
  }

  const markdown = readFileSync(path, 'utf-8');
  const tasks = parseOpenTasks(markdown);
  logInfo(`parsed ${tasks.length} open task(s) from ${path}`);

  let skip = !!opts.startAfter;
  let createdCount = 0;
  for (const t of tasks) {
    if (skip) {
      if (t.id === opts.startAfter) skip = false;
      continue;
    }
    const labels = [
      opts.defaultPriority,
      `subsystem:${t.subsystem}`,
      `migrated-from:TODO_PLAN.md`,
    ];
    const body = `${t.body || ''}\n\n_Migrated from TODO_PLAN.md Task ${t.id}._`.trim();
    console.log('---');
    console.log(`Task ${t.id} → [${t.subsystem}] P2: ${t.title}`);
    if (process.env.GADMIN_VERBOSE && body) {
      console.log('body:', body.replace(/\n/g, '\n  '));
    }
    if (!opts.apply) continue;
    try {
      const url = ghCreateIssue({ owner, repo, title: t.title, body, labels });
      console.log(`  created: ${url}`);
      createdCount++;
    } catch (e) {
      logWarn(`failed to create issue for Task ${t.id}: ${e.message}`);
    }
  }

  if (!opts.apply) {
    console.log('---');
    logInfo('dry-run; re-run with --apply to create issues');
  } else {
    logInfo(`created ${createdCount} issue(s)`);
    logInfo('next: run `gadmin github issue sync-plan --repo ' + opts.repo + '` to refresh the autogen block');
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
