# Dynomark extension

The MV3 browser extension of Dynomark (`docs/design/DYNOMARK.DESIGN.md`):
watches `Follow Up`, captures a saved page from its open tab (and, on the
writer, from a background tab when no tab shows it), applies the daemon's
write batches to the native bookmark tree, and serves the `bm` omnibox
keyword. MVP pages: the chat surface, the diff view, and the writer-marker
status and backfill on the settings page. It talks to the daemon only
through native messaging (host `tds.dynomark`, contract `../contract/v1/`).

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
   hello outcome, daemon role, host id, models, queue depth; the writer
   marker (a red banner while another host's marker is in `Dynomark`: no
   batch is applied until it is cleared); the two capture settings (open
   tab; background tab on the writer, default on); Backfill existing
   bookmarks (ten ingests a second, resumes after a worker restart). The
   toolbar popup is the history page: Undo per APPLIED batch, Retry per
   FAILED job.
5. Save a page into `Follow Up` with Ctrl+D (created under the bookmarks bar
   on first start). Search with `bm <words>` in the address bar; the last row
   is always `Ask: <words>`, and Enter with no hit asks too.
6. Chat: the Ask row, or Alt+Shift+K (chrome://extensions/shortcuts to
   change), opens `chat.html` in a popup window. A citation opens in one
   click; "why here" shows the placement reason; an external URL can be
   filed into `Follow Up`. Batches that ended PARTIAL or REJECTED and FAILED
   jobs are listed on top, each job with Retry.
7. Diffs: `diff.html` (linked from the settings page). Propose an audit or
   a rebuild, open it, accept one item at a time; each accepted item is a
   batch whose state shows on its row. Pin or lock owned folders there.

## Durable state

Everything the service worker keeps across a restart goes through the
`StoragePort` (`src/ports/storage.ts`), on `chrome.storage.local`, except
`capture_window`, which the background-tab adapter keeps there itself. The
rest is in memory and is rebuilt, or re-sent, after the next full hello.

| Key              | What                                                                                                                                              | Bound                                                                   |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `settings`       | profile id, transport, the two capture settings                                                                                                   | one record                                                              |
| `local_index`    | the rebuildable LocalIndex the omnibox searches                                                                                                   | the daemon's index                                                      |
| `batch_cursor`   | the in-flight batch: how far it got, each op's outcome                                                                                            | one batch                                                               |
| `backfill`       | backfill candidates, how far it got (design, Open Question 3), and the one frame answered busy or internal, re-sent with its id                   | the tree when it started, plus one bookmark                             |
| `owed_captures`  | Follow Up saves owed a background capture: made while the role was unknown, or whose capture may open a background tab, until the daemon has them | Follow Up's children, at most 1000                                      |
| `pending_saves`  | ingest frames sent and not yet answered (id, bookmark, capture), re-sent unchanged by the next worker                                             | 16 frames and 1,048,576 characters of capture text; the oldest go first |
| `pending_moves`  | move.observed frames sent and not yet answered (id, move), re-sent unchanged after a backoff or by the next full hello                            | 64 frames; the oldest go first                                          |
| `capture_window` | the minimized window a background capture has open (window and tab id); the next worker's start closes it if still that window                    | one window                                                              |

## Test

```zsh
npm run typecheck && npm run format:check && npm test && npm run build && npm run e2e
```

| Tier        | Where                                     | Runs                                                                                               |
| ----------- | ----------------------------------------- | -------------------------------------------------------------------------------------------------- |
| unit        | `test/unit`, `test/contract`, `test/arch` | `npm test` (first, shuffled): fakes and small chrome.* stubs, no I/O                               |
| perf        | `test/perf`                               | `npm test` (then, one file at a time): Goal 4's tier-1 bound                                       |
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
socket, and routed pages; no network: every web request not to 127.0.0.1 is
aborted unless a test routes it, and the background-tab test loads its page
from a throw-away HTTP server on 127.0.0.1. The omnibox cannot be typed into
headless, so e2e drives its handler through `globalThis.dynomark`, the
diagnostic handle the service worker exposes on its own global scope; the
keyboard command is covered by unit tests only.

## Layout

| Path                                                    | Layer                                                                                  |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| `src/domain/`                                           | rules and values; imports nothing else                                                 |
| `src/wire/`                                             | zod schemas of contract v1                                                             |
| `src/ports/`                                            | seams: tree, history, content, storage, transport, clock, ids, timer, navigator, pages |
| `src/app/`                                              | use cases and the background workflow (`runtime.ts`)                                   |
| `src/adapters/`                                         | chrome.* adapters (the only code that names a browser API)                             |
| `src/ui/`                                               | the options, history, chat and diff page views                                         |
| `src/background.ts`, `src/options.ts`, `src/history.ts` | entry points / composition roots (also `src/chat.ts`, `src/diff.ts`)                   |
