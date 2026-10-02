# LMDE Component: Observability

## Overview

Provides a local, persistent observability stack for agents and services. Other components (like `clai`) push metrics, logs, and traces to the OTel collector, which routes metrics to Prometheus, logs to Loki, and traces to Tempo; Grafana reads all three.

## Architecture

- **Infrastructure**: Running on a dedicated `kind` cluster named `lmde-observability`.
- **Telemetry ingest**: The OTel collector is exposed to the host on `localhost:4317`/`4318` via `kind` `extraPortMappings`.
- **Host access**: Grafana is reached at `grafana.lmde.localhost` through Caddy and an in-cluster `ingress-nginx` controller -- see [networking/](../networking/README.md).
- **Persistence**: Prometheus uses a HostPath PersistentVolume; Loki and Tempo use `hostPath` subdirectories (`loki/`, `tempo/`) of the same host data directory. All three survive cluster restarts.

## Components

1. **OTel Collector**:
   - Receiver: OTLP (gRPC/HTTP).
   - Processor: Batch, Resourcedetection.
   - Exporters: Prometheus (metrics), Loki via `otlp_http/loki` (logs),
     Tempo via `otlp_grpc/tempo` (traces).
   - Connector: `sum` -- derives Prometheus token-usage metrics
     (`gen_ai.client.token.usage.*`) from the `gen_ai.usage.*_tokens` span
     attributes that agents emit (e.g. Antigravity via `specs/otel-hooks/`).
     The traces pipeline feeds this connector as well as Tempo.
     `traces_to_metrics` is alpha as of collector-contrib 0.155.0.
2. **Prometheus**:
   - Scrapes the OTel collector.
   - Stores metrics for 15 days.
3. **Loki** (`specs/loki/`):
   - Single binary, filesystem store, 14-day retention.
   - OTLP ingest at `/otlp`; resource attributes become labels
     (`service_name`, ...), `trace_id` is structured metadata.
4. **Tempo** (`specs/tempo/`):
   - Monolithic, local backend, 14-day block retention (Tempo's default).
   - OTLP gRPC ingest on `4317` (in-cluster only; the host's `4317` is the
     collector).
   - Loki and Tempo images are distroless and run as uid `10001`; an init
     container from the pinned Prometheus image chowns their data dir.
5. **Grafana**:
   - Data Sources: Prometheus, Loki (uid `loki`), Tempo (uid `tempo`). A
     Loki line's `trace_id` links to the trace; a span links to its logs.
   - Default Dashboards: Agent Performance, Token Usage, Success Rates.
   - The Coding Agents dashboard can be sliced by `airframe_session_id` (promoted from the OTel resource attribute `airframe.session_id`, alongside `airframe_connection_id` / `airframe_agent_kind`) to correlate agent metrics with the airframe session that spawned them.
   - Its "Antigravity Token Usage (gen_ai)" row graphs the token metrics derived
     by the collector's `sum` connector, also sliceable by `airframe_session_id`.
   - Reached at `grafana.lmde.localhost` (ingress-nginx route + Caddy vhost).

### Antigravity (agy) telemetry bridge

Antigravity CLI has no native OpenTelemetry. `specs/otel-hooks/` bridges it via
[`opentelemetry-hooks`](https://github.com/o11y-dev/opentelemetry-hooks), which
rides agy's Hooks to emit `gen_ai.*` spans to this collector; the `sum` connector
turns those into the token metrics above. See `specs/otel-hooks/README.md`.

## Setup Logic

- `setup.sh`: Orchestrates `kind cluster create`, the `ingress-nginx` install, Helm installs, and Grafana vhost registration.
- `specs/`: Kubernetes manifests (ConfigMaps, Deployments, the Grafana `Ingress`).
