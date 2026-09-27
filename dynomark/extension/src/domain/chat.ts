// chat.ts -- one chat exchange (design, "Turn / Question / Answer / Citation")
// and the conversation the chat page keeps (design, "Chat surface":
// conversation state lives in the page), sent as history within the
// contract's caps.

import { MAX_ANSWER_TEXT, MAX_HISTORY_TURNS, MAX_QUESTION, fitText } from './limits.js';
import type { FolderPath } from './tree.js';
import type { Identity, Title, Url } from './values.js';

/** The user's text. */
export type Question = string;

/** A prior exchange sent as history. */
export interface Turn {
  readonly question: Question;
  readonly answer: string;
}

/** A corpus entry named by identity, with where it is filed. */
export interface EntryRef {
  readonly identity: Identity;
  readonly title: Title;
  readonly path: FolderPath;
}

/** A reference to a `CorpusEntry` identity the retrieval step returned. */
export type Citation = EntryRef;

/** The grounded reply: citations from the corpus, other URLs marked external. */
export interface Answer {
  readonly text: string;
  readonly citations: readonly Citation[];
  readonly external_urls: readonly Url[];
}

// --- Pure helpers ---

/** The question as it may be sent: trimmed, well-formed and within its cap; undefined when blank. */
export function askableQuestion(question: Question): Question | undefined {
  const trimmed = question.trim();
  return trimmed === '' ? undefined : fitText(trimmed, MAX_QUESTION).text;
}

/** The most recent turns, oldest first, each well-formed and within its caps; blank questions are left out. */
export function historyFor(turns: readonly Turn[]): Turn[] {
  return turns
    .flatMap((turn) => {
      const question = askableQuestion(turn.question);
      return question === undefined ? [] : [{ question, answer: fitText(turn.answer, MAX_ANSWER_TEXT).text }];
    })
    .slice(-MAX_HISTORY_TURNS);
}

/** The conversation with one more exchange at the end. */
export function withTurn(turns: readonly Turn[], turn: Turn): Turn[] {
  return [...turns, turn];
}
