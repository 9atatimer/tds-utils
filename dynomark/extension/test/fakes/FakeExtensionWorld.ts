// FakeExtensionWorld.ts -- the browser plus one extension service worker, all
// faked, with the worker's lifetime modelled.
//
// The browser's own data (bookmark tree, history, open tabs) and extension
// storage outlive any worker. Each worker gets its ports bound to its
// lifetime and its own daemon connection. When the worker dies -- killed by
// terminate(), or by a fault armed on the tree -- every port it holds refuses
// from then on, so nothing it attempts after the kill can land, and its
// connection drops. restart() starts a fresh worker over the same browser
// data and storage: exactly the state the design says survives.

import type { EpochMs } from '../../src/domain/values.js';
import type { BookmarkTreePort } from '../../src/ports/bookmarkTree.js';
import type { Clock } from '../../src/ports/clock.js';
import type { ContentSourcePort } from '../../src/ports/contentSource.js';
import type { HistoryPort } from '../../src/ports/history.js';
import type { IdSource } from '../../src/ports/idSource.js';
import type { StoragePort } from '../../src/ports/storage.js';
import type { TransportPort } from '../../src/ports/transport.js';
import { FakeBookmarkTree } from './FakeBookmarkTree.js';
import { FakeClock } from './FakeClock.js';
import { FakeHistory } from './FakeHistory.js';
import { FakeStorage } from './FakeStorage.js';
import { FakeTabs } from './FakeTabs.js';
import { FakeTransport } from './FakeTransport.js';
import { SequentialIdSource } from './SequentialIdSource.js';
import { WorkerTerminated } from './WorkerTerminated.js';

// --- Constants ---

const DEFAULT_START: EpochMs = 1_790_000_000_000;

/** Methods that return a value rather than a promise: a dead worker's call throws instead of rejecting. */
const SYNC_METHODS: ReadonlySet<PropertyKey> = new Set(['now', 'next', 'onEvent']);

// --- Types ---

/** The ports one service worker holds; what the composition root will hand the use cases. */
export interface WorkerPorts {
  readonly tree: BookmarkTreePort;
  readonly history: HistoryPort;
  readonly content: ContentSourcePort;
  readonly storage: StoragePort;
  readonly transport: TransportPort;
  readonly clock: Clock;
  readonly ids: IdSource;
}

export interface FakeExtensionWorldOptions {
  readonly flavor: 'chrome' | 'firefox';
  readonly accountStorage?: boolean;
  readonly start?: EpochMs;
}

interface Worker {
  alive: boolean;
  readonly connection: FakeTransport;
  readonly ports: WorkerPorts;
}

// --- The world ---

export class FakeExtensionWorld {
  readonly clock: FakeClock;
  readonly tree: FakeBookmarkTree;
  readonly history = new FakeHistory();
  readonly tabs = new FakeTabs();
  readonly storage = new FakeStorage();
  readonly ids = new SequentialIdSource();
  private current: Worker;

  constructor(options: FakeExtensionWorldOptions) {
    this.clock = new FakeClock(options.start ?? DEFAULT_START);
    this.tree = new FakeBookmarkTree({
      flavor: options.flavor,
      clock: this.clock,
      ...(options.accountStorage === undefined ? {} : { accountStorage: options.accountStorage }),
    });
    this.current = this.spawn();
  }

  /** The live worker's ports. */
  worker(): WorkerPorts {
    return this.current.ports;
  }

  /** The live worker's daemon connection, to script the daemon (answer, emit, autoAnswer, sent). */
  connection(): FakeTransport {
    return this.current.connection;
  }

  /** The daemon end of the live worker's connection. */
  daemon(): FakeTransport['daemon'] {
    return this.current.connection.daemon;
  }

  /** Kill the live worker: its ports refuse from now on and its connection drops. */
  terminate(): void {
    if (!this.current.alive) return;
    this.current.alive = false;
    void this.current.connection.daemon.drop('disconnected');
  }

  /** Kill the live worker if needed, then start a new one over the same browser data and storage. */
  restart(): WorkerPorts {
    this.terminate();
    this.current = this.spawn();
    return this.current.ports;
  }

  private spawn(): Worker {
    const connection = new FakeTransport();
    const partial: { alive: boolean } = { alive: true };
    const bind = <T extends object>(target: T): T => this.bind(target, partial);
    const ports: WorkerPorts = {
      tree: bind<BookmarkTreePort>(this.tree),
      history: bind<HistoryPort>(this.history),
      content: bind<ContentSourcePort>(this.tabs),
      storage: bind<StoragePort>(this.storage),
      transport: bind<TransportPort>(connection),
      clock: bind<Clock>(this.clock),
      ids: bind<IdSource>(this.ids),
    };
    return Object.assign(partial, { connection, ports });
  }

  /** Wrap a port so each call first checks the worker is alive, and a WorkerTerminated from inside kills it. */
  private bind<T extends object>(target: T, worker: { alive: boolean }): T {
    const onDeath = (error: unknown): never => {
      if (error instanceof WorkerTerminated && worker === this.current) this.terminate();
      throw error;
    };
    return new Proxy(target, {
      get: (obj, prop) => {
        const value: unknown = Reflect.get(obj, prop, obj);
        if (typeof value !== 'function') return value;
        return (...args: unknown[]): unknown => {
          if (!worker.alive) {
            if (SYNC_METHODS.has(prop)) throw new WorkerTerminated();
            return Promise.reject(new WorkerTerminated());
          }
          const result: unknown = Reflect.apply(value, obj, args);
          return result instanceof Promise ? result.catch(onDeath) : result;
        };
      },
    });
  }
}
