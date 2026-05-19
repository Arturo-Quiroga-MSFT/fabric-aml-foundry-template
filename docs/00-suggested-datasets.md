

> **Status as of May 2026 — read this first.**
>
> This doc captured early-POC dataset brainstorming. The POC has since
> committed to **`publicholidays` as the primary dataset** — the trained
> model, MCP tool (`is_paid_holiday`), Foundry agent, blue/green
> deployment, monitoring queries, and the 30-min demo runbook are all
> built around it.
>
> **`nyctaxi_yellow` is now the secondary "pipeline-is-reusable" proof**:
> notebook [01b-nyctaxi-end-to-end.ipynb](../notebooks/01b-nyctaxi-end-to-end.ipynb)
> runs the same `src/train.py` against a totally different schema for ~2
> minutes in the demo. See [09-add-nyctaxi-to-fabric.md](09-add-nyctaxi-to-fabric.md)
> for how to (re)load it via `python -m src.load_nyctaxi_to_fabric`.
>
> The options below remain useful **for post-POC follow-ups** — especially
> option 2 (synthetic M365 support tickets) if Contoso wants a dataset
> closer to their actual product domain.

- A **realistic business-y prediction** that maps to Contoso's domain (governance, M365, SaaS ops).
- A chance to demo **multi-table joins in Fabric** (lakehouse SQL endpoint) before training — a story partners care about.
- A **second model registration** so you can show blue/green deploy across *different* models, not just versions.

## Recommended options (ranked for Contoso context)

| Rank | Dataset | Where it lives | Why it fits Contoso | Realistic ML task |
|---|---|---|---|---|
| **1** | **NYC Taxi (yellow / green)** | Azure Open Datasets — already available in Fabric via "Sample data" | Big enough to look real (~10s GB), partitioned by date, clean schema. Great for **regression** (fare amount) or **classification** (will trip be tipped). Lets you demo Fabric SQL endpoint joins (taxi + weather + holidays). | Predict `tip_amount > 0` (binary) or `fare_amount` (regression) |
| **2** | **Microsoft Customer Support tickets** (synthetic — generate from a public template) | Generate locally with Faker + push to Fabric | **Closest to Contoso's actual domain** (M365 governance, SaaS support). You control schema + size. Demonstrates a "tickets → priority" or "tickets → SLA breach" model partners can immediately re-skin. | Predict ticket priority or SLA-breach risk |
| 3 | **UCI Online Retail II** (transactional, ~1M rows) | Public CSV, copy into Fabric Files | Realistic e-commerce txns — RFM features, churn prediction, basket analysis. Well-known so partners trust the schema. | Predict customer churn or 30-day repeat purchase |
| 4 | **Kaggle "M365 Defender" / "Microsoft Malware Prediction"** | Kaggle download → Fabric Files | Microsoft-branded, security flavored. Big (~4 GB). | Malware risk classification |
| 5 | **Synthetic SaaS usage logs** (generate) | Faker-generated parquet | Mirror Contoso's product telemetry pattern. Full control. | Predict feature adoption or seat-license churn |

## My top pick: **NYC Taxi + the existing publicholidays**

Reasons:
- It's **already** in Azure Open Datasets — you can register it in Fabric in one click via the Fabric portal.
- Joining `nyc_taxi` ⨝ `publicholidays` (on date+country=US) gives you a **multi-table demo** without leaving Fabric.
- ~50M rows / year — proves the pattern scales beyond a tiny demo.
- The "predict tip" model is intuitive in any boardroom.

## Minimal plan if you go with NYC Taxi

| Step | Where | Effort |
|---|---|---|
| 1. Add `nyctaxi_yellow` table to the Fabric Lakehouse via Azure Open Datasets shortcut | Fabric portal (Lakehouse → Get data → Sample data) | 5 min, no code |
| 2. Add `ONELAKE_TABLE_TAXI=nyctaxi_yellow` to .env | repo | 1 min |
| 3. New notebook `01b-eda-taxi.ipynb` — explore + downsample (1 month) | repo | 30 min |
| 4. New notebook `02b-train-taxi-tip.ipynb` reusing train.py (already takes `--target` + `--drop-cols`) | repo | 20 min |
| 5. Register `contoso-poc-taxi-model`, deploy alongside `contoso-poc-model` (different endpoint) | repo | run helpers |
| 6. Update 08-notebook-sequence.md to show two parallel training/serve tracks | repo | 10 min |

## Recommendation

**Historical note** — when this was written, the recommendation was to
add NYC Taxi for the POC because it's effortless to ingest in Fabric
and gives a meaty multi-table story. **That happened**: see
notebook 01b and `src/load_nyctaxi_to_fabric.py`. NYC Taxi is now the
secondary "pipeline-is-reusable" demo, not the primary dataset.

For a **post-POC** follow-up closer to Contoso's product domain,
option 2 (synthetic M365 support tickets, ~500K Faker-generated rows
pushed to OneLake) is the recommended next step.

