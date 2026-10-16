// chatSurface.ts -- the ChatSurfacePort on Firefox (task-032: the sidebar is
// the chat surface; manifest "sidebar_action" shows chat.html). Opened with
// no question (the toolbar's sidebar button, the keyboard shortcut, or this
// call), the sidebar shows the chat. Firefox opens a sidebar only while it is
// handling a user action, so sidebarAction.open is called before anything is
// awaited; when Firefox refuses it, the page opens as it does on Chrome. A
// question is not put into the sidebar: its panel URL would keep the question
// and re-ask it each time the sidebar is opened again, so the page carrying it
// opens as on Chrome (a popup window, else a tab).

import type { Question } from '../../domain/chat.js';
import type { ChatSurfacePort } from '../../ports/chatSurface.js';
import type { SidebarActionApi } from './namespace.js';

// --- The adapter ---

export class FirefoxChatSurface implements ChatSurfacePort {
  constructor(
    private readonly sidebar: SidebarActionApi,
    /** Where the chat opens when the sidebar cannot show it. */
    private readonly fallback: ChatSurfacePort,
  ) {}

  open(question: Question | undefined): Promise<void> {
    if (question !== undefined) return this.fallback.open(question);
    return this.sidebar.open().catch(() => this.fallback.open(undefined));
  }
}
