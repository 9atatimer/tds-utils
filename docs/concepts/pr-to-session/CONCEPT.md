# PR to Session

> **Phase:** 1 -- CONCEPT. Unfunded, non-binding, not a design record.
> **Date:** 2026-09-27  **Author:** Todd Stumpf (captured with AI assistance)
> **Issue:** tds-utils issue#323 holds the ask and the handoff notes.

## The idea

I want a QoL browser extension that works with a mac dashboard app. When
I am on GitHub, and I am looking at a PR, I want to be able to go back to
the Terminal/tmux session(s) that are responsible for that PR.

I think this may suggest that we need the tmux-herd tool to have some
sort of daemon, with a tracking state, so that reverse mapping is always
available to the browser extension.

Take this at the concept/design phase, determine how it might work, and
then see if we can PoC or MVP it.

## Story sets

| File | Theme |
|---|---|
| STORIES.finding.md | standing on a PR page and learning which sessions made it |
| STORIES.jumping.md | the click that lands me in the terminal, on that session |
| STORIES.tracking.md | what keeps the reverse map true as sessions and branches move |
| STORIES.dashboard.md | the mac app on its own, without a PR page in front of me |

## Notes

**Settled in session (Todd's words):**

- The surface is a browser extension on the GitHub PR page, working with
  a mac dashboard app.
- The destination is the Terminal/tmux session(s) responsible for the PR.
  Plural: more than one session can be responsible.
- Concept and design first, then a PoC or MVP.
- A PoC was funded for a cloud session: the concept tree plus the spikes
  below. The MVP, the design record and the dashboard are not funded yet.

**Still open (nobody's yet):**

- Whether the map needs a daemon that holds tracking state, or can be
  answered from the live tmux server on every ask. Todd's hypothesis is
  the daemon; the tmux-herd design (DRAFT) rejects any persisted state on
  the grounds that state drifting from the tmux server is worse than no
  state. Both readings stay on the table; spike A is evidence, not a
  ruling.
- How the extension reaches the machine-side half: native messaging, a
  loopback HTTP service, or a URL scheme the mac app registers.
- Whether the dashboard is a new app or a view inside the chores
  dashboard.
- Which browser(s). Chrome is assumed for the spike only.
- The name. `pr-to-session` is a working label for this directory.

**Aspirational, may not be buildable as stated:**

- A PR produced by a cloud session (branches named `claude/...` from
  claude.ai/code) has no tmux session anywhere. The map has a hole there
  by construction; what the extension shows for it is a phase 2
  question.
- "Responsible for" may mean sessions that are gone. Whether a dead
  session is still worth showing, and what could be shown for it, is
  open.

**What the idea leans on that exists (placement only, nothing chosen):**

- `docs/design/TMUX-HERD.DESIGN.md` (DRAFT; task-020, blocked on
  task-021 / issue#307). Its discovery pass and git adapter already
  derive, per session, the pair this idea needs to look up: `owner/repo`
  from `origin` and the branch from `HEAD`, and bake them into the
  session name (`<agent>@<owner/repo>=<branch>+<slug>`). It persists
  nothing, on purpose.
- The PR page carries the other half of the key: head repo and head
  branch are in the page. A PR number to branch hop is also
  `gh pr view`.
- `bin/branch-merged-check` already asks GitHub the reverse question
  (branch to PR) with `gh pr list --head <branch>`, behind a fake seam.
- Mac surfaces: the rumps menu-bar apps (`bin/lmde-sync-monitor`,
  `bin/skills-drift-monitor`, `bin/chores-monitor`) with plists in
  `macos/launchd/`; Dock tiles via `macos/apps/mkmacapp`
  (`MACOS-APPS.DESIGN.md` defers menu-bar agents). Chores set the
  dashboard mould: one status query, four surfaces (CLI, TUI, menu bar,
  Dock), and rejected a Swift status-item app and any web dashboard.
- Terminal.app is the terminal (AppleScript branding in `TODO_PLAN.md`).
- Localhost transport precedents: `log-hoarderd` (loopback HTTP + JSON,
  bind address is the auth, UNIX sockets rejected) and NATS KV on
  127.0.0.1:4222 (`AGENT-NOTIFICATIONS.DESIGN.md`, Adopt on the radar).
- Browser precedent: orgmarks chose a CLI over an extension;
  `lmde/TECH_RADAR.md` records Chrome 142+ disabling `--load-extension`
  for branded Chrome under automation. No extension or userscript exists
  in either repo.
- Stable session identity, `#{session_id}`, is task-021's deliverable;
  a reverse map wants it more than the mutable name.

**What the idea leans on that does not exist yet:**

- `bin/tmux-herd` itself (design is DRAFT, no code).
- Any daemon, any extension, any URL-scheme handler
  (`CFBundleURLTypes`) in either repo.
- Tech-radar rows for whatever the extension and the dashboard are built
  with: MV3 extensions, rumps (issue#288), Swift, Electron, Tauri are all
  un-radared. Any of them is a proposal, never a silent add.

## Spike findings

Spikes live in `spikes/`, one question each, throwaway. They are evidence
that something is possible, never the design. Findings as of 2026-09-27,
from a Linux cloud container (tmux 3.4, git, zsh 5.9, Playwright
Chromium); nothing below was run on a Mac.

**A -- the map, no daemon, no state (`spikes/A-map.zsh`, `A-verify.zsh`):**

- Answered. A throwaway tmux server with two clones, one worktree, a
  two-pane session and a session with no git: the filter for
  `9atatimer/tds-utils` + `claude/foo` returns exactly the worktree's
  session id. Panes in the same session collapse to one row; a pane with
  no git drops out; `owner/repo` comes from `origin` (ssh and https forms
  both parsed).
- Cost is linear in panes, about 30 ms per pane (three `git` calls each):

  | sessions | filtered lookup |
  |---|---|
  | 4 | 95 ms |
  | 30 | 1085 ms |

  Under a second up to roughly 25 sessions with nothing cached. Whether
  that is "always available" enough is the phase 2 question Todd's daemon
  hypothesis is about; the evidence says the stateless answer is at the
  edge, not past it, and one `git` call per distinct cwd instead of three
  per pane would move it well inside.
- The TMUX-HERD design's discovery command as written
  (`-F '...\t...'`) does not work on tmux 3.4: a `\t` escape is emitted
  as the two characters, and a literal tab is rewritten to `_`. The spike
  uses `|` with the path last. Worth a line on the design before task-020.

**Loopback stand-in (`spikes/serve.py`):**

- Answered. A `http.server` on 127.0.0.1 running A per request, no state,
  returns JSON in the time A takes plus nothing measurable. Bind address
  as the only auth, the `log-hoarderd` pattern, was enough for the spike.

**B -- the jump (`spikes/B-jump.zsh`):**

- NOT RUN. Authored for the Mac: switch an attached client if there is
  one, else open a Terminal window attached to the session, then activate
  Terminal. Expected output is in the file header.

**C -- the extension (`spikes/C-extension/`, Chromium 141, Playwright):**

- Answered. An unpacked MV3 extension with a content script on
  `https://github.com/*/pull/*` read `owner/repo:branch` from the classic
  `.head-ref` span's title, injected a button beside it, and on click got
  the session list back from the loopback service.
- The fetch does NOT have to live in the service worker. From the
  service worker (`host_permissions` for `http://127.0.0.1/*`) it works
  with or without CORS headers. From the content script, in the page's
  `https://github.com` origin, it works when the service sends
  `Access-Control-Allow-Origin` and is blocked without it. No mixed
  content block (loopback counts as trustworthy) and no Private Network
  Access preflight was observed in this Chromium; a newer Chrome may add
  the preflight, and the service already answers `OPTIONS` with
  `Access-Control-Allow-Private-Network: true` for that day.
- Service down: both paths fail in milliseconds with
  `ERR_CONNECTION_REFUSED`, so "cannot ask right now" is distinguishable
  from "no session" (the finding story asks for that).
- Unverified: the fixture page is the classic github.com PR header,
  hand-written because github.com HTML is 403 from this container. The
  `.head-ref` selector and the "Load unpacked" step on real Chrome are
  Todd's to confirm on the Mac.
- Harness note only: Playwright request interception (`context.route`)
  pauses the extension service worker's requests too and never releases
  them, so the harness serves the fixture from a local TLS server mapped
  to github.com instead.
