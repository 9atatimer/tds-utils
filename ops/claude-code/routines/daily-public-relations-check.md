---
name: Daily Public Relations Check
scope: tds-utils-singleton
live_id: trig_01ShpVykkWyFV5ThYwThK5Xc
schedule: "0 19 * * *"       # daily 19:00 local
enabled: true
session: fresh               # create_new_session_on_fire
environment_id: env_011CUoVj9AwEUcCmKxLVKt8u
model: claude-sonnet-5
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch]
autofix_on_pr_create: false
mcp_connections: []
sources:
  - https://github.com/9atatimer/tds-utils
---
The tds-utils repo is one of the few public repos I work with -- the rest I keep private -- and so my muscle memory may not be appropriate to keep embarrassing things out of the limelight.

Please look at recent changes to tds-utils and flag anything that should not have been made to a public repo.  You run daily, so don't bother with things that are more than 48h old.

This could be security blunders, like leaking keys or credentials, but also editorial blunders, like calling a team or technology a bunch of pejoratives.  Or just swearing in general.

Bring these issues to my attention -- I don't want to project negativity that could reflect poorly on me, my employers, or my colleagues.
