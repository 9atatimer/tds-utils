// lib/ocr-review/host-tools.mjs -- OCR on Demand: the host tools the review
// job takes from its runner (docs/design/OCR-ON-DEMAND.DESIGN.md: State
// Machine, FAILED from AUTHORIZED; Key Decisions, runner tools row;
// tds-utils#446).
//
// The review job runs on the caller's CI_RUNS_ON pool or on a GitHub-hosted
// runner, and installs nothing those images lack but the 1Password CLI. The
// rule, by owner ruling 2026-10-13: use the runner's `op` when it is on
// PATH (the pool image bakes a verified one in), install it otherwise. The
// pinned install action needs gpg (signature check) and unzip, so those are
// needed only on the install path; git is needed always (bin/ocr-review's
// verdict and the upstream action). A needed tool that is absent fails the
// run `runner-tool-missing`, naming it, before any credential is loaded.
//
// Pure: bin/ocr-review looks the tools up on PATH and passes the answers in.

// --- Constants --------------------------------------------------------------

/** The tools the check reports, in report order. */
export const HOST_TOOLS = Object.freeze(['git', 'unzip', 'gpg', 'op']);

/** Needed whichever way op arrives. */
const ALWAYS_NEEDED = Object.freeze(['git']);

/** Needed only to install the 1Password CLI (the pinned install action). */
const INSTALL_NEEDS = Object.freeze(['unzip', 'gpg']);

// --- Predicates -------------------------------------------------------------

/** True when the runner has no op, so the job must install it. */
export function shouldInstallOp(present) {
  return !present.op;
}

// --- Pure helpers -----------------------------------------------------------

/** The tools the chosen path needs, in report order. */
function toolsNeeded({ installOp }) {
  const needed = new Set([...ALWAYS_NEEDED, ...(installOp ? INSTALL_NEEDS : [])]);
  return HOST_TOOLS.filter((tool) => needed.has(tool));
}

/**
 * The check over `present` ({ tool: boolean } for each of HOST_TOOLS).
 * Returns { ok: true, installOp, missing: [] } or { ok: false, installOp,
 * missing, cause: 'runner-tool-missing', detail } where detail names the
 * missing tools, comma-separated.
 */
export function checkHostTools(present) {
  const installOp = shouldInstallOp(present);
  const missing = toolsNeeded({ installOp }).filter((tool) => !present[tool]);
  if (missing.length === 0) return { ok: true, installOp, missing };
  return { ok: false, installOp, missing, cause: 'runner-tool-missing', detail: missing.join(', ') };
}

/** One line saying, per tool, whether the runner has it. */
export function describeHostTools(present) {
  return HOST_TOOLS.map((tool) => `${tool} ${present[tool] ? 'present' : 'missing'}`).join(', ');
}
