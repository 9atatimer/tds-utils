# Antigravity (agy) -> OpenTelemetry hook

Bridge agy's agent events to OpenTelemetry via `opentelemetry-hooks`. Antigravity
inherited Gemini CLI's Hooks, so a hook can stream each agent event to the
exporter until agy ships native telemetry
(`google-antigravity/antigravity-cli#366`).

## Hook command

Register a hook/workflow in agy that, on each agent event, runs:

    env IDE_OTEL_IDE_NAME=antigravity otel-hook

agy pipes the event as JSON on stdin; `otel-hook` emits OpenTelemetry spans and
logs over OTLP and returns the runner-compatible success response on stdout.

## Notes

- The exact workflow/hook file format is agy-version-specific. Start from the
  upstream template `examples/antigravity-workflow.example.md` in
  `o11y-dev/opentelemetry-hooks` and replace its `{{SCRIPT_PATH}}` placeholder
  with the command above.
- Exporter target and IDE name come from `otel_config.json` in this directory.
- `airframe.session_id` correlation is automatic: clai sets
  `OTEL_RESOURCE_ATTRIBUTES` on the agy process, and `otel-hook` (invoked by agy
  as a child) inherits it -- env takes precedence over `otel_config.json`.
