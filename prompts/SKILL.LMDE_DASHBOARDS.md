# SKILL: Crafting and Deploying LMDE Grafana Consoles

> Purpose: Standardized workflow for designing, version-controlling, and deploying Grafana dashboards into the LMDE.
> When to use: When you need to visualize new metrics (from agents, systems, or apps) in the permanent observability stack.
> Update Discipline: MAINTAINED BY THE HUMAN. Propose dashboard JSON changes to the human for review before committing to the repo.

---

## 1. The Design Loop (UI-First)

Grafana dashboards are complex JSON objects. The most efficient way to craft them is via the Grafana UI, then export them for version control.

1.  **Access the UI**: Ensure the stack is running and visit `http://localhost:3000` (admin/admin).
2.  **Experiment**: Use the "Explore" tab to verify your Prometheus queries.
3.  **Build**: Create a new Dashboard, add Panels, and refine the layout.
4.  **Export**: 
    - Click the **Dashboard Settings** (gear icon).
    - Select **JSON Model**.
    - Copy the entire JSON block.

## 2. The Deployment Pipeline (Code-First)

Once you have the JSON, you must graduate it from an ad-hoc UI change to a managed part of the LMDE.

### A. Create the Dashboard File
Save the exported JSON into a new file in the repository:
`lmde/components/observability/specs/grafana/dashboards/<dashboard-name>.json`

### B. Define the ConfigMap
Grafana is configured to load dashboards from Kubernetes ConfigMaps. Create a manifest for your dashboard:
`lmde/components/observability/specs/grafana/dashboards/<dashboard-name>.yaml`

Example:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-dashboard-<dashboard-name>
  namespace: observability
  labels:
    grafana_dashboard: "1" # CRITICAL: This label tells Grafana to ingest this CM
data:
  <dashboard-name>.json: |
    # [PASTE JSON HERE]
```

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
