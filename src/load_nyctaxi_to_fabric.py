"""Load a NYC Yellow Taxi sample into the Fabric lakehouse as a Delta table.

Run from the repo root after `az login`:

    python -m src.load_nyctaxi_to_fabric \
        --start 2024-01 --end 2024-02 \
        --table nyctaxi_yellow

The script pulls the slice from the NYC TLC public parquet feed (no creds
needed), then writes it to OneLake at the path computed from `.env`:

    abfss://<workspace>@onelake.dfs.fabric.microsoft.com/
        <lakehouse>.Lakehouse/Tables/<schema>/<table>

It uses DefaultAzureCredential — works locally with `az login` and on AML
compute with the workspace's managed identity.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime

import pandas as pd
from deltalake import write_deltalake

from .config import load_settings
from .data import _onelake_storage_options

TLC_URL = (
    "https://d37ci6vzurychx.cloudfront.net/trip-data/"
    "yellow_tripdata_{year:04d}-{month:02d}.parquet"
)

# Map TLC snake_case columns -> Azure Open Datasets camelCase that downstream
# notebooks (notably notebooks/01b-nyctaxi-end-to-end.ipynb) expect.
_COLUMN_RENAME = {
    "VendorID": "vendorID",
    "tpep_pickup_datetime": "tpepPickupDateTime",
    "tpep_dropoff_datetime": "tpepDropoffDateTime",
    "passenger_count": "passengerCount",
    "trip_distance": "tripDistance",
    "RatecodeID": "rateCodeId",
    "store_and_fwd_flag": "storeAndFwdFlag",
    "PULocationID": "puLocationId",
    "DOLocationID": "doLocationId",
    "payment_type": "paymentType",
    "fare_amount": "fareAmount",
    "extra": "extra",
    "mta_tax": "mtaTax",
    "tip_amount": "tipAmount",
    "tolls_amount": "tollsAmount",
    "improvement_surcharge": "improvementSurcharge",
    "total_amount": "totalAmount",
    "congestion_surcharge": "congestionSurcharge",
    "Airport_fee": "airportFee",
}



def _parse_year_month(value: str) -> tuple[int, int]:
    """Accept YYYY-MM or full ISO date; return (year, month)."""
    if len(value) == 7:
        dt = datetime.strptime(value, "%Y-%m")
    else:
        dt = datetime.fromisoformat(value)
    return dt.year, dt.month


def _month_range(start: str, end: str) -> list[tuple[int, int]]:
    sy, sm = _parse_year_month(start)
    ey, em = _parse_year_month(end)
    months: list[tuple[int, int]] = []
    y, m = sy, sm
    while (y, m) < (ey, em):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def fetch_nyctaxi(start: str, end: str) -> pd.DataFrame:
    """Pull NYC Yellow Taxi months from the TLC public parquet feed."""
    frames: list[pd.DataFrame] = []
    for year, month in _month_range(start, end):
        url = TLC_URL.format(year=year, month=month)
        print(f"  downloading {year:04d}-{month:02d} ...")
        try:
            frames.append(pd.read_parquet(url))
        except Exception as exc:  # pragma: no cover
            print(f"    skipped {year:04d}-{month:02d}: {exc}")
    if not frames:
        raise RuntimeError("No NYC Taxi months downloaded — check the date range.")
    df = pd.concat(frames, ignore_index=True)
    df = df.rename(columns={k: v for k, v in _COLUMN_RENAME.items() if k in df.columns})
    return df



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
    p.add_argument("--start", default="2024-01", help="YYYY-MM, inclusive month")
    p.add_argument("--end",   default="2024-02", help="YYYY-MM, exclusive month")
    p.add_argument("--table", default="nyctaxi_yellow", help="Delta table name in the lakehouse")
    p.add_argument(
        "--mode",
        default="overwrite",
        choices=["overwrite", "append", "error", "ignore"],
        help="deltalake write mode",
    )
    p.add_argument("--sample", type=int, default=0, help="Optionally subsample to N rows after download")
    args = p.parse_args(argv)

    df = fetch_nyctaxi(args.start, args.end)
    if args.sample and args.sample < len(df):
        df = df.sample(args.sample, random_state=0).reset_index(drop=True)
        print(f"Subsampled to {len(df):,} rows.")

    uri = write_to_onelake(df, table=args.table, mode=args.mode)
    print(f"\nDone. Table available at {uri}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
