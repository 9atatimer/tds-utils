# Dynomark extension

The MV3 browser extension of Dynomark (`docs/design/DYNOMARK.DESIGN.md`):
watches `Follow Up`, captures a saved page from its open tab, applies the
daemon's write batches to the native bookmark tree, and serves the `bm`
omnibox keyword. It talks to the daemon only through native messaging
(host `tds.dynomark`, contract `../contract/v1/`).

## Extension id

The manifest's `key` is the public half of a keypair generated once; the
private half was discarded (an unpacked extension needs none). The id is
therefore fixed:

```
iiflkiojolkdbmlgfbdfeobinoinnfjp
```

The daemon's native-messaging host manifest must allow exactly
`chrome-extension://iiflkiojolkdbmlgfbdfeobinoinnfjp/`.

## Build

```zsh
npm ci
npm run build        # tsc -> dist/, then scripts/postbuild.mjs
```

`dist/` is the unpacked extension. No bundler: `postbuild.mjs` copies the
manifest and `static/` pages, vendors zod's ESM build into `dist/vendor/zod`,
rewrites the bare `zod` import (an MV3 service worker cannot resolve one),
and fails the build if any bare specifier is left.

## Run (macOS, Chrome)

1. `npm ci && npm run build`
2. `chrome://extensions` -> Developer mode -> Load unpacked -> `dynomark/extension/dist`.
   Check the id shown is the one above.
3. Install and start the daemon, whose installer writes the host manifest
   `tds.dynomark.json` to
   `~/Library/Application Support/Google/Chrome/NativeMessagingHosts/`.
4. Options page (right-click the toolbar icon -> Options): native link,
   hello outcome, daemon role, host id, models, queue depth; the capture
   setting. The toolbar popup is the history page: Undo per APPLIED batch,
   Retry per FAILED job.
5. Save a page into `Follow Up` with Ctrl+D (created under the bookmarks bar
   on first start). Search with `bm <words>` in the address bar.

## Test

```zsh
npm run typecheck && npm run format:check && npm test && npm run build && npm run e2e
```

| Tier        | Where                                     | Runs                                                                                               |
| ----------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| unit        | `test/unit`, `test/contract`, `test/arch` | `npm test`: fakes and small chrome.* stubs, no I/O                                                 |
| integration | `test/integration`                        | `npm run e2e` (first half): the port contract suites against the real chrome adapters in Chromium  |
| e2e         | `e2e/`                                    | `npm run e2e` (second half, Playwright): the built extension against a fake native host and daemon |

Both browser tiers need `dist/` built and a Chromium that honours
`--load-extension` (not branded Chrome). They use, in order:
`$DYNOMARK_CHROMIUM`; the build `@playwright/test` expects, if installed;
the newest `chromium-*` build under `$PLAYWRIGHT_BROWSERS_PATH`. On a Mac,
Chrome for Testing works (chrome-mcp skill):

```zsh
npx @puppeteer/browsers install chrome@stable --path ~/.cache/dynomark-cft
export DYNOMARK_CHROMIUM="$(ls -d ~/.cache/dynomark-cft/chrome/mac_arm-*/chrome-mac-arm64/'Google Chrome for Testing.app'/Contents/MacOS/'Google Chrome for Testing' | head -1)"
```

Hermetic: a temp profile whose `NativeMessagingHosts/` registers the host
(Chromium reads per-user host manifests from the user data dir), a temp unix
socket, and routed pages; no network. The omnibox cannot be typed into
headless, so e2e drives its handler through `globalThis.dynomark`, the
diagnostic handle the service worker exposes on its own global scope.

## Layout

| Path                                                    | Layer                                                                                  |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `src/domain/`                                           | rules and values; imports nothing else                                                 |
| `src/wire/`                                             | zod schemas of contract v1                                                             |
| `src/ports/`                                            | seams: tree, history, content, storage, transport, clock, ids, timer, navigator, pages |
| `src/app/`                                              | use cases and the background workflow (`runtime.ts`)                                   |
| `src/adapters/`                                         | chrome.* adapters (the only code that names a browser API)                             |
| `src/ui/`                                               | the options and history page views                                                     |
| `src/background.ts`, `src/options.ts`, `src/history.ts` | entry points / composition roots                                                       |
