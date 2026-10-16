/// <reference types="node" />
// firefoxBuild.test.ts -- the build's Firefox output (task-032): beside the
// Chrome extension in dist/, `npm run build` writes dist-firefox/, a Firefox
// MV3 extension loadable as a temporary add-on (about:debugging). Firefox
// needs what Chrome does not take: background scripts (an event page, no
// service worker), a fixed gecko id (the daemon's host manifest names it in
// allowed_extensions), options_ui, and the sidebar as the chat surface with
// the chat shortcut opening it. Everything else is the Chrome manifest's.
// Every file the manifest and its pages load must be in dist-firefox/, and
// every module the background script imports must resolve there.
//
// Integration: reads the built output; needs `npm run build` first.

import { existsSync, readFileSync } from 'node:fs';
import { dirname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

// --- Constants ---

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const DIST = join(ROOT, 'dist');
const FIREFOX = join(ROOT, 'dist-firefox');
/** The gecko id the Firefox build pins; `install-host-manifest --browser firefox` takes it. */
const GECKO_ID = 'dynomark@tds.dynomark';
const SPECIFIER = /(?:\bfrom\s*|\bimport\s*\(?\s*)(['"])([^'"]+)\1/g;
const PAGE_SCRIPT = /<script[^>]*\bsrc="([^"]+)"/g;

// --- Helpers ---

type Manifest = Record<string, unknown> & {
  readonly background?: Record<string, unknown>;
  readonly commands?: Record<string, { readonly suggested_key?: unknown; readonly description?: string }>;
};

function readManifest(dir: string): Manifest {
  return JSON.parse(readFileSync(join(dir, 'manifest.json'), 'utf8')) as Manifest;
}

/** Every module reachable from `entry` by relative import, as paths under `dir`. */
function moduleGraph(dir: string, entry: string): string[] {
  const seen = new Set<string>();
  const queue = [normalize(entry)];
  for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
    if (seen.has(next)) continue;
    seen.add(next);
    if (!existsSync(join(dir, next))) continue;
    for (const [, , spec] of readFileSync(join(dir, next), 'utf8').matchAll(SPECIFIER)) {
      if (spec?.startsWith('.') === true) queue.push(normalize(join(dirname(next), spec)));
    }
  }
  return [...seen];
}

// --- Tests ---

describe('the Firefox build (dist-firefox/)', () => {
  it('Given a build, When the Firefox manifest is read, Then it pins the gecko id and runs background scripts as a module, with no service worker or Chrome key', () => {
    const manifest = readManifest(FIREFOX);
    expect(manifest['manifest_version']).toBe(3);
    expect(manifest['browser_specific_settings']).toMatchObject({ gecko: { id: GECKO_ID, strict_min_version: expect.any(String) } });
    expect(manifest.background).toEqual({ scripts: ['firefoxBackground.js'], type: 'module' });
    expect(manifest).not.toHaveProperty('key');
    expect(manifest).not.toHaveProperty('options_page');
  });

  it('Given a build, When the Firefox manifest is read, Then the sidebar shows the chat, the chat shortcut opens it, and options open in a tab', () => {
    const manifest = readManifest(FIREFOX);
    const chrome = readManifest(DIST);
    expect(manifest['sidebar_action']).toMatchObject({ default_panel: 'chat.html', default_title: 'Dynomark' });
    expect(manifest.commands).toEqual({
      _execute_sidebar_action: {
        suggested_key: chrome.commands?.['open-chat']?.suggested_key,
        description: chrome.commands?.['open-chat']?.description,
      },
    });
    expect(manifest['options_ui']).toEqual({ page: 'options.html', open_in_tab: true });
  });

  it('Given a build, When both manifests are read, Then Firefox asks for exactly what Chrome asks for and serves the same keyword and popup', () => {
    const manifest = readManifest(FIREFOX);
    const chrome = readManifest(DIST);
    for (const key of ['name', 'version', 'description', 'permissions', 'host_permissions', 'omnibox', 'action']) {
      expect(manifest[key], key).toEqual(chrome[key]);
    }
  });

  it('Given a build, When every file the Firefox manifest and its pages load is looked for, Then each is in dist-firefox/', () => {
    const manifest = readManifest(FIREFOX);
    const pages = ['chat.html', 'options.html', 'history.html', 'diff.html'];
    const scripts = pages.flatMap((page) => [...readFileSync(join(FIREFOX, page), 'utf8').matchAll(PAGE_SCRIPT)].map((m) => m[1] ?? ''));
    const loaded = [...((manifest.background?.['scripts'] as string[] | undefined) ?? []), ...pages, ...scripts];
    expect(loaded.filter((file) => !existsSync(join(FIREFOX, file)))).toEqual([]);
  });

  it('Given a build, When the Firefox background module graph is walked, Then every import resolves inside dist-firefox/', () => {
    const graph = moduleGraph(FIREFOX, 'firefoxBackground.js');
    expect(graph.length).toBeGreaterThan(10);
    expect(graph.filter((file) => !existsSync(join(FIREFOX, file)))).toEqual([]);
  });

  it('Given a build, When the Chrome manifest is read, Then it is still the service-worker extension with no Firefox settings', () => {
    const chrome = readManifest(DIST);
    expect(chrome.background).toEqual({ service_worker: 'background.js', type: 'module' });
    expect(chrome).not.toHaveProperty('browser_specific_settings');
    expect(chrome).not.toHaveProperty('sidebar_action');
  });
});
