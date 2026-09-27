// runtime.ts -- the extension's background workflow, over ports only (design,
// "The extension"; Module map: "the extension's background entry point wires
// the browser adapters and the transport adapter"). The entry point
// (src/background.ts) builds the chrome adapters and hands them here; this
// file decides what happens, so every step runs on the fakes too.
//
// On start: settings (a profile id generated once), Follow Up (created under
// the bar when missing; extra ones reported), the LocalIndex from storage,
// then one Connection whose every hello runs the connect routine (snapshot,
// replay, index pull) and, when full, re-ingests the Follow Up backlog.
// Daemon events go to DaemonEvents (batch offers to the BatchLane); bookmark
// events to the TreeWatch; a lost link is reconnected with backoff. Every
// step is short and repeatable: the worker can die between any two events.

import type { Settings, SettingsChange } from '../domain/settings.js';
import { isOpenable } from '../domain/search.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { BookmarkEvent } from '../ports/bookmarkEvents.js';
import type { ChatSurfacePort } from '../ports/chatSurface.js';
import type { Clock } from '../ports/clock.js';
import type { ContentSourcePort } from '../ports/contentSource.js';
import type { HistoryPort } from '../ports/history.js';
import type { IdSource } from '../ports/idSource.js';
import type { Disposition, Navigator } from '../ports/navigator.js';
import type { PageRequest, PageResponse } from '../ports/pages.js';
import type { StoragePort } from '../ports/storage.js';
import type { Timer } from '../ports/timer.js';
import { TransportLost, type LinkState, type TransportLink, type TransportPort } from '../ports/transport.js';
import type { WriteBatch } from '../domain/batch.js';
import type { BatchContext } from './applyBatch.js';
import { Backfill } from './backfill.js';
import { BatchLane } from './batchLane.js';
import { Connection, type HelloOutcome } from './connection.js';
import { DiffAcceptance } from './diffs.js';
import { DaemonEvents } from './daemonEvents.js';
import { openFollowUp, type FollowUpFolder } from './followUp.js';
import { IndexCache } from './indexCache.js';
import { IssuedMoves } from './issuedMoves.js';
import { OmniboxSession, type Suggest } from './omnibox.js';
import { onConnected } from './onConnected.js';
import { answerPage } from './pages.js';
import { Reconnector } from './reconnect.js';
import { changeSettings, ensureSettings } from './settings.js';
import { SubmittedSaves } from './submitSave.js';
import { TreeWatch } from './treeWatch.js';
import { WriterWatch } from './writerWatch.js';

export { SNAPSHOT_DEBOUNCE_MS } from './treeWatch.js';

// --- Constants ---

/** Problems kept for the options page, newest last. */
const MAX_PROBLEMS = 20;

// --- Types ---

/** Every port the background needs; the entry point supplies the chrome adapters. */
export interface RuntimePorts {
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

/** What start() established; the rest of the runtime waits for it. */
interface Started {
  readonly settings: Settings;
  readonly followUp: FollowUpFolder;
  readonly connection: Connection;
  readonly watch: TreeWatch;
  readonly backfill: Backfill;
}

// --- The runtime ---

export class ExtensionRuntime {
  private readonly tracked = new Set<Promise<unknown>>();
  private readonly problemLog: string[] = [];
  private readonly index: IndexCache;
  private readonly issued: IssuedMoves;
  private readonly omnibox: OmniboxSession;
  private readonly saves: SubmittedSaves;
  private readonly acceptance = new DiffAcceptance();
  private readonly writer = new WriterWatch();
  /** Offers pass here in the order they arrived, each after any writer conflict is re-checked. */
  private admission: Promise<void> = Promise.resolve();
  private readonly ready: Promise<Started>;
  private resolveReady: (started: Started) => void = () => undefined;
  private state: Started | undefined;

  constructor(private readonly ports: RuntimePorts) {
    this.ready = new Promise((resolve) => (this.resolveReady = resolve));
    this.saves = new SubmittedSaves(ports.storage);
    this.index = new IndexCache(ports, (work) => this.track(work));
    this.issued = new IssuedMoves(ports.tree);
    this.omnibox = new OmniboxSession({
      transport: { send: (r) => this.connection().then((c) => c.send(r)), onEvent: () => () => undefined },
      ids: ports.ids,
      timer: ports.timer,
      index: () => this.index.index(),
      frecency: () => this.index.frecency(),
      roots: () => this.state?.connection.outcome()?.owned_roots,
      track: (work) => this.track(work),
    });
  }

  /** Load settings, open Follow Up and the index, and start connecting. Resolves before the daemon answers. */
  async start(): Promise<void> {
    const settings = await ensureSettings(this.ports);
    const followUp = await openFollowUp(this.ports);
    if (followUp.others.length > 0) {
      this.problem(`other folders named Follow Up are not watched: node ids ${followUp.others.join(', ')}`);
    }
    await this.index.load();
    const connection = this.connect(settings, followUp);
    const watch = new TreeWatch(
      { ...this.ports, transport: connection, saves: this.saves },
      {
        followUp: () => this.state?.followUp.path,
        outcome: () => connection.outcome(),
        settings: () => this.state?.settings ?? settings,
        isOwnMove: (node_id, parent_id) => this.issued.consume(node_id, parent_id),
        track: (work) => this.track(work),
        snapshotSent: () => this.track(this.writer.confirm({ transport: connection, ids: this.ports.ids })),
      },
    );
    const backfill = new Backfill(
      { ...this.ports, transport: connection },
      {
        skip: () => {
          const outcome = connection.outcome();
          if (outcome?.mode !== 'full') return undefined;
          return [followUp.path, outcome.owned_roots.follow_up, outcome.owned_roots.graveyard];
        },
        track: (work) => this.track(work),
        problem: (message) => this.problem(message),
      },
    );
    this.state = { settings, followUp, connection, watch, backfill };
    this.resolveReady(this.state);
  }

  /** A bookmark event from the browser; handled once start() is done. */
  onBookmarkEvent(event: BookmarkEvent): void {
    this.track(this.ready.then((s) => s.watch.handle(event)));
  }

  /** One omnibox keystroke. */
  omniboxInput(text: string, suggest: Suggest): void {
    this.omnibox.input(text, suggest);
  }

  /** Omnibox Enter: open the chosen hit's identity (http(s) only), or open the chat surface with the question. */
  async omniboxEnter(text: string, disposition: Disposition): Promise<void> {
    await this.ready; // the stored index is loaded: a fresh worker decides on the same rows
    const action = this.omnibox.enter(text);
    if (action.kind === 'ask') await this.ports.surface.open(action.question);
    else if (action.kind === 'open' && isOpenable(action.identity)) await this.ports.navigator.open(action.identity, disposition);
  }

  /** The keyboard command: open the chat surface empty. */
  async openChat(): Promise<void> {
    await this.ports.surface.open(undefined);
  }

  /** Answer an extension page. */
  async page(request: PageRequest): Promise<PageResponse> {
    const started = await this.ready;
    const response = await answerPage(request, {
      transport: started.connection,
      ids: this.ports.ids,
      tree: this.ports.tree,
      navigator: this.ports.navigator,
      clock: this.ports.clock,
      acceptance: this.acceptance,
      writer: this.writer,
      backfill: started.backfill,
      link: () => this.ports.transport.linkState(),
      outcome: () => started.connection.outcome(),
      settings: () => this.state?.settings ?? started.settings,
      changeSettings: (change) => this.updateSettings(change),
      followUp: () => this.state?.followUp.path,
      problems: () => [...this.problemLog],
    });
    if (!response.ok && response.code === 'writer_conflict') this.writer.noteRefusal();
    return response;
  }

  /** Resolves once no background work (event handling, pulls, debounced sends already due) is running. */
  async idle(): Promise<void> {
    while (this.tracked.size > 0) await Promise.allSettled([...this.tracked]);
  }

  // --- Wiring ---

  private connect(settings: Settings, followUp: FollowUpFolder): Connection {
    const storage = this.index.observing(this.ports.storage);
    const connection: Connection = new Connection(
      { profile_id: settings.profile_id, follow_up: followUp.path },
      { transport: this.ports.transport, ids: this.ports.ids },
      (outcome) => this.onReady(outcome, connection, storage),
    );
    const laneDeps = { ...this.ports, tree: this.issued, storage, transport: connection };
    const lane = new BatchLane(() => this.batchContext(connection.outcome()), laneDeps);
    const events = new DaemonEvents(
      { transport: connection, ids: this.ports.ids, storage, timer: this.ports.timer },
      { offer: (batch) => this.admit(batch, lane, connection) },
      (work) => this.track(work),
    );
    connection.onEvent((event) => this.track(events.handle(event)));
    const reconnector = new Reconnector(() => connection.connect(), { timer: this.ports.timer, track: (work) => this.track(work) });
    this.ports.transport.onLink((link) => this.onLink(link, connection, reconnector));
    reconnector.now();
    return connection;
  }

  /**
   * The connect routine, then (full mode) the Follow Up backlog, backfill and
   * writer status. A routine step that fails for any reason but a lost link
   * is reported and does not hold those back; the failure still reaches the
   * Connection, which runs the routine again at the reconnector's next try.
   */
  private async onReady(outcome: HelloOutcome, connection: Connection, storage: StoragePort): Promise<void> {
    try {
      await onConnected(outcome, { ...this.ports, tree: this.issued, storage, transport: connection });
    } catch (error) {
      if (error instanceof TransportLost) throw error;
      this.problem(`connect routine: ${error instanceof Error ? error.message : String(error)}`);
      this.afterConnect(outcome, connection);
      throw error;
    }
    this.afterConnect(outcome, connection);
  }

  private afterConnect(outcome: HelloOutcome, connection: Connection): void {
    if (outcome.mode !== 'full') return;
    this.track(this.ready.then((s) => s.watch.submitBacklog()));
    this.track(this.ready.then((s) => s.backfill.resume()));
    this.track(
      this.writer
        .refresh({ transport: connection, ids: this.ports.ids })
        .catch((error: unknown) => this.problem(`writer.status: ${String(error)}`)),
    );
  }

  /** Hand an offer to the lane in arrival order, once a reported writer conflict has been asked about again. */
  private admit(batch: WriteBatch, lane: BatchLane, connection: Connection): Promise<void> {
    const admitted = this.admission.then(() => this.writer.confirm({ transport: connection, ids: this.ports.ids }));
    this.admission = admitted;
    return admitted.then(() => lane.offer(batch));
  }

  private onLink(link: LinkState, connection: Connection, reconnector: Reconnector): void {
    try {
      if (link.state === 'superseded') reconnector.stop();
      if (link.state !== 'disconnected') return;
      connection.linkLost();
      reconnector.schedule();
    } catch (error) {
      this.problem(`reconnect: ${String(error)}`);
    }
  }

  private batchContext(outcome: HelloOutcome | undefined): BatchContext | undefined {
    if (outcome === undefined) return undefined;
    return { owned_roots: outcome.owned_roots, host_id: outcome.host_id, writer_conflict: this.writer.conflict() };
  }

  private async connection(): Promise<Connection> {
    return (await this.ready).connection;
  }

  private async updateSettings(change: SettingsChange): Promise<Settings> {
    const started = await this.ready;
    const next = await changeSettings(this.state?.settings ?? started.settings, change, this.ports);
    this.state = { ...(this.state ?? started), settings: next };
    return next;
  }

  // --- Bookkeeping ---

  private track(work: Promise<unknown>): void {
    const settled = work.catch((error: unknown) => this.problem(error instanceof Error ? error.message : String(error)));
    this.tracked.add(settled);
    void settled.finally(() => this.tracked.delete(settled));
  }

  private problem(message: string): void {
    this.problemLog.push(message);
    if (this.problemLog.length > MAX_PROBLEMS) this.problemLog.shift();
  }
}
