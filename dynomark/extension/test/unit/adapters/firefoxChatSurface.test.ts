// firefoxChatSurface.test.ts -- the chat surface on Firefox (task-032: the
// sidebar is the chat surface). With no question the sidebar opens; Firefox
// opens it only while handling a user action, so the call is made before
// anything is awaited, and when Firefox refuses it the page opens as on Chrome
// (a popup window, else a tab). A question opens that page carrying it: a
// sidebar's panel URL would keep the question and re-ask it every time the
// sidebar is opened again.

import { describe, expect, it } from 'vitest';
import { firefoxPorts } from '../../../src/adapters/firefox/ports.js';
import { fakeFirefox } from '../../stubs/firefoxBrowser.js';

describe('Firefox chat surface', () => {
  it('Given no question, When the surface opens, Then the sidebar opens and no window or tab does', async () => {
    const fx = fakeFirefox();
    await firefoxPorts(fx.api).surface.open(undefined);
    expect(fx.sidebar).toEqual(['open']);
    expect(fx.opened).toEqual([]);
  });

  it('Given no question, When the surface is asked to open, Then the sidebar is asked before anything is awaited (Firefox requires the user action)', () => {
    const fx = fakeFirefox();
    void firefoxPorts(fx.api).surface.open(undefined);
    expect(fx.sidebar).toEqual(['open']);
  });

  it('Given Firefox refuses the sidebar, When the surface opens, Then chat.html opens in a focused popup window instead', async () => {
    const fx = fakeFirefox({ sidebarRefuses: true });
    await firefoxPorts(fx.api).surface.open(undefined);
    expect(fx.opened).toEqual(['popup moz-extension://self/chat.html focused=true']);
  });

  it('Given a question, When the surface opens, Then chat.html opens carrying it and the sidebar is left alone', async () => {
    const fx = fakeFirefox();
    await firefoxPorts(fx.api).surface.open('why rust');
    expect(fx.opened).toEqual(['popup moz-extension://self/chat.html?q=why%20rust focused=true']);
    expect(fx.sidebar).toEqual([]);
  });
});
