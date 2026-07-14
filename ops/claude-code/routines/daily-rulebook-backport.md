---
name: Daily Rulebook Backport
scope: tds-utils-singleton
live_id: trig_01FqiSDtVstKu9ZazP4YyuDp
schedule: "0 16 * * *"       # daily 16:00 local
enabled: true
session: fresh               # create_new_session_on_fire
environment_id: env_011CUoVj9AwEUcCmKxLVKt8u
model: claude-sonnet-4-6
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch]
autofix_on_pr_create: true
mcp_connections: [Google_Drive]
sources:
  - https://github.com/Nine-At-A-Time-Media/GammaGo
---
The active development on the table top RPG, rulebooks/handbooks/ needs to be back-ported to the regulation-style rulebooks rulebooks/regulations/

Please take a look at recent changes within 24h to the repo that affect handbooks/, and make the regulations reflect those changes.  Use the REGULATIONS skill when working in the regulations/ tree.

If there are no changes in the last 24h, do nothing.

Generate a PR with your changes.  Resolve the copilot feedback for that PR according to the GITHUB.md triage instructions.
