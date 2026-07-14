# Claude Code Routines -- git source of truth

Canonical specs for the scheduled Claude Code **Routines** (persistent cron
triggers) run against my repos. Git is the source of truth; the live triggers
are reconciled *from* these files.

Today all five are **global singletons** -- one instance each, no per-repo or
per-environment variants -- so we file them under `scope: tds-utils-singleton`
until that stops being true.

## Files

One `*.md` per Routine: YAML front-matter (the config) + the prompt body
(everything after the `---`). Slug names are `daily-*` / `weekly-*` by cadence.

| File | Schedule | Target |
|---|---|---|
| `daily-ci-magic-improvement.md` | `0 7 * * *` | template-tools + tds-utils |
| `daily-rulebook-backport.md` | `0 16 * * *` | GammaGo |
| `daily-public-relations-check.md` | `0 19 * * *` | tds-utils |
| `weekly-sandbox-verification.md` | Mon `0 19 * * 1` | tau |
| `weekly-lmde-clai-smoketest.md` | Wed `13 18 * * 3` | tds-utils |

## Front-matter schema

```yaml
name:                  # human name, matched against the live trigger
scope:                 # tds-utils-singleton (for now)
live_id:               # current trigger id (informational; used to map on reconcile)
schedule:              # 5-field cron, local time
enabled:               # true | false
session:               # fresh | bound:<session_id>
environment_id:        # env_...
model:                 # default | claude-sonnet-5 | claude-sonnet-4-6 | ...
allowed_tools: []      # tool allow-list
autofix_on_pr_create:  # true | false
mcp_connections: []    # connector names
sources: []            # repo URLs the session is started with
notifications:         # optional; push/email/slack channels. Omit when unset/off (the default for all five today)
```

## Reconcile workflow

There is **no standalone authenticated CLI** for Routines -- the trigger API is
reachable only through the `Claude_Code_Remote` MCP tools, which live inside a
Claude Code session. So "apply from the repo" means: open a session and tell it
to reconcile this directory. It reads each spec, diffs against
`list_triggers`, and converges with `create_trigger` / `update_trigger` /
`delete_trigger`.

- **Export (live -> git):** read `list_triggers`; the full definition
  (cron, prompt, env, tools, model, sources, autofix, MCP) is in
  `job_config.ccr`. Write/refresh the spec files. Fully faithful.
- **Apply (git -> live):** map by `live_id`/`name`; create missing, delete
  extras. See the fidelity gaps below before trusting a round-trip.

**Do not edit the prompt body.** Everything after the front-matter `---` is a
verbatim snapshot of the live Routine's deployed prompt. Do not normalize its
whitespace, punctuation, or typos, and do not apply SKILL.MARKDOWN.md to it --
those rules govern authored Markdown, not captured data. "Fixing" prompt-body
text silently desyncs the spec from the running trigger. To change a prompt,
edit the live Routine and re-export.

## Fidelity gaps (read before applying)

The MCP **write** surface is narrower than the **read** surface. `create_trigger`
accepts only: name, prompt, cron/run_once_at, environment_id, session binding,
notifications. It does **not** accept:

- `allowed_tools`
- `model`
- `sources`
- `autofix_on_pr_create`
- `mcp_connections`

Those five fields **cannot be set from the MCP** -- they must be set in the web
UI. Most affected: `daily-rulebook-backport` (sonnet-4-6 + autofix + Drive MCP)
and `daily-public-relations-check` (sonnet-5).

`update_trigger` is narrower still: it changes only **name, cron, enabled,
run_once_at** -- **not the prompt**. Editing a prompt = `delete_trigger` +
`create_trigger` (which re-incurs the gaps above).

Net: git is a faithful **record** and a faithful applier for
schedule/prompt/env/session. The prompt-only fields are documented here and
must be reconciled by hand in the UI until the API grows those parameters.
