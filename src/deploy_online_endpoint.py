"""Manage the Contoso POC managed online endpoint deployment.

Subcommands:
    create-endpoint   Create the endpoint (idempotent). Uses aml_token + default
                      system-assigned identity. Workspace must already have
                      systemDatastoresAuthMode=identity.
    grant-rbac        Grant the endpoint's system-assigned MI the RBAC required
                      to pull the model + inference image (run after create).
    deploy            Blue/green deploy: create the inactive color from
                      --model-version, shift traffic to it, then delete the
                      previously-live color. Zero-downtime.
    status            Print endpoint + deployment status.
    invoke            Send a sample scoring request from a JSON file.

Examples:
    uv run python -m src.deploy_online_endpoint create-endpoint
    uv run python -m src.deploy_online_endpoint create-endpoint --use-case nyctaxi
    uv run python -m src.deploy_online_endpoint grant-rbac
    uv run python -m src.deploy_online_endpoint deploy --use-case nyctaxi --model-version 2
    uv run python -m src.deploy_online_endpoint status
    uv run python -m src.deploy_online_endpoint invoke --request data/sample_request.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.entities import ManagedOnlineDeployment, ManagedOnlineEndpoint
from azure.identity import DefaultAzureCredential

from src.config import load_settings

ENDPOINT_NAME = "contoso-endpoint"
MODEL_NAME = "contoso-poc-model"
DEFAULT_INSTANCE = "Standard_DS2_v2"
COLORS = ("blue", "green")  # blue/green deployment slots
USE_CASE_TARGETS = {
    "holidays": {
        "endpoint_name": "contoso-endpoint",
        "model_name": "contoso-poc-model",
    },
    "nyctaxi": {
        "endpoint_name": "contoso-taxi-endpoint",
        "model_name": "contoso-poc-taxi-model",
    },
    "tickets": {
        "endpoint_name": "support-tickets-endpoint",
        "model_name": "support-tickets-sla-model",
    },
}


def _pick_target_color(ep) -> tuple[str, str | None]:
    """Return (target_color_to_deploy, currently_live_color_or_None).

    The live color is whichever has the highest non-zero traffic weight.
    If nothing is live yet, default to deploying 'blue'.
    """
    traffic = ep.traffic or {}
    live = max(traffic, key=traffic.get) if any(v > 0 for v in traffic.values()) else None
    if live is None:
        return "blue", None
    target = "green" if live == "blue" else "blue"
    return target, live


def _client() -> MLClient:
    s = load_settings()
    return MLClient(
        DefaultAzureCredential(),
        s.subscription_id,
        s.resource_group,
        s.aml_workspace,
    )


def _ts() -> str:
    return time.strftime("%H:%M:%S")


def _resolve_az_cmd() -> str:
    """Return a callable Azure CLI executable path across OS/shell variants."""
    az_cmd = shutil.which("az") or shutil.which("az.cmd")
    if az_cmd:
        return az_cmd
    fallback = Path(r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd")
    if fallback.exists():
        return str(fallback)
    raise RuntimeError(
        "Azure CLI executable not found. Install Azure CLI or ensure az/az.cmd is on PATH."
    )


def _resolve_target(args: argparse.Namespace, require_model: bool = False) -> tuple[str, str | None]:
    """Resolve endpoint/model from explicit args or a use-case preset."""
    preset = USE_CASE_TARGETS.get(getattr(args, "use_case", None), {})
    endpoint_name = args.endpoint_name or preset.get("endpoint_name") or ENDPOINT_NAME
    model_name = getattr(args, "model_name", None) or preset.get("model_name") or MODEL_NAME
    if require_model:
        return endpoint_name, model_name
    return endpoint_name, None


def cmd_create_endpoint(args: argparse.Namespace) -> int:
    ml = _client()
    endpoint_name, _ = _resolve_target(args)
    try:
        ep = ml.online_endpoints.get(endpoint_name)
        print(f"[{_ts()}] Endpoint already exists: {ep.name} ({ep.provisioning_state})")
        return 0
    except Exception:
        pass

    print(f"[{_ts()}] Creating endpoint {endpoint_name} (aml_token, default system MI)...")
    ep = ManagedOnlineEndpoint(name=endpoint_name, auth_mode="aml_token")
    ml.online_endpoints.begin_create_or_update(ep).result()
    ep = ml.online_endpoints.get(endpoint_name)
    print(f"[{_ts()}] Endpoint: {ep.provisioning_state}")
    print(f"[{_ts()}] System MI principal_id: {ep.identity.principal_id}")
    print(f"[{_ts()}] Scoring URI: {ep.scoring_uri}")
    print(
        "Next: run `grant-rbac` then `deploy` (the system MI starts with no roles)."
    )
    return 0


def cmd_grant_rbac(args: argparse.Namespace) -> int:
    """Grant the RBAC required for an online deployment to succeed.

    Three grants required (see docs/06 Issues 4.10, 4.11):
      1. Endpoint system MI -> Storage Blob Data Reader on workspace storage
      2. Endpoint system MI -> AcrPull on workspace ACR
      3. Workspace UAMI     -> Key Vault Secrets Officer on workspace KV
         (Secrets User is NOT enough; image-prep flow runs setSecret under
         the workspace identity, not the endpoint identity.)
    """
    import subprocess

    ml = _client()
    s = load_settings()
    endpoint_name, _ = _resolve_target(args)
    az_cmd = _resolve_az_cmd()

    ep = ml.online_endpoints.get(endpoint_name)
    endpoint_pid = ep.identity.principal_id
    print(f"[{_ts()}] Endpoint MI principal_id: {endpoint_pid}")

    # Resolve workspace's attached storage + ACR from the workspace itself
    ws = ml.workspaces.get(s.aml_workspace)
    sa_id = ws.storage_account
    acr_id = ws.container_registry
    kv_id = ws.key_vault
    print(f"[{_ts()}] Storage: {sa_id.split('/')[-1]}")
    print(f"[{_ts()}] ACR:     {acr_id.split('/')[-1]}")
    print(f"[{_ts()}] KV:      {kv_id.split('/')[-1]}")

    # Resolve workspace UAMI principal_id from workspace identity metadata first
    # to avoid requiring Entra directory read permissions.
    uami_pid = ""
    ws_identity = getattr(ws, "identity", None)
    uami_map = getattr(ws_identity, "user_assigned_identities", None) if ws_identity else None
    if isinstance(uami_map, dict):
        for _, identity_val in uami_map.items():
            client_id = getattr(identity_val, "client_id", None)
            principal_id = getattr(identity_val, "principal_id", None)
            if client_id == s.uami_client_id and principal_id:
                uami_pid = principal_id
                break

    # ARM fallback: resolve managed identity principal_id by clientId.
    if not uami_pid:
        try:
            uami_pid = subprocess.check_output(
                [
                    az_cmd,
                    "identity",
                    "list",
                    "-g",
                    s.resource_group,
                    "--query",
                    f"[?clientId=='{s.uami_client_id}'].principalId | [0]",
                    "-o",
                    "tsv",
                ],
                text=True,
            ).strip()
        except subprocess.CalledProcessError:
            uami_pid = ""

    # Cross-resource-group fallback inside the subscription.
    if not uami_pid:
        try:
            uami_pid = subprocess.check_output(
                [
                    az_cmd,
                    "identity",
                    "list",
                    "--query",
                    f"[?clientId=='{s.uami_client_id}'].principalId | [0]",
                    "-o",
                    "tsv",
                ],
                text=True,
            ).strip()
        except subprocess.CalledProcessError:
            uami_pid = ""

    # Final fallback for older SDK payloads or if ARM queries are blocked.
    if not uami_pid:
        try:
            uami_pid = subprocess.check_output(
                [
                    az_cmd, "ad", "sp", "list",
                    "--filter", f"appId eq '{s.uami_client_id}'",
                    "--query", "[0].id", "-o", "tsv",
                ],
                text=True,
            ).strip()
        except subprocess.CalledProcessError as ex:
            raise RuntimeError(
                "Could not resolve workspace UAMI principal_id. "
                "The current identity may lack permissions to query managed identities "
                "and Entra service principals. Ask an admin to run this step, or grant "
                "Reader on the UAMI resource and directory read scope."
            ) from ex

    if not uami_pid:
        raise RuntimeError(
            "Resolved empty workspace UAMI principal_id. Check USER_ASSIGNED_MI_CLIENT_ID and workspace identity config."
        )
    print(f"[{_ts()}] Workspace UAMI principal_id: {uami_pid}")

    grants = [
        ("Storage Blob Data Reader", sa_id, endpoint_pid, "endpoint MI"),
        ("AcrPull", acr_id, endpoint_pid, "endpoint MI"),
        ("Key Vault Secrets Officer", kv_id, uami_pid, "workspace UAMI"),
    ]
    failed_grants: list[tuple[str, str, int]] = []
    for role, scope, principal, who in grants:
        print(f"[{_ts()}] Granting '{role}' to {who} ({principal})...")
        result = subprocess.run(
            [
                az_cmd, "role", "assignment", "create",
                "--assignee-object-id", principal,
                "--assignee-principal-type", "ServicePrincipal",
                "--role", role,
                "--scope", scope,
                "-o", "none",
            ],
            check=False,
        )
        if result.returncode != 0:
            failed_grants.append((role, scope, result.returncode))

    if failed_grants:
        print(f"[{_ts()}] One or more RBAC grants failed:")
        for role, scope, code in failed_grants:
            print(f"  - role='{role}' scope='{scope}' exit={code}")
        print(
            "You likely need Owner or User Access Administrator on these scopes "
            "to create role assignments."
        )
        return 1

    print(f"[{_ts()}] Done. Wait ~30-60s for RBAC propagation, then run `deploy`.")
    return 0


def cmd_deploy(args: argparse.Namespace) -> int:
    """Blue/green deploy with zero downtime.

    Steps:
      1. Pick `target` color = whichever is NOT currently serving traffic.
         (First deploy ever -> 'blue'.)
      2. If a stale `target` deployment exists from a prior failed attempt,
         delete it first (its traffic is already 0 so this is safe).
      3. Create the new `target` deployment from `--model-version`.
      4. Shift 100% traffic to `target`.
      5. Delete the previous `live` deployment (now 0 traffic).

    The old deployment keeps serving until step 4 completes, so callers
    see no downtime.
    """
    ml = _client()
    endpoint_name, model_name = _resolve_target(args, require_model=True)
    ep = ml.online_endpoints.get(endpoint_name)
    target, live = _pick_target_color(ep)
    print(f"[{_ts()}] Live: {live or '(none)'} -> deploying to: {target}")

    # Clean up any stale `target` deployment from a prior failed attempt.
    existing = {d.name for d in ml.online_deployments.list(endpoint_name=endpoint_name)}
    if target in existing:
        # If it somehow still has traffic, zero it first.
        if (ep.traffic or {}).get(target, 0) > 0:
            print(f"[{_ts()}] Stale '{target}' has traffic; zeroing before delete...")
            ep.traffic = {k: 0 for k in (ep.traffic or {})}
            if live:
                ep.traffic[live] = 100
            ml.online_endpoints.begin_create_or_update(ep).result()
        print(f"[{_ts()}] Deleting stale '{target}' deployment...")
        ml.online_deployments.begin_delete(
            name=target, endpoint_name=endpoint_name
        ).result()

    model_ref = f"azureml:{model_name}:{args.model_version}"
    print(f"[{_ts()}] Creating '{target}' from {model_ref} on {args.instance_type}...")
    dep = ManagedOnlineDeployment(
        name=target,
        endpoint_name=endpoint_name,
        model=model_ref,
        instance_type=args.instance_type,
        instance_count=args.instance_count,
    )
    r = ml.online_deployments.begin_create_or_update(dep).result()
    print(f"[{_ts()}] Deployment: {r.name} | {r.provisioning_state}")

    if r.provisioning_state != "Succeeded":
        print(f"[{_ts()}] Deployment did not succeed; leaving '{live}' live. Check portal logs.")
        return 1

    print(f"[{_ts()}] Shifting 100% traffic: {live or '(none)'} -> {target}...")
    ep = ml.online_endpoints.get(endpoint_name)
    ep.traffic = {target: 100}
    if live and live != target:
        ep.traffic[live] = 0
    ml.online_endpoints.begin_create_or_update(ep).result()
    ep = ml.online_endpoints.get(endpoint_name)
    print(f"[{_ts()}] Traffic: {ep.traffic}")

    if live and live != target:
        print(f"[{_ts()}] Deleting previous '{live}' deployment...")
        ml.online_deployments.begin_delete(
            name=live, endpoint_name=endpoint_name
        ).result()
        print(f"[{_ts()}] Deleted '{live}'.")

    print(f"[{_ts()}] Scoring URI: {ep.scoring_uri}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ml = _client()
    endpoint_name, _ = _resolve_target(args)
    ep = ml.online_endpoints.get(endpoint_name)
    print(f"Endpoint: {ep.name}")
    print(f"  state:   {ep.provisioning_state}")
    print(f"  auth:    {ep.auth_mode}")
    print(f"  traffic: {ep.traffic}")
    print(f"  scoring: {ep.scoring_uri}")
    print(f"  MI pid:  {ep.identity.principal_id}")
    print("Deployments:")
    for d in ml.online_deployments.list(endpoint_name=endpoint_name):
        print(f"  - {d.name} | {d.provisioning_state} | model={d.model} | sku={d.instance_type}")
    return 0


def cmd_invoke(args: argparse.Namespace) -> int:
    ml = _client()
    endpoint_name, _ = _resolve_target(args)
    req_path = Path(args.request)
    if not req_path.exists():
        print(f"Request file not found: {req_path}", file=sys.stderr)
        return 2
    print(f"[{_ts()}] Invoking {endpoint_name} with {req_path} (via traffic routing)...")
    # Omit deployment_name so the request is routed by the endpoint's
    # traffic weights — proves blue/green traffic shift actually works.
    out = ml.online_endpoints.invoke(
        endpoint_name=endpoint_name,
        request_file=str(req_path),
    )
    print(f"[{_ts()}] Response:")
    try:
        print(json.dumps(json.loads(out), indent=2))
    except Exception:
        print(out)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    use_case_choices = sorted(USE_CASE_TARGETS)

    def _add_endpoint_arg(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--endpoint-name",
            default=None,
            help=(
                "Online endpoint name. If omitted, resolved from --use-case "
                f"or defaults to {ENDPOINT_NAME}."
            ),
        )

    def _add_use_case_arg(parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "--use-case",
            choices=use_case_choices,
            default=None,
            help="Preset target: holidays, nyctaxi, or tickets.",
        )

    pc = sub.add_parser("create-endpoint", help="Create the managed online endpoint")
    _add_use_case_arg(pc)
    _add_endpoint_arg(pc)

    pg = sub.add_parser("grant-rbac", help="Grant required RBAC to the endpoint MI + workspace UAMI")
    _add_use_case_arg(pg)
    _add_endpoint_arg(pg)

    pd = sub.add_parser("deploy", help="Blue/green deploy: create inactive color, shift traffic, delete old")
    _add_use_case_arg(pd)
    _add_endpoint_arg(pd)
    pd.add_argument(
        "--model-name",
        default=None,
        help=(
            "Registered model name. If omitted, resolved from --use-case "
            f"or defaults to {MODEL_NAME}."
        ),
    )
    pd.add_argument("--model-version", required=True, help="Registered model version, e.g. 2")
    pd.add_argument("--instance-type", default=DEFAULT_INSTANCE)
    pd.add_argument("--instance-count", type=int, default=1)

    ps = sub.add_parser("status", help="Show endpoint + deployment status")
    _add_use_case_arg(ps)
    _add_endpoint_arg(ps)

    pi = sub.add_parser("invoke", help="Score a sample JSON request")
    _add_use_case_arg(pi)
    _add_endpoint_arg(pi)
    pi.add_argument("--request", required=True, help="Path to JSON request file")

    args = p.parse_args()
    return {
        "create-endpoint": cmd_create_endpoint,
        "grant-rbac": cmd_grant_rbac,
        "deploy": cmd_deploy,
        "status": cmd_status,
        "invoke": cmd_invoke,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
