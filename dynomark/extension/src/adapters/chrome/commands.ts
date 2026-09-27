/// <reference types="chrome" />
// commands.ts -- the extension's keyboard commands on chrome.commands
// (manifest "commands"). Listeners are added synchronously when called, so the
// service worker registers them before its first await.

// --- Types ---

interface EventLike<A extends unknown[]> {
  addListener(callback: (...args: A) => void): void;
}

/** The part of chrome.commands this adapter uses. */
export interface CommandsApi {
  readonly onCommand: EventLike<[string]>;
}

// --- Constants ---

/** Opens the chat surface empty (manifest "commands"). */
export const OPEN_CHAT_COMMAND = 'open-chat';

// --- Entry ---

/** Run the handler named by each command that fires; unknown commands are ignored. */
export function listenCommands(handlers: Readonly<Record<string, () => void>>, api: CommandsApi = chrome.commands): void {
  api.onCommand.addListener((command) => {
    if (Object.hasOwn(handlers, command)) handlers[command]?.();
  });
}
