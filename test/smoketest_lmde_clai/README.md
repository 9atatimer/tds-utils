# smoketest_lmde_clai -- LMDE/CLAI behavioral smoketest

Black-box behavioral smoketest for the LMDE/CLAI dev-environment pairing. It
stands inside a REAL target -- a laptop `clai claude` session, or a Claude Code
cloud session -- and interrogates the observable end-state a user/agent would
see. It is not a unit test: nothing is stubbed, and the probes do not care
which tool placed a given artifact, only that the world matches what the
design promises.

Why black-box: the two environments acquire the world by different means (a
laptop uses `lmde acquire`; the cloud uses `@nine-at-a-time-media/sandbox`),
yet the observable end-state is the same. Asserting the end-state -- not the
mechanism -- lets one probe run in both places.

## What it checks

`probe-lmde.sh` -- "did the world get acquired?" (agent-agnostic artifacts):

| id | check                | laptop | cloud |
|----|----------------------|--------|-------|
| L1 | clai on PATH, runnable            | assert | assert |
| L2 | ast-mcp binary at ~/.local/bin    | assert | assert |
| L3 | global CLAUDE.md + known marker   | skip*  | assert |
| L4 | ~/.local/bin on PATH              | assert | assert |

`probe-clai.sh` -- "does the agent see the configuration?" (agent-aware wiring):

| id | check                             | laptop | cloud |
|----|-----------------------------------|--------|-------|
| C1 | ast-mcp in the MCP server list (.mcp.json) | assert | assert |
| C2 | cloudflare MCP disabled (~/.claude.json)   | assert | skip** |
| C3 | clai injects OTEL telemetry env            | assert | pass** |
| C4 | skills placed in .claude/skills            | assert | assert |

\* L3 is skipped on a laptop by design: `naatm-sandbox` places the global
CLAUDE.md only in a cloud sandbox (`setup-core.sh` skips it on a real
checkout). In the cloud it lands at `/etc/claude-code/CLAUDE.md` (override
`CLAUDE_GLOBAL_ETC_DIR`, fallback `$HOME/CLAUDE.md`) and must contain the
marker "Specificity is a virtue".

\*\* C2/C3 are launch-time effects of the `clai claude` wrapper (the
cloudflare-disable pre-hook; the injected OTEL env). In the cloud the provider
launches the agent directly with no clai wrapper (boundary Non-Goal G1), so C2
is skipped and C3 auto-passes there per project convention.

## How to run

### Laptop

    test/smoketest_lmde_clai/run-laptop.sh

This launches a real headless session through clai (`clai claude -p ...`) with
cwd at this checkout, has it run the probes, and grades the `OVERALL` line.
Going through `clai claude` is what makes the launch-time cells real: the
SessionStart hook runs `clai provision` (populating `.claude/skills` and
`.mcp.json`) and the cloudflare-disable pre-hook fires. Exit 0 == green.

### Cloud

There is no committed cloud driver -- a cloud session is spun up out of band
(a dedicated `smoketest` Claude Code environment, manually provisioned with the
`@nine-at-a-time-media/sandbox` setup script + PAT). Inside that session, run:

    bash test/smoketest_lmde_clai/run-probes.sh

and read the `OVERALL env=cloud failed=N` line. `run-probes.sh` auto-detects
the cloud via `CLAUDE_CODE_REMOTE=true` and applies the cloud column above.

## Notes / caveats

- `run-probes.sh` is the in-target executor: it runs both probes and prints an
  `OVERALL env=<env> failed=<n>` line. It is what a session actually runs.
- Each check prints one line: `PASS <id> <desc>` / `FAIL <id> <desc> -- <detail>`
  / `SKIP <id> <desc> -- <reason>`. A probe ends with
  `SMOKE-RESULT <probe> passed=.. failed=.. skipped=..` and exits with its
  failure count.
- C2 asserts end-state (cloudflare names present in this project's
  `disabledMcpServers`). Because that is a file, it can read as green even if a
  prior run -- not this launch -- wrote it. That is acceptable for a smoketest,
  which asks "does the world look right?", not "who made it so?".
- C3 reads `clai env` (which execs `env` through clai's launcher) rather than
  the probe's own inherited environment. Claude Code's Bash tool does not
  mirror the parent claude process's OTEL_* vars into child shells, so an
  in-session probe cannot observe the injection any other way.
- The markdown-ascii lint gate is intentionally out of scope: it is a
  `naatm-hooks` pre-commit hook used by `template-base`-derived repos, not a
  clai responsibility, and tds-utils does not wire it.
