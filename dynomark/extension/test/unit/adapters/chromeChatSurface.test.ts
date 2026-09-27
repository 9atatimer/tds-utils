// chromeChatSurface.test.ts -- the chat surface on chrome.windows (design,
// "The extension": Chat surface is an extension page; Ask fall-through opens
// it with the query pre-sent): a popup window on chat.html, a tab when the
// browser refuses a popup; and the keyboard command that opens it empty.

import { describe, expect, it } from 'vitest';
import { ChromeChatSurface, chatPagePath } from '../../../src/adapters/chrome/chatSurface.js';
import { OPEN_CHAT_COMMAND, listenCommands } from '../../../src/adapters/chrome/commands.js';
import { EventStub } from '../../stubs/chromeEvents.js';

// --- Builders ---

function apis(options: { readonly popupFails?: boolean } = {}) {
  const calls: string[] = [];
  return {
    calls,
    windows: {
      create: (data: { url: string; type: 'popup'; focused: boolean }) => {
        if (options.popupFails === true) return Promise.reject(new Error('No current window'));
        calls.push(`popup ${data.url} focused=${String(data.focused)}`);
        return Promise.resolve({});
      },
    },
    tabs: {
      create: (p: { url: string; active: boolean }) => Promise.resolve(void calls.push(`tab ${p.url} active=${String(p.active)}`)),
    },
    runtime: { getURL: (path: string) => `chrome-extension://self/${path}` },
  };
}

// --- Tests ---

describe('chatPagePath', () => {
  it('Given a question, When the page path is built, Then it carries the question URL-encoded; none gives the bare page', () => {
    expect(chatPagePath('a&b = c?')).toBe('chat.html?q=a%26b%20%3D%20c%3F');
    expect(chatPagePath(undefined)).toBe('chat.html');
  });
});

describe('ChromeChatSurface', () => {
  it('Given a question, When the surface opens, Then a focused popup window shows chat.html with it', async () => {
    const a = apis();
    await new ChromeChatSurface(a.windows, a.tabs, a.runtime).open('why rust');
    expect(a.calls).toEqual(['popup chrome-extension://self/chat.html?q=why%20rust focused=true']);
  });

  it('Given the browser refuses a popup window, When the surface opens, Then a foreground tab shows it instead', async () => {
    const a = apis({ popupFails: true });
    await new ChromeChatSurface(a.windows, a.tabs, a.runtime).open(undefined);
    expect(a.calls).toEqual(['tab chrome-extension://self/chat.html active=true']);
  });
});

describe('listenCommands', () => {
  it('Given the open-chat command and an unknown one, When they fire, Then only the open-chat handler runs', () => {
    const onCommand = new EventStub<[string]>();
    const ran: string[] = [];
    listenCommands({ [OPEN_CHAT_COMMAND]: () => void ran.push('chat') }, { onCommand });
    onCommand.fire(OPEN_CHAT_COMMAND);
    onCommand.fire('something-else');
    expect(ran).toEqual(['chat']);
  });
});
