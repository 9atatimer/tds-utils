/// <reference types="node" />
// browser.ts -- Chromium with the built extension loaded unpacked and the
// REAL native-messaging host registered, on a throw-away home.
//
// The host manifest is written by the daemon's own installer
// (`dynomark-daemon install-host-manifest --browser chromium`) with HOME set
// to that home, and Chromium runs with that same home and with its user data
// dir at the directory the installer wrote into. Chromium reads per-user host
// manifests from <user-data-dir>/NativeMessagingHosts when given a custom
// --user-data-dir (the extension's e2e found this; verified on Chromium /
// Linux), so the installer's output is exactly what the browser reads -- the
// manifest, its `path` to dynomark-host and its `allowed_origins` for the
// pinned extension id are all under test. Nothing outside the home is
// touched.
//
// Which Chromium: $DYNOMARK_CHROMIUM when set; else the build @playwright/test
// expects when it is installed (CI: `npx playwright install chromium`); else
// the newest chromium-* build under $PLAYWRIGHT_BROWSERS_PATH. Never branded
// Chrome: it ignores --load-extension under automation.

import { execFileSync } from 'node:child_process';
import { existsSync, readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { chromium, type BrowserContext, type Page, type Worker } from '@playwright/test';
import { homeEnv } from './daemon.js';
import { DAEMON_BIN, EXTENSION_DIST } from './paths.js';

// --- Constants ---

/** The id the extension manifest's public key pins (extension README, "Extension id"). */
export const PINNED_EXTENSION_ID = 'iiflkiojolkdbmlgfbdfeobinoinnfjp';

const CHROMIUM_BINARIES = [
  ['chrome-linux', 'chrome'],
  ['chrome-linux64', 'chrome'],
  ['chrome-mac', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'],
  ['chrome-mac-arm64', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'],
];

// --- Types ---

export interface Browser {
  readonly context: BrowserContext;
  /** The user data dir: where the installer put NativeMessagingHosts/. */
  readonly userDataDir: string;
  /** The extension's running service worker. */
  serviceWorker(): Promise<Worker>;
  /** A page of the extension (e.g. history.html). */
  extensionPage(path: string): Promise<Page>;
  /** Terminate every service worker, as the browser does to an idle one. */
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

/** Run the daemon's installer for Chromium under `home`; the manifest path it wrote. */
function installHostManifest(home: string): string {
  const out = execFileSync(
    join(DAEMON_BIN, 'dynomark-daemon'),
    [
      'install-host-manifest',
      '--extension-id',
      PINNED_EXTENSION_ID,
      '--browser',
      'chromium',
      '--host-path',
      join(DAEMON_BIN, 'dynomark-host'),
    ],
    { env: homeEnv(home), encoding: 'utf8' },
  );
  const written = out.trim().split('\n').at(-1);
  if (written === undefined || !written.endsWith('tds.dynomark.json')) throw new Error(`install-host-manifest wrote: ${out}`);
  return written;
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

/** Launch Chromium on `home` with the extension (dist/ must be built) and the real host registered. */
export async function launchBrowser(home: string): Promise<Browser> {
  if (!existsSync(join(EXTENSION_DIST, 'manifest.json'))) throw new Error('extension dist/ is not built (global setup builds it)');
  const userDataDir = dirname(dirname(installHostManifest(home)));
  const executablePath = chromiumPath();
  const context = await chromium.launchPersistentContext(userDataDir, {
    headless: true,
    env: homeEnv(home),
    ...(executablePath === undefined ? {} : { executablePath }),
    args: [`--disable-extensions-except=${EXTENSION_DIST}`, `--load-extension=${EXTENSION_DIST}`],
  });
  // No network: only the 127.0.0.1 test server is reachable.
  await context.route(
    (url) => /^(https?|wss?):$/.test(url.protocol) && url.hostname !== '127.0.0.1',
    (route) => route.abort('internetdisconnected'),
  );
  const serviceWorker = async (): Promise<Worker> =>
    context.serviceWorkers().find((w) => w.url().includes(PINNED_EXTENSION_ID)) ??
    (await context.waitForEvent('serviceworker', (w) => w.url().includes(PINNED_EXTENSION_ID)));
  await serviceWorker();
  return {
    context,
    userDataDir,
    serviceWorker,
    extensionPage: async (path) => {
      const page = await context.newPage();
      await page.goto(`chrome-extension://${PINNED_EXTENSION_ID}/${path}`);
      return page;
    },
    stopServiceWorkers: () => stopWorkers(context),
    close: () => context.close(),
  };
}
