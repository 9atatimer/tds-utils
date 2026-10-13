// lib/ocr-bakeoff/bakeoff.mjs -- the OCR bake-off (tds-utils Issue#468):
// which model reviews best, measured on diffs Copilot or Codex reviewed and
// the inline findings on them that triage accepted (cases.json beside this
// file).
//
// Pure rules: the cases and the model list, the job matrix, the ocr
// invocation, locating accepted findings among a model's findings, the run
// record, and the per-model collation. bin/ocr-bakeoff does the I/O.
//
// "Located" is mechanical: a finding on the same path whose lines come
// within LINE_WINDOW of the accepted finding's. It says where a model
// looked, not that it named the same defect; judging that is a person's
// (or a verifier's) job over the uploaded results.

import { readEngineResult } from '../ocr-review/verdict.mjs';

// --- Constants --------------------------------------------------------------

/** GitHub's ceiling on jobs one matrix may generate. */
export const MAX_JOBS = 256;

/** How far, in lines, a finding may sit from an accepted one and locate it. */
export const LINE_WINDOW = 10;

/** OCR on Demand's own settings (ocr-review.yml, the pinned action's
 * defaults), so a bake-off run reviews exactly as production would. */
export const OCR_SETTINGS = Object.freeze({
  extraBody: '{"thinking": {"type": "disabled"}, "stream": true}',
  language: 'English',
  llmTimeoutSeconds: '300',
  taskTimeoutMinutes: '15',
  token: 'ollama',
});

export const RECORD_VERSION = 1;

const SHA = /^[0-9a-f]{40}$/;
/** An ollama model reference: registry host, namespace, name and tag. */
const MODEL_NAME = /^[A-Za-z0-9][A-Za-z0-9._:/-]*$/;

// --- Cases and models -------------------------------------------------------

/** The cases document -> its cases, validated. Throws naming the defect. */
export function parseCases(text) {
  let doc;
  try {
    doc = JSON.parse(String(text));
  } catch {
    throw new Error('cases: not JSON');
  }
  if (!Array.isArray(doc?.cases)) throw new Error('cases: no "cases" array');
  const seen = new Set();
  for (const c of doc.cases) {
    if (!c?.id || typeof c.id !== 'string') throw new Error('cases: a case has no id');
    if (seen.has(c.id)) throw new Error(`cases: duplicate id ${c.id}`);
    seen.add(c.id);
    if (!SHA.test(c.base ?? '')) throw new Error(`cases: ${c.id} has no full base SHA`);
    if (!SHA.test(c.head ?? '')) throw new Error(`cases: ${c.id} has no full head SHA`);
    if (!Array.isArray(c.accepted) || c.accepted.length === 0) throw new Error(`cases: ${c.id} has no accepted findings`);
  }
  return doc.cases;
}

/** The dispatch's model list (one per line or comma) -> names, in order. */
export function parseModels(text) {
  const names = [
    ...new Set(
      String(text ?? '')
        .split(/[\n,]/)
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
  if (names.length === 0) throw new Error('no model to compare');
  for (const name of names) if (!MODEL_NAME.test(name)) throw new Error(`not a model name: ${JSON.stringify(name)}`);
  return names;
}

/** The cases a dispatch asked for: a comma list of ids, empty for all. */
export function selectCases(cases, only) {
  const ids = String(only ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  if (ids.length === 0) return cases;
  return ids.map((id) => {
    const found = cases.find((c) => c.id === id);
    if (!found) throw new Error(`unknown case: ${id}`);
    return found;
  });
}

// --- Matrix -----------------------------------------------------------------

/** One job per (model, case), model-major: the gateway holds one model, so
 * each model loads once and its first case carries the cold load. */
export function buildMatrix(models, cases) {
  const total = models.length * cases.length;
  if (total > MAX_JOBS) throw new Error(`${total} jobs exceeds the ${MAX_JOBS} one matrix allows; narrow the cases`);
  const include = models.flatMap((model, m) =>
    cases.map((c, i) => ({
      key: `m${m + 1}-${c.id}`,
      model,
      case: c.id,
      repo: c.repo,
      base: c.base,
      head: c.head,
      first_for_model: i === 0,
    })),
  );
  return { include };
}

// --- ocr invocation ---------------------------------------------------------

/** `ocr config set` argument lists, as the pinned action's Configure OCR
 * step writes them for OCR on Demand's inputs. */
export function configArgs({ url, model }) {
  return [
    ['config', 'unset', 'provider'],
    ['config', 'set', 'llm.auth_token', ''],
    ['config', 'set', 'llm.extra_headers', ''],
    ['config', 'set', 'llm.retry_codes', ''],
    ['config', 'set', 'llm.url', `${url.replace(/\/+$/, '')}/v1`],
    ['config', 'set', 'llm.model', model],
    ['config', 'set', 'llm.use_anthropic', 'false'],
    ['config', 'set', 'llm.protocol', 'openai'],
    ['config', 'set', 'llm.auth_header', ''],
    ['config', 'set', 'llm.auth_token_cmd', 'printf "%s" "$OCR_LLM_TOKEN"'],
    ['config', 'set', 'llm.extra_body', OCR_SETTINGS.extraBody],
    ['config', 'set', 'language', OCR_SETTINGS.language],
  ];
}

/** The review command over one case's range, as the action's Run step forms it. */
export function reviewArgs({ base, head }) {
  return ['review', '--from', base, '--to', head, '--audience', 'agent', '--format', 'json', '--timeout', OCR_SETTINGS.taskTimeoutMinutes];
}

// --- Scoring ----------------------------------------------------------------

/** A line number ocr or GitHub actually reported; ocr writes 0 for none. */
const isLine = (n) => Number.isInteger(n) && n > 0;

const span = (start, end) => {
  const a = isLine(start) ? start : end;
  const b = isLine(end) ? end : start;
  return isLine(a) ? [Math.min(a, b), Math.max(a, b)] : null;
};

/** Per accepted finding, whether some finding locates it. */
export function locate(accepted, findings, window = LINE_WINDOW) {
  return accepted.map((a) => {
    const target = span(a.start_line, a.line);
    if (!target) return false;
    return findings.some((f) => {
      if (f?.path !== a.path) return false;
      const got = span(f.start_line, f.end_line);
      return got !== null && got[0] <= target[1] + window && got[1] >= target[0] - window;
    });
  });
}

/** The fields of a finding worth keeping for judgment. */
const keep = (f) => ({
  path: f.path,
  start_line: f.start_line ?? null,
  end_line: f.end_line ?? null,
  severity: f.severity ?? null,
  category: f.category ?? null,
  content: f.content ?? '',
  existing_code: f.existing_code ?? '',
});

/** One run's record. `exit` is { code, timedOut } from the review, or, when
 * ocr never reviewed: { setupFailed: true } (a step before the probe
 * failed), { probeFailed: cause } (the gateway probe failed) or
 * { configFailed: { setting, why } } (an `ocr config` call failed). */
export function buildRunRecord({ entry, kase, exit, resultText, probeSeconds, reviewSeconds }) {
  const base = {
    record_version: RECORD_VERSION,
    key: entry.key,
    model: entry.model,
    case: entry.case,
    cold: Boolean(entry.first_for_model),
    probe_seconds: probeSeconds,
    review_seconds: reviewSeconds,
  };
  const failed = (outcome, detail) => ({
    ...base,
    outcome,
    detail,
    findings_total: 0,
    findings: [],
    files_reviewed: [],
    located: kase.accepted.map(() => false),
  });
  if (exit.setupFailed) return failed('setup-failed', 'a step before the probe failed (tools, checkout, credentials or the ocr install)');
  if (exit.configFailed) return failed('engine-error', `ocr config ${exit.configFailed.setting} ${exit.configFailed.why}`);
  if (exit.probeFailed !== undefined) return failed('probe-failed', `the gateway probe failed: ${exit.probeFailed || 'no cause reported'}`);
  if (exit.timedOut) return failed('timeout', 'the review outlived what was left of the job budget');
  if (exit.code !== 0) return failed('engine-error', `ocr exited ${exit.code}`);
  const engine = readEngineResult(resultText);
  if (!engine.ok) return failed('engine-error', `ocr's result lacks: ${engine.missing.join(', ')}`);
  return {
    ...base,
    outcome: 'complete',
    detail: null,
    findings_total: engine.findings.length,
    findings: engine.findings.map(keep),
    files_reviewed: engine.reviewed,
    located: locate(kase.accepted, engine.findings),
  };
}

// --- Collation --------------------------------------------------------------

const median = (xs) => {
  if (xs.length === 0) return null;
  const s = [...xs].sort((a, b) => a - b);
  const mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : Math.round((s[mid - 1] + s[mid]) / 2);
};

/** Per-model rows over every expected run; a run with no record is the
 * failure `no-record` (its job died before writing one). */
export function collate(records, { models, cases }) {
  const expected = buildMatrix(models, cases).include;
  const byKey = new Map(records.filter((r) => r?.record_version === RECORD_VERSION).map((r) => [r.key, r]));
  const missing = expected.filter((e) => !byKey.has(e.key)).map((e) => e.key);
  const rows = models.map((model) => {
    const runs = expected.filter((e) => e.model === model);
    const row = { model, runs: runs.length, complete: 0, failures: {}, located: 0, accepted: 0, findings: 0 };
    const reviewTimes = [];
    let coldProbe = null;
    for (const e of runs) {
      const kase = cases.find((c) => c.id === e.case);
      row.accepted += kase.accepted.length;
      const r = byKey.get(e.key);
      if (!r) {
        row.failures['no-record'] = (row.failures['no-record'] ?? 0) + 1;
        continue;
      }
      if (r.outcome === 'complete') row.complete += 1;
      else row.failures[r.outcome] = (row.failures[r.outcome] ?? 0) + 1;
      row.located += r.located.filter(Boolean).length;
      row.findings += r.findings_total;
      if (r.outcome === 'complete') reviewTimes.push(r.review_seconds);
      if (r.cold) coldProbe = r.probe_seconds;
    }
    row.cold_probe_seconds = coldProbe;
    row.median_review_seconds = median(reviewTimes);
    return row;
  });
  return { rows, missing };
}

const failuresText = (failures) =>
  Object.entries(failures)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .map(([cause, n]) => `${cause} ${n}`)
    .join(', ') || '-';

const cell = (v) => (v === null || v === undefined ? '-' : String(v));

/** The job-summary report: one row per model, then the missing runs. */
export function renderReport({ rows, missing }) {
  const out = [
    '## OCR bake-off',
    '',
    'Located = an accepted Copilot/Codex finding with a model finding on the same file within ' +
      `${LINE_WINDOW} lines; whether it names the same defect is judged from bakeoff-results.json.`,
    '',
    '| model | runs | complete | failures | located | findings | cold load s | median review s |',
    '|---|---|---|---|---|---|---|---|',
    ...rows.map(
      (r) =>
        `| ${r.model} | ${r.runs} | ${r.complete} | ${failuresText(r.failures)} | ${r.located} / ${r.accepted} | ${r.findings} | ${cell(r.cold_probe_seconds)} | ${cell(r.median_review_seconds)} |`,
    ),
    '',
  ];
  if (missing.length > 0) out.push(`Runs without a record: ${missing.join(', ')}`, '');
  return `${out.join('\n')}\n`;
}
