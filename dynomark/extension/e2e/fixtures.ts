/// <reference types="chrome" />
// fixtures.ts -- the e2e test object: every test gets its own launched
// extension (fresh profile, fresh fake daemon), closed after it.

import { test as base, expect } from '@playwright/test';
import { launchExtension, type Launched } from '../test/support/browser.js';
import type { RequestMessage } from '../src/wire/messages.js';

export { expect };

export const test = base.extend<{ ext: Launched }>({
  // eslint-style empty pattern: Playwright reads fixture dependencies from it.
  // eslint-disable-next-line no-empty-pattern
  ext: async ({}, use) => {
    const ext = await launchExtension();
    await use(ext);
    await ext.close();
  },
});

/** A predicate for requests of one type. */
export function ofType(type: RequestMessage['type']): (r: RequestMessage) => boolean {
  return (r) => r.type === type;
}

/** The node id of the Follow Up folder, read in an extension page. */
export async function followUpId(ext: Launched): Promise<string> {
  const page = await ext.extensionPage('history.html');
  const id = await page.evaluate(async () => (await chrome.bookmarks.search({ title: 'Follow Up' }))[0]?.id);
  await page.close();
  if (id === undefined) throw new Error('no Follow Up folder');
  return id;
}
