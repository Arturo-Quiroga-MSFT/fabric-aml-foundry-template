"""OneLake / Fabric data access helpers."""
from __future__ import annotations

import pandas as pd
from azure.identity import DefaultAzureCredential
from deltalake import DeltaTable

from .config import Settings


def _onelake_storage_options() -> dict[str, str]:
    """Build storage_options for deltalake/object_store to talk to OneLake.

    Uses DefaultAzureCredential so it works locally (az login),
    on AML compute (managed identity), and in pipelines.
    """
    cred = DefaultAzureCredential()
    # OneLake accepts an AAD bearer token scoped to storage.
    token = cred.get_token("https://storage.azure.com/.default").token
    return {
        "bearer_token": token,
        "use_fabric_endpoint": "true",
    }


def read_delta_table(
    settings: Settings,
    table: str | None = None,
    schema: str | None = None,
) -> pd.DataFrame:
    """Read a OneLake Delta table into a pandas DataFrame.

    Defaults to the table configured in ``settings`` when ``table`` is
    omitted, so existing call sites keep working.
    """
    uri = settings.onelake_table_uri_for(table=table, schema=schema)
    dt = DeltaTable(uri, storage_options=_onelake_storage_options())
    return dt.to_pandas()


__all__ = ["read_delta_table"]

