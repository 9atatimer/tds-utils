// runtime.ts -- an ExtensionRuntime on one fake worker, its daemon scripted:
// the lifecycle answers of scriptedDaemon plus whatever `extra` answers first.

import { ExtensionRuntime } from '../../src/app/runtime.js';
import type { RequestMessage, ResponseMessage } from '../../src/wire/messages.js';
import { FakeExtensionWorld } from '../fakes/FakeExtensionWorld.js';
import { scriptedDaemon, type HelloAnswer } from './daemon.js';

// --- Types ---

/** Answers a test gives before the scripted daemon's: undefined falls through. */
export type ExtraAnswers = (r: RequestMessage) => ResponseMessage | undefined;

// --- Builders ---

/** Script the live worker's daemon: `extra` first, then the lifecycle answers. */
export function scriptDaemon(w: FakeExtensionWorld, hello: HelloAnswer = {}, extra: ExtraAnswers = () => undefined): void {
  const lifecycle = scriptedDaemon(hello);
  w.connection().autoAnswer((r) => extra(r) ?? lifecycle(r));
}

/** A runtime on the live worker, started, and settled. */
export async function startRuntime(w: FakeExtensionWorld): Promise<ExtensionRuntime> {
  const runtime = new ExtensionRuntime(w.worker());
  await runtime.start();
  await runtime.idle();
  return runtime;
}

/** The types of every request the live worker sent, in order. */
export function sentTypes(w: FakeExtensionWorld): string[] {
  return w.connection().sent.map((r) => r.type);
}

/** Every request of `type` the live worker sent. */
export function sentOf<T extends RequestMessage['type']>(w: FakeExtensionWorld, type: T): Extract<RequestMessage, { type: T }>[] {
  return w.connection().sent.filter((r): r is Extract<RequestMessage, { type: T }> => r.type === type);
}
