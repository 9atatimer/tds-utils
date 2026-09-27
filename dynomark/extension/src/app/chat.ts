// chat.ts -- the extension half of the chat (design, "The extension": Chat
// surface; Behaviors rows "A question is answered with citations", "An
// out-of-corpus URL is marked", "A placement is explained"). Grounding --
// keeping only retrieved identities as citations, marking the rest external
// -- is the daemon's `ask`; the extension sends the question with the history
// the page kept, asks "why here", and files a URL the way a user would: by
// adding it to Follow Up, where the watch captures and ingests it.

import { askableQuestion, historyFor, type Answer, type Question, type Turn } from '../domain/chat.js';
import { isCapturableUrl } from '../domain/capture.js';
import type { PlacementReason } from '../domain/diff.js';
import { existingBookmark } from '../domain/ops.js';
import { MAX_TITLE, fitText } from '../domain/limits.js';
import type { FolderPath } from '../domain/tree.js';
import type { Identity, NodeId, Title, Url } from '../domain/values.js';
import type { BookmarkTreePort } from '../ports/bookmarkTree.js';
import type { IdSource } from '../ports/idSource.js';
import type { TransportPort } from '../ports/transport.js';
import { CONTRACT_VERSION } from '../wire/messages.js';
import { resultOrThrow } from './errors.js';

// --- Types ---

interface Talk {
  readonly transport: TransportPort;
  readonly ids: IdSource;
}

/** The Follow Up bookmark a "file this" produced, and whether this call made it. */
export interface Filed {
  readonly node_id: NodeId;
  readonly created: boolean;
}

// --- Flow ---

/** Ask the daemon; the answer's citations are the corpus entries its retrieval returned, other URLs external. */
export async function askQuestion(question: Question, history: readonly Turn[], deps: Talk): Promise<Answer> {
  const asked = askableQuestion(question);
  if (asked === undefined) throw new Error('an empty question is not asked');
  const frame = { v: CONTRACT_VERSION, type: 'ask', id: deps.ids.next(), question: asked, history: historyFor(history) } as const;
  return resultOrThrow(await deps.transport.send(frame)).answer;
}

/** "Why here": the reason the daemon recorded when it placed this entry. */
export async function explainPlacement(identity: Identity, deps: Talk): Promise<PlacementReason> {
  const frame = { v: CONTRACT_VERSION, type: 'placement.explain', id: deps.ids.next(), identity } as const;
  return resultOrThrow(await deps.transport.send(frame)).reason;
}

/** "File this": a bookmark with exactly `url` in Follow Up, unless one is already there. Only http(s) URLs. */
export async function fileThis(url: Url, title: Title, followUp: FolderPath, deps: { readonly tree: BookmarkTreePort }): Promise<Filed> {
  if (!isCapturableUrl(url)) throw new Error('only http(s) URLs are filed');
  const folder = await deps.tree.resolveFolder(followUp);
  if (folder === undefined) throw new Error('the Follow Up folder does not resolve');
  const existing = existingBookmark(await deps.tree.getChildren(folder), folder, url);
  if (existing !== undefined) return { node_id: existing.id, created: false };
  const name = title.trim() === '' ? url : fitText(title, MAX_TITLE).text;
  return { node_id: (await deps.tree.createBookmark(folder, name, url)).id, created: true };
}
