/// <reference types="chrome" />
// navigator.ts -- the Navigator on chrome.tabs: the current tab is navigated,
// or a tab is opened in the foreground or background, as the omnibox reports
// the user's choice.

import type { Url } from '../../domain/values.js';
import type { Disposition, Navigator } from '../../ports/navigator.js';

// --- Types ---

/** The part of chrome.tabs this adapter uses. */
export interface NavigatorTabsApi {
  update(properties: { url: string }): Promise<unknown>;
  create(properties: { url: string; active: boolean }): Promise<unknown>;
}

// --- The adapter ---

export class ChromeNavigator implements Navigator {
  constructor(private readonly tabs: NavigatorTabsApi = chrome.tabs) {}

  async open(url: Url, disposition: Disposition): Promise<void> {
    if (disposition === 'currentTab') await this.tabs.update({ url });
    else await this.tabs.create({ url, active: disposition === 'newForegroundTab' });
  }
}
