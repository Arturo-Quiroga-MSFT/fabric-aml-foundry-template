# Runbook — Connect Microsoft Fabric (OneLake) to Azure ML

> Owner: **<author>**. Goal: prove the end-to-end Fabric ⇄ Azure ML connectivity story so Contoso engineers can reproduce it. Pair this runbook with screenshots from each step as you execute.

## 0. Prerequisites

- Azure subscription where you can create resource groups and role assignments.
- Microsoft Fabric tenant with capacity to assign (F2 / trial works).
- Your Entra **object ID** and **UPN**:

  ```bash
  az ad signed-in-user show --query '{id:id, upn:userPrincipalName}'
  ```

- Azure CLI ≥ 2.60 with Bicep installed.

## 1. Deploy the Azure side

```bash
RG=<resource-group>
LOC=eastus2
az group create -n "$RG" -l "$LOC"

# Edit infra/main.parameters.json with your objectId + UPN, then:
az deployment group create \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters @infra/main.parameters.json
```

Capture from the deployment outputs:

| Output | Use |
|--------|-----|
| `amlWorkspaceName` | `.env` → `AML_WORKSPACE_NAME` |
| `keyVaultName` | `.env` → `KEY_VAULT_NAME` |
| `managedIdentityClientId` | `.env` → `USER_ASSIGNED_MI_CLIENT_ID` |
| `managedIdentityPrincipalId` | Used in step 4 (Fabric workspace role assignment) |

> **Screenshot:** Resource group view showing all resources.

## 2. Create the Fabric workspace + lakehouse

1. Open https://app.fabric.microsoft.com.
2. **Workspaces → New workspace** → name it (e.g., `contoso-poc-ws`) and assign a **capacity** (F2 or Trial).
3. Inside the workspace: **+ New → Lakehouse** → name it (e.g., `contoso_poc_lh`).
4. Under the Lakehouse → **Get data → Upload files** (or **Load to tables**) and load a sample dataset (<author> will pick the file). Confirm a Delta table appears under **Tables**.

> **Screenshot:** Lakehouse view with at least one Delta table under `Tables/`.

Record:

- `FABRIC_WORKSPACE_NAME` = workspace name (or workspace GUID — both work in the OneLake URI)
- `FABRIC_LAKEHOUSE_NAME` = lakehouse name (without `.Lakehouse`)
- `ONELAKE_TABLE` = table name

## 3. Grant access to the AML managed identity

Two grants are needed:

### 3a. Tenant setting (one-time, by Fabric admin)

In the Fabric **Admin portal → Tenant settings**, ensure the following is **enabled** for the relevant security group containing the AML workspace MI (or for the whole org for the POC):

- **Service principals can use Fabric APIs**
- **Users can access data stored in OneLake with apps external to Fabric** (or the equivalent "OneLake — external app access" toggle in your tenant)

> Without these, AML cannot read OneLake even with role assignments.

### 3b. Workspace role

In the Fabric workspace → **Manage access → + Add people or groups**:

- Add the **user-assigned managed identity** by name (`contoso-mi-*`) as **Contributor** (Viewer is enough for read-only; Contributor gives you write back to OneLake too).
- Also add yourself (UPN) as **Admin** so you can troubleshoot.

> **Screenshot:** Manage access panel showing the MI as Contributor.

## 4. Wire local environment

```bash
cp .env.example .env
# fill values from steps 1–3, then:
uv sync   # or: pip install -e .
```

Authenticate locally:

```bash
az login --tenant <your-tenant-id>
```

## 5. Verify direct OneLake read

Open and run:

- [../notebooks/00-fabric-onelake-connectivity.ipynb](../notebooks/00-fabric-onelake-connectivity.ipynb)

Expected: row count + `df.head()` for the Delta table. If this fails, recheck step 3a (tenant settings).

> **Screenshot:** notebook output showing a populated DataFrame.

## 6. Register OneLake as an AML datastore

Open and run:

- [../notebooks/00b-register-onelake-datastore.ipynb](../notebooks/00b-register-onelake-datastore.ipynb)

Then in **AML Studio → Data → Datastores**, confirm the new `fabric_onelake` datastore is listed and you can browse to `Tables/<your-table>` from the Studio UI.

> **Screenshot:** AML Studio Datastores page with `fabric_onelake` visible.

## 7. Copy a snapshot into AML as a versioned MLTable data asset

Open and run:

- [../notebooks/01a-copy-fabric-to-aml.ipynb](../notebooks/01a-copy-fabric-to-aml.ipynb)

In **AML Studio → Data → Data assets**, confirm `contoso-poc-dataset` v1 appears with type **MLTable**.

> **Screenshot:** Data asset detail page showing rows + schema.

## 8. Sanity check — load the data asset back

```python
from azure.ai.ml import MLClient
from azure.identity import DefaultAzureCredential
import mltable
from src.config import load_settings

s = load_settings()
ml = MLClient(DefaultAzureCredential(), s.subscription_id, s.resource_group, s.aml_workspace)
asset = ml.data.get(name="contoso-poc-dataset", version="1")

tbl = mltable.load(asset.path)   # Or use uri: f"azureml:{asset.name}:{asset.version}"
print(tbl.to_pandas_dataframe().head())
```

## 9. What "done" looks like for this track

- [ ] Bicep deployed cleanly into `<resource-group>`.
- [ ] Fabric workspace + lakehouse + sample Delta table exist.
- [ ] Tenant settings allow external app access to OneLake.
- [ ] AML MI is Contributor on the Fabric workspace.
- [ ] `00-fabric-onelake-connectivity.ipynb` reads the table.
- [ ] `00b-register-onelake-datastore.ipynb` registers the datastore and it shows in AML Studio.
- [ ] `01a-copy-fabric-to-aml.ipynb` produces a versioned MLTable data asset.
- [ ] Screenshots captured and added to `docs/screenshots/`.

## Troubleshooting

> See [06-deployment-journey.md](06-deployment-journey.md) for the full set of issues we hit on 2026-05-06 (Bicep RBAC race, Power BI SP disabled, OneLake URI rules, Apple Silicon dep issues).

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `403 AuthorizationPermissionMismatch` from OneLake | Tenant setting blocks external app access OR MI not on workspace | Re-check 3a + 3b |
| `OneLakeArtifact` import error | Old `azure-ai-ml` SDK | `uv pip install -U "azure-ai-ml>=1.20"` |
| `DefaultAzureCredential` picks wrong account | Multiple `az` accounts | `az account set -s <sub-id>` and/or `AZURE_TENANT_ID` env var |
| Table not visible in AML Datastore browser | Datastore points to wrong artifact name | Artifact must be `<lakehouse>.Lakehouse` (note the `.Lakehouse` suffix) |
| Pandas read returns 0 rows | Reading parent folder; need `Tables/<name>` | Update `ONELAKE_TABLE` |
| `FriendlyNameSupportDisabled` 400 | Mixed GUID + friendly-name in URI | Use both names OR both GUIDs; `src/config.py` handles this if you set them consistently |
| `AADSTS500014: powerbi/api is disabled` in Fabric portal | Power BI Service SP disabled in tenant | Enable via Graph PATCH (see doc 06 §3.1) |
| AML workspace deploy: `Microsoft.KeyVault/vaults/read` denied | UAMI lacks RG Contributor or RBAC hasn't propagated | See doc 06 §2.3–2.4; use two-phase deploy |
| `azureml-dataprep-native` no wheel for arm64 macOS | `azureml-fsspec` transitively requires it | Don't install `azureml-fsspec` on Apple Silicon; use `deltalake` directly (see doc 06 §4.1) |
