# Monitoring

Observability assets for the POC.

Planned:

- `workbook.json` — Azure Monitor Workbook template (endpoint latency, error rate, drift KPIs, prediction volume).
- `alerts.bicep` — alert rules (drift threshold breach, endpoint 5xx rate, latency P95).
- `kql/` — saved KQL queries for the Workbook tiles.

The Workbook reads from the Log Analytics workspace deployed by `infra/main.bicep`.
