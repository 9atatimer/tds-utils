---
name: Daily ci-magic Improvement
scope: tds-utils-singleton
live_id: trig_013v39ospyYD9APvc6mq2KS8
schedule: "0 7 * * *"        # daily 07:00 local
enabled: true
session: fresh               # create_new_session_on_fire
environment_id: env_011CUoVj9AwEUcCmKxLVKt8u
model: default
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, WebFetch, WebSearch]
autofix_on_pr_create: false
mcp_connections: []
sources:
  - https://github.com/Nine-At-A-Time-Media/template-tools
  - https://github.com/9atatimer/tds-utils
---
Review the ci-magic design doc, focusing on the goals scope.

Examine the implementation on-disk, code and workflows.

Propose a QoL enhancement, or cost savings enhancement, as an Issue.  Mark it with the QoL tag.  Ensure the Issue has a justification.

Then look at the QoL issues, and pick one that seems like the least work, but has a good justification.  Do that work in a PR.  If you  hit a blocker, just abandon the code and update the Issue with the challenge.  Someone else will handle it.

Make sure your PR includes updating the design doc with your enhancement if it is a design change.  You do not need to update the design doc if it just an implementation improvement.
Leave the design doc matter of fact.  Only add a Key Decision change if it really is a significant change in design.
