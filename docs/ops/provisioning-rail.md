# Putting a machine on the provisioning rail

Moved from tds-utils `AGENT.md`. `tds-release` makes this repo's config live; this is how agent tooling (skills, `clai`, `ast-mcp`, `gadmin`) becomes current.

`tds-release` makes this repo's config live. It does NOT make agent tooling
current -- skills, `clai`, `ast-mcp`, `gadmin` come from `lmde acquire`, and
nothing runs that by itself until the machine carries the session engine.

A machine without it is not broken, it is SILENT: the committed
`.claude/hooks/session-start.sh` walks its find-engine ladder, finds nothing,
prints one line to stderr and exits 0. Sessions start normally with whatever
tooling happened to be installed. That is how `ast-mcp` sat on 0.2.1 while
the fleet pin said 0.4.0, and how `clai` stayed on a build that could not
start on macOS (issue #232, template-tools#522).

Two commands, once per machine:

```zsh
npm install -g @nine-at-a-time-media/sandbox   # the engine
naatm-sandbox setup                            # seed + register the hook
```

`setup` seed-acquires the fleet, writes `~/.claude/hooks/naatm-session-start.sh`,
and registers it in user-scope `~/.claude/settings.json`. From then on every
new session acquires and provisions before you type anything.

Three things worth knowing:

- **No token needed.** `lmde acquire` resolves the credential from
  `GH_PAT_NAATM_PACKAGES_RO`, then the deprecated `GH_AI_TOOLS_PAT`, then
  your own `gh auth token`. A default `gh auth login` does NOT grant
  `read:packages` though -- if installs 401, run
  `gh auth refresh -h github.com -s read:packages`.
- **Remove the older user-scope hook.** `~/.claude/hooks/session-start.sh`
  (registered by `clai hooks install`) runs `clai provision` only, and
  `naatm-sandbox-session-start` supersedes it -- acquire AND provision.
  SANDBOX-LIFECYCLE.DESIGN.md D3 already records that the `clai hooks
  install` call is "REMOVED -- superseded, not no-op"; a machine set up
  before naatm-sandbox 0.6.0 still has the leftover. Left in place the two
  disagree about symlink-vs-copy and rewrite each other's work every session.
- **Check what you are running** with `lmde acquire --check`, which reports
  each package as current or stale without installing anything. It is also
  what `git-hooks/pre-push` runs.
