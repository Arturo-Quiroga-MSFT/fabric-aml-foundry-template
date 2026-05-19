"""Register a Microsoft Fabric / OneLake lakehouse as an AML datastore.

This makes the lakehouse appear as a first-class data source in the AML Studio UI
(Data > Datastores), in addition to the copy-into-AML pattern in
`copy_fabric_to_aml.py`.

Auth model:
- Identity-based access (recommended for the POC). The AML workspace's identity
  (or the user-assigned MI we deploy in Bicep) must have at least Viewer on the
  Fabric workspace and Read on the lakehouse.
"""
from __future__ import annotations

import argparse

from azure.ai.ml import MLClient
from azure.ai.ml.entities import OneLakeArtifact, OneLakeDatastore
from azure.identity import DefaultAzureCredential

from .config import _GUID_RE, load_settings


def register_onelake_datastore(
    datastore_name: str = "fabric_onelake",
    artifact_name: str | None = None,
    description: str = "Fabric OneLake lakehouse used by the Contoso POC.",
) -> str:
    """Register a OneLake lakehouse as an AML datastore.

    `artifact_name` defaults to the lakehouse identifier from settings.
    When the lakehouse is a GUID, no `.Lakehouse` suffix is appended.
    Returns the datastore name.
    """
    s = load_settings()
    if artifact_name:
        artifact = artifact_name
    elif _GUID_RE.match(s.fabric_lakehouse):
        artifact = s.fabric_lakehouse
    else:
        artifact = f"{s.fabric_lakehouse}.Lakehouse"

    ml = MLClient(
        DefaultAzureCredential(),
        subscription_id=s.subscription_id,
        resource_group_name=s.resource_group,
        workspace_name=s.aml_workspace,
    )

    datastore = OneLakeDatastore(
        name=datastore_name,
        description=description,
        one_lake_workspace_name=s.fabric_workspace,
        artifact=OneLakeArtifact(name=artifact, type="lake_house"),
        # SDK prepends https://; pass hostname only or you get https://https://...
        endpoint="onelake.dfs.fabric.microsoft.com",
    )

    created = ml.datastores.create_or_update(datastore)
    print(f"Registered OneLake datastore: {created.name}")
    print(f"  workspace: {s.fabric_workspace}")
    print(f"  artifact:  {artifact}")
    print(
        "  Browse paths in AML with: "
        f"azureml://datastores/{created.name}/paths/Tables/<table>"
    )
    return created.name


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="fabric_onelake")
    parser.add_argument("--artifact", default=None, help="Override <lakehouse>.Lakehouse")
    args = parser.parse_args()
    register_onelake_datastore(datastore_name=args.name, artifact_name=args.artifact)
