/// <reference types="chrome" />
/// <reference types="node" />
// chromeAdapters.test.ts -- the port contract suites, unchanged, against the
// real chrome adapters in a real Chromium: each adapter method runs in an
// extension page (test/support/remote.ts) of a copy of the built extension
// with no background worker, so nothing else touches the profile. The
// transport runs against a real native-messaging host (the pipe host) over a
// real unix socket. HistoryPort cannot run its contract for real: Chrome
// records a visit only at the current time, so its own checks follow.
//
// Integration: needs dist/ built and a Chromium (test/support/browser.ts);
// hermetic (temp profile and socket; every page it opens is routed).

import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { Page } from '@playwright/test';
import { launchExtension, type Launched } from '../support/browser.js';
import { ManualDaemon } from '../support/manualDaemon.js';
import {
  RemoteBookmarkTree,
  RemoteEvents,
  RemoteHistory,
  RemoteStorage,
  RemoteTabContent,
  RemoteTransport,
  resetBookmarks,
} from '../support/remote.js';
import { describeBookmarkTreeContract } from '../port-contracts/bookmarkTree.contract.js';
import { describeContentSourceContract } from '../port-contracts/contentSource.contract.js';
import { describeStorageContract } from '../port-contracts/storage.contract.js';
import { describeTransportContract } from '../port-contracts/transport.contract.js';

// --- Constants ---

const CONTRACT_HOST = 'tds.dynomark_contract';

// --- One browser for the file ---
// beforeAll, not beforeEach: launching Chromium per test would cost ~1 s x 40.
// Hermeticity is kept per test instead: every make() below resets what its
// port touches (bookmarks, a fresh storage key prefix, tabs and routes, a
// fresh transport instance).

let ext: Launched;
let page: Page;
let daemon: ManualDaemon;
let events: RemoteEvents;
let prefixes = 0;
let socketDir: string;

beforeAll(async () => {
  socketDir = mkdtempSync(join(tmpdir(), 'dmc-'));
  daemon = await ManualDaemon.listen(join(socketDir, 'c.sock'));
  ext = await launchExtension({
    manifest: ({ background: _none, ...rest }) => rest,
    files: { 'harness.html': '<!doctype html><title>adapter harness</title>' },
    hosts: { [CONTRACT_HOST]: daemon.socketPath },
  });
  page = await ext.extensionPage('harness.html');
  events = await RemoteEvents.expose(page, (event) => daemon.delivered(event.event_id));
});

afterAll(async () => {
  await ext.close();
  await daemon.close();
  rmSync(socketDir, { recursive: true, force: true });
});

/** Close every tab but the harness and drop every route: no page but the ones a test opens. */
async function resetTabs(): Promise<void> {
  await ext.context.unrouteAll();
  for (const other of ext.context.pages()) if (other !== page) await other.close();
}

// --- Contract suites, run for real ---

describeBookmarkTreeContract('ChromeBookmarkTree (real chrome.bookmarks)', () => new RemoteBookmarkTree(page, resetBookmarks(page)));

describeStorageContract('ChromeStorage (real chrome.storage.local)', () => {
  prefixes += 1;
  return new RemoteStorage(page, `contract-${prefixes}:`);
});

describeContentSourceContract('ChromeTabContent (real chrome.tabs and chrome.scripting)', () => {
  const ready = resetTabs();
  return {
    content: new RemoteTabContent(page, ready),
    openTab: async (url, content) => {
      await ready;
      const html = `<!doctype html><title>${content.title}</title><body><nav>menu</nav><main>${content.text}</main></body>`;
      await ext.context.route(url, (route) => route.fulfill({ status: 200, contentType: 'text/html', body: html }));
      await (await ext.context.newPage()).goto(url);
    },
    openUnreadableTab: async (url) => {
      await ready;
      await ext.context.route(url, (route) => route.abort());
      await (await ext.context.newPage()).goto(url).catch(() => undefined);
    },
  };
});

describeTransportContract('NativeMessagingTransport (real native messaging, pipe host, unix socket)', () => {
  daemon.reset();
  return { transport: new RemoteTransport(page, CONTRACT_HOST, events), daemon: daemon.end };
});

// --- HistoryPort, for real (visit times cannot be chosen) ---

describe('ChromeHistory (real chrome.history)', () => {
  it('Given a URL visited now, When its visits are read, Then one visit comes back, timed now, and a variant of it has none', async () => {
    const history = new RemoteHistory(page);
    const before = Date.now();
    await page.evaluate(() => chrome.history.addUrl({ url: 'https://history.test/page' }));
    const after = Date.now();
    const visits = await history.visitsTo('https://history.test/page');
    expect(visits).toHaveLength(1);
    expect(visits[0]?.visited_at).toBeGreaterThanOrEqual(before - 1_000);
    expect(visits[0]?.visited_at).toBeLessThanOrEqual(after + 1_000);
    expect(await history.visitsTo('https://history.test/page?utm_source=x')).toEqual([]);
    expect(await history.visitsTo('https://never.test/')).toEqual([]);
  });
});
