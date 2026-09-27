/// <reference types="chrome" />
// remote.ts -- the real chrome adapters, driven from Node: each port method
// runs inside an extension page of a live Chromium (page.evaluate), on the
// built adapter module, and its result or error comes back. This lets the
// port contract suites -- written for Vitest -- run unchanged against the
// real chrome.* APIs. Errors are rebuilt by name (BrowserRefused,
// TransportLost) so the suites' instanceof checks hold.

import type { Page } from '@playwright/test';
import type { BatchCursor } from '../../src/domain/batch.js';
import type { TabContent } from '../../src/domain/capture.js';
import type { LocalIndex, Visit } from '../../src/domain/search.js';
import type { Settings } from '../../src/domain/settings.js';
import type { FolderPath, SnapshotNode, TreeRead } from '../../src/domain/tree.js';
import type { NodeId, Title, Url } from '../../src/domain/values.js';
import { BrowserRefused, type BookmarkTreePort } from '../../src/ports/bookmarkTree.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';
import type { HistoryPort } from '../../src/ports/history.js';
import type { StoragePort } from '../../src/ports/storage.js';
import { TransportLost, type LossReason, type TransportPort } from '../../src/ports/transport.js';
import type { ErrorMessage, EventMessage, RequestMessage, ResultOf } from '../../src/wire/messages.js';

// --- Types ---

type Outcome =
  { readonly ok: unknown } | { readonly error: { readonly name: string; readonly message: string; readonly reason?: LossReason } };

/** Which adapter a remote call builds, and how. */
interface Target {
  readonly module: string;
  readonly className: string;
  /** Instances are kept in the page by key, so stateful adapters (the transport) live across calls. */
  readonly key: string;
  readonly options?: Readonly<Record<string, string>>;
}

// --- The remote call ---

/**
 * The page side of a call, as source text: Vitest rewrites `import()` in test
 * code for Node, and this must run in the page as written (a DevTools
 * evaluation, so the extension's CSP does not apply to it).
 */
const PAGE_CALL = `async ({ target, method, args }) => {
  globalThis.__adapters ??= new Map();
  if (!globalThis.__adapters.has(target.key)) {
    globalThis.__adapters.set(target.key, (async () => {
      const mod = await import(target.module);
      const Adapter = mod[target.className];
      if (Adapter === undefined) throw new Error('no ' + target.className + ' in ' + target.module);
      return target.options === undefined ? new Adapter() : new Adapter(undefined, target.options);
    })());
  }
  const instance = await globalThis.__adapters.get(target.key);
  try {
    return { ok: await instance[method](...args) };
  } catch (e) {
    return { error: { name: e?.name ?? 'Error', message: e?.message ?? String(e), ...(e?.reason === undefined ? {} : { reason: e.reason }) } };
  }
}`;

async function call(page: Page, target: Target, method: string, args: readonly unknown[]): Promise<unknown> {
  const outcome = (await page.evaluate(`(${PAGE_CALL})(${JSON.stringify({ target, method, args })})`)) as Outcome;
  if ('ok' in outcome) return outcome.ok;
  if (outcome.error.name === 'BrowserRefused') throw new BrowserRefused(outcome.error.message);
  if (outcome.error.name === 'TransportLost') throw new TransportLost(outcome.error.reason ?? 'disconnected');
  throw new Error(`${outcome.error.name}: ${outcome.error.message}`);
}

// --- Remote ports ---

let instances = 0;

function target(module: string, className: string, options?: Readonly<Record<string, string>>): Target {
  instances += 1;
  return { module, className, key: `${className}-${instances}`, ...(options === undefined ? {} : { options }) };
}

/** Remove every user node under the top-level folders: a fresh profile's tree. */
export function resetBookmarks(page: Page): Promise<void> {
  return page.evaluate(async () => {
    const [root] = await chrome.bookmarks.getTree();
    for (const top of root?.children ?? []) for (const child of top.children ?? []) await chrome.bookmarks.removeTree(child.id);
  });
}

export class RemoteBookmarkTree implements BookmarkTreePort {
  private readonly target = target('./adapters/chrome/bookmarkTree.js', 'ChromeBookmarkTree');

  constructor(
    private readonly page: Page,
    private readonly ready: Promise<void>,
  ) {}

  readTree(): Promise<TreeRead> {
    return this.call('readTree') as Promise<TreeRead>;
  }

  resolveFolder(path: FolderPath): Promise<NodeId | undefined> {
    return this.call('resolveFolder', path) as Promise<NodeId | undefined>;
  }

  getNode(id: NodeId): Promise<SnapshotNode | undefined> {
    return this.call('getNode', id) as Promise<SnapshotNode | undefined>;
  }

  getChildren(folderId: NodeId): Promise<readonly SnapshotNode[]> {
    return this.call('getChildren', folderId) as Promise<readonly SnapshotNode[]>;
  }

  createFolder(parentId: NodeId, title: Title): Promise<SnapshotNode> {
    return this.call('createFolder', parentId, title) as Promise<SnapshotNode>;
  }

  createBookmark(parentId: NodeId, title: Title, url: Url): Promise<SnapshotNode> {
    return this.call('createBookmark', parentId, title, url) as Promise<SnapshotNode>;
  }

  move(nodeId: NodeId, parentId: NodeId): Promise<SnapshotNode> {
    return this.call('move', nodeId, parentId) as Promise<SnapshotNode>;
  }

  private async call(method: string, ...args: unknown[]): Promise<unknown> {
    await this.ready;
    return call(this.page, this.target, method, args);
  }
}

export class RemoteStorage implements StoragePort {
  private readonly target: Target;

  constructor(
    private readonly page: Page,
    prefix: string,
  ) {
    this.target = target('./adapters/chrome/storage.js', 'ChromeStorage', { prefix });
  }

  loadSettings(): Promise<Settings | undefined> {
    return this.call('loadSettings') as Promise<Settings | undefined>;
  }

  saveSettings(settings: Settings): Promise<void> {
    return this.call('saveSettings', settings) as Promise<void>;
  }

  loadLocalIndex(): Promise<LocalIndex | undefined> {
    return this.call('loadLocalIndex') as Promise<LocalIndex | undefined>;
  }

  saveLocalIndex(index: LocalIndex): Promise<void> {
    return this.call('saveLocalIndex', index) as Promise<void>;
  }

  loadCursor(): Promise<BatchCursor | undefined> {
    return this.call('loadCursor') as Promise<BatchCursor | undefined>;
  }

  saveCursor(cursor: BatchCursor): Promise<void> {
    return this.call('saveCursor', cursor) as Promise<void>;
  }

  clearCursor(): Promise<void> {
    return this.call('clearCursor') as Promise<void>;
  }

  private call(method: string, ...args: unknown[]): Promise<unknown> {
    return call(this.page, this.target, method, args);
  }
}

export class RemoteHistory implements HistoryPort {
  private readonly target = target('./adapters/chrome/history.js', 'ChromeHistory');

  constructor(private readonly page: Page) {}

  visitsTo(url: Url): Promise<readonly Visit[]> {
    return call(this.page, this.target, 'visitsTo', [url]) as Promise<readonly Visit[]>;
  }
}

export class RemoteTabContent implements ContentSourcePort {
  private readonly target = target('./adapters/chrome/tabContent.js', 'ChromeTabContent');

  constructor(
    private readonly page: Page,
    private readonly ready: Promise<void>,
  ) {}

  async readTab(url: Url): Promise<TabContent | undefined> {
    await this.ready;
    return (await call(this.page, this.target, 'readTab', [url])) as TabContent | undefined;
  }
}

/** The transport lives in the page (it holds the native port); events come back through an exposed binding. */
export class RemoteTransport implements TransportPort {
  private readonly target: Target;
  private readonly listeners = new Set<(event: EventMessage) => void>();
  private subscribed = false;

  constructor(
    private readonly page: Page,
    hostName: string,
    private readonly events: RemoteEvents,
  ) {
    this.target = target('./adapters/chrome/nativeTransport.js', 'NativeMessagingTransport', { hostName });
  }

  send<R extends RequestMessage>(request: R): Promise<ResultOf<R['type']> | ErrorMessage> {
    return call(this.page, this.target, 'send', [request]) as Promise<ResultOf<R['type']> | ErrorMessage>;
  }

  onEvent(listener: (event: EventMessage) => void): () => void {
    this.listeners.add(listener);
    if (!this.subscribed) {
      this.subscribed = true;
      this.events.route(this.target.key, (event) => [...this.listeners].forEach((l) => l(event)));
      void this.subscribe();
    }
    return () => this.listeners.delete(listener);
  }

  /** Create the page-side instance (a first call does), then subscribe it to the page binding: this opens its link. */
  private async subscribe(): Promise<void> {
    await call(this.page, this.target, 'linkState', []);
    await this.page.evaluate(async (key) => {
      const scope = globalThis as unknown as {
        __adapters: Map<string, Promise<{ onEvent(l: (e: unknown) => void): () => void }>>;
        __dmEvent: (key: string, event: unknown) => Promise<void>;
      };
      (await scope.__adapters.get(key))?.onEvent((e) => void scope.__dmEvent(key, e));
    }, this.target.key);
  }
}

/** The one page binding events come back through, routed to their transport by key. */
export class RemoteEvents {
  private readonly routes = new Map<string, (event: EventMessage) => void>();

  static async expose(page: Page, onDelivered: (event: EventMessage) => void): Promise<RemoteEvents> {
    const events = new RemoteEvents();
    await page.exposeFunction('__dmEvent', (key: string, event: EventMessage) => {
      events.routes.get(key)?.(event);
      onDelivered(event);
    });
    return events;
  }

  route(key: string, deliver: (event: EventMessage) => void): void {
    this.routes.set(key, deliver);
  }
}
