#!/usr/bin/env node
/**
 * scripts/gadmin/github-octokit.mjs
 * GitHub integration helpers for AI agents and developers
 * Uses Octokit library - pure v8 JavaScript, sandbox-friendly
 *
 * Usage: gadmin octokit <command> [options]
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
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { resolve as resolvePath } from 'node:path';
import {
  formatCommand,
  parseApplied,
  newTxId,
} from './issue-grammar.mjs';

// Resolve `octokit` from (a) this script's location, then (b) the consuming
// project's CWD. This script lives in tds-utils (outside any node_modules
// tree), so the project's node_modules must be reachable for tier-2 to work.
async function loadOctokit() {
  try {
    return (await import('octokit')).Octokit;
  } catch (err) {
    const notFound =
      err?.code === 'ERR_MODULE_NOT_FOUND' ||
      /Cannot find (package|module) 'octokit'/.test(err?.message || '');
    if (!notFound) throw err;
  }
  try {
    const req = createRequire(resolvePath(process.cwd(), 'package.json'));
    const octokitPath = req.resolve('octokit');
    return (await import(pathToFileURL(octokitPath).href)).Octokit;
  } catch (_) {
    console.error("Error: gadmin octokit requires the 'octokit' package, but it is not installed.");
    console.error("Install it with: npm install octokit");
    console.error("Or use the primary tier: gadmin github (requires gh CLI)");
    process.exit(1);
  }
}

const Octokit = await loadOctokit();

// ANSI color codes
const GREEN = '\x1b[0;32m';
const NC = '\x1b[0m'; // No Color

const LOG_PREFIX = '[gadmin]';

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
Usage: gadmin octokit <command> [options]

Commands:
  pr-comments    List PR review comments in token-efficient format
  pending-comments --pr <number>  List unaddressed PR comments (no robot emoji reply)
  reply          Reply to a comment with standardized emoji annotation
  actions        Retrieve GitHub Actions workflow run outputs
  issue <sub>    Issue CRUD + workflow primitives. Subcommands:
                   list, view, create, edit, comment, close, reopen,
                   priority, block, unblock, claim, release, next

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
  gadmin octokit pr-comments --repo MyOrg/myrepo --pr 603
  gadmin octokit pending-comments --repo MyFork/myrepo --pr 89
  gadmin octokit reply --repo MyFork/myrepo --id 12345 --type accept --msg "Fixed typo"
  gadmin octokit actions list-runs --repo MyOrg/myrepo --workflow "Security Scan" --limit 5
  gadmin octokit actions get-job --repo MyOrg/myrepo --run 19762881348 --job "Trivy Scan"
  gadmin octokit actions get-logs --repo MyOrg/myrepo --run 19762881348
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
 * Get an authenticated Octokit instance
 */
function getOctokit() {
  const token = getToken();
  return new Octokit({ auth: token });
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

async function validatePrMatchesBranch(octokit, owner, repo, prNumber) {
  const currentBranch = getCurrentGitBranch();
  if (!currentBranch) {
    logWarn('Skipping PR/branch validation: not in a git repository');
    return true;
  }

  try {
    const { data: pr } = await octokit.rest.pulls.get({
      owner,
      repo,
      pull_number: prNumber,
    });
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

  const octokit = getOctokit();

  // Validate PR branch matches current git branch (unless --ignore-branch)
  if (!ignoreBranch) {
    const isValid = await validatePrMatchesBranch(octokit, owner, repo, prNumber);
    if (!isValid) {
      process.exit(1);
    }
  }

  // Fetch all comments using octokit pagination
  const comments = await octokit.paginate(octokit.rest.pulls.listReviewComments, {
    owner,
    repo,
    pull_number: prNumber,
    per_page: 100,
  });

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

  const octokit = getOctokit();

  // Validate PR branch matches current git branch (unless --ignore-branch)
  if (!ignoreBranch) {
    const isValid = await validatePrMatchesBranch(octokit, owner, repo, prNumber);
    if (!isValid) {
      process.exit(1);
    }
  }

  // Fetch all comments using octokit pagination
  const comments = await octokit.paginate(octokit.rest.pulls.listReviewComments, {
    owner,
    repo,
    pull_number: prNumber,
    per_page: 100,
  });

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
  const octokit = getOctokit();

  console.log(`Replying to ${commentId}...`);

  // 1. Fetch comment details to get PR number
  const { data: comment } = await octokit.rest.pulls.getReviewComment({
    owner,
    repo,
    comment_id: parseInt(commentId, 10),
  });

  // Extract PR number from pull_request_url
  // URL format: https://api.github.com/repos/Owner/Repo/pulls/123
  const prUrlMatch = comment.pull_request_url.match(/\/pulls\/(\d+)$/);
  if (!prUrlMatch) {
    logError(`Could not determine PR number for comment ${commentId}`);
    process.exit(1);
  }

  const prNumber = parseInt(prUrlMatch[1], 10);

  // 2. Post reply using octokit
  await octokit.rest.pulls.createReplyForReviewComment({
    owner,
    repo,
    pull_number: prNumber,
    comment_id: parseInt(commentId, 10),
    body: fullBody,
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
  const octokit = getOctokit();

  let runs;

  if (workflow) {
    // Get workflow ID first
    const { data: workflowsData } = await octokit.rest.actions.listRepoWorkflows({
      owner,
      repo,
    });

    const matchedWorkflow = workflowsData.workflows.find(
      (w) => w.name === workflow || (w.path && w.path.includes(workflow))
    );

    if (!matchedWorkflow) {
      logError(`Workflow not found: ${workflow}`);
      process.exit(1);
    }

    const params = {
      owner,
      repo,
      workflow_id: matchedWorkflow.id,
      per_page: limit,
    };
    if (branch) params.branch = branch;
    if (status) params.status = status;

    const { data } = await octokit.rest.actions.listWorkflowRuns(params);
    runs = data.workflow_runs;
  } else {
    const params = {
      owner,
      repo,
      per_page: limit,
    };
    if (branch) params.branch = branch;
    if (status) params.status = status;

    const { data } = await octokit.rest.actions.listWorkflowRunsForRepo(params);
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
  const octokit = getOctokit();

  // Fetch jobs for the run using pagination
  const jobs = await octokit.paginate(octokit.rest.actions.listJobsForWorkflowRun, {
    owner,
    repo,
    run_id: parseInt(runId, 10),
    per_page: 100,
  });

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
    const { data: logs } = await octokit.rest.actions.downloadJobLogsForWorkflowRun({
      owner,
      repo,
      job_id: job.id,
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
  const octokit = getOctokit();

  // Fetch jobs for the run
  const { data: jobsData } = await octokit.rest.actions.listJobsForWorkflowRun({
    owner,
    repo,
    run_id: parseInt(runId, 10),
    per_page: 100,
  });
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
        const { data: logs } = await octokit.rest.actions.downloadJobLogsForWorkflowRun({
          owner,
          repo,
          job_id: job.id,
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
// command comments. Mirrors github-gitapi.mjs surface; uses Octokit transport.
// ============================================================================

function getAgentId() {
  return process.env.GADMIN_AGENT || `octokit-${process.pid}`;
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

async function postIssueComment(octokit, owner, repo, issueNumber, body) {
  const { data } = await octokit.rest.issues.createComment({
    owner, repo, issue_number: issueNumber, body,
  });
  return data;
}

async function emitCommand(octokit, owner, repo, issueNumber, ops, { assumeVersion } = {}) {
  const cmd = {
    tx: newTxId(),
    agent: getAgentId(),
    assumeVersion,
    ops,
  };
  await postIssueComment(octokit, owner, repo, issueNumber, formatCommand(cmd));
  return cmd.tx;
}

async function pollAppliedReceipt(octokit, owner, repo, issueNumber, tx, { timeoutMs = 30000, intervalMs = 3000 } = {}) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const comments = await octokit.paginate(octokit.rest.issues.listComments, {
      owner, repo, issue_number: issueNumber, per_page: 100,
    });
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

async function maybeWaitTx(octokit, owner, repo, issueNumber, tx, options) {
  if (!options['wait-tx'] && options['wait-tx'] !== '') return;
  const timeoutMs = parseInt(options.timeout || '30', 10) * 1000;
  logInfo(`waiting for /gadmin-applied tx=${tx} (timeout ${timeoutMs / 1000}s)`);
  const result = await pollAppliedReceipt(octokit, owner, repo, issueNumber, tx, { timeoutMs });
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
  const octokit = getOctokit();

  const params = { owner, repo, state, per_page: 100 };
  if (labels.length) params.labels = labels.join(',');
  if (assignee) params.assignee = assignee;
  const items = await octokit.paginate(octokit.rest.issues.listForRepo, params);
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
    const labelNames = (it.labels || []).map((l) => l.name || l);
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
  const octokit = getOctokit();
  const { data: it } = await octokit.rest.issues.get({ owner, repo, issue_number: num });
  console.log(`#${it.number}  ${it.state.toUpperCase()}  ${it.title}`);
  const labelNames = (it.labels || []).map((l) => l.name || l);
  if (labelNames.length) console.log(`labels: ${labelNames.join(', ')}`);
  const assignees = (it.assignees || []).map((a) => a.login);
  if (assignees.length) console.log(`assignees: ${assignees.join(', ')}`);
  console.log(`url: ${it.html_url}`);
  console.log('-'.repeat(72));
  console.log(it.body || '(no body)');

  if (options['with-comments']) {
    const comments = await octokit.paginate(octokit.rest.issues.listComments, {
      owner, repo, issue_number: num, per_page: 100,
    });
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
    await maybeWaitTx(octokit, owner, repo, num, options['wait-tx'], options);
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
  const octokit = getOctokit();
  const { data: created } = await octokit.rest.issues.create({
    owner, repo, title: options.title, body, labels,
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
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, ops, {
    assumeVersion: options['assume-tx'],
  });
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
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
  const octokit = getOctokit();
  await postIssueComment(octokit, owner, repo, num, options.body);
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
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [
    { kind: 'close', value: reason },
  ]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueReopen(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [{ kind: 'reopen' }]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

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
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [
    { kind: 'priority', value: p },
  ]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueBlock(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  const by = parseInt(options.by, 10);
  if (!num || !by) {
    logError('Need --number <n> and --by <m>');
    process.exit(1);
  }
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [
    { kind: 'add-label', value: `blocked-by:#${by}` },
  ]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueUnblock(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const octokit = getOctokit();
  if (options.by) {
    const tx = await emitCommand(octokit, owner, repo, num, [
      { kind: 'remove-label', value: `blocked-by:#${parseInt(options.by, 10)}` },
    ]);
    console.log(tx);
    await maybeWaitTx(octokit, owner, repo, num, tx, options);
    return;
  }
  const { data: it } = await octokit.rest.issues.get({ owner, repo, issue_number: num });
  const targets = (it.labels || [])
    .map((l) => l.name || l)
    .filter((n) => n.startsWith('blocked-by:'));
  if (targets.length === 0) {
    logInfo('no blocked-by:* labels on issue');
    return;
  }
  const ops = targets.map((t) => ({ kind: 'remove-label', value: t }));
  const tx = await emitCommand(octokit, owner, repo, num, ops);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueClaim(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [{ kind: 'claim' }]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueRelease(options) {
  const { owner, repo } = requireRepo(options.repo);
  const num = parseInt(options.number || options.n, 10);
  if (!num) {
    logError('Missing required option: --number <n>');
    usage();
  }
  const octokit = getOctokit();
  const tx = await emitCommand(octokit, owner, repo, num, [{ kind: 'release' }]);
  console.log(tx);
  await maybeWaitTx(octokit, owner, repo, num, tx, options);
}

async function cmdIssueNext(options) {
  const { owner, repo } = requireRepo(options.repo);
  const subsystem = options.subsystem;
  const octokit = getOctokit();
  const items = await octokit.paginate(octokit.rest.issues.listForRepo, {
    owner, repo, state: 'open', per_page: 100,
  });
  const issues = items.filter(isIssue);
  const candidates = issues
    .map((it) => ({
      it,
      labels: (it.labels || []).map((l) => l.name || l),
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
    }
    process.exit(1);
  }
}

main();
