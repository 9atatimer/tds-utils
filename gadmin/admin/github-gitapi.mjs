#!/usr/bin/env node
/**
 * scripts/gadmin/github-gitapi.mjs
 * GitHub integration helpers for AI agents and developers
 * Uses GitHub REST API directly via fetch (no gh CLI or octokit required)
 *
 * Usage: gadmin gitapi <command> [options]
 *
 * Commands:
 *   pr-comments --pr <number>   List PR review comments in token-efficient format
 *   pending-comments --pr <number>  List unaddressed PR comments (no robot emoji reply)
 *   reply          Reply to a comment with standardized emoji annotation
 *   actions        Retrieve GitHub Actions workflow run outputs
 *
 * Environment:
 *   GITHUB_TOKEN   Required. Personal access token or GitHub App token
 */

import { execSync } from 'child_process';
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import {
  formatCommand,
  parseApplied,
  newTxId,
} from './issue-grammar.mjs';
import { syncPlanFile } from './issue-plan-sync.mjs';

// ANSI color codes
const GREEN = '\x1b[0;32m';
const NC = '\x1b[0m'; // No Color

const LOG_PREFIX = '[gadmin]';
const GITHUB_API = 'https://api.github.com';

function logInfo(msg) {
  console.log(`${LOG_PREFIX} ${msg}`);
}

function logWarn(msg) {
  console.error(`${LOG_PREFIX} ${msg}`);
}

function logError(msg) {
  console.error(`${LOG_PREFIX} ${msg}`);
}

function usage() {
  const helpText = `
Usage: gadmin gitapi <command> [options]

Commands:
  pr-comments    List PR review comments in token-efficient format
  pending-comments --pr <number>  List unaddressed PR comments (no robot emoji reply)
  reply          Reply to a comment with standardized emoji annotation
  actions        Retrieve GitHub Actions workflow run outputs
  issue <sub>    Issue CRUD + workflow primitives. Subcommands:
                   list, view, create, edit, comment, close, reopen,
                   priority, block, unblock, claim, release, next,
                   sync-plan

Options for pr-comments / pending-comments:
  --pr <number>         PR number (required)
  --repo <owner/repo>   Repository (required, e.g., MyOrg/myrepo or MyFork/myrepo)
  --unannotated         Only show comments without robot emoji replies
  --detailed            Show full comment bodies instead of previews (for pr-comments only)
  --ignore-branch       Skip branch validation check (use when intentionally checking different branch)

Options for reply:
  --id <comment_id>     Comment ID to reply to
  --type <accept|reject> Type of reply (adds 🤖👀✅ or 🤖👀❌)
  --msg <message>       Reply message body
  --repo <owner/repo>   Repository (required)

Options for actions:
  list-runs              List recent workflow runs
    --repo <owner/repo>  Repository (required)
    --workflow <name>    Filter by workflow name (optional)
    --branch <name>      Filter by branch (optional)
    --status <status>    Filter by status (optional)
    --limit <n>          Limit results (default: 10)

  get-job                Get specific job output from a run
    --repo <owner/repo>  Repository (required)
    --run <id>           Workflow run ID (required)
    --job <name>         Job name or ID (required)

  get-logs               Get all logs from a workflow run
    --repo <owner/repo>  Repository (required)
    --run <id>           Workflow run ID (required)
    --job <name>         Filter to specific job (optional)

Examples:
  gadmin gitapi pr-comments --repo MyOrg/myrepo --pr 603
  gadmin gitapi pending-comments --repo MyFork/myrepo --pr 89
  gadmin gitapi reply --repo MyFork/myrepo --id 12345 --type accept --msg "Fixed typo"
  gadmin gitapi actions list-runs --repo MyOrg/myrepo --workflow "Security Scan" --limit 5
  gadmin gitapi actions get-job --repo MyOrg/myrepo --run 19762881348 --job "Trivy Scan"
  gadmin gitapi actions get-logs --repo MyOrg/myrepo --run 19762881348
`;
  console.log(helpText);
  process.exit(0);
}

function parseArgs(args) {
  const result = {
    command: null,
    subcommand: null,
    options: {},
  };

  let i = 0;
  while (i < args.length) {
    const arg = args[i];

    if (arg === '--help' || arg === '-h') {
      usage();
    } else if (arg.startsWith('--')) {
      const key = arg.slice(2);
      // Check bounds before accessing next argument
      const hasNextArg = i + 1 < args.length;
      const value = hasNextArg ? args[i + 1] : undefined;
      if (value && !value.startsWith('--')) {
        result.options[key] = value;
        i += 2;
      } else {
        result.options[key] = true;
        i += 1;
      }
    } else if (!result.command) {
      result.command = arg;
      i += 1;
    } else if (!result.subcommand) {
      result.subcommand = arg;
      i += 1;
    } else {
      i += 1;
    }
  }

  return result;
}

function getToken() {
  const token = process.env.GITHUB_TOKEN;
  if (!token) {
    logError('GITHUB_TOKEN environment variable is required');
    logError('Set it with: export GITHUB_TOKEN=<your-token>');
    process.exit(1);
  }
  return token;
}

/**
 * Make an authenticated GitHub API request
 */
async function githubApi(endpoint, options = {}) {
  const token = getToken();
  const url = endpoint.startsWith('http') ? endpoint : `${GITHUB_API}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    headers: {
      'Authorization': `Bearer ${token}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const errorBody = await response.text();
    const error = new Error(`GitHub API error: ${response.status} ${response.statusText}`);
    error.status = response.status;
    error.body = errorBody;
    throw error;
  }

  // Check if response is JSON or text (for logs)
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return response.json();
  }
  return response.text();
}

/**
 * Paginate through GitHub API results
 */
async function githubApiPaginate(endpoint, options = {}) {
  const results = [];
  let url = endpoint.startsWith('http') ? endpoint : `${GITHUB_API}${endpoint}`;

  // Add per_page if not present
  if (!url.includes('per_page')) {
    url += url.includes('?') ? '&per_page=100' : '?per_page=100';
  }

  while (url) {
    const token = getToken();
    const response = await fetch(url, {
      ...options,
      headers: {
        'Authorization': `Bearer ${token}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorBody = await response.text();
      const error = new Error(`GitHub API error: ${response.status} ${response.statusText}`);
      error.status = response.status;
      error.body = errorBody;
      throw error;
    }

    const data = await response.json();
    results.push(...(Array.isArray(data) ? data : []));

    // Check for next page in Link header
    const linkHeader = response.headers.get('link');
    url = null;
    if (linkHeader) {
      const match = linkHeader.match(/<([^>]+)>;\s*rel="next"/);
      if (match) {
        url = match[1];
      }
    }
  }

  return results;
}

function parseRepo(repoString) {
  if (!repoString) {
    return { owner: null, repo: null };
  }
  const [owner, repo] = repoString.split('/');
  return { owner, repo };
}

function extractRepoAndPrFromUrl(input) {
  const match = input.match(/^https?:\/\/github\.com\/([^/]+)\/([^/]+)\/pull\/(\d+)/);
  if (match) {
    return { owner: match[1], repo: match[2], pr: parseInt(match[3], 10) };
  }
  return null;
}

function resolveRepoAndPr(prInput, repoInput) {
  const extracted = extractRepoAndPrFromUrl(prInput);
  if (extracted) {
    if (repoInput) {
      logWarn('Ignoring --repo flag; using repository from PR URL');
    }
    return { owner: extracted.owner, repo: extracted.repo, prNumber: extracted.pr };
  }

  const { owner, repo } = parseRepo(repoInput);
  const prNumber = parseInt(prInput, 10);
  if (Number.isNaN(prNumber)) {
    logError(`Invalid PR number: "${prInput}"`);
    return { owner, repo, prNumber: null };
  }
  return { owner, repo, prNumber };
}

function getCurrentGitBranch() {
  try {
    return execSync('git rev-parse --abbrev-ref HEAD', { encoding: 'utf-8' }).trim();
  } catch {
    return null;
  }
}

async function validatePrMatchesBranch(owner, repo, prNumber) {
  const currentBranch = getCurrentGitBranch();
  if (!currentBranch) {
    logWarn('Skipping PR/branch validation: not in a git repository');
    return true;
  }

  try {
    const pr = await githubApi(`/repos/${owner}/${repo}/pulls/${prNumber}`);
    const prBranch = pr.head.ref;

    if (currentBranch !== prBranch) {
      logWarn('⚠️  Branch mismatch detected!');
      logWarn(`   Current branch: ${currentBranch}`);
      logWarn(`   PR #${prNumber} branch: ${prBranch}`);
      logWarn('   You may be looking at the wrong PR or repo.');
      console.error('');
      return false;
    }
  } catch (error) {
    logWarn(`Could not fetch PR #${prNumber} from ${owner}/${repo} - PR may not exist`);
    return false;
  }

  return true;
}

function stripAnsiCodes(str) {
  return str.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, '').replace(/\x1b\(B/g, '').replace(/\x0d/g, '');
}

function truncatePath(path, maxLen = 38) {
  if (path.length > maxLen) {
    return '...' + path.slice(-(maxLen - 3));
  }
  return path;
}

function cleanPreview(text, maxLen = 50) {
  return text.replace(/\n/g, ' ').slice(0, maxLen);
}

// ============================================================================
// Command: pr-comments
// ============================================================================
async function cmdPrComments(options) {
  const prInput = options.pr;
  const repoInput = options.repo;
  const ignoreBranch = options['ignore-branch'];
  const unannotatedOnly = options.unannotated;
  const detailed = options.detailed;

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  if (!prInput) {
    logError('Missing required option: --pr <number>');
    usage();
  }

  const { owner, repo, prNumber } = resolveRepoAndPr(prInput, repoInput);

  if (!prNumber) {
    logError('Invalid PR number or URL');
    usage();
  }

  if (!owner || !repo) {
    logError('Missing required option: --repo <owner/repo> (or provide full PR URL)');
    usage();
  }

  // Validate PR branch matches current git branch (unless --ignore-branch)
  if (!ignoreBranch) {
    const isValid = await validatePrMatchesBranch(owner, repo, prNumber);
    if (!isValid) {
      process.exit(1);
    }
  }

  // Fetch all comments (paginate automatically)
  const comments = await githubApiPaginate(`/repos/${owner}/${repo}/pulls/${prNumber}/comments`);

  if (comments.length === 0) {
    console.log(`No review comments found on PR #${prNumber}`);
    return;
  }

  if (unannotatedOnly) {
    await cmdPendingCommentsInternal(owner, repo, prNumber, comments);
  } else if (detailed) {
    // Show detailed comments with full body (token-efficient format)
    for (const comment of comments) {
      const line = comment.line || comment.original_line || 'N/A';
      console.log('----------------------------------------------------------------');
      console.log(`ID: ${comment.id}  |  User: ${comment.user.login}  |  File: ${comment.path}  |  Line: ${line}`);
      console.log('----------------------------------------------------------------');
      console.log(comment.body);
      console.log('');
    }
  } else {
    // Show all comments in table format
    console.log(
      `${'ID'.padEnd(12)} ${'USER'.padEnd(10)} ${'FILE'.padEnd(40)} PREVIEW`
    );
    console.log('-'.repeat(110));

    for (const comment of comments) {
      const id = String(comment.id).padEnd(12);
      const user = comment.user.login.padEnd(10);
      const path = truncatePath(comment.path).padEnd(40);
      const preview = cleanPreview(comment.body);
      console.log(`${id} ${user} ${path} ${preview}`);
    }
  }
}

// ============================================================================
// Command: pending-comments
// ============================================================================
async function cmdPendingComments(options) {
  const prInput = options.pr;
  const repoInput = options.repo;
  const ignoreBranch = options['ignore-branch'];

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  if (!prInput) {
    logError('Missing required option: --pr <number>');
    usage();
  }

  const { owner, repo, prNumber } = resolveRepoAndPr(prInput, repoInput);

  // Validate PR branch matches current git branch (unless --ignore-branch)
  if (!ignoreBranch) {
    const isValid = await validatePrMatchesBranch(owner, repo, prNumber);
    if (!isValid) {
      process.exit(1);
    }
  }

  // Fetch all comments
  const comments = await githubApiPaginate(`/repos/${owner}/${repo}/pulls/${prNumber}/comments`);

  await cmdPendingCommentsInternal(owner, repo, prNumber, comments);
}

async function cmdPendingCommentsInternal(owner, repo, prNumber, comments) {
  // Group comments by thread
  const threads = {};
  const rootComments = [];

  for (const c of comments) {
    if (c.in_reply_to_id) {
      if (!threads[c.in_reply_to_id]) {
        threads[c.in_reply_to_id] = [];
      }
      threads[c.in_reply_to_id].push(c);
    } else {
      rootComments.push(c);
    }
  }

  const pending = [];

  for (const root of rootComments) {
    const replies = threads[root.id] || [];
    // Check if ANY reply has the robot emoji
    const hasAnnotation = replies.some(
      (r) => r.body.includes('🤖') || r.body.includes(':robot:')
    );

    if (!hasAnnotation) {
      pending.push({
        id: root.id,
        user: root.user.login,
        path: root.path,
        body: root.body,
        line: root.line || root.original_line,
      });
    }
  }

  if (pending.length === 0) {
    logInfo(`${GREEN}All review comments have been addressed.${NC}`);
    return;
  }

  for (const p of pending) {
    console.log('----------------------------------------------------------------');
    console.log(`ID: ${p.id}  |  User: ${p.user}  |  File: ${p.path}`);
    console.log('----------------------------------------------------------------');
    console.log(p.body);
    console.log('');
  }
}

// ============================================================================
// Command: reply
// ============================================================================
async function cmdReply(options) {
  const commentId = options.id;
  const type = options.type;
  const msg = options.msg;
  const repoInput = options.repo;

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  if (!commentId || !type || !msg) {
    logError('Missing required options. Need --id, --type, and --msg');
    usage();
  }

  let prefix = '';
  if (type === 'accept') {
    prefix = '🤖👀✅';
  } else if (type === 'reject') {
    prefix = '🤖👀❌';
  } else {
    logError(`Invalid type: ${type}. Must be accept or reject`);
    process.exit(1);
  }

  const fullBody = `${prefix} ${msg}`;
  const { owner, repo } = parseRepo(repoInput);

  console.log(`Replying to ${commentId}...`);

  // 1. Fetch comment details to get PR number
  const comment = await githubApi(`/repos/${owner}/${repo}/pulls/comments/${commentId}`);

  // Extract PR number from pull_request_url
  // URL format: https://api.github.com/repos/Owner/Repo/pulls/123
  const prUrlMatch = comment.pull_request_url.match(/\/pulls\/(\d+)$/);
  if (!prUrlMatch) {
    logError(`Could not determine PR number for comment ${commentId}`);
    process.exit(1);
  }

  const prNumber = parseInt(prUrlMatch[1], 10);

  // 2. Post reply
  await githubApi(`/repos/${owner}/${repo}/pulls/${prNumber}/comments`, {
    method: 'POST',
    body: JSON.stringify({
      body: fullBody,
      in_reply_to: parseInt(commentId, 10),
    }),
  });

  console.log('✅ Reply posted.');
}

// ============================================================================
// Command: actions
// ============================================================================
async function cmdActions(subcommand, options) {
  if (!subcommand) {
    logError('Missing actions subcommand');
    usage();
  }

  switch (subcommand) {
    case 'list-runs':
      await cmdActionsListRuns(options);
      break;
    case 'get-job':
      await cmdActionsGetJob(options);
      break;
    case 'get-logs':
      await cmdActionsGetLogs(options);
      break;
    case '--help':
    case '-h':
      usage();
      break;
    default:
      logError(`Unknown actions subcommand: ${subcommand}`);
      usage();
  }
}

async function cmdActionsListRuns(options) {
  const repoInput = options.repo;
  const workflow = options.workflow;
  const branch = options.branch;
  const status = options.status;
  const limit = parseInt(options.limit || '10', 10);

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  const { owner, repo } = parseRepo(repoInput);

  let runs;

  if (workflow) {
    // Get workflow ID first
    const workflowsData = await githubApi(`/repos/${owner}/${repo}/actions/workflows`);

    const matchedWorkflow = workflowsData.workflows.find(
      (w) => w.name === workflow || (w.path && w.path.includes(workflow))
    );

    if (!matchedWorkflow) {
      logError(`Workflow not found: ${workflow}`);
      process.exit(1);
    }

    let url = `/repos/${owner}/${repo}/actions/workflows/${matchedWorkflow.id}/runs?per_page=${limit}`;
    if (branch) url += `&branch=${encodeURIComponent(branch)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    const data = await githubApi(url);
    runs = data.workflow_runs;
  } else {
    let url = `/repos/${owner}/${repo}/actions/runs?per_page=${limit}`;
    if (branch) url += `&branch=${encodeURIComponent(branch)}`;
    if (status) url += `&status=${encodeURIComponent(status)}`;

    const data = await githubApi(url);
    runs = data.workflow_runs;
  }

  if (!runs || runs.length === 0) {
    console.log('No workflow runs found');
    return;
  }

  // Display results in table format
  console.log(
    `${'RUN ID'.padEnd(12)} ${'WORKFLOW'.padEnd(30)} ${'BRANCH'.padEnd(20)} ${'STATUS'.padEnd(12)} ${'CONCLUSION'.padEnd(12)} CREATED`
  );
  console.log('-'.repeat(120));

  for (const run of runs) {
    const id = String(run.id).padEnd(12);
    let name = run.name;
    if (name.length > 28) name = name.slice(0, 25) + '...';
    name = name.padEnd(30);

    let branchName = run.head_branch;
    if (branchName.length > 18) branchName = branchName.slice(0, 15) + '...';
    branchName = branchName.padEnd(20);

    const statusStr = run.status.padEnd(12);
    const conclusion = (run.conclusion || 'N/A').padEnd(12);
    const created = run.created_at.split('T')[0];

    console.log(`${id} ${name} ${branchName} ${statusStr} ${conclusion} ${created}`);
  }
}

async function cmdActionsGetJob(options) {
  const repoInput = options.repo;
  const runId = options.run;
  const jobName = options.job;

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  if (!runId) {
    logError('Missing required option: --run <id>');
    usage();
  }

  if (!jobName) {
    logError('Missing required option: --job <name>');
    usage();
  }

  const { owner, repo } = parseRepo(repoInput);

  // Fetch jobs for the run
  const jobs = await githubApiPaginate(`/repos/${owner}/${repo}/actions/runs/${runId}/jobs`);

  // Find matching job (by name or ID)
  let job;
  if (/^\d+$/.test(jobName)) {
    // Job name is numeric, treat as ID
    job = jobs.find((j) => j.id === parseInt(jobName, 10));
  } else {
    // Search by name (case-insensitive partial match)
    const lowerJobName = jobName.toLowerCase();
    job = jobs.find((j) => j.name.toLowerCase().includes(lowerJobName));
  }

  if (!job) {
    logError(`Job not found: ${jobName}`);
    console.error(`Available jobs in run ${runId}:`);
    for (const j of jobs) {
      console.error(`  - ${j.name} (ID: ${j.id})`);
    }
    process.exit(1);
  }

  // Print job info
  console.log(`Job: ${job.name}`);
  console.log(`Status: ${job.status}`);
  console.log(`Conclusion: ${job.conclusion || 'N/A'}`);
  console.log(`Started: ${job.started_at}`);
  console.log(`Completed: ${job.completed_at || 'N/A'}`);
  console.log('='.repeat(80));
  console.log('');

  // Fetch and display job logs
  try {
    const logs = await githubApi(`/repos/${owner}/${repo}/actions/jobs/${job.id}/logs`, {
      headers: {
        'Accept': 'application/vnd.github+json',
      },
    });
    console.log(stripAnsiCodes(logs));
  } catch (error) {
    logError(`Failed to fetch logs: ${error.message}`);
  }
}

async function cmdActionsGetLogs(options) {
  const repoInput = options.repo;
  const runId = options.run;
  const jobFilter = options.job;

  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }

  if (!runId) {
    logError('Missing required option: --run <id>');
    usage();
  }

  const { owner, repo } = parseRepo(repoInput);

  // Fetch jobs for the run - the API returns {jobs: [...]} for this endpoint
  const jobsData = await githubApi(`/repos/${owner}/${repo}/actions/runs/${runId}/jobs?per_page=100`);
  const jobs = jobsData.jobs || [];

  if (jobFilter) {
    // Find matching job
    let job;
    if (/^\d+$/.test(jobFilter)) {
      job = jobs.find((j) => j.id === parseInt(jobFilter, 10));
    } else {
      const lowerJobFilter = jobFilter.toLowerCase();
      job = jobs.find((j) => j.name.toLowerCase().includes(lowerJobFilter));
    }

    if (!job) {
      logError(`Job not found: ${jobFilter}`);
      process.exit(1);
    }

    // Get single job logs
    await cmdActionsGetJob({
      repo: repoInput,
      run: runId,
      job: String(job.id),
    });
  } else {
    // Get all job logs
    for (const job of jobs) {
      console.log('');
      console.log('='.repeat(80));
      console.log(`Job: ${job.name} (ID: ${job.id})`);
      console.log('='.repeat(80));
      console.log('');

      try {
        const logs = await githubApi(`/repos/${owner}/${repo}/actions/jobs/${job.id}/logs`, {
          headers: {
            'Accept': 'application/vnd.github+json',
          },
        });
        console.log(stripAnsiCodes(logs));
      } catch (error) {
        logError(`Failed to fetch logs for job ${job.name}: ${error.message}`);
      }
      console.log('');
    }
  }
}

// ============================================================================
// Issue primitives (Phase A): list/view direct, mutations via /gadmin
// command comments. Labels and assignees are computed; the aggregator is the
// sole writer of canonical fields. `create` is the exception since no issue
// exists yet to comment on.
// ============================================================================

function getAgentId() {
  return process.env.GADMIN_AGENT || `gitapi-${process.pid}`;
}

function isIssue(item) {
  return !item.pull_request;
}

function requireRepo(repoInput) {
  if (!repoInput) {
    logError('Missing required option: --repo <owner/repo>');
    usage();
  }
  const { owner, repo } = parseRepo(repoInput);
  if (!owner || !repo) {
    logError(`Invalid --repo: "${repoInput}"`);
    process.exit(1);
  }
  return { owner, repo };
}

async function postIssueComment(owner, repo, issueNumber, body) {
  const created = await githubApi(
    `/repos/${owner}/${repo}/issues/${issueNumber}/comments`,
    { method: 'POST', body: JSON.stringify({ body }) }
  );
  return created;
}

async function emitCommand(owner, repo, issueNumber, ops, { assumeVersion } = {}) {
  const cmd = {
    tx: newTxId(),
    agent: getAgentId(),
    assumeVersion,
    ops,
  };
  await postIssueComment(owner, repo, issueNumber, formatCommand(cmd));
  return cmd.tx;
}

/**
 * Poll the issue's comments for /gadmin-applied tx=<tx>. Used by clients
 * that can't reach the local NATS daemon (e.g. ephemeral cloud agents).
 * Returns { status, reason? } or null on timeout.
 */
async function pollAppliedReceipt(owner, repo, issueNumber, tx, { timeoutMs = 30000, intervalMs = 3000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const comments = await githubApiPaginate(
      `/repos/${owner}/${repo}/issues/${issueNumber}/comments`
    );
    for (const c of comments) {
      const applied = parseApplied(c.body || '');
      if (applied && applied.tx === tx) {
        return { status: applied.status, reason: applied.reason };
      }
    }
    await new Promise((r) => setTimeout(r, intervalMs));
  }
  return null;
}

async function maybeWaitTx(owner, repo, issueNumber, tx, options) {
  if (!options['wait-tx'] && options['wait-tx'] !== '') return;
  const timeoutMs = parseInt(options.timeout || '30', 10) * 1000;
  logInfo(`waiting for /gadmin-applied tx=${tx} (timeout ${timeoutMs / 1000}s)`);
  const result = await pollAppliedReceipt(owner, repo, issueNumber, tx, { timeoutMs });
  if (!result) {
    logWarn(`timed out waiting for tx=${tx}; aggregator may catch up later`);
    return;
  }
  if (result.status === 'ok') {
    logInfo(`tx=${tx} applied`);
  } else {
    logWarn(`tx=${tx} ${result.status}${result.reason ? ': ' + result.reason : ''}`);
  }
}

function asLabelList(opt) {
  if (!opt) return [];
  if (Array.isArray(opt)) return opt;
  return String(opt).split(',').map((s) => s.trim()).filter(Boolean);
}

async function cmdIssueList(options) {
  const { owner, repo } = requireRepo(options.repo);
  const state = options.state || 'open';
  const labels = asLabelList(options.label);
  const assignee = options.assignee;

  const params = new URLSearchParams({ state, per_page: '100' });
  if (labels.length) params.set('labels', labels.join(','));
  if (assignee) params.set('assignee', assignee);

  const items = await githubApiPaginate(
    `/repos/${owner}/${repo}/issues?${params.toString()}`
  );
  const issues = items.filter(isIssue);
  if (issues.length === 0) {
    console.log('No issues match');
    return;
  }
  console.log(
    `${'NUM'.padEnd(6)} ${'STATE'.padEnd(7)} ${'PRIORITY'.padEnd(9)} ${'LABELS'.padEnd(38)} TITLE`
  );
  console.log('-'.repeat(110));
  for (const it of issues) {
    const num = `#${it.number}`.padEnd(6);
    const st = it.state.padEnd(7);
    const labelNames = (it.labels || []).map((l) => l.name);
    const priority = (labelNames.find((n) => /^P[0-9]$/.test(n)) || '-').padEnd(9);
    const otherLabels = labelNames
      .filter((n) => !/^P[0-9]$/.test(n))
      .join(',');
    const shownLabels = (otherLabels.length > 36 ? otherLabels.slice(0, 33) + '...' : otherLabels).padEnd(38);
    console.log(`${num} ${st} ${priority} ${shownLabels} ${it.title}`);
  }
}

async function cmdIssueView(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const it = await githubApi(`/repos/${owner}/${repo}/issues/${num}`);
  console.log(`#${it.number}  ${it.state.toUpperCase()}  ${it.title}`);
  const labelNames = (it.labels || []).map((l) => l.name);
  if (labelNames.length) console.log(`labels: ${labelNames.join(', ')}`);
  const assignees = (it.assignees || []).map((a) => a.login);
  if (assignees.length) console.log(`assignees: ${assignees.join(', ')}`);
  console.log(`url: ${it.html_url}`);
  console.log('-'.repeat(72));
  console.log(it.body || '(no body)');

  if (options['with-comments']) {
    const comments = await githubApiPaginate(
      `/repos/${owner}/${repo}/issues/${num}/comments`
    );
    if (comments.length) {
      console.log('-'.repeat(72));
      console.log(`${comments.length} comment(s):`);
      for (const c of comments) {
        console.log('-'.repeat(40));
        console.log(`${c.user.login}  ${c.created_at}`);
        console.log(c.body);
      }
    }
  }

  if (options['wait-tx']) {
    await maybeWaitTx(owner, repo, num, options['wait-tx'], options);
  }
}

async function cmdIssueCreate(options) {
  const { owner, repo } = requireRepo(options.repo);
  if (!options.title) {
    logError('Missing required option: --title <text>');
    usage();
  }
  const labels = asLabelList(options.label);
  const body = options.body || '';
  const created = await githubApi(`/repos/${owner}/${repo}/issues`, {
    method: 'POST',
    body: JSON.stringify({ title: options.title, body, labels }),
  });
  console.log(`#${created.number}`);
  if (process.env.GADMIN_VERBOSE) {
    console.log(created.html_url);
  }
}

async function cmdIssueEdit(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const ops = [];
  if (options.title) ops.push({ kind: 'edit-title', value: options.title });
  if (options.body) ops.push({ kind: 'edit-body', value: options.body });
  for (const l of asLabelList(options['add-label'])) {
    ops.push({ kind: 'add-label', value: l });
  }
  for (const l of asLabelList(options['remove-label'])) {
    ops.push({ kind: 'remove-label', value: l });
  }
  if (ops.length === 0) {
    logError('Nothing to edit. Pass --title, --body, --add-label, or --remove-label.');
    process.exit(1);
  }
  const tx = await emitCommand(owner, repo, num, ops, {
    assumeVersion: options['assume-tx'],
  });
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueComment(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  if (!options.body) {
    logError('Missing required option: --body <text>');
    usage();
  }
  await postIssueComment(owner, repo, num, options.body);
  console.log('comment posted');
}

async function cmdIssueClose(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const reason = options.reason || 'completed';
  const tx = await emitCommand(owner, repo, num, [
    { kind: 'close', value: reason },
  ]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueReopen(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const tx = await emitCommand(owner, repo, num, [{ kind: 'reopen' }]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

// ---- Phase B: workflow composites ------------------------------------------

const VALID_PRIORITIES = new Set(['P0', 'P1', 'P2']);

async function cmdIssuePriority(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const p = options.priority;
  if (!VALID_PRIORITIES.has(p)) {
    logError(`Invalid --priority: "${p}". Must be P0, P1, or P2.`);
    process.exit(1);
  }
  const tx = await emitCommand(owner, repo, num, [
    { kind: 'priority', value: p },
  ]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueBlock(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  const by = parseInt(options.by, 10);
  if (!num || !by) {
    logError('Need --number <n> and --by <m>');
    process.exit(1);
  }
  const tx = await emitCommand(owner, repo, num, [
    { kind: 'add-label', value: `blocked-by:#${by}` },
  ]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueUnblock(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  if (options.by) {
    const tx = await emitCommand(owner, repo, num, [
      { kind: 'remove-label', value: `blocked-by:#${parseInt(options.by, 10)}` },
    ]);
    console.log(tx);
    await maybeWaitTx(owner, repo, num, tx, options);
    return;
  }
  // No --by: remove all blocked-by:* labels currently on the issue.
  const it = await githubApi(`/repos/${owner}/${repo}/issues/${num}`);
  const targets = (it.labels || [])
    .map((l) => l.name)
    .filter((n) => n.startsWith('blocked-by:'));
  if (targets.length === 0) {
    logInfo('no blocked-by:* labels on issue');
    return;
  }
  const ops = targets.map((t) => ({ kind: 'remove-label', value: t }));
  const tx = await emitCommand(owner, repo, num, ops);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueClaim(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const tx = await emitCommand(owner, repo, num, [{ kind: 'claim' }]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueRelease(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const tx = await emitCommand(owner, repo, num, [{ kind: 'release' }]);
  console.log(tx);
  await maybeWaitTx(owner, repo, num, tx, options);
}

async function cmdIssueNext(options) {
  const { owner, repo } = requireRepo(options.repo);
  const subsystem = options.subsystem;
  const params = new URLSearchParams({ state: 'open', per_page: '100' });
  const labelFilters = ['P0,P1,P2'.split(',')]; // not directly usable; we filter client-side instead
  const items = await githubApiPaginate(
    `/repos/${owner}/${repo}/issues?${params.toString()}`
  );
  const issues = items.filter(isIssue);
  const candidates = issues
    .map((it) => ({
      it,
      labels: (it.labels || []).map((l) => l.name),
    }))
    .filter(({ labels }) => {
      if (labels.some((n) => n.startsWith('blocked-by:'))) return false;
      if (labels.some((n) => n.startsWith('claimed-by:'))) return false;
      if (subsystem && !labels.includes(`subsystem:${subsystem}`)) return false;
      return true;
    })
    .map(({ it, labels }) => ({
      it,
      labels,
      priority: labels.find((n) => /^P[0-9]$/.test(n)) || 'P9',
    }))
    .sort((a, b) => a.priority.localeCompare(b.priority) || a.it.number - b.it.number);

  if (candidates.length === 0) {
    console.log('no ready issues');
    return;
  }
  const top = candidates[0].it;
  console.log(`#${top.number}  ${top.title}`);
  if (process.env.GADMIN_VERBOSE) {
    console.log(top.html_url);
  }
}

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

async function cmdIssueSyncPlan(options) {
  const { owner, repo } = requireRepo(options.repo);
  const planPath = options.path || findTodoPlan(process.cwd());
  if (!planPath) {
    logError('Could not find TODO_PLAN.md (pass --path)');
    process.exit(1);
  }
  const params = new URLSearchParams({ state: 'open', per_page: '100' });
  const items = await githubApiPaginate(
    `/repos/${owner}/${repo}/issues?${params.toString()}`
  );
  const issues = items.filter(isIssue);
  const changed = syncPlanFile(planPath, issues);
  if (changed) {
    logInfo(`updated ${planPath} (${issues.length} open issue(s))`);
  } else {
    logInfo(`no changes to ${planPath}`);
  }
}

async function dispatchIssue(subcommand, options) {
  if (!subcommand) {
    logError('Missing issue subcommand');
    usage();
  }
  switch (subcommand) {
    case 'list':       return cmdIssueList(options);
    case 'view':       return cmdIssueView(options);
    case 'create':     return cmdIssueCreate(options);
    case 'edit':       return cmdIssueEdit(options);
    case 'comment':    return cmdIssueComment(options);
    case 'close':      return cmdIssueClose(options);
    case 'reopen':     return cmdIssueReopen(options);
    case 'priority':   return cmdIssuePriority(options);
    case 'block':      return cmdIssueBlock(options);
    case 'unblock':    return cmdIssueUnblock(options);
    case 'claim':      return cmdIssueClaim(options);
    case 'release':    return cmdIssueRelease(options);
    case 'next':       return cmdIssueNext(options);
    case 'sync-plan':  return cmdIssueSyncPlan(options);
    case '--help':
    case '-h':
      usage();
      break;
    default:
      logError(`Unknown issue subcommand: ${subcommand}`);
      usage();
  }
}

// ============================================================================
// Main
// ============================================================================
async function main() {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    usage();
  }

  const parsed = parseArgs(args);

  try {
    switch (parsed.command) {
      case 'pr-comments':
        await cmdPrComments(parsed.options);
        break;
      case 'pending-comments':
        await cmdPendingComments(parsed.options);
        break;
      case 'reply':
        await cmdReply(parsed.options);
        break;
      case 'actions':
        await cmdActions(parsed.subcommand, parsed.options);
        break;
      case 'issue':
        await dispatchIssue(parsed.subcommand, parsed.options);
        break;
      case '--help':
      case '-h':
        usage();
        break;
      default:
        logError(`Unknown command: ${parsed.command}`);
        usage();
    }
  } catch (error) {
    if (error.status === 401) {
      logError('Authentication failed. Check your GITHUB_TOKEN.');
    } else if (error.status === 404) {
      logError('Resource not found. Check the repository, PR number, or run ID.');
    } else {
      logError(`Error: ${error.message}`);
      if (error.body) {
        console.error(error.body);
      }
    }
    process.exit(1);
  }
}

main();
