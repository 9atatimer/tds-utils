/// <reference types="node" />
// daemon.ts -- the REAL daemon, run from dynomark/daemon with `uv run`, on a
// throw-away home: its config file, state directory (store, log) and socket
// all live under that home (one store per host id, as two hosts would
// have), exactly where `dynomark-daemon serve` puts them
// on a laptop. Only the models are fakes: the daemon's test-support entry
// point (dynomark_daemon.testing.e2e) serves the production composition with
// HashingEmbedding and a ScriptedCompletion answering from `script`.
//
// The socket is named in the config file ([socket] path), not in the
// environment, because the browser starts dynomark-host with its own
// environment and the host finds the socket through the same config file.

import { execFileSync, spawn, type ChildProcess } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { connect } from 'node:net';
import { isAbsolute, join } from 'node:path';
import { DAEMON_DIR } from './paths.js';

// --- Types ---

export type HostRole = 'writer' | 'reader';

/** A contract v1 FolderPath. */
export interface FolderPath {
  readonly root: 'bar' | 'other' | 'mobile' | 'menu';
  readonly names: readonly string[];
}

/** A contract v1 Operation, as a scripted diff item carries it. */
export type Operation =
  | { readonly op: 'create_folder'; readonly index: number; readonly parent: FolderPath; readonly title: string }
  | { readonly op: 'create'; readonly index: number; readonly parent: FolderPath; readonly title: string; readonly url: string };

/** What the fake completion answers, per method, in order (dynomark_daemon/testing/e2e.py). */
export interface Script {
  readonly enrich?: readonly { readonly summary: string; readonly tags: readonly string[] }[];
  readonly choose_folder?: readonly { readonly folder: FolderPath; readonly rationale: string }[];
  readonly answer?: readonly { readonly text: string; readonly cited: readonly string[]; readonly urls: readonly string[] }[];
  readonly propose_diff?: readonly (readonly {
    readonly action: 'add' | 'move' | 'merge';
    readonly description: string;
    readonly operations: readonly Operation[];
  }[])[];
}

export interface DaemonOptions {
  readonly role: HostRole;
  readonly hostId: string;
  readonly script: Script;
}

/** One JSON line of the daemon's structlog file. */
export type LogEvent = Readonly<Record<string, unknown>> & { readonly event: string };

// --- Constants ---

const READY_TIMEOUT_MS = 30_000;
const STOP_TIMEOUT_MS = 10_000;
const POLL_MS = 50;
/** Environment the daemon must not inherit: it would move files out of the throw-away home. */
const LEAKY = /^(XDG_[A-Z_]+|DYNOMARK_SOCKET|OLLAMA_HOST)$/;

// --- Pure helpers ---

function toml(options: DaemonOptions, home: string, socket: string): string {
  return [
    `role = "${options.role}"`,
    `host_id = "${options.hostId}"`,
    '',
    '[store]',
    `path = "${join(home, `store-${options.hostId}.sqlite3`)}"`,
    '',
    '[socket]',
    `path = "${socket}"`,
    '',
    '[retry]',
    'attempts = 2',
    'initial_backoff_ms = 500',
    'max_backoff_ms = 1000',
    '',
  ].join('\n');
}

/** The environment a process under `home` runs with: the caller's, minus what would escape `home`. */
export function homeEnv(home: string, extra: Readonly<Record<string, string>> = {}): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(process.env)) {
    if (value !== undefined && !LEAKY.test(key)) env[key] = value;
  }
  return { ...env, HOME: home, ...extra };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- Effectful helpers ---

function listening(socket: string): Promise<boolean> {
  return new Promise((resolve) => {
    const probe = connect(socket);
    probe.once('connect', () => {
      probe.destroy();
      resolve(true);
    });
    probe.once('error', () => resolve(false));
  });
}

let uvCache: string | undefined;

/** uv's own cache, kept outside the throw-away home so `uv run` does not re-resolve there. */
function uvCacheDir(): string {
  // --color never: the Playwright runner sets FORCE_COLOR, and a colored path would be taken as a relative one.
  uvCache ??= execFileSync('uv', ['--color', 'never', 'cache', 'dir'], { cwd: DAEMON_DIR, encoding: 'utf8' }).trim();
  if (!isAbsolute(uvCache)) throw new Error(`uv cache dir is not an absolute path: ${JSON.stringify(uvCache)}`);
  return uvCache;
}

// --- The daemon ---

export class RealDaemon {
  private exited = false;
  private readonly stderr: string[] = [];

  private constructor(
    private readonly child: ChildProcess,
    readonly home: string,
    readonly socket: string,
    readonly options: DaemonOptions,
  ) {
    child.stderr?.on('data', (chunk: Buffer) => this.stderr.push(chunk.toString('utf8')));
    child.once('exit', () => (this.exited = true));
  }

  /** The daemon's structlog file (JSON lines). */
  get logPath(): string {
    return join(this.home, '.local', 'state', 'dynomark', 'daemon.log');
  }

  /** Write the config and script under `home`, start the daemon, and wait until its socket answers. */
  static async start(home: string, socket: string, options: DaemonOptions): Promise<RealDaemon> {
    const configDir = join(home, '.config', 'dynomark');
    mkdirSync(configDir, { recursive: true });
    writeFileSync(join(configDir, 'config.toml'), toml(options, home, socket));
    const script = join(home, `script-${options.hostId}.json`);
    writeFileSync(script, JSON.stringify(options.script));
    const child = spawn('uv', ['run', '--frozen', '--no-sync', 'python', '-m', 'dynomark_daemon.testing.e2e', '--script', script], {
      cwd: DAEMON_DIR,
      env: homeEnv(home, { UV_CACHE_DIR: uvCacheDir() }),
      stdio: ['ignore', 'ignore', 'pipe'],
    });
    const daemon = new RealDaemon(child, home, socket, options);
    await daemon.ready();
    return daemon;
  }

  private async ready(): Promise<void> {
    const deadline = Date.now() + READY_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (this.exited) throw new Error(`the daemon exited before listening:\n${this.stderr.join('')}`);
      if (existsSync(this.socket) && (await listening(this.socket))) return;
      await delay(POLL_MS);
    }
    throw new Error(`the daemon did not listen on ${this.socket} within ${READY_TIMEOUT_MS} ms:\n${this.stderr.join('')}`);
  }

  /** Every event logged so far. */
  log(): LogEvent[] {
    if (!existsSync(this.logPath)) return [];
    return readFileSync(this.logPath, 'utf8')
      .split('\n')
      .filter((line) => line.trim() !== '')
      .map((line) => JSON.parse(line) as LogEvent);
  }

  /** The first logged event `match` accepts, waiting up to `timeoutMs`. */
  async waitForLog(match: (event: LogEvent) => boolean, timeoutMs = 30_000): Promise<LogEvent> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const found = this.log().find(match);
      if (found !== undefined) return found;
      if (this.exited) break;
      await delay(POLL_MS);
    }
    throw new Error(`no matching daemon log event within ${timeoutMs} ms; stderr:\n${this.stderr.join('')}`);
  }

  /** SIGTERM, as launchd stops it; SIGKILL if it does not exit in time. */
  async stop(): Promise<void> {
    if (this.exited) return;
    const exit = new Promise<void>((resolve) => this.child.once('exit', () => resolve()));
    this.child.kill('SIGTERM');
    const timer = setTimeout(() => this.child.kill('SIGKILL'), STOP_TIMEOUT_MS);
    await exit;
    clearTimeout(timer);
  }
}
