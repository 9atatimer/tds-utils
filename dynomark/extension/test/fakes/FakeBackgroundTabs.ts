// FakeBackgroundTabs.ts -- an in-memory background-tab ContentSourcePort: what
// each URL would show if the writer's browser loaded it (signed in), and a log
// of every URL it was asked to open. A read can be armed to kill the worker
// while the page loads (a background load takes seconds).

import type { TabContent } from '../../src/domain/capture.js';
import type { Url } from '../../src/domain/values.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';
import { WorkerTerminated } from './WorkerTerminated.js';

export class FakeBackgroundTabs implements ContentSourcePort {
  /** Every URL opened in a background tab, in order. */
  readonly opened: Url[] = [];
  private readonly pages = new Map<Url, TabContent>();
  private terminating = false;

  /** Loading `url` shows `page`; any other URL cannot be read. */
  serve(url: Url, page: TabContent): void {
    this.pages.set(url, page);
  }

  /** The next read opens its tab, then the worker dies before the page is read. */
  terminateOnNextRead(): void {
    this.terminating = true;
  }

  readTab(url: Url): Promise<TabContent | undefined> {
    this.opened.push(url);
    if (this.terminating) {
      this.terminating = false;
      return Promise.reject(new WorkerTerminated());
    }
    const page = this.pages.get(url);
    return Promise.resolve(page === undefined ? undefined : { ...page });
  }
}
