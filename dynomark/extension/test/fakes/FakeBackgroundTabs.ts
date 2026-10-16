// FakeBackgroundTabs.ts -- an in-memory BackgroundTabPort: what each URL
// would show if the writer's browser loaded it (signed in), where a load is
// redirected, a log of every URL it was asked to open and how each load was
// asked for. A read can be armed to kill the worker while the page loads (a
// background load takes seconds). It does not block anything itself: whether
// a load is guarded is recorded, and the guard is the adapter's (its tests).

import type { TabContent } from '../../src/domain/capture.js';
import type { Url } from '../../src/domain/values.js';
import type { BackgroundLoad, BackgroundTabPort, LoadedPage } from '../../src/ports/backgroundTab.js';
import { WorkerTerminated } from './WorkerTerminated.js';

export class FakeBackgroundTabs implements BackgroundTabPort {
  /** Every URL opened in a background tab, in order. */
  readonly opened: Url[] = [];
  /** How each load was asked for, in order. */
  readonly loads: (BackgroundLoad & { readonly url: Url })[] = [];
  private readonly pages = new Map<Url, TabContent>();
  private readonly redirects = new Map<Url, Url>();
  private terminating = false;

  /** Loading `url` shows `page`; any other URL cannot be read. */
  serve(url: Url, page: TabContent): void {
    this.pages.set(url, page);
  }

  /** Loading `from` is redirected to `to`: the page read is what `to` shows, at `to`. */
  redirect(from: Url, to: Url): void {
    this.redirects.set(from, to);
  }

  /** The next read opens its tab, then the worker dies before the page is read. */
  terminateOnNextRead(): void {
    this.terminating = true;
  }

  readTab(url: Url, load: BackgroundLoad): Promise<LoadedPage | undefined> {
    this.opened.push(url);
    this.loads.push({ url, ...load });
    if (this.terminating) {
      this.terminating = false;
      return Promise.reject(new WorkerTerminated());
    }
    const at = this.redirects.get(url) ?? url;
    const page = this.pages.get(at);
    return Promise.resolve(page === undefined ? undefined : { ...page, url: at });
  }
}
