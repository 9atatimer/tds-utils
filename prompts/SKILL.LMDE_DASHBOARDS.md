# SKILL: Crafting and Deploying LMDE Grafana Consoles

> Purpose: Standardized workflow for designing, version-controlling, and deploying Grafana dashboards into the LMDE.
> When to use: When you need to visualize new metrics (from agents, systems, or apps) in the permanent observability stack.
> Update Discipline: MAINTAINED BY THE AGENT. The Gemini CLI is responsible for authoring, refactoring, and optimizing dashboard JSON. The Human provides design intent or UI exports for fine-tuning.

---

## 1. The Design Loop (Agent-Led)

Grafana dashboards are complex JSON objects. While they can be crafted in the UI, the Gemini CLI manages their lifecycle in the repository.

1.  **Draft**: The agent generates or updates the dashboard JSON based on available metrics and user intent.
2.  **Deploy**: The agent wraps the JSON in a Kubernetes ConfigMap and applies it to the cluster.
3.  **Refine (Optional Human Input)**:
    - The Human can make ad-hoc adjustments in the Grafana UI (`http://localhost:3000`).
    - To persist these, the Human exports the **JSON Model** and provides it to the agent.
    - The agent proofs the JSON (removes volatile fields, ensures consistency) and updates the repo.

## 2. The Deployment Pipeline (Code-First)

The agent ensures every dashboard is a managed part of the LMDE.

### A. Create the Dashboard File

The agent saves the JSON into:
`lmde/components/observability/specs/grafana/dashboards/<dashboard-name>.json`

### B. Define the ConfigMap

Grafana's sidecar automatically loads dashboards from Kubernetes ConfigMaps. The agent creates the manifest:
`lmde/components/observability/specs/grafana/dashboards/<dashboard-name>.yaml`

Example:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-<dashboard-name>
  namespace: observability
  labels:
    grafana_dashboard: "1" # CRITICAL: The sidecar watches for this label
data:
  <dashboard-name>.json: |
    # [PASTE JSON HERE]

```

## 3. Best Practices

- **Sidecar Requirement**: Ensure the Grafana `sidecar.dashboards.enabled` value is set to `true`.
- **Templating**: Use Dashboard Variables (e.g., `$service_name`) to make dashboards reusable across different agents.
- **Labels**: Always ensure your Prometheus queries filter by meaningful labels (e.g., `job="otel-collector"`) to avoid metric crosstalk.

## 4. Current Console Inventory

| Console | Path | Status |
|---------|------|--------|
| Coding Agents | `lmde/.../coding-agents.yaml` | In Progress |

### C. Register in setup.sh (if needed)

Ensure the `setup.sh` script applies any new dashboard specs:
```bash
kubectl apply -f "${SCRIPT_DIR}/specs/grafana/dashboards/"
```

## 3. Best Practices

- **Persistence**: Dashboards created purely in the UI *will survive* pod restarts (stored in the persistent volume), but *will be lost* if the cluster is deleted unless they are version-controlled in the repo.
- **Templating**: Use Dashboard Variables (e.g., `$service_name`) to make dashboards reusable across different agents.
- **Labels**: Always ensure your Prometheus queries filter by meaningful labels (e.g., `job="otel-collector"`) to avoid metric crosstalk.

## 4. Current Console Inventory

| Console | Path | Status |
|---------|------|--------|
| (Empty) | N/A  | No dashboards provisioned yet. |
