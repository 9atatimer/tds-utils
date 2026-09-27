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

function adapter(stub = new BackgroundBrowserStub(), store = new StorageAreaStub()) {
  const timer = new FakeTimer(new FakeClock(1_790_000_000_000));
  return { stub, store, timer, source: new ChromeBackgroundTab(stub.windows, stub.tabs, stub.scripting, timer, store) };
}

// --- Tests ---

describe('ChromeBackgroundTab', () => {
  it('Given a page that loads, When read, Then an unfocused minimized window opens on the URL, the page is read and the window closes', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, PAGE);
    expect(await source.readTab(URL)).toEqual(PAGE);
    expect(stub.log).toEqual([`open ${URL} focused=false state=minimized`, `inject ${URL}`, `close ${URL}`]);
    expect(stub.openWindows()).toBe(0);
  });

  it('Given a page that never finishes loading, When the load timeout passes, Then nothing comes back, nothing is injected and the window closes', async () => {
    const { stub, timer, source } = adapter();
    stub.serve(URL, 'never-loads');
    const read = source.readTab(URL);
    await timer.advance(0);
    await timer.advance(BACKGROUND_LOAD_TIMEOUT_MS);
    expect(await read).toBeUndefined();
    expect(stub.log).toEqual([`open ${URL} focused=false state=minimized`, `close ${URL}`]);
  });

  it('Given a page the browser will not script (an error page), When read, Then nothing comes back and the window closes', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, 'unreadable');
    expect(await source.readTab(URL)).toBeUndefined();
    expect(stub.openWindows()).toBe(0);
  });

  it('Given a page with no readable text, When read, Then nothing comes back', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, { title: 'Blank', text: ' \n ' });
    expect(await source.readTab(URL)).toBeUndefined();
  });

  it('Given the browser refuses to open a window, When read, Then nothing comes back and nothing throws', async () => {
    const { stub, source } = adapter();
    stub.refuseWindows = true;
    await expect(source.readTab(URL)).resolves.toBeUndefined();
  });

  it('Given two reads at once, When both run, Then the second window opens only after the first has closed', async () => {
    const { stub, source } = adapter();
    stub.serve(URL, PAGE);
    stub.serve('https://b.example/', { title: 'B', text: 'bee' });
    const [a, b] = await Promise.all([source.readTab(URL), source.readTab('https://b.example/')]);
    expect([a?.title, b?.title]).toEqual(['Story', 'B']);
    expect(stub.log.map((l) => l.split(' ').slice(0, 2).join(' '))).toEqual([
      `open ${URL}`,
      `inject ${URL}`,
      `close ${URL}`,
      'open https://b.example/',
      'inject https://b.example/',
      'close https://b.example/',
    ]);
  });
});

describe('ChromeBackgroundTab -- across worker restarts', () => {
  it('Given a worker terminated while its background page loaded, When the next worker sweeps, Then the window it left is closed', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL);
    await first.timer.advance(0);
    expect(first.stub.openWindows()).toBe(1);
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(0);
    expect(first.store.keys()).toEqual([]);
  });

  it('Given a recorded window id that now names a window this adapter did not open, When swept, Then that window is left open and the record dropped', async () => {
    const first = adapter();
    first.stub.serve(URL, 'never-loads');
    void first.source.readTab(URL);
    await first.timer.advance(0);
    const stub = new BackgroundBrowserStub();
    await stub.windows.create({ url: 'https://mine.example/', focused: true, state: 'normal' });
    const next = adapter(stub, first.store);
    await next.source.sweep();
    expect(stub.openWindows()).toBe(1);
    expect(first.store.keys()).toEqual([]);
  });

  it('Given a capture that finished, When the next worker sweeps, Then nothing is closed', async () => {
    const first = adapter();
    first.stub.serve(URL, PAGE);
    await first.source.readTab(URL);
    const mine = await first.stub.windows.create({ url: 'https://mine.example/', focused: true, state: 'normal' });
    expect(mine.id).toBeDefined();
    const next = adapter(first.stub, first.store);
    await next.source.sweep();
    expect(first.stub.openWindows()).toBe(1);
  });
});
