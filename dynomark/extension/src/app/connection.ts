// connection.ts -- the connection lifecycle on the extension side (contract v1
// README, "Connection lifecycle", "Delivery and replay", "Roles and errors").
//
// A Connection is the TransportPort every other use case is handed. It says
// hello first on each connection, keeps what hello.result decided (mode,
// role, host id, owned roots), refuses locally any request the mode does not
// permit, and re-sends a request that went unanswered because the
// connection dropped (or the daemon answered hello_required) after a new
// hello, with the same id and body. `superseded` ends it for good.

import { isPermitted, modeFor, type ConnectionMode, type HostRole } from '../domain/roles.js';
import { fitPath } from '../domain/limits.js';
import type { FolderPath, OwnedRoots } from '../domain/tree.js';
import type { HostId, ProfileId } from '../domain/values.js';
import type { IdSource } from '../ports/idSource.js';
import { TransportLost, type TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION, type ErrorMessage, type EventMessage, type RequestMessage, type ResultOf } from '../wire/messages.js';
import { DaemonError } from './errors.js';

// --- Constants ---

/** How many times one request is re-sent after its connection is lost before the loss is reported. */
export const MAX_RESENDS = 3;

// --- Types ---

/** Who this extension is on every hello: its profile and the Follow Up folder it resolved. */
export interface ConnectionIdentity {
  readonly profile_id: ProfileId;
  readonly follow_up: FolderPath;
}

/** What hello.result decided for this connection. */
export interface HelloOutcome {
  readonly v: number;
  readonly mode: ConnectionMode;
  readonly role: HostRole;
  readonly host_id: HostId;
  readonly owned_roots: OwnedRoots;
}

/** Runs after every successful hello (the connect routine), before the request that triggered it. */
export type OnReady = (outcome: HelloOutcome) => Promise<void>;

/** The connection's mode does not permit this request; it never reached the wire. */
export class ModeRefused extends Error {
  readonly mode: ConnectionMode;

  constructor(mode: ConnectionMode, type: string) {
    super(`${type} is not permitted on a ${mode} connection`);
    this.name = 'ModeRefused';
    this.mode = mode;
  }
}

/** The daemon answered in a way the contract forbids; the connection is not used again. */
export class ContractViolation extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ContractViolation';
  }
}

type State =
  | { readonly kind: 'down' }
  | { readonly kind: 'connecting'; readonly ready: Promise<HelloOutcome> }
  | { readonly kind: 'up'; readonly outcome: HelloOutcome }
  | { readonly kind: 'broken'; readonly error: Error };

// --- Predicates ---

function samePath(a: FolderPath, b: FolderPath): boolean {
  return a.root === b.root && a.names.length === b.names.length && a.names.every((name, i) => b.names[i] === name);
}

function isHelloRequired(response: { readonly type: string }): boolean {
  return response.type === 'error' && (response as ErrorMessage).code === 'hello_required';
}

function isDisconnect(error: unknown): boolean {
  return error instanceof TransportLost && error.reason === 'disconnected';
}

// --- Pure helpers ---

/** The outcome of a hello.result, or the contract rule it breaks. */
function helloOutcome(result: ResultOf<'hello'>, identity: ConnectionIdentity): HelloOutcome | ContractViolation {
  if (!samePath(result.owned_roots.follow_up, fitPath(identity.follow_up))) {
    return new ContractViolation('hello.result owned_roots.follow_up differs from the follow_up this extension sent');
  }
  if (result.mode !== modeFor(CONTRACT_VERSION, result.v)) {
    return new ContractViolation(
      `hello.result mode ${result.mode} contradicts versions ${CONTRACT_VERSION} (extension) and ${result.v} (daemon)`,
    );
  }
  return { v: result.v, mode: result.mode, role: result.role, host_id: result.host_id, owned_roots: result.owned_roots };
}

// --- The connection ---

export class Connection implements TransportPort {
  private state: State = { kind: 'down' };
  /** Counts handshakes, so a loss reported by a request sent on an older connection cannot tear down a newer one. */
  private generation = 0;

  constructor(
    private readonly identity: ConnectionIdentity,
    private readonly deps: { readonly transport: TransportPort; readonly ids: IdSource },
    private readonly onReady: OnReady = () => Promise.resolve(),
  ) {}

  /** What the current connection's hello decided; undefined before hello or after a loss. */
  outcome(): HelloOutcome | undefined {
    return this.state.kind === 'up' ? this.state.outcome : undefined;
  }

  /** Say hello on the current connection if it has not been said, then run the connect routine. */
  connect(): Promise<HelloOutcome> {
    switch (this.state.kind) {
      case 'broken':
        return Promise.reject(this.state.error);
      case 'up':
        return Promise.resolve(this.state.outcome);
      case 'connecting':
        return this.state.ready;
      case 'down': {
        this.generation += 1;
        const ready = this.handshake(this.generation);
        this.state = { kind: 'connecting', ready };
        return ready;
      }
    }
  }

  async send<R extends RequestMessage>(request: R): Promise<ResultOf<R['type']> | ErrorMessage> {
    for (let attempt = 0; ; attempt += 1) {
      let generation = this.generation;
      try {
        const outcome = await this.connect();
        generation = this.generation;
        if (!isPermitted(outcome.mode, request.type)) throw new ModeRefused(outcome.mode, request.type);
        const response = await this.deps.transport.send(request);
        if (!isHelloRequired(response) || attempt >= MAX_RESENDS) return response;
        this.lose(this.generation);
      } catch (error) {
        this.noteFailure(error, generation);
        if (!isDisconnect(error) || attempt >= MAX_RESENDS) throw error;
      }
    }
  }

  onEvent(listener: (event: EventMessage) => void): () => void {
    return this.deps.transport.onEvent(listener);
  }

  private async handshake(generation: number): Promise<HelloOutcome> {
    const hello = {
      v: CONTRACT_VERSION,
      type: 'hello',
      id: this.deps.ids.next(),
      profile_id: this.identity.profile_id,
      follow_up: fitPath(this.identity.follow_up),
    } as const;
    try {
      const response = await this.deps.transport.send(hello);
      if (response.type === 'error') throw new DaemonError(response);
      const outcome = helloOutcome(response, this.identity);
      if (outcome instanceof ContractViolation) {
        this.state = { kind: 'broken', error: outcome };
        throw outcome;
      }
      this.state = { kind: 'up', outcome };
      await this.onReady(outcome);
      return outcome;
    } catch (error) {
      this.noteFailure(error, generation);
      throw error;
    }
  }

  /** A superseded connection is over for good; a disconnect (or a failed hello) returns to down so the next send says hello again. */
  private noteFailure(error: unknown, generation: number): void {
    if (error instanceof TransportLost && error.reason === 'superseded') this.state = { kind: 'broken', error };
    else if (isDisconnect(error)) this.lose(generation);
    else if (this.state.kind === 'connecting' && generation === this.generation) this.state = { kind: 'down' };
  }

  private lose(generation: number): void {
    if (generation === this.generation && this.state.kind !== 'broken') this.state = { kind: 'down' };
  }
}
