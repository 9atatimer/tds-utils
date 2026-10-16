// chromeBackgroundTab.test.ts -- the background-tab ContentSourcePort (design,
// Future Considerations "Background-tab capture (MVP)": open the saved URL in
// a background tab in a non-focused window, capture as from any tab, close;
// task-031). The window is minimized and unfocused; the page is read once it
// has loaded, or given up on at the timeout; the window is always closed --
// by the next worker, when the one that opened it was terminated first; one
// background capture runs at a time.

import { describe, expect, it } from 'vitest';
import { BACKGROUND_LOAD_TIMEOUT_MS, ChromeBackgroundTab } from '../../../src/adapters/chrome/backgroundTab.js';
import { FakeClock } from '../../fakes/FakeClock.js';
import { FakeTimer } from '../../fakes/FakeTimer.js';
import { StorageAreaStub } from '../../stubs/chromeStorage.js';
import { BackgroundBrowserStub } from '../../stubs/chromeWindows.js';

// --- Builders ---

const URL = 'https://news.example/paywalled/story';
const PAGE = { title: 'Story', text: 'Full text visible only when signed in.' };
/** A load with nothing blocked: the daemon's policy allows private addresses (the opt-out). */
const OPEN = { blockPrivateHosts: false };
/** A load under the daemon's default policy: private hosts are blocked by literal before they load. */
const GUARDED = { blockPrivateHosts: true };
const SECRET = { title: 'Router admin', text: 'WAN password: hunter2' };

function adapter(stub = new BackgroundBrowserStub(), store = new StorageAreaStub()) {
  const timer = new FakeTimer(new FakeClock(1_790_000_000_000));
  return {
    stub,
    store,
    timer,
    source: new ChromeBackgroundTab(stub.windows, stub.tabs, stub.scripting, timer, store, stub.declarativeNetRequest),
  };
}

// --- Tests ---

describe('ChromeBackgroundTab', () => {
  it('Given a page that loads, When read, Then an unfocused minimized window opens blank and is navigated to the URL, the page is read and the window closes', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, PAGE);
    expect(await source.readTab(URL, OPEN)).toEqual({ ...PAGE, url: URL });
    expect(stub.log).toEqual(['open about:blank focused=false state=minimized', `navigate ${URL}`, `inject ${URL}`, `close ${URL}`]);
    expect(stub.openWindows()).toBe(0);
  });

  it('Given a page that never finishes loading, When the load timeout passes, Then nothing comes back, nothing is injected and the window closes', async () => {
    const { stub, timer, source } = adapter();
    stub.serve(URL, 'never-loads');
    const read = source.readTab(URL, OPEN);
    await timer.advance(0);
    await timer.advance(BACKGROUND_LOAD_TIMEOUT_MS);
    expect(await read).toBeUndefined();
    expect(stub.log).toEqual(['open about:blank focused=false state=minimized', `navigate ${URL}`, `close ${URL}`]);
  });

  it('Given a page the browser will not script (an error page), When read, Then nothing comes back and the window closes', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, 'unreadable');
    expect(await source.readTab(URL, OPEN)).toBeUndefined();
    expect(stub.openWindows()).toBe(0);
  });

  it('Given a page with no readable text, When read, Then nothing comes back', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, { title: 'Blank', text: ' \n ' });
    expect(await source.readTab(URL, OPEN)).toBeUndefined();
  });

  it('Given the browser refuses to open a window, When read, Then nothing comes back and nothing throws', async () => {
    const { stub, source } = adapter();
    stub.refuseWindows = true;
    await expect(source.readTab(URL, OPEN)).resolves.toBeUndefined();
  });

  it('Given two reads at once, When both run, Then the second window opens only after the first has closed', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, PAGE);
    stub.serve('https://b.example/', { title: 'B', text: 'bee' });
    const [a, b] = await Promise.all([source.readTab(URL, OPEN), source.readTab('https://b.example/', OPEN)]);
    expect([a?.title, b?.title]).toEqual(['Story', 'B']);
    expect(stub.log.map((l) => l.split(' ').slice(0, 2).join(' '))).toEqual([
      'open about:blank',
      `navigate ${URL}`,
      `inject ${URL}`,
      `close ${URL}`,
      'open about:blank',
      'navigate https://b.example/',
      'inject https://b.example/',
      'close https://b.example/',
    ]);
  });
});

describe('ChromeBackgroundTab -- across worker restarts', () => {
  it('Given a worker terminated while its guarded background page loaded, When the next worker sweeps, Then the window it left is closed and its block rules removed', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL, GUARDED);
    await first.timer.advance(0);
    expect(first.stub.openWindows()).toBe(1);
    expect(first.stub.sessionRules()).not.toEqual([]);
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(0);
    expect(first.store.keys()).toEqual([]);
    expect(first.stub.sessionRules()).toEqual([]);
  });

  it('Given a worker terminated while its guarded background page loaded, When the next worker sweeps, Then the block rules are still in place when the window is closed (Codex on 9atatimer/tds-utils PR#535)', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL, GUARDED);
    await first.timer.advance(0);
    const installed = first.stub.sessionRules().length;
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(installed).toBeGreaterThan(0);
    expect(first.stub.rulesAtClose).toEqual([installed]);
    expect(first.stub.sessionRules()).toEqual([]);
  });

  it('Given a guarded capture whose window will not close, When the capture ends, Then its block rules stay with the window, and the next sweep that closes it removes them (Codex on 9atatimer/tds-utils PR#535)', async () => {
    const first = adapter();
    first.stub.serve(URL, PAGE);
    first.stub.refuseClose = true;
    await first.source.readTab(URL, GUARDED);
    expect(first.stub.openWindows()).toBe(1);
    expect(first.stub.sessionRules()).not.toEqual([]);
    first.stub.refuseClose = false;
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(0);
    expect(first.stub.sessionRules()).toEqual([]);
  });

  it('Given a guarded capture whose window will not close, When another capture is asked for, Then none runs while that window is open (its rules stay), and one runs once it closes', async () => {
    const first = adapter();
    first.stub.serve(URL, PAGE);
    first.stub.serve('https://b.example/', { title: 'B', text: 'bee' });
    first.stub.refuseClose = true;
    await first.source.readTab(URL, GUARDED);
    const rules = first.stub.sessionRules();
    expect(await first.source.readTab('https://b.example/', GUARDED)).toBeUndefined();
    expect(first.stub.openWindows()).toBe(1);
    expect(first.stub.sessionRules()).toEqual(rules);
    first.stub.refuseClose = false;
    expect((await first.source.readTab('https://b.example/', GUARDED))?.title).toBe('B');
    expect(first.stub.openWindows()).toBe(0);
    expect(first.stub.sessionRules()).toEqual([]);
  });

  it('Given a worker terminated while its guarded page loaded, and the user restored that window since, When the next worker sweeps, Then the capture tab is closed before its block rules go (Codex on 9atatimer/tds-utils PR#535)', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL, GUARDED);
    await first.timer.advance(0);
    const installed = first.stub.sessionRules().length;
    first.stub.restoreWindows();
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(0);
    expect(first.stub.rulesAtClose).toEqual([installed]);
    expect(first.stub.sessionRules()).toEqual([]);
    expect(first.store.keys()).toEqual([]);
  });

  it('Given the browser restarted (its session storage and session rules gone), When the next worker sweeps, Then a window that now holds the old ids is left open', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL, OPEN);
    await first.timer.advance(0);
    const stub = new BackgroundBrowserStub();
    await stub.windows.create({ url: 'https://mine.example/', focused: false, state: 'minimized' });
    const next = adapter(stub, new StorageAreaStub());
    await next.source.sweep();
    expect(stub.openWindows()).toBe(1);
  });

  it('Given a capture that finished, When the next worker sweeps, Then nothing is closed', async () => {
    const first = adapter();
    first.stub.serve(URL, PAGE);
    await first.source.readTab(URL, OPEN);
    const mine = await first.stub.windows.create({ url: 'https://mine.example/', focused: true, state: 'normal' });
    expect(mine.id).toBeDefined();
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(1);
  });
});

describe('ChromeBackgroundTab -- a guarded load never reaches a private host (issue #534)', () => {
  it('Given private hosts blocked, When a public URL 302s to http://127.0.0.1:8080/admin, Then the redirect is blocked before it loads, nothing is read, and the rules go with the window', async () => {
    const { stub, source } = adapter();
    stub.redirect(URL, 'http://127.0.0.1:8080/admin');
    stub.serve('http://127.0.0.1:8080/admin', SECRET);
    expect(await source.readTab(URL, GUARDED)).toBeUndefined();
    expect(stub.log).toContain('blocked http://127.0.0.1:8080/admin');
    expect(stub.log.filter((l) => l.startsWith('inject http://127.0.0.1'))).toEqual([]);
    expect(stub.sessionRules()).toEqual([]);
    expect(stub.openWindows()).toBe(0);
  });

  it.each([
    'http://127.0.0.1/',
    'http://127.8.9.10:3000/x',
    'http://0.0.0.0/',
    'http://10.1.2.3/',
    'http://100.64.0.1/',
    'http://169.254.169.254/latest/meta-data/',
    'http://172.16.0.1/',
    'http://172.31.255.255/',
    'http://192.168.1.1/',
    'http://192.0.2.7/',
    'http://224.0.0.1/',
    'https://user:pw@127.0.0.1/',
    'http://[::1]/',
    'http://[::]/',
    'http://[::ffff:7f00:1]/',
    'http://[::7f00:1]/',
    'http://[64:ff9b::7f00:1]/',
    'http://[fd12:3456::1]/',
    'http://[fc00::1]/',
    'http://[fe80::1]/',
    'http://[fec0::1]/',
    'http://[ff02::1]/',
    'http://[2002:7f00:1::]/',
    'http://[2001::1]/',
    'http://[2001:db8::1]/',
    'http://[100::1]/',
    'http://[2606:4700::1111]/',
    'http://[2001:4860:4860::8888]/',
    'http://localhost/',
    'http://localhost.:8080/',
    'http://intranet/wiki',
    'http://printer.local/',
    'http://app.localhost/',
    'http://metadata.google.internal/computeMetadata/v1/',
    'http://router.home.arpa/',
  ])('Given private hosts blocked, When the load is redirected to %s, Then it is blocked and nothing comes back', async (target) => {
    const { stub, source } = adapter();
    stub.redirect(URL, target);
    stub.serve(target, SECRET);
    expect(await source.readTab(URL, GUARDED)).toBeUndefined();
    expect(stub.log).toContain(`blocked ${target}`);
  });

  it.each([
    'https://example.com/',
    'http://8.8.8.8/',
    'http://11.0.0.1/',
    'http://126.255.0.1/',
    'http://128.0.0.1/',
    'http://172.15.0.1/',
    'http://172.32.0.1/',
    'http://192.169.0.1/',
    'http://100.128.0.1/',
    'http://10.example.com/',
    'http://127.0.0.1.example.com/',
    'https://localhost.example.com/',
    'https://local.example/',
    'https://news.example:8443/story',
  ])(
    'Given private hosts blocked, When the load is redirected to the public %s, Then it is read and the result names where it ended',
    async (target) => {
      const { stub, source } = adapter();
      stub.redirect(URL, target);
      stub.serve(target, PAGE);
      expect(await source.readTab(URL, GUARDED)).toEqual({ ...PAGE, url: target });
    },
  );

  it('Given private hosts blocked, When the URL loads with no redirect, Then the result names the URL it was read at', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, PAGE);
    expect(await source.readTab(URL, GUARDED)).toEqual({ ...PAGE, url: URL });
  });

  it('Given the browser refuses the block rules, When a guarded load is asked for, Then the URL is never loaded and nothing comes back', async () => {
    const { stub, source } = adapter();
    stub.refuseRules = true;
    stub.serve(URL, PAGE);
    expect(await source.readTab(URL, GUARDED)).toBeUndefined();
    expect(stub.log.filter((l) => l.includes(URL))).toEqual([]);
    expect(stub.openWindows()).toBe(0);
  });

  it('Given private hosts not blocked (the opt-out), When a public URL 302s to 127.0.0.1, Then no rule is installed and the page is read at where it ended', async () => {
    const { stub, source } = adapter();
    stub.redirect(URL, 'http://127.0.0.1:8080/admin');
    stub.serve('http://127.0.0.1:8080/admin', SECRET);
    expect(await source.readTab(URL, OPEN)).toEqual({ ...SECRET, url: 'http://127.0.0.1:8080/admin' });
    expect(stub.log.some((l) => l.startsWith('blocked'))).toBe(false);
  });
});
