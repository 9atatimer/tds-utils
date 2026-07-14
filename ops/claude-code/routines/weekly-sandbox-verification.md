---
name: Routine sandbox verification
scope: tds-utils-singleton
live_id: trig_01SRNVVjSAwtZkNdGQUt9aSu
schedule: "0 19 * * 1"       # weekly Monday 19:00 local
enabled: true
session: fresh               # create_new_session_on_fire
environment_id: env_011CUoVj9AwEUcCmKxLVKt8u
model: default
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch]
autofix_on_pr_create: false
mcp_connections: []
sources:
  - https://github.com/9atatimer/tau
---
Weekly sandbox provisioning audit (self-check, no external input — this routine's own job)

This is a recurring maintenance check I set up to confirm this environment is provisioned the way I expect. Please:

CLAUDE.md: Identify the paths of the CLAUDE.md files that are included in your initial prompt -- specifically do you see /etc/claude-code/ or /root/ CLAUDE.md files?

MCP servers: List which MCP servers/connectors are available in this session, which are active vs. installed-but-disabled, and their scope (e.g., which repos the GitHub server can reach). Flag anything unexpected — servers I wouldn't expect this environment to need, or expected ones that are missing.

Credential provisioning: List the names of environment variables that look credential-shaped (KEY/TOKEN/SECRET/PASSWORD/AUTH patterns) — names only, never values.

Git hook: identify which git-hooks are active, and characterize the functionality of their handlers (briefly).

NEVER show the value of an ENV var.  Only the keys; never the values.

Report findings as a short summary, not a raw terminal dump.

We anticipate:
- you have 'global' CLAUDE.md, outside of the repo are you running in, in of the locations enumerated above.  It should reference 'specificity'.
- you have several editing MCP servers, eg ast-mcp, available to you if you decide to edit certain types of files
- you have an ecosystem of hooks that prevent you from violating coding styles or security patterns that are required of you

If everything matches expected provisioning, say so briefly — no need for detail. If something's off (missing config, unexpected credentials, wrong repo scope), call it out clearly since that's the point of this check.
