"""Copy a Fabric / OneLake table into the AML workspace as a versioned data asset.

Produces:
  - Parquet snapshot in the AML default datastore
  - An MLTable folder alongside it (so AutoML / data assets can consume it)
  - A registered AML data asset (URI_FOLDER, MLTable type)
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Data
from azure.identity import DefaultAzureCredential

from .config import Settings, load_settings
from .data import read_delta_table

MLTABLE_YAML = """\
$schema: https://azuremlschemas.azureedge.net/latest/MLTable.schema.json
type: mltable
paths:
  - file: ./data.parquet
transformations:
  - read_parquet
"""


def copy_fabric_table_to_aml(
    settings: Settings | None = None,
    asset_name: str = "contoso-poc-dataset",
    description: str = "Snapshot of the Fabric/OneLake POC dataset.",
    table: str | None = None,
    schema: str | None = None,
) -> str:
    """Read a OneLake table and register it as an AML MLTable asset.

    Defaults to the table configured in ``settings`` when ``table`` is
    omitted. Returns the asset URI (`azureml:<name>:<version>`).
    """
    s = settings or load_settings()
    df = read_delta_table(s, table=table, schema=schema)
    print(f"Read {len(df):,} rows from OneLake.")

    ml_client = MLClient(
        DefaultAzureCredential(),
        subscription_id=s.subscription_id,
        resource_group_name=s.resource_group,
        workspace_name=s.aml_workspace,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        df.to_parquet(tmp_path / "data.parquet", index=False)
        (tmp_path / "MLTable").write_text(MLTABLE_YAML)

        data_asset = Data(
            name=asset_name,
            description=description,
            path=str(tmp_path),
            type=AssetTypes.MLTABLE,
        )
        registered = ml_client.data.create_or_update(data_asset)

    asset_uri = f"azureml:{registered.name}:{registered.version}"
    print(f"Registered data asset: {asset_uri}")
    return asset_uri


if __name__ == "__main__":
    copy_fabric_table_to_aml()
