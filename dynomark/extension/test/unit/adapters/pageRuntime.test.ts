// pageRuntime.test.ts -- which runtime API an extension page talks to the
// background over (task-032). The pages are shared by the Chrome and Firefox
// builds; Firefox's promise-based API is its `browser` namespace, so a page
// uses browser.runtime where it exists and chrome.runtime otherwise.

import { describe, expect, it } from 'vitest';
import { ChromePageClient, extensionRuntime, type PageClientApi } from '../../../src/adapters/chrome/pageChannel.js';

// --- Builders ---

function runtime(answer: string): PageClientApi {
  return { id: 'self', sendMessage: () => Promise.resolve({ ok: true, answer }) };
}

// --- Tests ---

describe('extensionRuntime', () => {
  it('Given a Firefox page (browser and chrome both defined), When the runtime is picked, Then it is browser.runtime', async () => {
    const picked = extensionRuntime({ browser: { runtime: runtime('browser') }, chrome: { runtime: runtime('chrome') } });
    expect(await new ChromePageClient(picked).request({ kind: 'overview' })).toEqual({ ok: true, answer: 'browser' });
  });

  it('Given a Chrome page (no browser namespace), When the runtime is picked, Then it is chrome.runtime', async () => {
    const picked = extensionRuntime({ chrome: { runtime: runtime('chrome') } });
    expect(await new ChromePageClient(picked).request({ kind: 'overview' })).toEqual({ ok: true, answer: 'chrome' });
  });
});
