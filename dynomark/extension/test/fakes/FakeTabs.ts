// FakeTabs.ts -- an in-memory ContentSourcePort: open tabs keyed by exact URL.

import type { TabContent } from '../../src/domain/capture.js';
import type { Url } from '../../src/domain/values.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';

export class FakeTabs implements ContentSourcePort {
  private readonly tabs = new Map<Url, TabContent | 'unreadable'>();

  /** Open a tab on `url`, readable with `page` or `'unreadable'`. */
  open(url: Url, page: TabContent | 'unreadable'): void {
    this.tabs.set(url, page);
  }

  close(url: Url): void {
    this.tabs.delete(url);
  }

  readTab(url: Url): Promise<TabContent | undefined> {
    const page = this.tabs.get(url);
    return Promise.resolve(page === undefined || page === 'unreadable' ? undefined : { ...page });
  }
}
