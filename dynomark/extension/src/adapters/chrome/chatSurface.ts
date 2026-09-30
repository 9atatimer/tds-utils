/// <reference types="chrome" />
// chatSurface.ts -- the ChatSurfacePort on chrome.windows (design, "The
// extension": Chat surface is an extension page). chat.html opens in a small
// focused popup window, carrying the pre-sent question in its query string;
// a browser that refuses a popup window (no normal window to anchor it) gets
// a foreground tab instead.

import type { Question } from '../../domain/chat.js';
import type { ChatSurfacePort } from '../../ports/chatSurface.js';

// --- Types ---

/** The part of chrome.windows this adapter uses. */
export interface ChatWindowsApi {
  create(data: { url: string; type: 'popup'; width: number; height: number; focused: boolean }): Promise<unknown>;
}

/** The part of chrome.tabs this adapter uses. */
export interface ChatTabsApi {
  create(properties: { url: string; active: boolean }): Promise<unknown>;
}

/** The part of chrome.runtime this adapter uses. */
export interface ExtensionUrlApi {
  getURL(path: string): string;
}

// --- Constants ---

const CHAT_PAGE = 'chat.html';
const POPUP_SIZE = { width: 560, height: 720 } as const;

// --- Pure helpers ---

/** The chat page's path, with the question to pre-send (URL-encoded) when there is one. */
export function chatPagePath(question: Question | undefined): string {
  return question === undefined ? CHAT_PAGE : `${CHAT_PAGE}?q=${encodeURIComponent(question)}`;
}

// --- The adapter ---

export class ChromeChatSurface implements ChatSurfacePort {
  constructor(
    private readonly windows: ChatWindowsApi = chrome.windows,
    private readonly tabs: ChatTabsApi = chrome.tabs,
    private readonly runtime: ExtensionUrlApi = chrome.runtime,
  ) {}

  async open(question: Question | undefined): Promise<void> {
    const url = this.runtime.getURL(chatPagePath(question));
    try {
      await this.windows.create({ url, type: 'popup', ...POPUP_SIZE, focused: true });
    } catch {
      await this.tabs.create({ url, active: true });
    }
  }
}
