# LMDE Component: Observability

## Overview

Provides a local, persistent observability stack for agents and services. Other components (like `clai`) can push metrics to the OTel collector, which then routes them to Prometheus for storage and Grafana for visualization.

## Architecture

- **Infrastructure**: Running on a dedicated `kind` cluster named `lmde-observability`.
- **Telemetry ingest**: The OTel collector is exposed to the host on `localhost:4317`/`4318` via `kind` `extraPortMappings`.
- **Host access**: Grafana is reached at `grafana.lmde.localhost` through Caddy and an in-cluster `ingress-nginx` controller -- see [networking/](../networking/README.md).
- **Persistence**: Prometheus uses local path provisioning for persistent metric storage across cluster restarts.

## Components

1. **OTel Collector**:
   - Receiver: OTLP (gRPC/HTTP).
   - Processor: Batch, Resourcedetection.
   - Exporter: Prometheus.
2. **Prometheus**:
   - Scrapes the OTel collector.
   - Stores metrics for 15 days.
3. **Grafana**:
   - Data Source: Prometheus.
   - Default Dashboards: Agent Performance, Token Usage, Success Rates.
   - The Coding Agents dashboard can be sliced by `airframe_session_id` (promoted from the OTel resource attribute `airframe.session_id`, alongside `airframe_connection_id` / `airframe_agent_kind`) to correlate agent metrics with the airframe session that spawned them.
   - Reached at `grafana.lmde.localhost` (ingress-nginx route + Caddy vhost).

## Setup Logic

- `setup.sh`: Orchestrates `kind cluster create`, the `ingress-nginx` install, Helm installs, and Grafana vhost registration.
- `specs/`: Kubernetes manifests (ConfigMaps, Deployments, the Grafana `Ingress`).
