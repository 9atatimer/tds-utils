// FakeChatSurface.ts -- an in-memory ChatSurfacePort: records every time the
// chat surface was opened, and with which pre-sent question.

import type { Question } from '../../src/domain/chat.js';
import type { ChatSurfacePort } from '../../src/ports/chatSurface.js';

export class FakeChatSurface implements ChatSurfacePort {
  /** Each opening's pre-sent question (undefined: opened empty), in order. */
  readonly opened: (Question | undefined)[] = [];

  open(question: Question | undefined): Promise<void> {
    this.opened.push(question);
    return Promise.resolve();
  }
}
