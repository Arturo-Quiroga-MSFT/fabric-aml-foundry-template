"""Configuration helpers — loads .env and exposes typed accessors."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv(encoding="utf-8")

_GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Settings:
    subscription_id: str
    resource_group: str
    location: str
    aml_workspace: str
    aml_compute_cluster: str
    key_vault_name: str
    app_insights_connection_string: str
    fabric_workspace: str
    fabric_lakehouse: str
    onelake_table: str
    onelake_schema: str
    uami_client_id: str

    def onelake_table_uri_for(
        self,
        table: str | None = None,
        schema: str | None = None,
    ) -> str:
        """Build the OneLake `abfss://` URI for an arbitrary table.

        Defaults to the configured ``onelake_table`` / ``onelake_schema``
        when arguments are omitted.
        """
        t = table or self.onelake_table
        sc = self.onelake_schema if schema is None else schema
        if _GUID_RE.match(self.fabric_lakehouse):
            artifact = self.fabric_lakehouse
        else:
            artifact = f"{self.fabric_lakehouse}.Lakehouse"
        base = (
            f"abfss://{self.fabric_workspace}@onelake.dfs.fabric.microsoft.com/"
            f"{artifact}/Tables/"
        )
        if sc:
            return f"{base}{sc}/{t}"
        return f"{base}{t}"

    @property
    def onelake_table_uri(self) -> str:
        """URI of the default configured table (`ONELAKE_TABLE`)."""
        return self.onelake_table_uri_for()


def load_settings() -> Settings:
    def req(key: str) -> str:
        val = os.getenv(key, "")
        if not val:
            raise RuntimeError(f"Missing required env var: {key}")
        return val

    return Settings(
        subscription_id=req("AZURE_SUBSCRIPTION_ID"),
        resource_group=req("AZURE_RESOURCE_GROUP"),
        location=os.getenv("AZURE_LOCATION", "eastus2"),
        aml_workspace=req("AML_WORKSPACE_NAME"),
        aml_compute_cluster=os.getenv("AML_COMPUTE_CLUSTER", "cpu-cluster"),
        key_vault_name=req("KEY_VAULT_NAME"),
        app_insights_connection_string=os.getenv("APP_INSIGHTS_CONNECTION_STRING", ""),
        fabric_workspace=req("FABRIC_WORKSPACE_NAME"),
        fabric_lakehouse=req("FABRIC_LAKEHOUSE_NAME"),
        onelake_table=req("ONELAKE_TABLE"),
        onelake_schema=os.getenv("ONELAKE_SCHEMA", ""),
        uami_client_id=req("USER_ASSIGNED_MI_CLIENT_ID"),
    )
