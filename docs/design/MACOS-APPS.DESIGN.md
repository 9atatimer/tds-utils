# macOS App Launchers

> **Status:** DRAFT
> **Date:** 2026-08-08
> **Authors:** Todd Stumpf, Claude Opus 5
> **Depends on:** none

---

## Overview

Some `bin/` tools are worth reaching for without a terminal open. `monctl
flip` is the motivating case: it moves the Dell U2725QE between the home
Mac and the work Mac, and the moment you want it is the moment you are
not looking at a shell.

This tree turns any repo command into a clickable macOS `.app` -- Desktop,
Dock, Spotlight, or Raycast -- with a real icon and a notification for
the result. `macos/apps/mkmacapp` is the builder; each app under
`macos/apps/<name>/` supplies only its parameters and its icon.

---

## Goals

1. **A repo command becomes a double-clickable app** -- `mkmacapp
   --name "Flip Monitor" --command 'monctl flip'` produces a working
   bundle, no Xcode and no manual Finder steps.
2. **The custom icon actually wins** -- the built bundle shows the
   supplied `.icns` in Finder and the Dock, not the stock AppleScript
   applet scroll.
3. **Portable across machines** -- nothing under version control names
   `/Users/stumpf`; a fresh clone on another Mac builds a working bundle.
4. **Installing needs no Python** -- `.icns` artifacts are committed
   next to their generators, so `mkmacapp` depends only on the macOS
   base system.
5. **Verifiable without clicking** -- a smoketest builds into a tmpdir
   and asserts bundle structure, icon precedence, and signature.

---

## Non-Goals

- **Menu bar / status item apps** -- an `NSStatusItem` agent is a
  different animal (`LSUIElement`, a persistent process, a Swift build).
  Out of scope here; see Future Considerations.
- **GUI for arbitrary interaction** -- these are fire-and-forget command
  launchers. Anything needing input, output streaming, or a window
  should be a terminal program.
- **Code signing with a real identity** -- ad-hoc signing only. These
  bundles are built locally from a local checkout and never distributed,
  so notarization buys nothing.
- **Linux desktop entries** -- `.desktop` files are a genuinely different
  format. If LMDE wants launchers, that is its own tree.

---

## Architecture Overview

```
macos/apps/<name>/build          osacompile
   |  parameters                    ^
   v                                |
macos/apps/mkmacapp  ------> generated AppleScript wrapper
   |                                |
   |  icon.icns                     v
   +----------------------->  <name>.app bundle
                                    |
                             --dest / --dock
                                    v
                        Desktop, /Applications, Dock
```

At runtime the bundle is self-contained and calls back into the checkout:

```
click -> applet -> do shell script -> PATH=<repo>/bin:... -> monctl flip
                                          |
                                          v
                                  display notification
```

---

## Design

### `mkmacapp` -- the builder

The volatile edge. Everything that knows about Apple bundle mechanics
lives here and nowhere else.

#### Responsibilities

| Responsibility | Details |
|----------------|---------|
| Generate the wrapper | Emits AppleScript that runs the command and reports via `display notification`, success and failure alike |
| Resolve the repo root | Derives it from `mkmacapp`'s own location, so the committed source stays path-free |
| Compile | `osacompile -o <dest>/<name>.app` |
| Install the icon | Copies the `.icns` over `Contents/Resources/applet.icns` |
| Win the icon fight | Deletes the stock `Assets.car` and the `CFBundleIconName` key, both of which outrank `applet.icns` on modern macOS |
| Identify the bundle | Sets `CFBundleIdentifier` and `CFBundleName` |
| Sign | `xattr -cr` then ad-hoc `codesign -f -s -`; signing fails outright if extended attributes are left behind |
| Pin | `--dock` appends a `persistent-apps` tile and restarts the Dock |

#### Interface

```
mkmacapp --name NAME --command CMD [options]

  --name NAME        bundle and display name, e.g. "Flip Monitor"
  --command CMD      shell command, run with the repo's bin/ on PATH
  --icon PATH        .icns file; omitted means the stock applet icon
  --identifier ID    CFBundleIdentifier (default derived from --name)
  --dest DIR         where to write the bundle (default ~/Applications)
  --dock             also pin the built bundle to the Dock
  --force            replace an existing bundle at that path

Exit:
  0   bundle built
  64  usage error
  1   build failed (osacompile, codesign, missing icon)
```

### `macos/apps/<name>/` -- one directory per app

The stable core: parameters and artwork, no bundle mechanics.

| File | Role |
|------|------|
| `build` | Calls `mkmacapp` with this app's flags; passes extra args through, so `./build --dock` works |
| `icon.py` | Draws the icon set and compiles `icon.icns` via `iconutil` |
| `icon.icns` | The committed result, so installing needs no Pillow |

### `flip-monitor` -- the first app

Runs `monctl flip`. Icon is a white monitor with a two-way arrow on a
blue-indigo squircle -- legible at 16px, which rules out anything with
fine detail.

`monctl` is invoked by name, not as `mc`: `mc` is an interactive-shell
alias from `macos/dot.alias` and does not exist to Launch Services.

---

## Security Considerations

- **Arbitrary command execution by double-click** -- inherent to the
  format. The mitigation is that bundles are built locally from a
  reviewed checkout, never downloaded; `--dest` defaults inside `$HOME`.
- **Ad-hoc signature only** -- the bundle carries no notarization, so
  Gatekeeper would block it if it ever arrived with a quarantine
  attribute. That is the correct behavior; these are local artifacts.
- **`do shell script` and injection** -- the command is baked in at build
  time from a reviewed `build` script, not assembled from runtime input.
  `mkmacapp` still quotes it into the generated source rather than
  interpolating raw.

---

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where the tree lives | `macos/apps/`, sibling to `macos/launchd/` | Precedent already set for macOS subsystem subdirs; these bundles are macOS-only by construction |
| Builder vs. per-app scripts | One generic `mkmacapp` | The applet quirks (Assets.car, xattr-before-codesign) are knowledge that should be written down once, not re-derived per app |
| Icon artifact | Commit `icon.icns` alongside `icon.py` | Otherwise every install needs Pillow, a heavy dependency for an install-time step |
| Path handling | Derive repo root from `mkmacapp`'s location | Keeps `/Users/stumpf` out of version control; a clone on any Mac builds a working bundle |
| Result reporting | `display notification` | A `.command` file or Terminal launch would open a window for a one-line result |
| Default `--dest` | `~/Applications` | Reachable by Spotlight and Dock without `sudo`; Desktop and `/Applications` remain explicit choices |

---

## Open Questions

1. **Does the notification survive an unsigned-identity applet on this
   macOS version?** -- verified working on the hand-built prototype
   (2026-08-08, Darwin 25.5). If a future macOS tightens this, the
   fallback is `osascript -e 'display dialog'`, which is modal and worse.

---

## Rejections

- **`.command` shell script on the Desktop** -- opens a Terminal window
  for a one-line result, and cannot carry a custom icon without the same
  bundle surgery anyway.
- **Automator Quick Action** -- not version-controllable as source; the
  workflow is an opaque plist tree.
- **Templating the AppleScript from a `.in` file with placeholder
  substitution** -- generating the source directly in `mkmacapp` is
  fewer moving parts, and the wrapper is short enough to read inline.
- **A menu bar item for the first cut** -- needs a compiled `LSUIElement`
  Swift agent and a login item; strictly more machinery than a Dock tile
  for the same click.
- **Committing the built `.app`** -- a binary tree in git that must be
  re-signed per machine anyway.

---

## Future Considerations

- **Menu bar agent** -- a small `LSUIElement` status-item app showing
  current input and flipping on click. Relevant if the Dock round-trip
  starts to feel slow, or if live status display becomes wanted.
- **More apps in the tree** -- the shape is speculative generality at
  N=1 and pays off at N=2. Candidates are any `bin/` tool wanted
  without a shell.
- **Raycast / Spotlight ergonomics** -- `--dest ~/Applications` already
  makes bundles Spotlight-visible; a Raycast script command may be the
  better surface for keyboard-driven use.

---

## Related Documents

- `bin/monctl` -- the command the first app wraps; its header records
  the DDC/CI constraints (direct cable, Auto Select off).
