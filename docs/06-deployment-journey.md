# Deployment Journey & Roadblock Log — May 6, 2026

> Purpose: capture every issue hit while standing up the Contoso POC test bed and the exact fix applied, so Contoso engineers (and our future selves) can reproduce the environment without re-discovering the same lessons.

Author: <author> (PSA). Session date: 2026-05-06.

## 1. Final state achieved

| Layer | Resource | Name |
|---|---|---|
| Subscription | <your-tenant> | `<your-subscription-id>` |
| Tenant | <your-tenant> | `<your-tenant-id>` |
| Resource Group | East US 2 | `<resource-group>` |
| AML workspace | UserAssigned-MI primary | `<aml-workspace-name>` |
| Storage (AML default) | HNS=false | `contosost` |
| Key Vault | RBAC-enabled | `<key-vault-name>` |
| App Insights | workspace-based | `contoso-ai` |
| Log Analytics | | `contoso-law` |
| Container Registry | Standard | `contosoacr` |
| User-Assigned MI | AML primary identity | `contoso-mi` |
| MI clientId | | `<your-mi-client-id>` |
| MI principalId | | `<your-mi-principal-id>` |
| Compute cluster | `Standard_DS3_v2`, 0–4 nodes | `cpu-cluster` |
| Compute instance | `Standard_DS3_v2` | `ci` |
| Fabric workspace | Trial capacity, East US 2 | `<your-fabric-workspace-id>` (display: `AVEPOIINT-POC`) |
| Fabric lakehouse | Schema-enabled | `<your-fabric-lakehouse-id>` (display: `contoso_poc_lh`) |
| Sample Delta table | Loaded from Fabric samples | `Tables/dbo/publicholidays` (69,557 rows) |

**Verified end-to-end**: `DefaultAzureCredential` from a local Mac reads the Delta table from OneLake into a pandas DataFrame.

## 2. Bicep deployment — what failed and why

### Issue 2.1 — `Cannot use storage with HNS enabled`

**Symptom** (first deploy attempt):

```
The AzureML workspace cannot use a storage account with hierarchical namespace enabled
```

**Cause**: The default storage account attached to an AML workspace must be a **flat (Blob) account**, not ADLS Gen2 with HNS. Our initial Bicep had `isHnsEnabled: true`.

**Fix**: Set `isHnsEnabled: false` on the default storage account in `infra/main.bicep`. (OneLake itself is HNS-backed; we don't need HNS on the AML default storage.)

### Issue 2.2 — `isHnsEnabled cannot be updated`

**Symptom** (second attempt, after fixing 2.1):

```
Property 'isHnsEnabled' cannot be updated as it is a read-only property
```

**Cause**: The storage account from the first failed deployment still existed with HNS=true. `isHnsEnabled` cannot be flipped after creation.

**Fix**: Manually delete the orphan storage account before re-deploying:

```bash
az storage account delete -n <name> -g <resource-group> --yes
```

(Later we generalized this to a full RG delete + recreate to clear all stale state.)

### Issue 2.3 — UAMI lacks `Microsoft.KeyVault/vaults/read` during workspace provisioning

**Symptom** (third attempt and beyond):

```
User assigned identity doesn't have enough permissions.
The client '<guid>' with object id '<guid>' does not have authorization to perform action
'Microsoft.KeyVault/vaults/read' over scope '.../Microsoft.KeyVault/vaults/<key-vault-name>'
```

**Cause #1 — Ordering**: The original Bicep declared role assignments **after** the AML workspace resource. ARM deployed the workspace first, the workspace tried to read its dependent KV/Storage/ACR using the UAMI, and the role assignments hadn't been created yet → 403.

**Fix**: Move all UAMI role assignments **above** the AML workspace and add explicit `dependsOn` from the workspace to each:

```bicep
resource aml '...workspaces@2024-04-01' = {
  ...
  dependsOn: [ raStorageUami, raKvUami, raAcrUami, raRgUami ]
}
```

**Cause #2 — Insufficient scope**: `Storage Blob Data Contributor` + `Key Vault Secrets User` + `AcrPull` only let the UAMI read **data plane** APIs. AML workspace provisioning needs **control plane reads** (`Microsoft.KeyVault/vaults/read` etc.) on the dependent resources.

**Fix**: Grant the UAMI **Contributor on the resource group** (covers control-plane reads on KV, Storage, ACR, App Insights all at once):

```bicep
resource raRgUami 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, uami.id, 'Contributor')
  scope: resourceGroup()
  properties: {
    principalId: uami.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      'b24988ac-6180-42a0-ab88-20f7382dd24c'  // Contributor
    )
  }
}
```

### Issue 2.4 — RBAC propagation race (the killer)

**Symptom**: Even after fixes 2.1–2.3, the AML workspace creation **still** failed with the same KV permission error. Verified that:

- `raRgUami` was successfully created (visible in deployment operations).
- The role assignment GUID was stored in ARM.
- But the principal ID in the error message did **not** match our UAMI principal ID.

**Diagnosis**:

```bash
az identity show -g <resource-group> -n contoso-mi \
  --query "{principalId:principalId, clientId:clientId}"
# principalId = <your-mi-principal-id>

# But error message shows principalId = 65a87a5e-...
```

The mismatched principal ID belonged to a **system-assigned managed identity** that AML implicitly created earlier (when our Bicep used `type: 'SystemAssigned, UserAssigned'`). Even after deleting the workspace, that system-assigned identity remained "soft-bound" to the workspace name in the AML control plane, and the next deploy attempt resurrected it without giving it RBAC.

**Fix #1 — UserAssigned-only identity**: Change the AML workspace identity block to drop `SystemAssigned`:

```bicep
identity: {
  type: 'UserAssigned'        // was: 'SystemAssigned, UserAssigned'
  userAssignedIdentities: { '${uami.id}': {} }
}
```

**Fix #2 — Rename the AML workspace** to break the soft-deleted-identity binding:

```bicep
var amlName = toLower('${namePrefix}-aml-${substring(uniq, 0, 5)}2')  // appended '2'
```

After both fixes, the workspace deployed cleanly on the next attempt.

### Issue 2.5 — Two-phase deploy pattern (defensive)

Because RBAC propagation can take 30s–5min and AML workspace provisioning makes its first KV read almost immediately, we added a `deployAml` parameter to the Bicep:

```bicep
@description('Deploy AML workspace + computes. Set false on first deploy, true on second.')
param deployAml bool = true

resource aml '...' = if (deployAml) { ... }
resource cluster '...' = if (deployAml) { ... }
resource ci '...' = if (deployAml) { ... }
resource raAmlDeveloper '...' = if (deployAml) { ... }
```

Workflow when deploying into a fresh sub/RG:

```bash
# Phase 1: identity + dependent resources + RBAC (no AML)
az deployment group create -g $RG -n phase1 \
  -f infra/main.bicep -p @infra/main.parameters.json -p deployAml=false

# Wait ~2 min for RBAC to propagate

# Phase 2: AML workspace + computes
az deployment group create -g $RG -n phase2 \
  -f infra/main.bicep -p @infra/main.parameters.json -p deployAml=true
```

For idempotent re-runs after the env is healthy, you can deploy in a single shot with `deployAml=true` (default).

## 3. Fabric tenant setup — what failed and why

### Issue 3.1 — `AADSTS500014: The service principal for resource 'powerbi/api' is disabled`

**Symptom**: Opening https://app.fabric.microsoft.com produced a portal-level auth error banner. Clicking through to provision Fabric capacity failed with `AADSTS500014`.

**Cause**: In <your-tenant> sandbox tenants, the **Power BI Service** service principal (well-known appId `00000009-0000-0000-c000-000000000000`) is disabled by default. Fabric is built on top of Power BI, so without it, no token can be issued for Fabric APIs.

**Fix**: A tenant Global Admin must enable the SP:

```bash
az login --tenant <your-tenant-id> --allow-no-subscriptions

az ad sp show --id 00000009-0000-0000-c000-000000000000 \
  --query "{id:id, displayName:displayName, accountEnabled:accountEnabled}"

# Enable via Graph (the `az ad sp update --set` form silently no-ops on this property):
SP_ID=$(az ad sp show --id 00000009-0000-0000-c000-000000000000 --query id -o tsv)
az rest --method PATCH \
  --url "https://graph.microsoft.com/v1.0/servicePrincipals/$SP_ID" \
  --headers "Content-Type=application/json" \
  --body '{"accountEnabled": true}'
```

Verify:

```bash
az ad sp show --id 00000009-0000-0000-c000-000000000000 --query accountEnabled
# true
```

Sign out / back in to the Fabric portal and retry.

### Issue 3.2 — Fabric Trial capacity region selection

**Symptom**: When activating the 60-day Fabric Trial, you must pick a region for the trial capacity, and the choice is **permanent for the trial**.

**Decision**: Pick the same region as your Azure RG (here, **East US 2**) to avoid cross-region egress costs and minimize latency when copying OneLake → AML default storage.

### Issue 3.3 — Required tenant settings (already enabled in this sandbox)

Two tenant settings must be **on** for AML to read OneLake:

| Setting | Location | State in our tenant |
|---|---|---|
| Service principals can call Fabric public APIs | Tenant settings → Developer settings | ✅ Already enabled org-wide |
| Users can access data stored in OneLake with apps external to Fabric | Tenant settings → OneLake settings | ✅ Already enabled org-wide |

If either is off, the OneLake read returns `403 AuthorizationPermissionMismatch` or no token at all.

### Issue 3.4 — Workspace role grant for the AML UAMI

**What we did**: In the Fabric workspace → **Manage access → + Add people or groups**, searched for `contoso-mi` (the user-assigned managed identity) and assigned **Contributor**.

**Why Contributor (not Viewer)**: read-only would suffice for the OneLake snapshot copy, but Contributor enables future patterns where AML writes prediction outputs back to OneLake.

## 4. Local development environment — what failed and why

### Issue 4.1 — `azureml-dataprep-native` has no arm64 macOS wheel

**Symptom**:

```
error: Distribution `azureml-dataprep-native==41.0.0` can't be installed because it doesn't
have a source distribution or wheel for the current platform
hint: You're on macOS (`macosx_26_0_arm64`), but `azureml-dataprep-native` (v41.0.0) only
has wheels for: manylinux1_x86_64, macosx_10_9_x86_64, win_amd64
```

**Cause**: `azureml-fsspec` transitively depends on `azureml-dataprep-native`, which Microsoft only ships for x86_64 Linux/macOS and Windows. Apple Silicon is not supported.

**Fix**: Drop `azureml-fsspec` from the base `pyproject.toml`. It's only needed when reading AML data assets via `fsspec://azureml/...` URIs, which we exercise from AML compute (Linux), not from the local Mac. We use `deltalake` directly for OneLake access on the laptop.

### Issue 4.2 — pyarrow-based OneLake reader can't authenticate

**Symptom**: First version of `src/data.py` used `pyarrow.dataset.dataset(uri, ...)` which silently failed to pass credentials to OneLake.

**Fix**: Switched to the `deltalake` library with an explicit AAD bearer token:

```python
from azure.identity import DefaultAzureCredential
from deltalake import DeltaTable

cred = DefaultAzureCredential()
token = cred.get_token("https://storage.azure.com/.default").token
dt = DeltaTable(
    settings.onelake_table_uri,
    storage_options={
        "bearer_token": token,
        "use_fabric_endpoint": "true",
    },
)
df = dt.to_pandas()
```

Benefits: proper Delta log handling (snapshot isolation, time travel, schema evolution) and a clean credential surface that works locally and on AML compute.

### Issue 4.3 — OneLake URI rules: GUIDs vs friendly names

**Symptom**:

```xml
<Error>
  <Code>FriendlyNameSupportDisabled</Code>
  <Message>Request Failed with WorkspaceId and ArtifactId should be either valid Guids or valid Names</Message>
</Error>
```

**Cause**: OneLake URIs have two valid forms, and you cannot mix them:

| Form | Workspace segment | Lakehouse segment |
|---|---|---|
| Friendly names | workspace **name** | `<lakehouse_name>.Lakehouse` |
| GUIDs | workspace **GUID** | `<lakehouse_guid>` (no `.Lakehouse` suffix) |

We had `FABRIC_WORKSPACE_NAME` set to a GUID and `FABRIC_LAKEHOUSE_NAME` set to a friendly name with `.Lakehouse` suffix → mixed → 400 Bad Request.

**Fix**: Both `.env.example` and `src/config.py` updated. `Settings.onelake_table_uri` now detects GUIDs via regex and omits the `.Lakehouse` suffix when both segments are GUIDs:

```python
_GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

@property
def onelake_table_uri(self) -> str:
    if _GUID_RE.match(self.fabric_lakehouse):
        artifact = self.fabric_lakehouse                # bare GUID
    else:
        artifact = f"{self.fabric_lakehouse}.Lakehouse" # friendly name + suffix
    base = (
        f"abfss://{self.fabric_workspace}@onelake.dfs.fabric.microsoft.com/"
        f"{artifact}/Tables/"
    )
    if self.onelake_schema:
        return f"{base}{self.onelake_schema}/{self.onelake_table}"
    return f"{base}{self.onelake_table}"
```

### Issue 4.4 — Schema-enabled lakehouses

**Observation**: The Fabric sample data created the `publicholidays` table under a `dbo` schema (visible in Fabric Explorer as `Tables → dbo → publicholidays`). New Fabric lakehouses default to schema-enabled mode.

**Fix**: Added `ONELAKE_SCHEMA` env var (default empty). When set, the URI inserts `Tables/<schema>/<table>` instead of `Tables/<table>`.

### Issue 4.5 — `OneLakeDatastore` registration: `Endpoint` parameter quirks

**Symptom A** (no endpoint): registration fails with

```
azure.core.exceptions.HttpResponseError: (BlankOrEmpty) Value cannot be null. (Parameter 'Endpoint')
```

**Symptom B** (endpoint set as full URL `https://onelake.dfs.fabric.microsoft.com`): registration succeeds, but AML Studio's Browse panel shows "Network error" and the artifact URL renders as `https://https://onelake.dfs.fabric.microsoft.com/...`.

**Cause**: The `OneLakeDatastore` SDK class requires `endpoint` to be set (auto-defaulting is broken in `azure-ai-ml >= 1.20`), but it **prepends** `https://` to whatever you pass — so passing a full URL produces a double scheme.

**Fix**: pass the bare hostname:

```python
OneLakeDatastore(
    name="fabric_onelake",
    one_lake_workspace_name=settings.fabric_workspace,
    artifact=OneLakeArtifact(name=settings.fabric_lakehouse, type="lake_house"),
    endpoint="onelake.dfs.fabric.microsoft.com",   # NOT https://onelake...
)
```

If you've already registered with the bad endpoint, delete and re-register:

```python
ml.datastores.delete("fabric_onelake")
```

### Issue 4.6 — `workspaceblobstore` not auto-created (UAMI-only workspaces)

**Symptom**: `ml_client.data.create_or_update(...)` fails with:

```
azure.ai.ml.exceptions.MlException: Could not find datastore: workspaceblobstore
```

`ml.datastores.list()` shows only the datastores you registered explicitly — no `workspaceblobstore`, no `workspacefilestore`.

**Root cause**: When the AML workspace is created with **UserAssigned-only** primary
identity, AML's auto-provisioning of the default datastores can be skipped. The legacy
auto-creation flow uses account keys and requires
`Microsoft.Storage/storageAccounts/listkeys/action`, which the UAMI typically does not
have. Result: the storage account and the `azureml-blobstore-<workspace-guid>`
container exist, but no datastore record points at them.

**Fix**: Register `workspaceblobstore` manually with **identity-based** auth
(no account keys needed). See `src/bootstrap_aml_datastores.py`:

```python
from azure.ai.ml.entities import AzureBlobDatastore
ml.datastores.create_or_update(AzureBlobDatastore(
    name="workspaceblobstore",
    account_name="<aml-default-storage>",
    container_name="azureml-blobstore-<workspace-guid>",  # auto-created by AML
    protocol="https",
    # No credentials => identity-based access
))
```

**Side requirement**: Whoever uploads data assets from the laptop also needs
`Storage Blob Data Contributor` on the AML default storage account. The UAMI
already has it (granted by Bicep `raStorageUami`), but the developer principal
typically does not. Grant it once:

```bash
az role assignment create \
    --assignee-object-id $(az ad signed-in-user show --query id -o tsv) \
    --assignee-principal-type User \
    --role "Storage Blob Data Contributor" \
    --scope $(az storage account show -g <rg> -n <aml-default-storage> --query id -o tsv)
```

After this, `ml.data.create_or_update(...)` uploads succeed and the asset
appears under **Data → Data assets** in AML Studio.

### Issue 4.7 — `workspaceartifactstore` also missing (job artifacts/logs fail)

**Symptom**: After fixing Issue 4.6, an AML `command` job starts and reaches
`Running`, then fails immediately. `ml.jobs.download(name=..., all=False)`
returns:

```
azure.core.exceptions.ResourceNotFoundError: (UserError)
Could not find datastore: workspaceartifactstore.
```

**Root cause**: Same UAMI / `listKeys` gap as Issue 4.6, but for the **second**
default datastore. AML uses `workspaceblobstore` for data assets and
`workspaceartifactstore` for job logs/artifacts. The artifact store points at
the auto-created `azureml` container (not `azureml-blobstore-<guid>`).

**Fix**: Register it the same way:

```bash
uv run python -m src.bootstrap_aml_datastores \
    --name workspaceartifactstore \
    --storage-account contosost \
    --container azureml
```

After this, jobs complete and `ml.jobs.download(...)` works.

### Issue 4.8 — sklearn `Unknown label type: unknown` after MLTable round-trip

**Symptom**: Local training works; the same code submitted as an AML
`command` job fails inside `RandomForestClassifier.fit()`:

```
ValueError: Unknown label type: unknown. Maybe you are trying to fit a
classifier, which expects discrete classes on a regression target with
continuous values.
```

**Root cause**: When pandas writes a column containing a mix of `bool` and
`None` to parquet (as MLTable does), the column comes back as `dtype=object`
holding `True`/`False`/`None` Python objects. After `dropna`, sklearn's
`check_classification_targets` cannot infer the label type and rejects it.

**Fix**: In `src/train.py`, explicitly cast object/bool target columns to
`str` before fitting:

```python
if df[target].dtype == object:
    df[target] = df[target].astype(str)
elif pd.api.types.is_bool_dtype(df[target]):
    df[target] = df[target].astype(str)
```

### Issue 4.9 — Managed online endpoint creation: opaque `InternalServerError` with explicit UAMI

**Symptom**: Creating a `ManagedOnlineEndpoint` and explicitly passing
`IdentityConfiguration(type='user_assigned', user_assigned_identities=[...])`
together with `auth_mode='key'` returns:

```
(InternalServerError) An internal server error occurred. Please try again.
```

No useful detail in the response body. Switching to `auth_mode='aml_token'`
(while still passing the explicit UAMI) finally surfaces the underlying
error: `FailedIdentityOperation`.

**Root cause**: On a UAMI-only AML workspace where
`systemDatastoresAuthMode=accesskey` (the default), the MFE backend tries
to resolve the endpoint's UAMI against subscription-level identity APIs and
fails. The 500 hides the real error.

**Workaround that worked**: omit the explicit identity entirely and let the
endpoint default to a **system-assigned** managed identity, with
`auth_mode='aml_token'`:

```python
ep = ManagedOnlineEndpoint(name='contoso-endpoint', auth_mode='aml_token')
ml.online_endpoints.begin_create_or_update(ep).result()
```

The endpoint provisions Succeeded, and AML auto-creates a system-assigned
MI (visible via `ml.online_endpoints.get(...).identity.principal_id`). Also
patch the workspace to `systemDatastoresAuthMode=identity` first:

```bash
az rest --method PATCH \
  --url "https://management.azure.com/subscriptions/$SUB/resourceGroups/$RG/providers/Microsoft.MachineLearningServices/workspaces/$WS?api-version=2024-04-01" \
  --body '{"properties":{"systemDatastoresAuthMode":"identity"}}'
```

### Issue 4.10 — Endpoint MI needs RBAC on Storage + ACR before deployment

**Symptom**: First `ManagedOnlineDeployment` create attempt fails after
several minutes with:

```
ImageBuildFailure / OnlineImageAndModelPrepError
```

with inner error `ForbiddenByRbac` on the Key Vault, and the deployment
moves to `provisioning_state=Failed`.

**Root cause**: The endpoint's system-assigned MI has **no roles by
default**. AML's image-prep flow needs that MI to:

1. Read model artifacts from the workspace storage account.
2. Pull the inference image from ACR after the build.
3. Read/write transient secrets in the workspace Key Vault during build.

**Fix**: After the endpoint is created, grant the endpoint's principal_id:

```bash
EP_PID=$(uv run python -c "
from azure.ai.ml import MLClient; from azure.identity import DefaultAzureCredential
from src.config import load_settings; s=load_settings()
ml=MLClient(DefaultAzureCredential(), s.subscription_id, s.resource_group, s.aml_workspace)
print(ml.online_endpoints.get('contoso-endpoint').identity.principal_id)
")
SA_ID=$(az storage account show -g $RG -n contosost --query id -o tsv)
ACR_ID=$(az acr show -n contosoacr -g $RG --query id -o tsv)

az role assignment create --assignee-object-id $EP_PID \
  --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Reader" --scope $SA_ID
az role assignment create --assignee-object-id $EP_PID \
  --assignee-principal-type ServicePrincipal \
  --role "AcrPull" --scope $ACR_ID
```

> Note: `az ml online-endpoint show --query identity.principalId -o tsv`
> returns **empty** — the CLI doesn't surface this field. Use the Python
> SDK or `az rest` to extract `principal_id`.

### Issue 4.11 — Workspace UAMI needs `Key Vault Secrets Officer` for image build

**Symptom**: Even after fixing Issue 4.10, the deployment image-build job
still fails with:

```
KeyVaultErrorException: Forbidden
Caller: appid=<workspace-UAMI-clientId>
Action: 'Microsoft.KeyVault/vaults/secrets/setSecret/action'
Resource: '.../<key-vault-name>/secrets/<guid>'
```

Notice the **caller is the workspace UAMI** (`<your-mi-principal-id>`), not the
endpoint MI. The image-prep flow runs under the workspace identity, not the
endpoint identity, and needs to **write** transient secrets — `Key Vault
Secrets User` (read-only) is not enough.

**Root cause**: Bicep originally granted the workspace UAMI only `Key Vault
Secrets User`. The AML image-prep flow uses `setSecret` to stash temporary
build artifacts.

**Fix**: Grant the workspace UAMI `Key Vault Secrets Officer` on the
workspace KV:

```bash
KV_ID=$(az keyvault show -n <key-vault-name> -g $RG --query id -o tsv)
az role assignment create \
  --assignee-object-id <your-mi-principal-id> \
  --assignee-principal-type ServicePrincipal \
  --role "Key Vault Secrets Officer" --scope $KV_ID
```

Then **delete the failed deployment** (a failed `blue` cannot be updated
in place — you must `begin_delete` and recreate) and resubmit. Image build
runs ~6 minutes (visible as a child job `imgbldrun_*` under the
`prepare_image` experiment), then the model+image are downloaded to a
`Standard_DS2_v2` VM and the scoring container starts.

**Bicep follow-up**: update `infra/main.bicep` to grant the workspace UAMI
`Key Vault Secrets Officer` instead of `Key Vault Secrets User` so this
isn't re-discovered on the next clean deploy.

### Issue 4.12 — MLflow no-code online deploy: missing `azureml-ai-monitoring`

**Symptom**: After Issues 4.9–4.11 are fixed, the deployment image builds,
the container starts, then crashes immediately:

```
File "/var/mlflow_resources/mlflow_score_script.py", line 20, in <module>
    from azureml.ai.monitoring import Collector
ModuleNotFoundError: No module named 'azureml'
```

`gunicorn` reports `Worker failed to boot. Reason: Worker failed to boot.`
and the deployment moves to `Failed`.

**Root cause**: AML's auto-generated MLflow scoring script (`mlflow_score_script.py`)
imports `azureml.ai.monitoring.Collector` for data collection. The MLflow
model's recorded environment (`conda.yaml` + `requirements.txt`) does not
include `azureml-ai-monitoring`, because it was never an `mlflow.sklearn`
training dependency. The auto-built deploy environment therefore lacks it.

**Fix**: download the model artifacts, append `azureml-ai-monitoring` to
both `conda.yaml` and `requirements.txt`, and re-register as a new model
version. Helper: `src/patch_mlflow_model.py`:

```bash
uv run python -m src.patch_mlflow_model \
    --name contoso-poc-model --version 1 \
    --add-package azureml-ai-monitoring \
    --description "v2: added azureml-ai-monitoring for online deploy"
```

Then redeploy from the new version (the existing `blue` must be deleted
first; see Issue 4.11):

```bash
uv run python -m src.deploy_online_endpoint deploy --model-version 2
```

**Better long-term fix**: log the dependency at training time so the model
ships with it baked in:

```python
import mlflow
mlflow.sklearn.log_model(
    model,
    artifact_path="model",
    pip_requirements=[..., "azureml-ai-monitoring"],
)
```

### Issue 4.13 — MLflow online endpoint payload format

**Symptom**: With a deployed and healthy endpoint, the first scoring call
returns 500 with:

```
ValueError: Expected 2D array, got scalar array instead:
array={'columns': array([...]), 'data': array([...])}.
```

The `azureml_inference_server` deserialized the request but passed the raw
dict (the entire `input_data` value) into the sklearn pipeline instead of
unwrapping it into a DataFrame.

**Root cause**: AML's MLflow scoring wrapper expects pandas
`split` orientation, which requires **all three** of `columns`, `index`,
and `data`. Sending only `{"columns": ..., "data": ...}` is silently
treated as opaque JSON and forwarded as-is.

A second call with everything as strings (e.g. `"1973"` instead of `1973`)
worked structurally but produced wrong predictions because the
`OneHotEncoder`/`StandardScaler` pipeline was trained on numeric
`date_year/month/day/dayofweek` columns.

**Fix**: emit the canonical payload — see `src/build_sample_request.py`:

```json
{
  "input_data": {
    "columns": ["countryOrRegion", "holidayName", "normalizeHolidayName",
                "date_year", "date_month", "date_day", "date_dayofweek"],
    "index": [0, 1, 2],
    "data": [
      ["New Zealand", "New Year's Day", "New Year's Day", 1973, 1, 1, 0],
      ["Ireland",     "New Year's Day", "New Year's Day", 1974, 1, 1, 1],
      ["Ireland",     "New Year's Day", "New Year's Day", 1978, 1, 1, 6]
    ]
  }
}
```

Successful response:

```json
["True", "True", "True"]
```

`src/build_sample_request.py` preserves numeric dtypes by converting
`numpy.int64`/`numpy.float64` to native Python `int`/`float` before
`json.dumps` (otherwise pandas `astype(object)` round-trips ints to
strings).

## 5. Updated patterns / conventions for Contoso engineers

### 5.1 Bicep authoring rules (AML workspaces)

1. AML default storage **must** have `isHnsEnabled: false`. OneLake is your HNS data lake; the AML default storage is for run artifacts and is plain Blob.
2. The UAMI used as `primaryUserAssignedIdentity` needs **Contributor on the RG** (or equivalent control-plane reads on each dependent resource). Data-plane roles alone are insufficient.
3. All UAMI role assignments must be **declared before** the AML workspace and the workspace must `dependsOn:` them.
4. Use **UserAssigned-only** identity (`type: 'UserAssigned'`). Avoid `SystemAssigned, UserAssigned` mixed mode — it creates a hidden system-assigned principal that has no RBAC and causes confusing failures.
5. If a deploy fails mid-flight and you need to re-deploy, prefer **deleting the RG** over patching state. AML workspaces and storage accounts retain hidden state that ARM cannot fully overwrite.
6. For brand-new subs, use the **two-phase deploy** (`deployAml=false` → wait → `deployAml=true`) to avoid RBAC-propagation races.

### 5.2 Fabric tenant prerequisites

| Required | Setting | Rationale |
|---|---|---|
| ✅ | Power BI Service SP `accountEnabled=true` | Without it, no Fabric tokens can be issued |
| ✅ | "Service principals can call Fabric public APIs" | UAMI is a service principal |
| ✅ | "Users can access data stored in OneLake with apps external to Fabric" | AML compute is an external app |
| ✅ | Fabric Trial or F-SKU capacity in the same region as AML | Cost + latency |

### 5.3 OneLake URI cheatsheet

```
abfss://<WORKSPACE>@onelake.dfs.fabric.microsoft.com/<ARTIFACT>/Tables/[<SCHEMA>/]<TABLE>

WORKSPACE = workspace name OR workspace GUID
ARTIFACT  = "<lakehouse_name>.Lakehouse"  (when WORKSPACE is a name)
          = "<lakehouse_guid>"            (when WORKSPACE is a GUID)
SCHEMA    = "dbo" for schema-enabled lakehouses; omit otherwise
```

### 5.4 Python deps for OneLake on Apple Silicon

| Use case | Package | Notes |
|---|---|---|
| Read OneLake Delta tables (laptop or AML) | `deltalake>=0.20` | Bring your own AAD bearer token |
| AML SDK v2 | `azure-ai-ml>=1.20` | Cross-platform |
| AML data asset URIs (`azureml://`) | `azureml-fsspec` | **Linux/x86_64 only** — install only on AML compute |
| MLflow integration | `azureml-mlflow` | Cross-platform |

### 5.5 Managed online endpoints on UAMI-only workspaces

1. **Patch first**: set `systemDatastoresAuthMode=identity` on the workspace before creating any endpoints (REST PATCH, api-version `2024-04-01`).
2. **Auth**: prefer `auth_mode='aml_token'` over `'key'`. Key auth requires the endpoint MI to read keys from the workspace KV at scoring time, adding another moving part.
3. **Identity**: do **not** pass an explicit `IdentityConfiguration` for the endpoint — let AML default to a system-assigned MI. Explicit UAMI assignment fails with an opaque 500 on UAMI-only workspaces.
4. **Three RBAC grants required before deployment can succeed**:
   - Endpoint system MI → `Storage Blob Data Reader` on the workspace storage account
   - Endpoint system MI → `AcrPull` on the workspace ACR
   - Workspace UAMI → `Key Vault Secrets Officer` on the workspace KV (Secrets User is **not** enough)
5. **Read principal_id via SDK**, not CLI: `ml.online_endpoints.get(name).identity.principal_id`. The az CLI `--query identity.principalId` returns empty.
6. **Failed deployments cannot be updated in place** — `begin_delete` then recreate.
7. **Expect ~6 min image build + ~3 min container start** for sklearn MLflow models on `Standard_DS2_v2`. Watch the `prepare_image` experiment for the `imgbldrun_*` child job.
8. **Log `azureml-ai-monitoring` at training time** so the model ships with the dependency baked in (avoids the post-hoc `patch_mlflow_model.py` step):

   ```python
   mlflow.sklearn.log_model(model, "model",
       pip_requirements=[..., "azureml-ai-monitoring"])
   ```

9. **Scoring payload format** — AML's MLflow wrapper requires `input_data` with **all three** of `columns`, `index`, and `data`. Use `src/build_sample_request.py` to generate it. Preserve numeric dtypes (don't let pandas turn ints into strings).

## 6. Open items / next steps

1. Run `notebooks/00b-register-onelake-datastore.ipynb` to register the OneLake path as an AML datastore so it appears in AML Studio → Data → Datastores.
2. Run `notebooks/01a-copy-fabric-to-aml.ipynb` to materialize an MLTable snapshot in the AML default datastore — this isolates training from Fabric capacity availability.
3. Run `notebooks/02-sklearn-training.ipynb` on `cpu-cluster` to validate the MLflow + sklearn path.
4. Deploy a managed online endpoint via `notebooks/03-deploy-online-endpoint.ipynb`.
5. Wire the Foundry agent (`foundry-agent/`) to call the endpoint and emit traces to App Insights (`contoso-ai`).
6. Add a CI workflow in `.github/workflows/` that runs `ruff` + a Bicep what-if on PRs.

## 7. Useful CLI snippets

```bash
# Verify deployed UAMI identity ↔ RBAC
PRINCIPAL=$(az identity show -g <resource-group> -n contoso-mi --query principalId -o tsv)
az role assignment list --assignee-object-id $PRINCIPAL --assignee-principal-type ServicePrincipal --all -o table

# Smoke-test OneLake read from laptop
uv run python -c "
from src.config import load_settings
from src.data import read_delta_table
s = load_settings()
print('URI:', s.onelake_table_uri)
df = read_delta_table(s)
print('shape:', df.shape); print(df.head())
"

# Capture deploy outputs
az deployment group show -g <resource-group> -n contoso-phase2b \
  --query 'properties.outputs' -o json
```
