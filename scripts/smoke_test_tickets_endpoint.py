"""Smoke test for the support-tickets-endpoint AML online endpoint."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "data" / "sample_request.json"

ENDPOINT_NAME = "support-tickets-endpoint"
SCORING_URI = f"https://{ENDPOINT_NAME}.eastus2.inference.ml.azure.com/score"
DEPLOYMENT = "blue"

# Pulled from .env
RG = os.environ.get("AZURE_RESOURCE_GROUP", "<resource-group>")
WS = os.environ.get("AML_WORKSPACE_NAME", "<aml-workspace-name>")
SUB = os.environ.get("AZURE_SUBSCRIPTION_ID", "<your-subscription-id>")


def get_token() -> str:
    cmd = [
        "az", "ml", "online-endpoint", "get-credentials",
        "--name", ENDPOINT_NAME,
        "--resource-group", RG,
        "--workspace-name", WS,
        "--subscription", SUB,
        "-o", "json",
    ]
    print(f"[+] Fetching AML token via: {' '.join(cmd[:4])} ...")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print("[-] az ml get-credentials failed:", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    creds = json.loads(result.stdout)
    token = creds.get("accessToken") or creds.get("primaryKey")
    if not token:
        print(f"[-] No accessToken/primaryKey in response: {creds}", file=sys.stderr)
        sys.exit(1)
    return token


def score(payload: dict, token: str) -> tuple[int, str, float]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        SCORING_URI,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "azureml-model-deployment": DEPLOYMENT,
        },
    )
    t0 = time.perf_counter()
    try:
        with request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8")
            status = resp.status
    except error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        status = e.code
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return status, text, elapsed_ms


def main() -> int:
    if not SAMPLE.exists():
        print(f"[-] Missing sample payload: {SAMPLE}", file=sys.stderr)
        return 1
    payload = json.loads(SAMPLE.read_text())
    rows = len(payload.get("input_data", {}).get("data", []))
    print(f"[+] Endpoint: {SCORING_URI}")
    print(f"[+] Deployment: {DEPLOYMENT}")
    print(f"[+] Payload rows: {rows}")

    token = get_token()
    print(f"[+] Token acquired (len={len(token)}). Scoring...")

    status, text, elapsed_ms = score(payload, token)
    print(f"[+] HTTP {status} in {elapsed_ms:.1f} ms")
    print("--- response ---")
    try:
        parsed = json.loads(text)
        print(json.dumps(parsed, indent=2))
    except json.JSONDecodeError:
        print(text)
    print("--- end response ---")

    return 0 if status == 200 else 2


if __name__ == "__main__":
    raise SystemExit(main())
