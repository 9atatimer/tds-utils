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
import type { Navigator } from '../../src/ports/navigator.js';
import type { ChatSurfacePort } from '../../src/ports/chatSurface.js';
import type { Timer } from '../../src/ports/timer.js';
import type { TransportLink, TransportPort } from '../../src/ports/transport.js';
import { FakeBackgroundTabs } from './FakeBackgroundTabs.js';
import { FakeBookmarkTree } from './FakeBookmarkTree.js';
import { FakeChatSurface } from './FakeChatSurface.js';
import { FakeClock } from './FakeClock.js';
import { FakeHistory } from './FakeHistory.js';
import { FakeNavigator } from './FakeNavigator.js';
import { FakeStorage } from './FakeStorage.js';
import { FakeTabs } from './FakeTabs.js';
import { FakeTimer } from './FakeTimer.js';
import { FakeTransport } from './FakeTransport.js';
import { SequentialIdSource } from './SequentialIdSource.js';
import { WorkerTerminated } from './WorkerTerminated.js';

// --- Constants ---

const DEFAULT_START: EpochMs = 1_790_000_000_000;

/** Methods that return a value rather than a promise: a dead worker's call throws instead of rejecting. */
const SYNC_METHODS: ReadonlySet<PropertyKey> = new Set(['now', 'next', 'onEvent', 'after', 'onLink', 'linkState']);

// --- Types ---

/** The ports one service worker holds; what the composition root will hand the use cases. */
export interface WorkerPorts {
  readonly tree: BookmarkTreePort;
  readonly history: HistoryPort;
  readonly content: ContentSourcePort;
  /** Opens a URL in a background tab and reads it (the writer's third ContentSourcePort adapter). */
  readonly background: ContentSourcePort;
  readonly storage: StoragePort;
  readonly transport: TransportPort & TransportLink;
  readonly clock: Clock;
  readonly ids: IdSource;
  readonly timer: Timer;
  readonly navigator: Navigator;
  readonly surface: ChatSurfacePort;
}

export interface FakeExtensionWorldOptions {
  readonly flavor: 'chrome' | 'firefox';
  readonly accountStorage?: boolean;
  readonly start?: EpochMs;
}

interface Worker {
  alive: boolean;
  readonly connection: FakeTransport;
  readonly timer: FakeTimer;
  readonly ports: WorkerPorts;
}

// --- The world ---

export class FakeExtensionWorld {
  readonly clock: FakeClock;
  readonly tree: FakeBookmarkTree;
  readonly history = new FakeHistory();
  readonly tabs = new FakeTabs();
  /** What a background tab would show for each URL (the browser is signed in); every URL opened. */
  readonly backgroundTabs = new FakeBackgroundTabs();
  readonly storage = new FakeStorage();
  readonly ids = new SequentialIdSource();
  /** Every navigation any worker asked for (the browser's tabs outlive workers). */
  readonly navigator = new FakeNavigator();
  /** Every time any worker opened the chat surface. */
  readonly surface = new FakeChatSurface();
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

  /** The live worker's timers; advancing them moves the shared clock. */
  timer(): FakeTimer {
    return this.current.timer;
  }

  /** The daemon end of the live worker's connection. */
  daemon(): FakeTransport['daemon'] {
    return this.current.connection.daemon;
  }

  /** Kill the live worker: its ports refuse from now on and its connection drops. */
  terminate(): void {
    if (!this.current.alive) return;
    this.current.alive = false;
    this.current.timer.clear();
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
    const timer = new FakeTimer(this.clock);
    const partial: { alive: boolean } = { alive: true };
    const bind = <T extends object>(target: T): T => this.bind(target, partial);
    const ports: WorkerPorts = {
      tree: bind<BookmarkTreePort>(this.tree),
      history: bind<HistoryPort>(this.history),
      content: bind<ContentSourcePort>(this.tabs),
      background: bind<ContentSourcePort>(this.backgroundTabs),
      storage: bind<StoragePort>(this.storage),
      transport: bind<TransportPort & TransportLink>(connection),
      clock: bind<Clock>(this.clock),
      ids: bind<IdSource>(this.ids),
      timer: bind<Timer>(timer),
      navigator: bind<Navigator>(this.navigator),
      surface: bind<ChatSurfacePort>(this.surface),
    };
    return Object.assign(partial, { connection, timer, ports });
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
