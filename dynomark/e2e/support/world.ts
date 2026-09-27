/// <reference types="node" />
/// <reference types="chrome" />
// world.ts -- the test object every scenario gets: one throw-away home
// holding the real daemon's config, state and socket and the browser's
// profile; a 127.0.0.1 page server; Chromium with the extension and the real
// host. Torn down after the scenario, whatever happened.
//
// A scenario starts the daemon (role, host id, fake-model script) before the
// browser, as launchd does before a user opens Chrome; it may stop it and
// start another daemon on the same socket (a second host's configuration),
// and the extension reconnects to it by itself.

import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test as base, expect, type Page, type TestInfo, type Worker } from '@playwright/test';
import { launchBrowser, type Browser } from './browser.js';
import { RealDaemon, type DaemonOptions, type LogEvent } from './daemon.js';
import { servePages, type PageServer } from './pages.js';
import { Tree } from './tree.js';

export { expect };

// --- Types ---

/** The omnibox rows the background handler suggests: hits (tier and identity), then the Ask row. */
export interface Suggestion {
  readonly hits: readonly { readonly identity: string; readonly tier: string }[];
  readonly ask?: string;
}

// --- The world ---

export class World {
  readonly home = mkdtempSync(join(tmpdir(), 'dme-'));
  readonly socket = join(this.home, 'd.sock');
  private current: RealDaemon | undefined;
  private started: Browser | undefined;
  private server: PageServer | undefined;
  private treePage: Page | undefined;

  constructor(private readonly info: TestInfo) {}

  get daemon(): RealDaemon {
    if (this.current === undefined) throw new Error('no daemon started');
    return this.current;
  }

  get browser(): Browser {
    if (this.started === undefined) throw new Error('no browser launched');
    return this.started;
  }

  get pages(): PageServer {
    if (this.server === undefined) throw new Error('no pages served');
    return this.server;
  }

  /** Serve `pages` on 127.0.0.1 for this scenario. */
  async serve(pages: Readonly<Record<string, string>>): Promise<PageServer> {
    this.server = await servePages(pages);
    return this.server;
  }

  /** Start the daemon (stopping any running one), then the browser if it is not up yet. */
  async start(options: DaemonOptions): Promise<void> {
    await this.current?.stop();
    this.current = await RealDaemon.start(this.home, this.socket, options);
    if (this.started === undefined) {
      this.started = await launchBrowser(this.home);
      if (process.env['DM_DEBUG']) {
        const w = await this.started.serviceWorker();
        w.on('console', (m) => console.log('SW', m.type(), m.text().slice(0, 400)));
      }
    }
  }

  /** Stop the running daemon (SIGTERM), leaving the browser up. */
  async stopDaemon(): Promise<void> {
    await this.current?.stop();
  }

  /** The bookmark tree, read and edited from a long-lived extension page. */
  async tree(): Promise<Tree> {
    if (this.treePage === undefined || this.treePage.isClosed()) this.treePage = await this.browser.extensionPage('history.html');
    return new Tree(this.treePage);
  }

  /** The extension's service worker, restarting it if the browser stopped it. */
  async worker(): Promise<Worker> {
    const live = this.browser.context.serviceWorkers().at(-1);
    if (live !== undefined) return live;
    const next = this.browser.context.waitForEvent('serviceworker');
    await this.browser.extensionPage('options.html');
    return next;
  }

  /** Open `url` in a tab, as the user reading the page they are about to save. */
  async openTab(url: string): Promise<Page> {
    const tab = await this.browser.context.newPage();
    await tab.goto(url);
    return tab;
  }

  /** Save `url` the way the user does: open it in a tab, then bookmark it into Follow Up (Ctrl+D). The new node's id. */
  async save(url: string, title: string): Promise<string> {
    const tree = await this.tree();
    await until(
      () => tree.titles([]),
      (titles) => titles.includes('Follow Up'),
    );
    await this.openTab(url);
    return tree.create(['Follow Up'], title, url);
  }

  /** Save `url` and wait until the node is filed at `into`; the node's id. */
  async saveAndFile(url: string, title: string, into: readonly string[]): Promise<string> {
    const node = await this.save(url, title);
    const tree = await this.tree();
    await until(
      () => tree.pathOf(node),
      (p) => p?.join('/') === into.join('/'),
    );
    return node;
  }

  /** Ask the background what an extension page asks it (the pages' runtime-message channel); the raw answer. */
  async pageRequest(request: Readonly<Record<string, unknown>>): Promise<Record<string, unknown>> {
    if (this.treePage === undefined || this.treePage.isClosed()) await this.tree();
    const page = this.treePage as Page;
    return page.evaluate(async (r) => (await chrome.runtime.sendMessage({ dynomark_page: r })) as Record<string, unknown>, request);
  }

  /** Feed `text` to the omnibox handler (headless has no address bar) and collect what it suggests within `settleMs`. */
  async omnibox(text: string, settleMs = 1_500): Promise<Suggestion[]> {
    const worker = await this.worker();
    return worker.evaluate(
      async ({ query, settle }) => {
        const runtime = (
          globalThis as unknown as {
            dynomark: {
              omniboxInput(t: string, s: (rows: { hits: readonly { identity: string; tier: string }[]; ask?: string }) => void): void;
            };
          }
        ).dynomark;
        const seen: { hits: { identity: string; tier: string }[]; ask?: string }[] = [];
        runtime.omniboxInput(query, (rows) =>
          seen.push({
            hits: rows.hits.map((h) => ({ identity: h.identity, tier: h.tier })),
            ...(rows.ask === undefined ? {} : { ask: rows.ask }),
          }),
        );
        await new Promise((resolve) => setTimeout(resolve, settle));
        return seen;
      },
      { query: text, settle: settleMs },
    );
  }

  /** Record the Goal 2 intervals (ingest received -> APPLIED) the daemon logged, in the test output. */
  reportGoal2(): number[] {
    const intervals = this.daemon
      .log()
      .filter((e: LogEvent) => e.event === 'job.applied' && typeof e['interval_ms'] === 'number')
      .map((e) => e['interval_ms'] as number);
    for (const ms of intervals) {
      this.info.annotations.push({ type: 'Goal 2 interval (ingest received -> APPLIED)', description: `${ms} ms` });
      console.log(`Goal 2: ingest received -> APPLIED in ${ms} ms (daemon log, job.applied)`);
    }
    return intervals;
  }

  /**
   * What went wrong between the runtimes without failing a scenario's own
   * assertions: the extension's reported problems (settings page) and every
   * daemon log event at warning or above.
   */
  async interopProblems(): Promise<string[]> {
    const found: string[] = [];
    if (this.started !== undefined) {
      const options = await this.started.extensionPage('options.html');
      await expect(options.locator('#link')).toHaveText('connected');
      found.push(...(await options.locator('#problems li').allTextContents()).map((p) => `extension: ${p}`));
      await options.close();
    }
    for (const event of this.current?.log() ?? []) {
      if (event['level'] !== 'info' && event['level'] !== 'debug') found.push(`daemon: ${JSON.stringify(event)}`);
    }
    return found;
  }

  async close(): Promise<void> {
    if (process.env['DM_DEBUG']) {
      for (const e of this.current?.log() ?? []) if (e['level'] !== 'info') console.log('DAEMON', JSON.stringify(e).slice(0, 600));
      for (const e of this.current?.log() ?? []) if (e.event === 'job.ran') console.log('JOB', JSON.stringify(e).slice(0, 300));
    }
    await this.started?.close().catch(() => undefined);
    await this.current?.stop();
    await this.server?.close();
    rmSync(this.home, { recursive: true, force: true });
  }
}

// --- The fixture ---

export const test = base.extend<{ world: World }>({
  // eslint-style empty pattern: Playwright reads fixture dependencies from it.
  // eslint-disable-next-line no-empty-pattern
  world: async ({}, use, info) => {
    const world = new World(info);
    try {
      await use(world);
      if (info.status === info.expectedStatus) expect(await world.interopProblems()).toEqual([]);
    } finally {
      await world.close();
    }
  },
});

/** Poll `read` until `accept` holds (Playwright's expect.poll with a scenario-sized timeout). */
export async function until<T>(read: () => Promise<T>, accept: (value: T) => boolean, timeoutMs = 30_000): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  let last = await read();
  while (!accept(last)) {
    if (Date.now() > deadline) throw new Error(`condition not met within ${timeoutMs} ms; last value: ${JSON.stringify(last)}`);
    await new Promise((resolve) => setTimeout(resolve, 100));
    last = await read();
  }
  return last;
}
