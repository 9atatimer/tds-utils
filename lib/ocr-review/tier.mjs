// tier.mjs -- the review job's runner and time budgets, from the PR's size.
//
// A review of a large PR outlives the standard niner's 10-minute ceiling and
// is killed with all its work (Issue#776; misvtt PR#88, cancelled at 9 min
// 14 s), and the gateway's model cannot finish even a small one inside its
// 7-minute task budget (Issue#787; misvtt PR#169, 7 files, timed out twice).
// So the review never runs on the standard niner when there is a longer one:
// - a large PR runs on the long niner (`cf-pool-long`, a 2-hour ceiling;
//   tds-internal PR#342), named by the owner's CI_RUNS_ON_LONG;
// - every other PR on the pool (CI_RUNS_ON set) runs on the medium niner
//   (`cf-pool-docker`, a 20-minute ceiling), named by CI_RUNS_ON_DOCKER. A
//   repository off the pool keeps GitHub-hosted runners and the caller's
//   longer timeout (Nine-At-A-Time-Media sets CI_RUNS_ON_DOCKER at org
//   level but not CI_RUNS_ON);
// - with neither, the caller's runner and timeout, as before.
// Pure: the authorize step feeds it and writes its outputs.

/** The long niner's ceiling is 120 minutes; the job stops under it. */
export const LONG_TIMEOUT_MINUTES = 115;
/** The medium niner's ceiling is 20 minutes; the job stops under it. */
export const MEDIUM_TIMEOUT_MINUTES = 19;
/** A PR above either of these is large, unless the caller sets its own:
 * 25 files or more, or more than 800 changed lines. */
export const DEFAULT_MAX_FILES = 24;
export const DEFAULT_MAX_LINES = 800;
/** The upstream action's own default per-task budget, kept as a cap. */
export const UPSTREAM_TASK_TIMEOUT_MINUTES = 15;
/** The minutes the steps after Review (verdict, uploads) keep for themselves. */
const AFTER_REVIEW_MINUTES = 2;
const DEFAULT_TIMEOUT_MINUTES = 9;
const HOSTED = '"ubuntu-latest"';

/** A non-negative integer from a string, else undefined. */
function count(value) {
  return /^\d+$/.test(String(value ?? '').trim()) ? Number(value) : undefined;
}

/** A setting: a positive integer, else undefined. The workflow's inputs
 * default to 0 for "use the default", so 0 is never a threshold or a
 * timeout: a 0 threshold would make every PR large. */
function setting(value) {
  const n = count(value);
  return n && n > 0 ? n : undefined;
}

/**
 * Inputs are the strings the workflow hands over: the PR's changed files and
 * lines (empty when unknown), the caller's review_runs_on and
 * review_timeout_minutes, the owner's CI_RUNS_ON, CI_RUNS_ON_DOCKER and
 * CI_RUNS_ON_LONG (JSON), and the caller's thresholds (empty for the
 * defaults). The caller's timeout goes only with the caller's runner or the
 * standard one: callers pass 9, the standard niner's budget, and it would
 * waste the medium niner's 20 minutes.
 */
export function reviewPlan({ changedFiles, changedLines, callerRunsOn, callerTimeout, runsOn, runsOnDocker, runsOnLong, maxFiles, maxLines }) {
  const files = count(changedFiles);
  const lines = count(changedLines);
  const large = (files ?? 0) > (setting(maxFiles) ?? DEFAULT_MAX_FILES) || (lines ?? 0) > (setting(maxLines) ?? DEFAULT_MAX_LINES);
  const medium = Boolean(runsOn && runsOnDocker);
  const tier = large ? 'long' : medium ? 'medium' : 'standard';
  const callerMinutes = setting(callerTimeout) ?? DEFAULT_TIMEOUT_MINUTES;

  let chosenRunsOn;
  let timeoutMinutes;
  let note = '';
  if (callerRunsOn) {
    // The caller chose this job's runner; its timeout goes with it.
    chosenRunsOn = callerRunsOn;
    timeoutMinutes = callerMinutes;
  } else if (large && runsOnLong) {
    chosenRunsOn = runsOnLong;
    timeoutMinutes = LONG_TIMEOUT_MINUTES;
  } else if (medium) {
    chosenRunsOn = runsOnDocker;
    timeoutMinutes = MEDIUM_TIMEOUT_MINUTES;
    if (large) note = 'a large PR, but CI_RUNS_ON_LONG is not set: reviewed on the medium runner';
  } else {
    chosenRunsOn = runsOn || HOSTED;
    timeoutMinutes = callerMinutes;
    if (large) note = 'a large PR, but CI_RUNS_ON_LONG is not set: reviewed on the standard runner';
  }

  const stepTimeoutMinutes = Math.max(1, timeoutMinutes - AFTER_REVIEW_MINUTES);
  const taskTimeoutMinutes = Math.min(UPSTREAM_TASK_TIMEOUT_MINUTES, stepTimeoutMinutes);
  return { tier, runsOn: chosenRunsOn, timeoutMinutes, stepTimeoutMinutes, taskTimeoutMinutes, note };
}
