# clai.d/agy

Overlay-hook directory for the **Antigravity CLI** (`agy`), Google's Go-based
successor to the deprecated Gemini CLI. Its presence registers `agy` as a
known agent for `clai --list-agents`; drop executable hooks under `pre/` (run
before the agent launches) or `post/` (run after it exits). clai runs both
stages for every agent it launches; this overlay ships a `pre/` directory only
(as does the existing `clai.d/claude` overlay), so create a `post/` directory
here if and when you add post-hooks.

The `pre/20-enable-ast-mcp` hook registers the ast-mcp MCP server into agy's
config (`~/.gemini/config/mcp_config.json`) at launch, pointing at the
LMDE-installed binary. This directory also makes `clai agy` recognised and
routes the `agy` alias in `macos/dot.alias` through clai for overlay hooks and
OpenTelemetry env (including airframe session correlation).
