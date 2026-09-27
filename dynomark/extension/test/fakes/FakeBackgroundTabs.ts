// FakeBackgroundTabs.ts -- an in-memory background-tab ContentSourcePort: what
// each URL would show if the writer's browser loaded it (signed in), and a log
// of every URL it was asked to open.

import type { TabContent } from '../../src/domain/capture.js';
import type { Url } from '../../src/domain/values.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';

export class FakeBackgroundTabs implements ContentSourcePort {
  /** Every URL opened in a background tab, in order. */
  readonly opened: Url[] = [];
  private readonly pages = new Map<Url, TabContent>();

  /** Loading `url` shows `page`; any other URL cannot be read. */
  serve(url: Url, page: TabContent): void {
    this.pages.set(url, page);
  }

  readTab(url: Url): Promise<TabContent | undefined> {
    this.opened.push(url);
    const page = this.pages.get(url);
    return Promise.resolve(page === undefined ? undefined : { ...page });
  }
}
