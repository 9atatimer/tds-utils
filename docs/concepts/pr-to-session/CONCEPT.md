# PR to Session

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-09-25  **Author:** Todd Stumpf (captured with AI assistance)

## The idea

QoL: when I am on GitHub looking at a PR, I want to be able to go back to
the Terminal/tmux session(s) responsible for that PR. A browser extension,
working with a mac dashboard app. This may mean tmux-herd needs some sort
of daemon with tracking state, so the reverse map (PR -> session) is
always available to the extension.

Working label `pr-to-session`; the name is open.

## Story sets

| File | Theme |
|---|---|
| STORIES.jumping.md | from a PR page back to the session that made it |
| STORIES.dashboard.md | the Mac-side view of what maps to what |

## Notes

**Settled in session (Todd's words):**

- The surface on the GitHub side is a browser extension.
- A Mac dashboard app is part of the idea.
- A daemon with tracking state in tmux-herd is a possibility Todd raised,
  not a decision.

**Still open (nobody's yet):**

- Daemon holding state, or a service answering over live tmux each time.
  Spike A (below) bears on this; it does not settle it.
- Extension to app channel: native messaging, loopback HTTP, or a URL
  scheme.
- Dashboard: a new menu-bar app, or a view inside the chores dashboard.
- Which browser(s). Chrome assumed.
- The name.
- Placement: verdict on the issue is a separate tree in tds-utils, not
  lmde, not a separate repo yet
  (https://github.com/9atatimer/tds-utils/issues/323#issuecomment-5824941156).

**Aspirational, may not be buildable as stated:**

- A PR from a claude.ai/code session (branch `claude/...`) has no tmux
  session at all. Whether the extension should say something useful there
  is a want, not a feature.

**What the idea leans on that exists (placement only, nothing chosen):**

- tmux-herd's discovery adapter (`docs/design/TMUX-HERD.DESIGN.md`, DRAFT,
  no code): session to agent cwd to git-common-dir to origin owner/repo +
  branch, baked into the session name. Its data model says "Nothing
  persisted" and it rejects a persistent state file -- in tension with a
  daemon; resolve in phase 2.
- The PR page carries head repo and head branch, so the lookup key is
  (owner/repo, branch).
- `bin/branch-merged-check` `query_gh()`: branch to PR, once.
- Mac surfaces: rumps menu-bar apps, launchd plists, `macos/apps/mkmacapp`.
  Chores is the dashboard mould (one `status()` query, several surfaces).
- log-hoarder's localhost HTTP+JSON daemon is the transport precedent;
  NATS KV `agent.<agent>.<session>.state` is the other.

**What the idea leans on that does not exist yet:**

- Stable session identity (`#{session_id}`, tmux-herd task-021 / issue #307).
- Any browser extension or userscript anywhere in tds-utils or
  template-tools. `lmde/TECH_RADAR.md` has no row for MV3 extensions,
  Swift, Electron, Tauri, Rust, or plain sqlite; rumps is un-radared
  (issue #288). Any of those is a proposal, never a silent add.
- A URL-scheme handler (`CFBundleURLTypes`) on the Mac.

**Spike findings (2026-09-25, mbp, throwaway code deleted):**

- **A -- (owner/repo, branch) to tmux session from live state: yes.**
  ~15 lines of zsh over `tmux list-panes -a` plus `git rev-parse
  --git-common-dir`, `--abbrev-ref HEAD` and `remote get-url origin`
  returned 13 unique (session, repo, branch) rows from 25 panes in 0.35s
  wall, no daemon, no stored state. So a daemon is not needed for the
  lookup to be fast enough; whether one is wanted for other reasons stays
  open. Caveats: used `pane_current_path` (the pane's foreground
  process cwd), not the agent process cwd, so a pane whose agent has
  `cd`-ed elsewhere resolves to the wrong repo; one session can span
  several repos (session 61 showed cgb and iommaps), so the answer is a
  set of sessions per key and a set of keys per session; a pane outside
  any git repo yields nothing; one repo had no `origin`. zsh gotcha for
  whoever writes the real one: `path` is tied to `$PATH`, so `read ...
  path` silently breaks every later command.
- **B -- bring Terminal.app forward on a session: partly.** Read-only
  half checked: Terminal.app exposes `tty of tab` via AppleScript, and
  `tmux list-clients -F '#{client_tty}'` matches it, so a session's
  attached client maps to a Terminal window/tab. Of 3 tmux clients, 2
  matched a Terminal tab; the third is on a tty Terminal does not own (a
  different terminal), so "raise the window" cannot cover every client.
  NOT exercised: `activate`, `tmux switch-client`, and the no-client and
  two-client cases, because they move the live windows; still to try.
- **C -- MV3 extension on `github.com/*/pull/*` reaching loopback: not
  tried.** Needs a Chromium with Load-unpacked; also see the radar note
  that Chrome 142+ ignores `--load-extension` under automation.
  Alternatives Todd has not ruled in or out: a userscript (Tampermonkey
  `GM_xmlhttpRequest`); native messaging instead of a port; a
  `tmuxherd://` URL scheme for the jump alone (lookup still needs a
  channel); a view in the chores dashboard instead of a new app.
