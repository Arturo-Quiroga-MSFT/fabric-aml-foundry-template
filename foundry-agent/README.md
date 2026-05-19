# Foundry agent

Owner: **<author> Bittencourt**.

This folder will host the **Microsoft Foundry agent** that uses the AML
managed online endpoints as tools, plus the supporting MCP server.

## `aml-mcp-server/` — MCP server (running)

A FastMCP server that exposes the AML endpoints as MCP tools:

| Tool                | Backing AML endpoint            | Model                                  |
|---------------------|---------------------------------|----------------------------------------|
| `is_paid_holiday`   | `contoso-endpoint`               | `contoso-poc-model`                   |
| `predict_sla_breach`| `support-tickets-endpoint`       | `support-tickets-sla-model`       |

### Environment variables

Per-tool endpoint configuration (preferred):

| Var | Required | Description |
|---|---|---|
| `HOLIDAY_ENDPOINT_URL` / `HOLIDAY_ENDPOINT_TOKEN` | for holidays tool | Scoring URI + `aml_token` for `contoso-endpoint` |
| `TICKETS_ENDPOINT_URL` / `TICKETS_ENDPOINT_TOKEN` | for tickets tool | Scoring URI + `aml_token` for `support-tickets-endpoint` |
| `AML_ENDPOINT_URL` / `AML_ENDPOINT_TOKEN` | optional fallback | Used by both tools if the per-tool vars are not set |

Observability:

| Var | Required | Description |
|---|---|---|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | optional | When set, OTel spans + logs are exported to App Insights via `azure-monitor-opentelemetry`. Unset = no-op. |
| `OTEL_SERVICE_NAME` | optional | Defaults to `contoso-aml-mcp-server`. Shows up as "Cloud role name" in App Insights. |

Get a fresh `aml_token` for the tickets endpoint:

```bash
az ml online-endpoint get-credentials \
  -g <resource-group> \
  -w <aml-workspace-name> \
  -n support-tickets-endpoint \
  --query accessToken -o tsv
```

### Run locally

```bash
cd foundry-agent/aml-mcp-server
uv sync
uv run python main.py   # serves http://127.0.0.1:9000
```

## Foundry agent (placeholder)

```text
foundry-agent/
├── aml-mcp-server/         # MCP server exposing AML endpoints (above)
├── agent.yaml              # Foundry agent definition (TBD)
├── tools/                  # Any extra tool code (TBD)
├── prompts/system.md       # System prompt (TBD)
└── README.md
```

Per the 6 May meeting, no constraint on UI — Teams, web chat, or CLI all acceptable. Pick whichever is fastest to demo.
