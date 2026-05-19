"""Contoso MCP server exposing AML online endpoints as tools.

Tools:
    - is_paid_holiday        -> contoso-endpoint (holidays classifier)
    - predict_sla_breach     -> support-tickets-endpoint (tickets SLA classifier)

Observability:
    OpenTelemetry tracing is initialized on import. When the env var
    ``APPLICATIONINSIGHTS_CONNECTION_STRING`` is set, spans are exported
    to Azure Monitor / Application Insights via
    ``azure-monitor-opentelemetry``. Otherwise the SDK runs no-op so the
    server still works locally and in CI. Outbound httpx calls to AML
    are auto-instrumented; each tool also creates an explicit span
    carrying the endpoint name, latency, and the returned prediction.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime
from typing import Annotated, Any

import holidays
import httpx
from azure.monitor.opentelemetry import configure_azure_monitor
from fastmcp import Context, FastMCP
from opentelemetry import trace

LOGGER = logging.getLogger(__name__)
_TELEMETRY_CONFIGURED = False
_OTEL_SERVICE_NAME = "aml-mcp-server"


def _configure_telemetry() -> None:
    """Configure OpenTelemetry export to Application Insights if enabled."""
    global _TELEMETRY_CONFIGURED
    if _TELEMETRY_CONFIGURED:
        return

    # Ensure exported telemetry has a stable service name in Application Insights.
    os.environ["OTEL_SERVICE_NAME"] = _OTEL_SERVICE_NAME

    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "").strip()
    if not connection_string:
        LOGGER.info("APPLICATIONINSIGHTS_CONNECTION_STRING not set. Telemetry export is disabled.")
        return

    configure_azure_monitor(connection_string=connection_string)
    _TELEMETRY_CONFIGURED = True
    LOGGER.info("Application Insights OpenTelemetry exporter configured.")


_configure_telemetry()
TRACER = trace.get_tracer("aml-mcp-server")

# --- OpenTelemetry bootstrap -------------------------------------------------

from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

_OTEL_CONN = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
_OTEL_SERVICE = os.getenv("OTEL_SERVICE_NAME", "contoso-aml-mcp-server")

if _OTEL_CONN:
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor(
        connection_string=_OTEL_CONN,
        resource_attributes={"service.name": _OTEL_SERVICE},
    )
    logging.getLogger(__name__).info(
        "OpenTelemetry initialized; exporting to Application Insights as %s",
        _OTEL_SERVICE,
    )
else:
    logging.getLogger(__name__).info(
        "APPLICATIONINSIGHTS_CONNECTION_STRING not set; OpenTelemetry export disabled."
    )

# Auto-instrument outbound httpx calls (spans are dropped if no exporter is configured).
HTTPXClientInstrumentor().instrument()

tracer = trace.get_tracer(__name__)

# -----------------------------------------------------------------------------

# Map common country names to ISO 3166-1 alpha-2 codes used by the holidays library.
_COUNTRY_CODES: dict[str, str] = {
    "united states": "US",
    "usa": "US",
    "us": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "uk": "GB",
    "germany": "DE",
    "france": "FR",
    "japan": "JP",
    "australia": "AU",
    "india": "IN",
    "brazil": "BR",
    "mexico": "MX",
    "italy": "IT",
    "spain": "ES",
    "china": "CN",
    "south korea": "KR",
    "netherlands": "NL",
}


def _resolve_country_code(country_or_region: str) -> str | None:
    """Try to resolve a country name to an ISO alpha-2 code."""
    key = country_or_region.strip().lower()
    if key in _COUNTRY_CODES:
        return _COUNTRY_CODES[key]
    # If already a 2-letter code, use it directly if supported.
    upper = country_or_region.strip().upper()
    if len(upper) == 2 and hasattr(holidays, upper):
        return upper
    return None


def _endpoint_config(prefix: str) -> tuple[str, str]:
    """Return (url, token) for a given env-var prefix, falling back to legacy AML_*."""
    url = os.getenv(f"{prefix}_ENDPOINT_URL") or os.getenv("AML_ENDPOINT_URL")
    token = os.getenv(f"{prefix}_ENDPOINT_TOKEN") or os.getenv("AML_ENDPOINT_TOKEN")
    if not url or not token:
        raise RuntimeError(
            f"Missing endpoint configuration: set {prefix}_ENDPOINT_URL and "
            f"{prefix}_ENDPOINT_TOKEN (or legacy AML_ENDPOINT_URL/AML_ENDPOINT_TOKEN)."
        )
    return url, token


async def _score(
    ctx: Context,
    *,
    span_name: str,
    endpoint_prefix: str,
    request_body: dict[str, Any],
    timeout_seconds: float = 10.0,
) -> Any:
    """Call an AML online endpoint and return the parsed JSON payload.

    Wraps the call in an OTel span so each scoring request is visible
    end-to-end in App Insights / Azure Monitor.
    """
    url, token = _endpoint_config(endpoint_prefix)
    await ctx.debug(f"AML request body: {json.dumps(request_body, indent=2)}")

    with tracer.start_as_current_span(span_name) as span:
        span.set_attribute("aml.endpoint.url", url)
        span.set_attribute("aml.endpoint.prefix", endpoint_prefix)
        span.set_attribute(
            "aml.request.rows",
            len(request_body.get("input_data", {}).get("data", [])),
        )

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(
                    url,
                    json=request_body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                response.raise_for_status()
                result = response.json()
        except Exception as exc:  # noqa: BLE001 - re-raised after recording
            span.record_exception(exc)
            span.set_status(trace.Status(trace.StatusCode.ERROR, str(exc)))
            raise
        finally:
            span.set_attribute(
                "aml.latency_ms",
                round((time.perf_counter() - started) * 1000, 1),
            )

        span.set_attribute("aml.response.preview", json.dumps(result)[:256])
        await ctx.debug(f"AML response body: {json.dumps(result, indent=2)}")
        return result


mcp = FastMCP("Contoso MCP Server for ML Models")

@mcp.tool(
    name="is_paid_holiday",
    description=(
        "Check whether a specific date is a recognized public holiday in a given country, "
        "and if so, whether it is paid time off. "
        "Requires country_or_region and date. The holiday name is looked up automatically."
    ),
)
async def is_paid_holiday(
    ctx: Context,
    country_or_region: Annotated[
        str, "Name of the country or region (e.g. 'United States', 'Japan'). Required."
    ],
    date: Annotated[str, "Date to check in YYYY-MM-DD format. Required."],
    holiday_name: Annotated[
        str, "Optional. Override the holiday name if the automatic lookup is wrong."
    ] = "",
) -> str:
    with TRACER.start_as_current_span("tool.is_paid_holiday") as span:
        span.set_attribute("mcp.tool.name", "is_paid_holiday")
        span.set_attribute("holiday.country_or_region", country_or_region or "")
        span.set_attribute("holiday.date", date or "")

        if not country_or_region or not date:
            return "Error: country_or_region and date are required."

        # --- Step 1: verify the date is a recognized holiday ---
        parsed_date = datetime.strptime(date, "%Y-%m-%d").date()
        country_code = _resolve_country_code(country_or_region)
        resolved_name = holiday_name  # use caller-provided name if given

        if country_code:
            try:
                country_holidays = holidays.country_holidays(country_code, years=parsed_date.year)
                if parsed_date not in country_holidays:
                    return (
                        f"{date} is NOT a recognized public holiday in {country_or_region}. "
                        f"No payment status to check."
                    )
                official_name = country_holidays.get(parsed_date)
                if not resolved_name:
                    resolved_name = official_name
                await ctx.info(
                    f"Confirmed holiday: {official_name} on {date} in {country_or_region}"
                )
            official_name = country_holidays.get(parsed_date)
            if not resolved_name:
                resolved_name = official_name
            await ctx.info(f"Confirmed holiday: {official_name} on {date} in {country_or_region}")
        except NotImplementedError:
            await ctx.warning(f"Holiday calendar not available for '{country_or_region}', skipping validation.")
    else:
        await ctx.warning(f"Could not resolve country code for '{country_or_region}', skipping holiday validation.")

    if not resolved_name:
        return f"Error: could not determine holiday name for {date} in {country_or_region}. Please provide holiday_name."

    # --- Step 2: call the model to determine paid/not-paid ---

    request_body = {
                "input_data": {
                    "columns": ["countryOrRegion", "holidayName", "normalizeHolidayName", "date_year", "date_month", "date_day", "date_dayofweek" ],               
                    "index": [0],
                    "data": [
                        [
                            country_or_region, 
                            resolved_name, 
                            resolved_name, 
                            date.split("-")[0], 
                            date.split("-")[1], 
                            date.split("-")[2], 
                            str(datetime.strptime(date, "%Y-%m-%d").weekday())  # Monday=0 ... Sunday=6
                        ]
                    ]  
                }
            }
        }

        await ctx.debug(f"AML request body: {json.dumps(request_body, indent=2)}")

    result = await _score(
        ctx,
        span_name="tool.is_paid_holiday",
        endpoint_prefix="HOLIDAY",
        request_body=request_body,
    )

    paid = str(result[0]).lower() == "true"
    return (
        f"On {date} in {country_or_region}, {resolved_name} is a "
        f"{'paid' if paid else 'not paid'} holiday."
    )


@mcp.tool(
    name="predict_sla_breach",
    description=(
        "Predict whether an Contoso / M365 support ticket will breach SLA. "
        "Returns 'True' (breach likely) or 'False'. Backed by the "
        "support-tickets-sla-model online endpoint."
    ),
)
async def predict_sla_breach(
    ctx: Context,
    tenant_seat_count: Annotated[int, "Number of seats on the tenant raising the ticket."],
    customer_tier: Annotated[str, "Customer tier, e.g. 'Standard', 'Premium', 'Enterprise'."],
    product_area: Annotated[str, "Contoso product area, e.g. 'Contoso Cloud Backup', 'Purview', 'Confide'."],
    issue_category: Annotated[str, "Issue category, e.g. 'Auth', 'Permissions', 'Performance', 'Data Loss'."],
    channel: Annotated[str, "Inbound channel, e.g. 'Portal', 'Teams', 'Email', 'Phone'."],
    region: Annotated[str, "Region, e.g. 'AMER', 'EMEA', 'APAC'."],
    language: Annotated[str, "ISO language code, e.g. 'en', 'pt', 'fr', 'de'."],
    priority_reported: Annotated[str, "Priority reported by the customer: 'Low', 'Medium', 'High', 'Critical'."],
    attached_logs: Annotated[bool, "Whether logs were attached to the ticket."],
    prior_tickets_30d: Annotated[float, "Tickets opened by this tenant in the last 30 days."],
    agent_tier: Annotated[str, "Assigned agent tier, e.g. 'T1', 'T2', 'T3'."],
    created_at: Annotated[str, "Ticket creation date in YYYY-MM-DD format."],
) -> str:
    """Score a single support ticket against the SLA-breach classifier."""
    try:
        created_dt = datetime.strptime(created_at, "%Y-%m-%d")
    except ValueError:
        return f"Error: created_at must be YYYY-MM-DD (got '{created_at}')."

    request_body = {
        "input_data": {
            "columns": [
                "tenant_seat_count", "customer_tier", "product_area", "issue_category",
                "channel", "region", "language", "priority_reported", "attached_logs",
                "prior_tickets_30d", "agent_tier",
                "created_at_year", "created_at_month", "created_at_day", "created_at_dayofweek",
            ],
            "index": [0],
            "data": [[
                int(tenant_seat_count),
                customer_tier,
                product_area,
                issue_category,
                channel,
                region,
                language,
                priority_reported,
                bool(attached_logs),
                float(prior_tickets_30d),
                agent_tier,
                created_dt.year,
                created_dt.month,
                created_dt.day,
                created_dt.weekday(),
            ]],
        }
    }

    result = await _score(
        ctx,
        span_name="tool.predict_sla_breach",
        endpoint_prefix="TICKETS",
        request_body=request_body,
    )

    prediction = str(result[0])
    breach = prediction.lower() == "true"
    span = trace.get_current_span()
    span.set_attribute("aml.prediction", prediction)
    span.set_attribute("aml.prediction.breach", breach)

    verdict = "LIKELY TO BREACH SLA" if breach else "unlikely to breach SLA"
    return (
        f"Ticket scored: {verdict} "
        f"(model=support-tickets-sla-model, prediction={prediction})."
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=9000)
