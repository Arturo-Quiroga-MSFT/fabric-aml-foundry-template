"""Register the default workspaceblobstore datastore with identity-based auth.

When an AML workspace is provisioned with a User-Assigned MI as the primary
identity (no system-assigned), AML sometimes does NOT auto-create the
`workspaceblobstore` and `workspacefilestore` datastores because the UAMI
lacks `Microsoft.Storage/storageAccounts/listkeys/action`.

Identity-based datastores avoid the need for account keys.
"""
from __future__ import annotations

import argparse

from azure.ai.ml import MLClient
from azure.ai.ml.entities import AzureBlobDatastore
from azure.identity import DefaultAzureCredential

from .config import load_settings


def ensure_workspace_blobstore(
    datastore_name: str = "workspaceblobstore",
    storage_account: str | None = None,
    container_name: str | None = None,
) -> str:
    """Ensure an identity-based AzureBlobDatastore exists on the workspace.

    If `storage_account` / `container_name` are omitted, they are discovered
    from the workspace's linked default storage account.
    """
    s = load_settings()
    ml = MLClient(
        DefaultAzureCredential(),
        subscription_id=s.subscription_id,
        resource_group_name=s.resource_group,
        workspace_name=s.aml_workspace,
    )

    if not storage_account:
        ws = ml.workspaces.get(s.aml_workspace)
        # storage_account is the full ARM ID; take the last segment
        storage_account = ws.storage_account.rsplit("/", 1)[-1]

    if not container_name:
        # AML default container follows the pattern azureml-blobstore-<workspace-guid>
        from azure.storage.blob import BlobServiceClient

        bsc = BlobServiceClient(
            f"https://{storage_account}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )
        for c in bsc.list_containers(name_starts_with="azureml-blobstore-"):
            container_name = c.name
            break
        if not container_name:
            raise RuntimeError(
                f"No azureml-blobstore-* container found on {storage_account}"
            )

    datastore = AzureBlobDatastore(
        name=datastore_name,
        description="Default workspace blob datastore (identity-based).",
        account_name=storage_account,
        container_name=container_name,
        protocol="https",
        # No credentials = identity-based access; uses the caller's AAD token
        # for SDK/CLI ops and the workspace MI for jobs.
    )
    created = ml.datastores.create_or_update(datastore)
    print(f"Datastore: {created.name}")
    print(f"  account:   {storage_account}")
    print(f"  container: {container_name}")
    print("  auth:      identity-based (no account key)")
    return created.name


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="workspaceblobstore")
    parser.add_argument("--storage-account", default=None)
    parser.add_argument("--container", default=None)
    args = parser.parse_args()
    ensure_workspace_blobstore(
        datastore_name=args.name,
        storage_account=args.storage_account,
        container_name=args.container,
    )
