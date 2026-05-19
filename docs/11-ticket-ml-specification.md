# 11 - Tickets ML Specification

This document defines the machine learning specification for the synthetic support tickets use case used in this POC.

## Use Case

Predict whether a support ticket will breach SLA.

- Problem type: binary classification
- Target column: `sla_breached`
- Positive class: `True` (breach)

## Data Sources

Primary table:

- OneLake Delta table: `dbo.support_tickets`

Fallback/local development source:

- Local parquet: `data/local/support_tickets.parquet`

## Training and Test Assets

Registered AML Data assets (MLTable):

- Train: `contoso-poc-tickets-train`
- Test: `contoso-poc-tickets-test`

Split strategy:

- Stratified train/test split
- Test size: `0.2`
- Random state: `42`

## Feature and Label Rules

Target handling:

- Drop rows where target is null
- Coerce target to string labels for sklearn compatibility

Dropped columns before training:

- `ticket_id`
- `tenant_id`
- `priority_actual`

Feature engineering:

- Datetime columns are expanded into:
  - `<col>_year`
  - `<col>_month`
  - `<col>_day`
  - `<col>_dayofweek`

## Model Specification

Training entrypoint:

- `python -m src.train`

Algorithm and pipeline:

- `RandomForestClassifier`
- Numeric preprocessing:
  - median imputation
  - standard scaling
- Categorical preprocessing:
  - constant imputation (`__missing__`)
  - one-hot encoding (`handle_unknown='ignore'`)

Core parameters used in tickets flow:

- `n_estimators`: 50 (notebook job setting)
- `max_depth`: 12 (notebook job setting)

## Evaluation and Artifacts

Primary metrics:

- `accuracy`
- `f1_weighted`
- `roc_auc` (when binary probabilities are available)

Evaluation artifacts written by training:

- `outputs/evaluation/metrics.json`
- `outputs/evaluation/predictions.csv`

MLflow logging:

- Parameters: split strategy and row counts
- Metrics: evaluation metrics above
- Artifacts: `evaluation/metrics.json`, `evaluation/predictions.csv`

## Registry and Lineage

Registered model:

- `support-tickets-sla-model`

Recommended model tags for lineage:

- `training_data_asset`
- `training_data_version`
- `test_data_asset`
- `test_data_version`
- `split_strategy`
- `target_column`
- `dropped_columns`
- `training_job_name`

Registered evaluation asset:

- `contoso-poc-tickets-evaluation` (URI folder)

## Online Inference

Endpoint preset:

- Endpoint: `support-tickets-endpoint`
- Model default: `support-tickets-sla-model`

Expected scoring payload shape:

- `{ "input_data": { "columns": [...], "index": [...], "data": [[...], ...] } }`

## Operational Notes

- Model registration does not create or update endpoints.
- Endpoint deployment may take 10 to 30+ minutes because of image prep and container warm-up.
- For deployment success, endpoint/workspace identities must have required RBAC on storage, ACR, and Key Vault.
