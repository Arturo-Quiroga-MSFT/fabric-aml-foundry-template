"""Train + register a model from the OneLake `support_tickets` table.

End-to-end driver:
  1. Read `dbo.support_tickets` from OneLake via `read_delta_table`.
  2. Drop the DataFrame to a temp parquet (so we can reuse the unmodified
     `src.train.train()` entrypoint).
  3. Train a scikit-learn classifier (MLflow flavor) using `src.train`.
  4. Register the resulting MLflow model in the AML workspace.

Defaults target the partner-resonant SLA-breach binary model and register it
under a *separate* model name so the existing `contoso-poc-model`
(publicholidays) keeps its blue/green slot untouched.

Usage:
    python -m src.train_tickets_from_onelake
    python -m src.train_tickets_from_onelake --target priority_actual \
        --register-name contoso-poc-priority-model
    python -m src.train_tickets_from_onelake --no-register
"""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from azure.ai.ml import MLClient
from azure.ai.ml.constants import AssetTypes
from azure.ai.ml.entities import Model
from azure.identity import DefaultAzureCredential

from src.config import load_settings
from src.data import read_delta_table
from src.train import train

# Columns to drop per target so we never leak the *other* label or row identifiers.
_LEAKY_BY_TARGET = {
    "sla_breached": ["ticket_id", "tenant_id", "priority_actual"],
    "priority_actual": ["ticket_id", "tenant_id", "sla_breached"],
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--table", default="support_tickets")
    p.add_argument(
        "--target",
        default="sla_breached",
        choices=sorted(_LEAKY_BY_TARGET),
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Where to save the MLflow model. Default: outputs/tickets-<target>-model",
    )
    p.add_argument(
        "--register-name",
        default=None,
        help="AML model name to register under. Default: contoso-poc-<target-slug>-model",
    )
    p.add_argument("--no-register", action="store_true", help="Skip AML model registration.")
    p.add_argument("--test-size", type=float, default=0.2)
    p.add_argument(
        "--n-estimators",
        type=int,
        default=50,
        help="RandomForest trees. Default 50 keeps the pickled model ~50–100 MB.",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=12,
        help="Max tree depth. Default 12 keeps the pickled model ~50–100 MB.",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    settings = load_settings()

    target = args.target
    target_slug = target.replace("_", "-")
    output_dir = args.output_dir or f"outputs/tickets-{target_slug}-model"
    register_name = args.register_name or f"contoso-poc-{target_slug}-model"
    drop_cols = _LEAKY_BY_TARGET[target]

    print(f"Reading OneLake table dbo.{args.table} ...")
    df = read_delta_table(settings, table=args.table)
    print(f"Loaded {len(df):,} rows / {df.shape[1]} cols from OneLake.")

    with tempfile.TemporaryDirectory(prefix="tickets-train-") as tmp:
        parquet_path = Path(tmp) / f"{args.table}.parquet"
        df.to_parquet(parquet_path, index=False)
        print(f"Staged data at {parquet_path} ({parquet_path.stat().st_size / 1e6:.1f} MB).")

        metrics = train(
            data_path=str(parquet_path),
            target=target,
            test_size=args.test_size,
            output_dir=output_dir,
            drop_cols=drop_cols,
            n_estimators=args.n_estimators,
            max_depth=args.max_depth,
        )
        print(f"Training complete. Metrics: {metrics}")

    if args.no_register:
        print("--no-register set; skipping AML model registration.")
        return 0

    print(f"Registering model '{register_name}' from {output_dir} ...")
    ml = MLClient(
        DefaultAzureCredential(),
        settings.subscription_id,
        settings.resource_group,
        settings.aml_workspace,
    )
    model = Model(
        name=register_name,
        path=output_dir,
        type=AssetTypes.MLFLOW_MODEL,
        description=(
            f"Contoso POC: {target} classifier trained on synthetic M365 support "
            f"tickets from OneLake dbo.{args.table}. "
            f"Metrics: {metrics}."
        ),
    )
    registered = ml.models.create_or_update(model)
    print(f"Registered: {registered.name} v{registered.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
