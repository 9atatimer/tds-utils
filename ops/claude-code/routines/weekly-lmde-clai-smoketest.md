---
name: LMDE/CLAI Smoketest
scope: tds-utils-singleton
live_id: trig_014F87KhHeReuvD1aNhaSKrQ
schedule: "13 18 * * 3"      # weekly Wednesday 18:13 local
enabled: true
session: bound:session_01Taw6ftYYeDJgqYthUwREG3   # persistent_session_id
environment_id: env_011CUoVj9AwEUcCmKxLVKt8u
model: default
allowed_tools: [Bash, Read, Grep, Glob]
autofix_on_pr_create: false
mcp_connections: [Google_Drive, Claude_Code_Remote]
sources:
  - https://github.com/9atatimer/tds-utils
---
LMDE/CLAI cloud smoketest (verdict-only; issue self-reporting is deferred to tds-utils#149 -- the cloud sandbox has no gh CLI).

Steps:
1. Find the tds-utils checkout you were started in and cd into it (a clone of github.com/9atatimer/tds-utils, default branch master, which contains the suite).
2. Run exactly this:
     bash test/smoketest_lmde_clai/run-probes.sh
3. Print that command's ENTIRE stdout verbatim, especially the final line: OVERALL env=<env> failed=<n>. failed=0 means the cloud smoketest passed.

Do NOT edit, commit, or push any repo files. Read and run only.
