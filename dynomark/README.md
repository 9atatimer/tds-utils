# Dynomark

Dynomark files the pages you save into the browser's own bookmark tree.
You save a page into `Follow Up` with the normal bookmark dialog (Ctrl+D).
A local daemon captures the page, summarizes and embeds it, and picks a
folder. A thin MV3 extension then files the bookmark under `Dynomark`,
serves the `bm` address-bar keyword (fuzzy title search, then full-text
and semantic search), and offers a chat grounded in what you saved. The
filed tree is ordinary synced bookmarks, so a phone can save into it and
browse it with nothing installed. Every change can be undone, and nothing
is ever hard-deleted: removals go to `Graveyard`. The design is
[docs/design/DYNOMARK.DESIGN.md](../docs/design/DYNOMARK.DESIGN.md)
(APPROVED).

## Layout

```
dynomark/
+-- contract/   the transport contract: v1/ schema, examples, README;
|               check.py self-check (stdlib only). Both runtimes build
|               against it; nothing else is shared between them.
+-- daemon/     the Python daemon: store, models, capture, placement,
|               socket server, native-messaging host (dynomark-host).
|               README: config, files, commands, adapter notes.
+-- extension/  the TypeScript MV3 extension: Follow Up watch, batch
|               apply, omnibox, chat, diff and history pages.
|               README: pinned id, build, test tiers.
+-- e2e/        the integration e2e: the built extension in Chromium, the
                real dynomark-host and the real daemon (fake models only),
                driven together with Playwright.
```

```
Chrome + extension --native messaging--> dynomark-host --unix socket--> dynomark-daemon
     (dist/)          (stdio frames)      (byte pipe)     (owner-only)    (launchd, Ollama)
```

## Gates

Every gate also runs in CI (`.github/workflows/dist-ci.yml`, all four jobs
are in `gate`).

| Package | Command, from the repo root |
|---|---|
| contract | `python3 dynomark/contract/check.py` |
| daemon | `cd dynomark/daemon && uv sync && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest` |
| extension | `cd dynomark/extension && npm ci && npm run typecheck && npm run format:check && npm test && npm run build && npm run e2e` |
| integration e2e | `cd dynomark/extension && npm ci && cd ../e2e && npm ci && npm run typecheck && npm run format:check && npm run e2e` |

The daemon runs its tests on both Linux and macOS. The extension's browser
tiers and the integration e2e need a Chromium that honours
`--load-extension`, never branded Chrome. They use `$DYNOMARK_CHROMIUM`
when it is set, else the build `@playwright/test` expects
(`npx playwright install chromium`), else the newest `chromium-*` build
under `$PLAYWRIGHT_BROWSERS_PATH`. On a Mac, Chrome for Testing works; the
extension README shows how to point `DYNOMARK_CHROMIUM` at it.

What the integration e2e does:

- Its global setup builds the extension and runs `uv sync --frozen` in the
  daemon.
- Each scenario gets a throw-away `HOME`. The daemon's config, store, log
  and socket live under it, and so does the Chromium profile.
- The host manifest is written by the daemon's own
  `install-host-manifest`, into the directory Chromium reads.
- The daemon starts with `uv run` through its test-support entry point,
  `python -m dynomark_daemon.testing.e2e --script S`. That entry point is
  the production composition with only the models replaced by the scripted
  fakes; no config key can select a fake.
- The browser has no network access. Pages come from a 127.0.0.1 server.
- The scenarios are named after the design's Goals and Behaviors rows.
- The filing scenario prints the measured ingest-received -> `APPLIED`
  interval from the daemon log (Goal 2), as the line
  `Goal 2: ingest received -> APPLIED in N ms`.

## Install on the mbp

Run these in order. Steps marked **[HUMAN]** cannot be scripted: they
happen in a GUI, download large files, or decide which host is the writer.
Run the commands from the release worktree (`~/.tds/release`), so that
switching branches in a checkout never changes what Chrome loads.

1. **[HUMAN] Ollama and the local models.** The pulls download several GB.

   ```zsh
   brew install ollama
   brew services start ollama
   ollama pull nomic-embed-text
   ollama pull llama3.1:8b
   ```

2. **Daemon** (puts `dynomark-daemon` and `dynomark-host` in
   `~/.local/bin`).

   ```zsh
   uv tool install ~/.tds/release/dynomark/daemon
   ```

3. **[HUMAN] Config: pick the writer.** Exactly one host is `writer`; every
   other host stays `reader` (the default when there is no file). See the
   daemon README, "Changing writers", before you ever move the role.

   ```zsh
   mkdir -p ~/.config/dynomark
   printf 'role = "writer"\nhost_id = "mbp"\n' > ~/.config/dynomark/config.toml
   mkdir -p -m 700 ~/.local/state/dynomark
   ```

4. **launchd** (a user LaunchAgent that runs `serve`, started now and at
   every login).

   ```zsh
   dynomark-daemon launchd-plist > ~/Library/LaunchAgents/tds.dynomark.daemon.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/tds.dynomark.daemon.plist
   ```

5. **Host manifest**, bound to the extension's pinned id.

   ```zsh
   dynomark-daemon install-host-manifest --extension-id iiflkiojolkdbmlgfbdfeobinoinnfjp --browser chrome
   ```

6. **Build the extension.**

   ```zsh
   cd ~/.tds/release/dynomark/extension && npm ci && npm run build
   ```

7. **[HUMAN] Load unpacked.** In `chrome://extensions`, turn on Developer
   mode, choose Load unpacked, and pick
   `~/.tds/release/dynomark/extension/dist`. Check that the id shown is
   `iiflkiojolkdbmlgfbdfeobinoinnfjp`. If it differs, the host manifest
   will refuse the extension.

8. **First check.**

   ```zsh
   dynomark-daemon check        # every line ok (socket: listening)
   ```

   **[HUMAN]** Open the extension's options page (right-click the toolbar
   icon, then Options). It should show the link `connected`, role
   `writer`, host `mbp`, both models `(local)`, and no writer-conflict
   banner. Then save one open page into `Follow Up` with Ctrl+D. It should
   move to `Dynomark/<folder>` within a minute. Read the interval with:

   ```zsh
   jq -r 'select(.event == "job.applied") | .interval_ms' ~/.local/state/dynomark/daemon.log
   ```

To stop the daemon, run
`launchctl bootout gui/$(id -u)/tds.dynomark.daemon`. After a release,
update it with `uv tool install --reinstall ~/.tds/release/dynomark/daemon`
followed by `launchctl kickstart -k gui/$(id -u)/tds.dynomark.daemon`.
Rebuild the extension, then press reload on its card in
`chrome://extensions`.
