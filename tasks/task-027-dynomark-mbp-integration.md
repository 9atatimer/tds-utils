---
id: task-027
kind: task
title: "dynomark phase 4: mbp integration -- real profile, host manifest, launchd daemon, live round trip, Goal 2 measured"
created: 2026-09-27
blocked_by: [task-025, task-026]
implements: docs/design/DYNOMARK.DESIGN.md
---

The one phase that needs the laptop. Nothing here is unit-tested; it is
the PoC acceptance run, recorded in the learning checkpoint with numbers.

1. Install the daemon under launchd for the user (owner-only socket, store
   under the state directory); `dynomark-daemon --check` green with Ollama
   reachable.
2. Load the unpacked extension into the real Chrome profile; register the
   native-messaging host manifest with the real extension id; hello/version
   exchange succeeds.
3. Backfill nothing (Open Question 3 in the design); start with an empty
   corpus.
4. Save ten pages into `Follow Up` with Ctrl+D, including two logged-in
   pages. Assert: each is filed under `Dynomark` within Goal 2's bound
   (measure ingest-received -> `APPLIED`), captured text is searchable via
   `bm`, logged-in pages captured from the tab.
5. Undo one batch; make an unrelated edit first and assert it survives.
6. Kill Chrome mid-batch (or reload the extension) and assert resume from
   the cursor with no duplicate folder.
7. Save one page from the phone; assert the writer files it (fetch
   capture; logged-in loss accepted per Key Decisions).
8. Run a week of daily use on the writer host; record every manual repair.

Acceptance: the eight steps above recorded with numbers in the checkpoint;
any design divergence cut as an issue per the retrospective skill, never
edited into the frozen design.

## Firefox acceptance (task-032)

The Firefox adapters are unit-tested over a stand-in `browser` namespace
only: the sandbox has no Firefox Playwright can drive. This run is their
real-browser acceptance, on the mbp, after the Chrome steps above pass. It
needs Firefox 128 or newer.

- Build: `cd ~/.tds/release/dynomark/extension && npm ci && npm run build`
  writes `dist-firefox/` beside `dist/`.
- Load: `about:debugging#/runtime/this-firefox` -> Load Temporary Add-on
  -> pick `~/.tds/release/dynomark/extension/dist-firefox/manifest.json`.
  Check the add-on id shown is `dynomark@tds.dynomark`. A temporary add-on
  is removed when Firefox quits; load it again after every restart.
- Permissions: `about:addons` -> Dynomark -> Permissions. Turn on "Access
  your data for all websites" if it is off; tab and background-tab capture
  need it.
- Host manifest: `dynomark-daemon install-host-manifest --extension-id
  dynomark@tds.dynomark --browser firefox` writes
  `~/Library/Application Support/Mozilla/NativeMessagingHosts/tds.dynomark.json`
  with `allowed_extensions` naming that id. The options page (Dynomark in
  `about:addons` -> Preferences) shows the native link connected and the
  hello outcome.
- One writer profile: Chrome and Firefox on one mbp share one daemon,
  which binds the first profile that says a full hello (design Key
  Decisions, Writer binding), so the second browser is served as a reader.
  Run this section with the binding on Firefox's profile: release it with
  `dynomark-daemon rebind` once that lands (issue #419), or use a daemon
  with a fresh store. Record which.
- Save, file: save three pages into `Follow Up` (Ctrl+D; the folder is
  created under the Bookmarks Toolbar on first start), one of them a
  logged-in page. Each is filed under `Dynomark` within Goal 2's bound; the
  logged-in one is captured from its tab.
- Separators: put a separator into the Bookmarks Toolbar and one inside
  `Dynomark`, then save another page. Filing succeeds and the separators
  stay where they were (the extension sends them as `separator` nodes, the
  shape of contract v1's `tree.snapshot--firefox-separator.json`).
- Search: `bm <words>` finds a saved page by title and by captured text;
  the rows are plain text (no `<match>` or `&amp;` shown); the last row is
  `Ask: <words>`.
- Chat: Alt+Shift+K, or View -> Sidebar -> Dynomark, opens the chat in the
  sidebar; the `Ask:` row opens it in a popup window with the question
  sent. A citation opens in one click.
- Undo: undo one batch from the toolbar popup after an unrelated edit;
  the edit survives.
- Background tab: with no tab showing a page saved on another device, the
  writer opens it in a minimized window, captures it and closes the
  window. Record whether Firefox kept the window unfocused.
- Resume: reload the add-on (about:debugging -> Reload) while a batch is
  applying; the batch resumes from the cursor with no duplicate folder.

Acceptance: each bullet recorded with its outcome in the checkpoint, any
Firefox-only divergence cut as an issue.
