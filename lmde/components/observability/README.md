# LMDE Component: Observability

## Overview
Provides a local, persistent observability stack for agents and services. Other components (like `clai`) can push metrics to the OTel collector, which then routes them to Prometheus for storage and Grafana for visualization.

## Architecture
- **Infrastructure**: Running on a dedicated `kind` cluster named `lmde-observability`.
- **Ingress**: The OTel collector is exposed to the host via a `nodePort` or `localhost` port forward.
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

## Setup Logic
- `setup.sh`: Orchestrates `kind cluster create`, Helm installs, and port-forward configurations.
- `specs/`: Kubernetes manifests (ConfigMaps, Deployments).
