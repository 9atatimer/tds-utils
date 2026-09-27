/// <reference types="node" />
// browser.ts -- launch the built extension (dist/) unpacked in a real
// Chromium on a throw-away profile, with its native-messaging host
// registered and pointed at a fake daemon. Hermetic: a temp user-data-dir,
// a temp unix socket, no network (tests route every page they open).
//
// Where Chromium looks for a per-user host manifest when given a custom
// --user-data-dir: <user-data-dir>/NativeMessagingHosts/<name>.json (Linux
// and macOS both derive the per-user directory from the user data dir;
// verified on Chromium 141 / Linux), so the manifest is written there before
// launch and the real ~/.config is never touched.
//
// Which Chromium: $DYNOMARK_CHROMIUM when set; else the build Playwright
// expects when it is installed; else the newest chromium-* build under
// $PLAYWRIGHT_BROWSERS_PATH (the sandbox's pre-installed one). Never
// branded Chrome: it ignores --load-extension under automation.

import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium, type BrowserContext, type Page, type Worker } from '@playwright/test';
import { FakeDaemon } from './fakeDaemon.js';

// --- Constants ---

/** The extension id the manifest's public key pins (README, "Extension id"). */
export const PINNED_EXTENSION_ID = 'iiflkiojolkdbmlgfbdfeobinoinnfjp';
export const HOST_NAME = 'tds.dynomark';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST = join(ROOT, 'dist');
const PIPE_HOST = join(ROOT, 'test', 'support', 'pipe-host.mjs');
const CHROMIUM_BINARIES = [
  ['chrome-linux', 'chrome'],
  ['chrome-linux64', 'chrome'],
  ['chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'],
  ['chrome-mac-arm64', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'],
];

// --- Types ---

export interface LaunchOptions {
  /** Load a copy of dist/ with the manifest changed (e.g. no background, for adapter tests). */
  readonly manifest?: (manifest: Record<string, unknown>) => Record<string, unknown>;
  /** Extra files to add to that copy (path -> contents). */
  readonly files?: Readonly<Record<string, string>>;
  /** Native-messaging hosts to register: host name -> socket its pipe connects to. The daemon's own is always registered. */
  readonly hosts?: Readonly<Record<string, string>>;
}

export interface Launched {
  readonly context: BrowserContext;
  readonly extensionId: string;
  readonly daemon: FakeDaemon;
  readonly dir: string;
  /** The extension's running service worker. */
  serviceWorker(): Promise<Worker>;
  /** A page of the extension (e.g. options.html). */
  extensionPage(path: string): Promise<Page>;
  /** Terminate every service worker (as the browser does to an idle one) and wait for the native link to close. */
  stopServiceWorkers(): Promise<void>;
  close(): Promise<void>;
}

// --- Effectful helpers ---

function chromiumPath(): string | undefined {
  const pinned = process.env['DYNOMARK_CHROMIUM'];
  if (pinned !== undefined && pinned !== '') return pinned;
  if (existsSync(chromium.executablePath())) return undefined;
  const root = process.env['PLAYWRIGHT_BROWSERS_PATH'];
  if (root === undefined || !existsSync(root)) return undefined;
  const builds = readdirSync(root)
    .filter((name) => /^chromium-\d+$/.test(name))
    .sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
  for (const build of builds) {
    for (const parts of CHROMIUM_BINARIES) {
      const candidate = join(root, build, ...parts);
      if (existsSync(candidate)) return candidate;
    }
  }
  return undefined;
}

/** An executable that runs the pipe host with its socket fixed (a host manifest names a program, not arguments). */
function writeHostLauncher(dir: string, name: string, socket: string): string {
  const path = join(dir, `${name}.mjs`);
  const source = [
    `#!${process.execPath}`,
    `process.env.DYNOMARK_SOCKET = ${JSON.stringify(socket)};`,
    `await import(${JSON.stringify(PIPE_HOST)});`,
    '',
  ].join('\n');
  writeFileSync(path, source);
  chmodSync(path, 0o755);
  return path;
}

function registerHost(userDataDir: string, name: string, launcher: string): void {
  const dir = join(userDataDir, 'NativeMessagingHosts');
  mkdirSync(dir, { recursive: true });
  const manifest = {
    name,
    description: 'Dynomark e2e pipe host',
    path: launcher,
    type: 'stdio',
    allowed_origins: [`chrome-extension://${PINNED_EXTENSION_ID}/`],
  };
  writeFileSync(join(dir, `${name}.json`), JSON.stringify(manifest));
}

function extensionDir(dir: string, options: LaunchOptions): string {
  if (options.manifest === undefined && options.files === undefined) return DIST;
  const copy = join(dir, 'extension');
  cpSync(DIST, copy, { recursive: true });
  const manifestPath = join(copy, 'manifest.json');
  const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')) as Record<string, unknown>;
  writeFileSync(manifestPath, JSON.stringify(options.manifest?.(manifest) ?? manifest));
  for (const [path, contents] of Object.entries(options.files ?? {})) writeFileSync(join(copy, path), contents);
  return copy;
}

async function stopWorkers(context: BrowserContext): Promise<void> {
  const page = await context.newPage();
  try {
    const cdp = await context.newCDPSession(page);
    await cdp.send('ServiceWorker.enable');
    await cdp.send('ServiceWorker.stopAllWorkers');
    await cdp.detach();
  } finally {
    await page.close();
  }
}

// --- Entry ---

/** Build nothing: dist/ must be built (`npm run build`). Launch Chromium with the extension and a fake daemon. */
export async function launchExtension(options: LaunchOptions = {}): Promise<Launched> {
  if (!existsSync(join(DIST, 'manifest.json'))) throw new Error('dist/ is not built: run npm run build first');
  const dir = mkdtempSync(join(tmpdir(), 'dm-'));
  const userDataDir = join(dir, 'profile');
  const daemon = await FakeDaemon.listen(join(dir, 'd.sock'));
  for (const [name, socket] of Object.entries({ ...options.hosts, [HOST_NAME]: daemon.socketPath })) {
    registerHost(userDataDir, name, writeHostLauncher(dir, name, socket));
  }
  const extension = extensionDir(dir, options);
  const executablePath = chromiumPath();
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: true,
    // Playwright's own build: channel chromium, because plain headless means the headless shell, which loads no extension.
    ...(executablePath === undefined ? { channel: 'chromium' } : { executablePath }),
    args: [`--disable-extensions-except=${extension}`, `--load-extension=${extension}`],
  });
  const firstWorker = async (): Promise<Worker> => context.serviceWorkers()[0] ?? (await context.waitForEvent('serviceworker'));
  let extensionId = PINNED_EXTENSION_ID;
  if (options.manifest === undefined) extensionId = new URL((await firstWorker()).url()).host;
  return {
    context,
    extensionId,
    daemon,
    dir,
    serviceWorker: firstWorker,
    extensionPage: async (path) => {
      const page = await context.newPage();
      await page.goto(`chrome-extension://${extensionId}/${path}`);
      return page;
    },
    stopServiceWorkers: async () => {
      await stopWorkers(context);
      await daemon.allClosed();
    },
    close: async () => {
      await context.close();
      await daemon.close();
      rmSync(dir, { recursive: true, force: true });
    },
  };
}
