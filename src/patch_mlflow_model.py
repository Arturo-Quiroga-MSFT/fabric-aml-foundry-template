"""Download an MLflow model, patch its conda.yaml + requirements.txt to add
extra pip packages, and re-register as a new version.

Used to work around no-code MLflow online deployments failing because the
auto-generated scoring script imports `azureml.ai.monitoring.Collector` which
isn't in the model's recorded environment.

Example:
    uv run python -m src.patch_mlflow_model \
        --name contoso-poc-model --version 1 \
        --add-package azureml-ai-monitoring \
        --description "v2: added azureml-ai-monitoring for online deploy"
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

import yaml
from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Model
from azure.identity import DefaultAzureCredential

from src.config import load_settings


def _patch_conda(conda_path: Path, packages: list[str]) -> None:
    with conda_path.open() as f:
        d = yaml.safe_load(f)
    pip_block = next(
        (x for x in d["dependencies"] if isinstance(x, dict) and "pip" in x),
        None,
    )
    if pip_block is None:
        pip_block = {"pip": []}
        d["dependencies"].append(pip_block)
    existing = set(p.split("==")[0].split("<")[0].split(">")[0] for p in pip_block["pip"])
    for pkg in packages:
        base = pkg.split("==")[0].split("<")[0].split(">")[0]
        if base not in existing:
            pip_block["pip"].append(pkg)
    with conda_path.open("w") as f:
        yaml.safe_dump(d, f, sort_keys=False)


def _patch_requirements(req_path: Path, packages: list[str]) -> None:
    if not req_path.exists():
        req_path.write_text("\n".join(packages) + "\n")
        return
    existing_lines = [
        ln.rstrip("\n") for ln in req_path.read_text().splitlines() if ln.strip()
    ]
    existing_bases = {ln.split("==")[0].split("<")[0].split(">")[0] for ln in existing_lines}
    for pkg in packages:
        base = pkg.split("==")[0].split("<")[0].split(">")[0]
        if base not in existing_bases:
            existing_lines.append(pkg)
    req_path.write_text("\n".join(existing_lines) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="Registered model name")
    p.add_argument("--version", required=True, help="Source model version to patch")
    p.add_argument(
        "--add-package",
        action="append",
        required=True,
        help="Package to add to conda.yaml + requirements.txt (can repeat)",
    )
    p.add_argument("--description", default="Patched model env")
    args = p.parse_args()

    s = load_settings()
    ml = MLClient(DefaultAzureCredential(), s.subscription_id, s.resource_group, s.aml_workspace)

    with tempfile.TemporaryDirectory(prefix="aml-model-") as tmp:
        tmp_path = Path(tmp)
        print(f"Downloading {args.name}:{args.version} -> {tmp_path}...")
        ml.models.download(name=args.name, version=args.version, download_path=str(tmp_path))

        # azure-ai-ml puts artifacts under <download_path>/<name>/<subdir>/...
        # For MLflow models the actual model dir contains MLmodel + conda.yaml.
        candidates = [p.parent for p in tmp_path.rglob("MLmodel")]
        if not candidates:
            print("ERROR: No MLmodel file found in downloaded artifacts.")
            return 2
        model_dir = candidates[0]
        print(f"Model dir: {model_dir}")

        conda_path = model_dir / "conda.yaml"
        req_path = model_dir / "requirements.txt"
        print(f"Patching conda.yaml + requirements.txt with: {args.add_package}")
        _patch_conda(conda_path, args.add_package)
        _patch_requirements(req_path, args.add_package)
        print("conda.yaml after patch:")
        print(conda_path.read_text())

        new_model = Model(
            name=args.name,
            path=str(model_dir),
            type=AssetTypes.MLFLOW_MODEL,
            description=args.description,
        )
        registered = ml.models.create_or_update(new_model)
        print(f"Registered: {registered.name} v{registered.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
