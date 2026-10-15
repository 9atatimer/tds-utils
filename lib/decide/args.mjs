// lib/decide/args.mjs -- decide: the command line (docs/ops/decide.md,
// "Usage"). The contract other tools build against:
//
//   decide run   [--model M] [--tool T] [--jsonl] [--concurrency N] [--file PATH]
//   decide probe [--model M]
//   decide --help
//
// Flags take `--flag value` or `--flag=value`. Pure.

import { DEFAULT_CONCURRENCY, MAX_CONCURRENCY } from './backend.mjs';

// --- Constants --------------------------------------------------------------

export const USAGE = `usage: decide run   [--model M] [--tool T] [--jsonl] [--concurrency N] [--file PATH]
       decide probe [--model M]
       decide --help

Ask a decision model typed questions (noul, choice, score); get probabilities.
  run     one record JSON ({"state", "questions", "images"?, "id"?}) from
          --file or stdin -> one decision JSON on stdout; with --jsonl, one
          record per line -> one decision per line, in input order, up to
          --concurrency (default ${DEFAULT_CONCURRENCY}, max ${MAX_CONCURRENCY}) in flight.
  probe   one tiny yes/no question -> {"ok", "model", "latency_ms"}.

Environment: DECIDE_BACKEND (cf-ai-gateway | systemone), DECIDE_GATEWAY_URL,
DECIDE_GATEWAY_TOKEN or DECIDE_GATEWAY_OP_ITEM, DECIDE_URL (systemone),
DECIDE_MODEL (clef | clef-flash), DECIDE_TOOL, DECIDE_TIMEOUT_MS,
DECIDE_LOG_PAYLOAD=1.
Exit: 0 ok, 2 config, 3 rejected, 4 unavailable, 5 auth, 6 malformed.
See docs/ops/decide.md.
`;

/** The flags each command accepts; true = takes a value. */
const COMMAND_FLAGS = Object.freeze({
  run: { model: true, tool: true, jsonl: false, concurrency: true, file: true },
  probe: { model: true, tool: true },
});

// --- Pure helpers -----------------------------------------------------------

const argFailure = (message) => ({ ok: false, error: { class: 'config', message, status: null } });

function parseConcurrency(raw) {
  if (raw === undefined) return DEFAULT_CONCURRENCY;
  if (!/^[1-9][0-9]*$/.test(raw)) return null;
  const n = Number(raw);
  return n <= MAX_CONCURRENCY ? n : null;
}

/**
 * Parse argv (without node and the script). Returns
 * { ok: true, command: 'help' } or { ok: true, command, flags } where flags
 * is { model?, tool?, jsonl, concurrency, file? }, or a config failure.
 */
export function parseArgs(argv) {
  if (argv.some((arg) => arg === '--help' || arg === '-h')) return { ok: true, command: 'help' };
  const [command, ...rest] = argv;
  if (!command) return argFailure('no command; expected run or probe');
  const accepted = COMMAND_FLAGS[command];
  if (!accepted) return argFailure(`unknown command "${command}"; expected run or probe`);
  const flags = { jsonl: false };
  for (let i = 0; i < rest.length; i += 1) {
    const match = /^--([a-z]+)(?:=(.*))?$/s.exec(rest[i]);
    if (!match || !(match[1] in accepted)) return argFailure(`unknown argument "${rest[i]}" for ${command}`);
    const [, name, inline] = match;
    if (!accepted[name]) {
      if (inline !== undefined) return argFailure(`--${name} takes no value`);
      flags[name] = true;
      continue;
    }
    const value = inline ?? rest[i + 1];
    if (inline === undefined) i += 1;
    if (value === undefined || value === '') return argFailure(`--${name} needs a value`);
    flags[name] = value;
  }
  const concurrency = parseConcurrency(flags.concurrency);
  if (concurrency === null) return argFailure(`--concurrency must be an integer from 1 to ${MAX_CONCURRENCY}`);
  return { ok: true, command, flags: { ...flags, concurrency } };
}
