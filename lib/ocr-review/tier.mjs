// tier.mjs -- the review job's runner and time budgets, from the PR's size.
//
// A review of a large PR outlives the standard niner's 10-minute ceiling and
// is killed with all its work (Issue#776; misvtt PR#88, cancelled at 9 min
// 14 s). Above a size threshold the review runs on the long niner
// (`cf-pool-long`, a 2-hour ceiling; tds-internal PR#342), named by the
// owner's CI_RUNS_ON_LONG variable. Every other PR keeps the caller's runner
// and timeout. Pure: the authorize step feeds it and writes its outputs.

/** The long niner's ceiling is 120 minutes; the job stops under it. */
export const LONG_TIMEOUT_MINUTES = 115;
/** A PR above either of these is large, unless the caller sets its own. */
export const DEFAULT_MAX_FILES = 25;
export const DEFAULT_MAX_LINES = 800;
/** The upstream action's own default per-task budget, kept as a cap. */
export const UPSTREAM_TASK_TIMEOUT_MINUTES = 15;
/** The minutes the steps after Review (verdict, uploads) keep for themselves. */
const AFTER_REVIEW_MINUTES = 2;
const DEFAULT_TIMEOUT_MINUTES = 9;
const HOSTED = '"ubuntu-latest"';

/** A positive integer from a string, else undefined. */
function count(value) {
  return /^\d+$/.test(String(value ?? '').trim()) ? Number(value) : undefined;
}

/**
 * Inputs are the strings the workflow hands over: the PR's changed files and
 * lines (empty when unknown), the caller's review_runs_on and
 * review_timeout_minutes, the owner's CI_RUNS_ON and CI_RUNS_ON_LONG (JSON),
 * and the caller's thresholds (empty for the defaults).
 */
export function reviewPlan({ changedFiles, changedLines, callerRunsOn, callerTimeout, runsOn, runsOnLong, maxFiles, maxLines }) {
  const files = count(changedFiles);
  const lines = count(changedLines);
  const large = (files ?? 0) > (count(maxFiles) ?? DEFAULT_MAX_FILES) || (lines ?? 0) > (count(maxLines) ?? DEFAULT_MAX_LINES);
  const tier = large ? 'long' : 'standard';
  const callerMinutes = count(callerTimeout) || DEFAULT_TIMEOUT_MINUTES;

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
  } else {
    chosenRunsOn = runsOn || HOSTED;
    timeoutMinutes = callerMinutes;
    if (large) note = 'a large PR, but CI_RUNS_ON_LONG is not set: reviewed on the standard runner';
  }

  const stepTimeoutMinutes = Math.max(1, timeoutMinutes - AFTER_REVIEW_MINUTES);
  const taskTimeoutMinutes = Math.min(UPSTREAM_TASK_TIMEOUT_MINUTES, stepTimeoutMinutes);
  return { tier, runsOn: chosenRunsOn, timeoutMinutes, stepTimeoutMinutes, taskTimeoutMinutes, note };
}
