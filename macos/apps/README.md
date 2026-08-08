# macos/apps -- clickable launchers for repo commands

Some `bin/` tools are worth reaching for without a terminal open. This tree
turns any repo command into a real macOS `.app` -- Desktop, Dock, Spotlight
-- with a custom icon and a notification for the result.

Design: `docs/design/MACOS-APPS.DESIGN.md`.

## Layout

```
mkmacapp            the builder: command + icon -> .app bundle
<app-name>/
  build             calls mkmacapp with this app's parameters
  icon.py           draws the artwork, writes icon.icns
  icon.icns         committed, so installing needs no Python
```

## Installing an app

```zsh
macos/apps/flip-monitor/build            # into ~/Applications
macos/apps/flip-monitor/build --dock     # ... and pin it to the Dock
```

Extra arguments pass straight through to `mkmacapp`, so `--dest`, `--force`,
and `--dock` all work from any app's `build`.

Bundles are built, not committed: they are ad-hoc signed per machine and
reference this checkout's absolute path. Re-run `build` after moving the
checkout.

## Adding an app

1. `mkdir macos/apps/<name>`
2. Write `build` -- one `mkmacapp` call with `--name`, `--command`, and
   `--icon`, forwarding `"$@"`. Copy `flip-monitor/build`.
3. Draw `icon.py`, run it to produce `icon.icns`, and commit both. Keep the
   artwork blunt; it has to survive being 16px in a Finder list.
4. Add a case to `test/smoketest_macos_apps.sh`.

Name the command by its real executable. Aliases from `macos/dot.alias` --
`mc`, for instance -- exist only in interactive zsh and are invisible to
Launch Services, so `build` scripts say `monctl flip`.

## Current apps

| App | Command | What it does |
|-----|---------|--------------|
| `flip-monitor` | `monctl flip` | Moves the Dell U2725QE between the home Mac (Thunderbolt) and the work Mac (DisplayPort) |

## Notes

- **First launch prompts for notification permission.** Allow it, or the
  result is silent and the launcher looks broken.
- **Gatekeeper.** Bundles are ad-hoc signed. That is fine for something
  built locally; it would be blocked if it ever arrived with a quarantine
  attribute, which is the correct outcome.
- **Prefer `~/Applications` over the Desktop.** With Desktop Stacks on
  (Finder > View > Use Stacks, grouping by Kind), every `.app` collapses
  into one pile, so several launchers become several identical icons in a
  stack you have to expand and aim at. A Dock tile is a single
  unambiguous target; that is why `--dest` defaults to `~/Applications`
  and `--dock` exists.
- **`--dock` restarts the Dock.** Windows are untouched, but the Dock
  visibly blinks.
