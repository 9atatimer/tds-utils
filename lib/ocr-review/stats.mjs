// lib/ocr-review/stats.mjs -- OCR on Demand: runs by outcome and failures by
// cause, per period (docs/design/OCR-ON-DEMAND.DESIGN.md: G7, Design/Stats).
//
// Run records of several record_versions coexist within retention, because
// callers pin different reusable-workflow SHAs. Each version has a reader
// below; a version with no reader is reported as unreadable, never guessed
// at. Pure: bin/ocr-review-stats fetches the records through gh.

// --- Constants --------------------------------------------------------------

const OUTCOMES = new Set(['success', 'failure', 'cancelled']);
const GRANULARITIES = new Set(['day', 'week', 'month']);

/** One reader per record_version: raw record -> { repo, outcome, cause, at }. */
const READERS = {
  1: (raw) => ({ repo: raw.repo, outcome: raw.outcome, cause: raw.cause ?? null, at: raw.finished_at ?? raw.started_at }),
};

// --- Pure helpers -----------------------------------------------------------

/** The period an ISO timestamp falls in: YYYY-MM-DD (day, or the Monday that
 * starts its ISO week) or YYYY-MM (month), in UTC. */
export function periodKey(iso, granularity) {
  if (!GRANULARITIES.has(granularity)) throw new Error(`unknown period: ${granularity}`);
  const date = new Date(iso);
  if (granularity === 'month') return date.toISOString().slice(0, 7);
  if (granularity === 'week') {
    const back = (date.getUTCDay() + 6) % 7;
    date.setUTCDate(date.getUTCDate() - back);
  }
  return date.toISOString().slice(0, 10);
}

/** A raw record (any version) -> { ok, version, repo, outcome, cause, at }
 * or { ok: false, reason }. */
export function normalizeRecord(raw) {
  if (!raw || typeof raw !== 'object') return { ok: false, reason: 'not a record' };
  const read = READERS[raw.record_version];
  if (!read) return { ok: false, reason: `record_version ${raw.record_version} is unknown` };
  const fields = read(raw);
  if (!OUTCOMES.has(fields.outcome)) return { ok: false, reason: `outcome ${fields.outcome} is unknown` };
  if (!fields.at || Number.isNaN(Date.parse(fields.at))) return { ok: false, reason: 'no timestamp' };
  return { ok: true, version: raw.record_version, ...fields };
}

/** Rows per period, oldest first: runs, per-outcome counts, failure causes. */
export function aggregate(records, granularity) {
  const rows = new Map();
  for (const record of records.filter((r) => r.ok)) {
    const period = periodKey(record.at, granularity);
    const row = rows.get(period) ?? { period, runs: 0, success: 0, failure: 0, cancelled: 0, causes: {} };
    row.runs += 1;
    row[record.outcome] += 1;
    if (record.outcome === 'failure') row.causes[record.cause ?? 'none'] = (row.causes[record.cause ?? 'none'] ?? 0) + 1;
    rows.set(period, row);
  }
  return [...rows.values()].sort((a, b) => a.period.localeCompare(b.period));
}

/** A plain-text report of the rows plus what could not be counted. */
export function renderTable(rows, { unreadable, unrecorded }) {
  const out = [];
  if (rows.length === 0) out.push('no run records in the window');
  else {
    out.push(`${'PERIOD'.padEnd(12)}${'RUNS'.padStart(6)}${'OK'.padStart(6)}${'FAIL'.padStart(6)}${'CANCEL'.padStart(8)}`);
    for (const row of rows) {
      out.push(
        `${row.period.padEnd(12)}${String(row.runs).padStart(6)}${String(row.success).padStart(6)}${String(row.failure).padStart(6)}${String(row.cancelled).padStart(8)}`,
      );
      for (const [cause, count] of Object.entries(row.causes).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))) {
        out.push(`  ${cause.padEnd(20)}${count}`);
      }
    }
  }
  out.push('', `unreadable records: ${unreadable}`, `runs without a record (skipped, or the report job failed): ${unrecorded}`);
  return `${out.join('\n')}\n`;
}
