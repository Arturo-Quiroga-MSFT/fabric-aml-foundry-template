"""Generate a sample scoring request from the local snapshot.

The Azure ML MLflow no-code scoring wrapper expects:

    {"input_data": {"columns": [...], "index": [...], "data": [[...], ...]}}

The inner shape matches pandas `DataFrame.to_dict(orient='split')`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.train import _engineer_features


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input-parquet", default="data/local/publicholidays_clf.parquet")
    p.add_argument("--target", default="isPaidTimeOff")
    p.add_argument("--drop-cols", nargs="*", default=["countryRegionCode"])
    p.add_argument("--rows", type=int, default=3)
    p.add_argument("--output", default="data/sample_request.json")
    args = p.parse_args()

    df = pd.read_parquet(args.input_parquet)
    df = _engineer_features(df)
    df = df.drop(columns=[args.target, *args.drop_cols], errors="ignore")
    df = df.head(args.rows).reset_index(drop=True)

    # Replace NaN with None and convert numpy scalars to native Python so json
    # is happy. Preserve numeric dtype for date_* columns.
    records = []
    for _, row in df.iterrows():
        rec = []
        for v in row:
            if pd.isna(v):
                rec.append(None)
            elif isinstance(v, (np.integer,)):
                rec.append(int(v))
            elif isinstance(v, (np.floating,)):
                rec.append(float(v))
            else:
                rec.append(v)
        records.append(rec)

    payload = {
        "input_data": {
            "columns": list(df.columns),
            "index": list(range(len(df))),
            "data": records,
        }
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out} ({args.rows} rows, {len(df.columns)} cols)")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
