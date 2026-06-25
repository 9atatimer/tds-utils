# clai.d/agy

Overlay-hook directory for the **Antigravity CLI** (`agy`), Google's Go-based
successor to the deprecated Gemini CLI. Its presence registers `agy` as a
known agent for `clai --list-agents`; drop executable hooks under `pre/` (run
before the agent launches) or `post/` (run after it exits). clai runs both
stages for every agent it launches; the existing `clai.d/claude` overlay
currently defines `pre/` hooks only.

No hooks are defined yet -- this directory exists so `clai agy` is recognised
and so the `agy` alias in `macos/dot.alias` routes through clai for overlay
hooks and OpenTelemetry env (including airframe session correlation).
