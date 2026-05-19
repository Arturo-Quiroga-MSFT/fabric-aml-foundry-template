#!/usr/bin/env bash
#
# bootstrap-github-actions-oidc.sh
#
# Idempotent bootstrap for GitHub Actions -> Azure deployments via OIDC.
# Creates (or reuses) an Entra app + service principal, adds federated
# credentials for one or more refs/branches/PRs, grants the required RBAC
# on the target ACR and resource group, and finally writes the matching
# secrets + variables into the GitHub repository via the `gh` CLI.
#
# Intended for the Contoso POC MCP server deployment workflow at
#   .github/workflows/mcp-server-containerapps-deploy.yml
# but the script is parameterized so it can be reused for similar setups.
#
# Pre-reqs:
#   - az CLI logged in to the right subscription (`az login` + `az account set`)
#   - gh CLI logged in with `repo` scope (`gh auth status`)
#   - You are an Owner (or have permission) on the target RG/ACR so role
#     assignments can be created.
#
# Usage:
#   ./scripts/bootstrap-github-actions-oidc.sh \
#       --repo <github-user>/fabric-aml-foundry-template \
#       --resource-group <resource-group> \
#       --acr-name contosoacr \
#       --app-name github-actions-contoso-mcp-deploy \
#       --branch feat-aca-otel --branch main --pull-request
#
# All options have sensible defaults — the above is what was used for this repo.
#
set -euo pipefail

# ----- Defaults (override via CLI flags) -------------------------------------
REPO="<github-user>/fabric-aml-foundry-template"
RESOURCE_GROUP="<resource-group>"
ACR_NAME="contosoacr"
APP_NAME="github-actions-contoso-mcp-deploy"
BRANCHES=()
INCLUDE_PR=false

# ----- Arg parsing -----------------------------------------------------------
usage() {
    sed -n '2,40p' "$0"
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repo)            REPO="$2"; shift 2 ;;
        --resource-group)  RESOURCE_GROUP="$2"; shift 2 ;;
        --acr-name)        ACR_NAME="$2"; shift 2 ;;
        --app-name)        APP_NAME="$2"; shift 2 ;;
        --branch)          BRANCHES+=("$2"); shift 2 ;;
        --pull-request)    INCLUDE_PR=true; shift ;;
        -h|--help)         usage 0 ;;
        *)                 echo "Unknown flag: $1" >&2; usage 2 ;;
    esac
done

# Default to main + feat-aca-otel if no --branch was passed.
if [[ ${#BRANCHES[@]} -eq 0 ]]; then
    BRANCHES=(main feat-aca-otel)
fi

# ----- Tool checks -----------------------------------------------------------
command -v az >/dev/null || { echo "az CLI not found" >&2; exit 1; }
command -v gh >/dev/null || { echo "gh CLI not found" >&2; exit 1; }

echo "==> Verifying az + gh auth"
az account show --query "{sub:id,tenant:tenantId,user:user.name}" -o table
gh auth status -h github.com >/dev/null || { echo "gh not authenticated" >&2; exit 1; }

# ----- Discover subscription + tenant ---------------------------------------
SUB_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
RG_ID="/subscriptions/$SUB_ID/resourceGroups/$RESOURCE_GROUP"

echo "==> Resolving ACR"
ACR_ID="$(az acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"
ACR_LOGIN_SERVER="$(az acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" --query loginServer -o tsv)"
echo "    ACR_ID=$ACR_ID"

# ----- Entra app + service principal (idempotent) ---------------------------
echo "==> Ensuring Entra app: $APP_NAME"
APP_ID="$(az ad app list --display-name "$APP_NAME" --query "[0].appId" -o tsv)"
if [[ -z "$APP_ID" ]]; then
    APP_ID="$(az ad app create --display-name "$APP_NAME" --query appId -o tsv)"
    echo "    Created app: $APP_ID"
else
    echo "    Reusing existing app: $APP_ID"
fi

echo "==> Ensuring service principal for app"
SP_OID="$(az ad sp list --filter "appId eq '$APP_ID'" --query "[0].id" -o tsv)"
if [[ -z "$SP_OID" ]]; then
    SP_OID="$(az ad sp create --id "$APP_ID" --query id -o tsv)"
    echo "    Created SP: $SP_OID"
else
    echo "    Reusing existing SP: $SP_OID"
fi

# ----- Federated credentials -------------------------------------------------
add_fic() {
    local name="$1"
    local subject="$2"

    if az ad app federated-credential list --id "$APP_ID" --query "[?name=='$name']" -o tsv | grep -q .; then
        echo "    FIC already exists: $name"
        return
    fi

    local body
    body="$(cat <<EOF
{
  "name": "$name",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "$subject",
  "audiences": ["api://AzureADTokenExchange"]
}
EOF
)"
    az ad app federated-credential create --id "$APP_ID" --parameters "$body" >/dev/null
    echo "    Created FIC: $name -> $subject"
}

echo "==> Configuring federated credentials"
for branch in "${BRANCHES[@]}"; do
    safe_name="github-$(echo "$branch" | tr '/' '-')"
    add_fic "$safe_name" "repo:${REPO}:ref:refs/heads/${branch}"
done

if [[ "$INCLUDE_PR" == true ]]; then
    add_fic "github-pull-request" "repo:${REPO}:pull_request"
fi

# ----- RBAC ------------------------------------------------------------------
ensure_role() {
    local role="$1"
    local scope="$2"

    if az role assignment list --assignee "$SP_OID" --scope "$scope" \
        --query "[?roleDefinitionName=='$role']" -o tsv | grep -q .; then
        echo "    Role already assigned: '$role' on $scope"
        return
    fi

    az role assignment create \
        --assignee-object-id "$SP_OID" \
        --assignee-principal-type ServicePrincipal \
        --role "$role" \
        --scope "$scope" >/dev/null
    echo "    Granted '$role' on $scope"
}

echo "==> Assigning RBAC"
ensure_role "AcrPush" "$ACR_ID"
ensure_role "Container Apps Contributor" "$RG_ID"

# ----- GitHub secrets + variables -------------------------------------------
echo "==> Writing GitHub secrets + variables to $REPO"
gh secret set AZURE_CLIENT_ID       --repo "$REPO" --body "$APP_ID"      >/dev/null
gh secret set AZURE_TENANT_ID       --repo "$REPO" --body "$TENANT_ID"   >/dev/null
gh secret set AZURE_SUBSCRIPTION_ID --repo "$REPO" --body "$SUB_ID"      >/dev/null

gh variable set AZURE_RESOURCE_GROUP --repo "$REPO" --body "$RESOURCE_GROUP"  >/dev/null
gh variable set ACR_NAME             --repo "$REPO" --body "$ACR_NAME"        >/dev/null
gh variable set ACR_LOGIN_SERVER     --repo "$REPO" --body "$ACR_LOGIN_SERVER" >/dev/null

echo
echo "==> Done."
echo
echo "Repo:            $REPO"
echo "App (clientId):  $APP_ID"
echo "Tenant:          $TENANT_ID"
echo "Subscription:    $SUB_ID"
echo "Resource group:  $RESOURCE_GROUP"
echo "ACR:             $ACR_NAME ($ACR_LOGIN_SERVER)"
echo
echo "Still pending — set once the Azure Container App exists:"
echo "  gh variable set AZURE_CONTAINER_APP_NAME --repo $REPO --body <app-name>"
echo "  gh variable set AZURE_CONTAINER_NAME     --repo $REPO --body <container-name>"
