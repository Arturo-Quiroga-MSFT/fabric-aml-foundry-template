# Infrastructure (Bicep)

Provisions the POC test bed. See [../docs/02-architecture.md](../docs/02-architecture.md) for the architecture and component overview.

## What it deploys

- User-assigned managed identity (`*-mi-*`)
- Storage account (ADLS Gen2, HNS) — AML default storage
- Key Vault (RBAC mode)
- Log Analytics workspace + Application Insights
- Azure Container Registry (Basic)
- Azure ML workspace
- AML compute cluster (`cpu-cluster`, autoscale 0→4, `Standard_DS3_v2`)
- AML compute instance (`ci-*`, `Standard_DS3_v2`, assigned to you)
- Role assignments (UAMI: Storage Blob Data Contributor, Key Vault Secrets User, AcrPull; you: AzureML Data Scientist, Key Vault Secrets Officer)

## Out of scope (do manually)

- **Microsoft Fabric capacity, workspace, lakehouse** — provision in the Fabric portal (or via separate Fabric IaC). Then grant the UAMI **Contributor** on the Fabric workspace.
- Online endpoint + deployment — created from a notebook so the model artifact exists first.
- Monitoring jobs and Workbook — added in a later phase from notebooks / a JSON workbook template.

## Prerequisites

- Azure CLI ≥ 2.60 with Bicep installed (`az bicep install`)
- Permission to create resource groups and role assignments in the target subscription
- Your Entra **object ID** and **UPN**:

  ```bash
  az ad signed-in-user show --query '{objectId:id, upn:userPrincipalName}'
  ```

## Deploy

```bash
RG=<resource-group>
LOC=eastus2

az group create -n "$RG" -l "$LOC"

# Edit infra/main.parameters.json first to fill in developerPrincipalId + computeInstanceOwnerUpn

az deployment group create \
  --resource-group "$RG" \
  --template-file infra/main.bicep \
  --parameters @infra/main.parameters.json
```

## Post-deployment

1. In the **Fabric portal**, create a workspace bound to a Fabric capacity (F2 or trial), create a Lakehouse, and add the UAMI as a **Contributor** on the workspace.
2. From the AML workspace, open the compute instance and clone this repo into the user folder.
3. Run [../notebooks/00-fabric-onelake-connectivity.ipynb](../notebooks/00-fabric-onelake-connectivity.ipynb) to verify OneLake access.

## Teardown

```bash
az group delete -n "$RG" --yes --no-wait
```
