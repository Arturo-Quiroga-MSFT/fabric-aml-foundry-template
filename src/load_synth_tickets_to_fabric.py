"""Generate synthetic Contoso / M365 support tickets and write to OneLake.

Run from the repo root after `az login`:

    python -m src.load_synth_tickets_to_fabric \
        --rows 200000 --table support_tickets

Writes a Delta table at the path computed from `.env`:

    abfss://<workspace>@onelake.dfs.fabric.microsoft.com/
        <lakehouse>.Lakehouse/Tables/<schema>/<table>

Auth is `DefaultAzureCredential` — works locally with `az login` and on
AML compute with the workspace's managed identity.

This is the synthetic tickets equivalent of `load_nyctaxi_to_fabric.py`.
"""
from __future__ import annotations

import argparse
import sys

import pandas as pd
from deltalake import write_deltalake

from .config import load_settings
from .data import _onelake_storage_options
from .synth_tickets import generate_tickets


def write_to_onelake(df: pd.DataFrame, table: str, mode: str) -> str:
    s = load_settings()
    uri = s.onelake_table_uri_for(table=table)
    print(f"Writing {len(df):,} rows to:\n  {uri}\n  mode={mode}")
    write_deltalake(
        uri,
        df,
        mode=mode,
        schema_mode="overwrite" if mode == "overwrite" else None,
        storage_options=_onelake_storage_options(),
    )
    return uri


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", type=int, default=200_000, help="Number of tickets to generate")
    p.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    p.add_argument("--table", default="support_tickets", help="Delta table name in the lakehouse")
    p.add_argument(
        "--mode",
        default="overwrite",
        choices=["overwrite", "append", "error", "ignore"],
        help="deltalake write mode",
    )
    p.add_argument(
        "--local-only",
        action="store_true",
        help="Skip OneLake write; just save to data/local/support_tickets.parquet",
    )
    args = p.parse_args(argv)

    print(f"Generating {args.rows:,} synthetic tickets (seed={args.seed}) ...")
    df = generate_tickets(n=args.rows, seed=args.seed)

    print("Label distribution:")
    print(df["priority_actual"].value_counts(normalize=True).round(3).to_string())
    print(f"sla_breached rate: {df['sla_breached'].mean():.1%}")

    if args.local_only:
        from pathlib import Path
        out = Path("data/local/support_tickets.parquet")
        out.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(out, index=False)
        print(f"\nLocal snapshot written: {out.resolve()}")
        return 0

    uri = write_to_onelake(df, table=args.table, mode=args.mode)
    print(f"\nDone. Table available at {uri}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
