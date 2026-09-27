---
id: task-026
kind: task
title: "dynomark phase 3b: extension adapters -- Chrome tree/history/tabs, native-messaging shim and client, omnibox surface"
created: 2026-09-27
blocked_by: [task-024]
implements: docs/design/DYNOMARK.DESIGN.md
---

The extension's edges and the MV3 shell. Driven end-to-end with
Chrome-for-Testing through the chrome-mcp skill (never the user's real
profile); unit tests stay on the fakes.

1. `BookmarkTreePort` on `chrome.bookmarks`: create-if-absent at path,
   move-if-not-there, remove-to-graveyard, full-tree snapshot; `Follow Up`
   resolution (zero -> create under the bookmarks bar; two -> use the bar's
   and report).
2. `HistoryPort` on `chrome.history` producing `Frecency`.
3. `ContentSourcePort` tab adapter on `chrome.scripting` with the all-sites
   host permission; readable-text extraction inside the adapter.
4. `TransportPort` client over `chrome.runtime.connectNative`, plus the
   native-messaging host: a shim that forwards one browser connection to
   the daemon's unix socket. Host manifest template with the extension id
   placeholder; an install script that writes it to the per-user
   NativeMessagingHosts directory (zsh on macOS, bash on Linux, per
   AGENT.md).
5. Composition root: the background entry point wires the adapters, the
   `Follow Up` watcher, batch offers -> `apply_batch` -> `ack_batch`, index
   sync on change, and the batch cursor in extension storage.
6. Omnibox keyword `bm`: tier-1 suggestions per keystroke, tier-2 appended
   after the debounce, Enter navigates. No `Ask` row in PoC (chat is MVP).
7. Settings page: transport selection, `Follow Up` behaviour; nothing
   secret.
8. e2e in Chrome-for-Testing: load unpacked, create a bookmark in
   `Follow Up`, assert the daemon fake (task-022 transport fake behind a
   test shim) received one ingest; apply a scripted batch and assert the
   tree; kill the service worker mid-batch and assert resume from cursor.
9. Learning checkpoint.

Acceptance: manifest declares only the permissions the design names
(bookmarks, history, scripting, nativeMessaging, storage, omnibox, all
sites); the e2e suite runs in the cloud sandbox with the pre-installed
Chromium.
