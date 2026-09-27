// contentSource.contract.ts -- what every extension-side ContentSourcePort
// must do (design, "Capture from the open tab": if a tab shows the saved URL
// the tab adapter returns its readable text; otherwise there is nothing to
// capture and the request carries source none). Extraction to readable text
// is the adapter's job; the port never throws for a missing or unreadable tab.

import { describe, expect, it } from 'vitest';
import type { TabContent } from '../../src/domain/capture.js';
import type { Url } from '../../src/domain/values.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';

/** A ContentSourcePort plus the out-of-band ways to open tabs in the browser. */
export interface ContentSourceHarness {
  readonly content: ContentSourcePort;
  openTab(url: Url, page: TabContent): Promise<void>;
  /** A tab showing `url` whose page the extension may not read (e.g. the browser refuses script injection). */
  openUnreadableTab(url: Url): Promise<void>;
}

const PAGE: TabContent = { title: 'Tutorial | Tokio', text: 'Tokio is an asynchronous runtime for Rust.' };

/** Registers the ContentSourcePort contract suite for one implementation. */
export function describeContentSourceContract(name: string, make: () => ContentSourceHarness): void {
  describe(`ContentSourcePort contract -- ${name}`, () => {
    it('Given a tab showing the URL, When it is read, Then its title and readable text come back', async () => {
      const { content, openTab } = make();
      await openTab('https://tokio.rs/tokio/tutorial', PAGE);
      expect(await content.readTab('https://tokio.rs/tokio/tutorial')).toEqual(PAGE);
    });

    it('Given no tab shows the URL, When it is read, Then nothing comes back', async () => {
      const { content, openTab } = make();
      await openTab('https://tokio.rs/', PAGE);
      expect(await content.readTab('https://tokio.rs/tokio/tutorial')).toBeUndefined();
    });

    it('Given a tab showing a variant of the URL, When the exact URL is read, Then the variant does not count', async () => {
      const { content, openTab } = make();
      await openTab('https://tokio.rs/tokio/tutorial?utm_source=x', PAGE);
      expect(await content.readTab('https://tokio.rs/tokio/tutorial')).toBeUndefined();
    });

    it('Given the only tab showing the URL is unreadable, When it is read, Then nothing comes back and nothing throws', async () => {
      const { content, openUnreadableTab } = make();
      await openUnreadableTab('https://tokio.rs/tokio/tutorial');
      await expect(content.readTab('https://tokio.rs/tokio/tutorial')).resolves.toBeUndefined();
    });
  });
}
