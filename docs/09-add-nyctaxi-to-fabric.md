# 09 — Add NYC Taxi to the Fabric lakehouse

The POC originally used `publicholidays` only. NYC Taxi (yellow cab
trips) is added as a **second dataset** to demonstrate:

- Multi-table data in the same lakehouse.
- A more realistic ML scenario (predict whether a trip will be tipped).
- That the `src/train.py` + deploy helpers are dataset-agnostic.

This step is one-time. **Preferred path: run the Python loader.** A
manual Fabric-portal fallback is included below.

## Option A (preferred) — Python loader

Loads a NYC Yellow Taxi slice from Azure Open Datasets straight into
OneLake as a Delta table. Auth is `DefaultAzureCredential` (`az login`).

```bash
uv run python -m src.load_nyctaxi_to_fabric \
    --start 2019-01-01 --end 2019-02-01 \
    --table nyctaxi_yellow
```

Common flags:

- `--start` / `--end` — ISO dates, end is exclusive (month-aligned).
- `--sample 200000` — subsample after download for quicker demos.
- `--mode overwrite|append` — defaults to overwrite.

When it finishes you'll see something like:

```
Done. Table available at abfss://...@onelake.dfs.fabric.microsoft.com/...Tables/dbo/nyctaxi_yellow
```

## Option B — Fabric portal (manual fallback)

Use this if you can't reach Open Datasets from your laptop, or want
to leverage the Fabric sample-data shortcut.

1. Open the Fabric workspace → **Lakehouses** → `contoso_poc_lh`.
2. In the lakehouse **Tables** view, click **... → Get data → Sample data**.
3. Pick **NYC Taxi & Limousine Commission - yellow taxi trip records**.
   - This creates a Delta table named `nyctaxi_yellow` under
     `Tables/dbo/` (or `Tables/` for legacy lakehouses).
4. Wait ~1-2 min for the load to complete.
5. Verify: in the Tables tree you should see `nyctaxi_yellow` with a
   row count in the millions.

## Update `.env`

Uncomment the taxi line:

```env
ONELAKE_TABLE_TAXI=nyctaxi_yellow
```

(Schema stays `dbo` — same as `publicholidays`.)

## Verify access from Python

```bash
uv run python -c "
from src.config import load_settings
from src.data import read_delta_table
s = load_settings()
df = read_delta_table(s, table='nyctaxi_yellow')
print(df.shape)
print(df.head())
"
```

You should see the trip schema (`vendorID`, `tpepPickupDateTime`,
`tripDistance`, `fareAmount`, `tipAmount`, ...).

## What runs next

Once the table is in OneLake and `.env` is updated, run
[notebooks/01b-nyctaxi-end-to-end.ipynb](../notebooks/01b-nyctaxi-end-to-end.ipynb)
which performs EDA → snapshot to AML → train → register
(`contoso-poc-taxi-model`).

Optional follow-ons (reuse existing helpers):

```bash
# Deploy the taxi model to its own endpoint
uv run python -m src.deploy_online_endpoint create-endpoint \
    --endpoint-name contoso-taxi-endpoint
uv run python -m src.deploy_online_endpoint grant-rbac \
    --endpoint-name contoso-taxi-endpoint
uv run python -m src.deploy_online_endpoint deploy \
    --endpoint-name contoso-taxi-endpoint \
    --model-name contoso-poc-taxi-model \
    --model-version 1
```
