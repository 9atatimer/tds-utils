// chatSurface.ts -- the ChatSurfacePort: show the chat surface (design, "The
// extension": Chat surface is an extension page; Ask fall-through opens it
// with the query pre-sent). Where it appears (a popup window, a tab) is the
// adapter's business.

import type { Question } from '../domain/chat.js';

export interface ChatSurfacePort {
  /** Show the chat surface; `question`, when given, is sent as soon as it opens. */
  open(question: Question | undefined): Promise<void>;
}
