# otel-hooks -- OpenTelemetry for Antigravity CLI (agy)

Antigravity CLI (`agy`) has **no native OpenTelemetry support** -- the capability
Gemini CLI had was dropped in the transition and is an open, unanswered request
upstream (`google-antigravity/antigravity-cli#366`). This directory bridges that
gap using [`o11y-dev/opentelemetry-hooks`](https://github.com/o11y-dev/opentelemetry-hooks),
which rides agy's retained **Hooks** mechanism to emit OpenTelemetry from each
agent event.

## How it works

```
agy (agent event, JSON on stdin)
  -> otel-hook  (opentelemetry-hooks, IDE_OTEL_IDE_NAME=antigravity)
     -> OTLP http/protobuf -> LMDE collector :4318
        -> traces  : gen_ai.* spans (token usage as span attributes)
        -> metrics : derived by the collector's `sum` connector (see below)
           -> Prometheus -> Grafana "coding-agents" dashboard
```

`opentelemetry-hooks` records token usage as **span attributes**
(`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.usage.cache_read.input_tokens`, ...), following the OpenTelemetry GenAI
semantic conventions -- it does **not** emit a token-usage metric. The LMDE OTel
collector therefore derives Prometheus metrics from those spans with the `sum`
connector (`specs/otel-collector/config.yaml`); without that, the spans are
dropped and nothing reaches Grafana.

## Setup

1. Install the hook runner:

       pipx install opentelemetry-hooks

2. Install this config so the runner targets the local LMDE collector:

       mkdir -p ~/.local/share/opentelemetry-hooks
       cp otel_config.json ~/.local/share/opentelemetry-hooks/otel_config.json

   (or point `IDE_OTEL_HOOK_HOME` at this directory).

3. Register the agy hook -- see `antigravity-otel.workflow.md`.

## airframe correlation

When agy is launched by clai inside an airframe session, clai sets
`OTEL_RESOURCE_ATTRIBUTES` (carrying `airframe.session_id` /
`airframe.connection_id`) on the agy process. `otel-hook` inherits that env, and
`opentelemetry-hooks` merges `OTEL_RESOURCE_ATTRIBUTES` into its resource (env is
highest precedence), so agy's telemetry is tagged with the airframe session and
joins the rest of the `coding-agents` dashboard.

## Caveats (validate on a real box before relying on this)

- The collector's `sum` connector `traces_to_metrics` path is **alpha** as of
  collector-contrib 0.155.0.
- Whether the connector preserves the source spans' **resource attributes** onto
  the derived metric is undocumented; if `airframe_session_id` does not appear on
  the token metrics, a `transform`/`groupbyattrs` step may be needed.
- The exact emitted Prometheus metric name (e.g. `_total` suffix) should be
  confirmed against the running collector and the dashboard query adjusted if
  needed.
