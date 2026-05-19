# Contoso POC — Fabric + Azure Machine Learning

Proof of concept demonstrating how to **copy data from Microsoft Fabric / OneLake into Azure Machine Learning**, train a **scikit-learn classification model in a notebook**, deploy it to a managed online endpoint, expose it to a **Microsoft Foundry agent**, and monitor it with an **observability layer**.


## Repository layout

```text
.
├── docs/                  # Engagement context, architecture, decisions, runbooks
├── infra/                 # Bicep IaC for the Azure test bed
├── notebooks/             # Connectivity, copy, EDA, training, deploy, monitoring
├── src/                   # Python helpers (config, data, copy, train)
├── pipelines/             # AML job / pipeline YAML definitions
├── monitoring/            # Workbook JSON, dashboards, alert rules
├── foundry-agent/         # Foundry agent that calls the AML endpoint (<author>)
├── .github/workflows/     # GitHub Actions CICD (<author>)
├── data/                  # Local sample data (gitignored except samples/)
├── partner-context/       # Materials shared internally / by Contoso
└── info-from-<author>.md     # Initial briefing
```

## Team and tracks

All team members are **Partner Solutions Architects (PSAs)**.

| Person | Role | Track |
|--------|------|-------|
| <author> | PSA | Repo scaffold, IaC, baseline notebooks, docs, **Fabric ⇄ AML connectivity** (datastore registration, OneLake access, data asset creation) |
| <author> Nosrat | PSA | Engagement lead, partner comms, model creation (sklearn), endpoint exposure |
| <author> Bittencourt | PSA | [`foundry-agent/`](foundry-agent/), [`.github/workflows/`](.github/workflows/) CICD, observability, sample dataset selection |
| <author> | PSA | Model creation (sklearn), endpoint exposure |

Details of the connectivity track: [docs/05-onelake-access-runbook.md](docs/05-onelake-access-runbook.md).

## Quick start

1. Read [docs/01-engagement-context.md](docs/01-engagement-context.md) and [docs/04-meeting-decisions-2026-05-06.md](docs/04-meeting-decisions-2026-05-06.md).
2. Review [docs/02-architecture.md](docs/02-architecture.md).
3. Provision the test bed using [infra/README.md](infra/README.md).
4. Verify Fabric access: [notebooks/00-fabric-onelake-connectivity.ipynb](notebooks/00-fabric-onelake-connectivity.ipynb).
5. Register Fabric OneLake as an AML datastore: [notebooks/00b-register-onelake-datastore.ipynb](notebooks/00b-register-onelake-datastore.ipynb).
6. Copy data into AML as a versioned MLTable: [notebooks/01a-copy-fabric-to-aml.ipynb](notebooks/01a-copy-fabric-to-aml.ipynb).
7. Train: [notebooks/02-sklearn-training.ipynb](notebooks/02-sklearn-training.ipynb).
8. Deploy: [notebooks/03-deploy-online-endpoint.ipynb](notebooks/03-deploy-online-endpoint.ipynb).
9. Monitor: [notebooks/04-monitoring-setup.ipynb](notebooks/04-monitoring-setup.ipynb).

Full connectivity walk-through (with screenshots checklist): [docs/05-onelake-access-runbook.md](docs/05-onelake-access-runbook.md).
