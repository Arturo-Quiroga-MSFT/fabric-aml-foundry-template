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
├── foundry-agent/         # Foundry agent that calls the AML endpoint
├── .github/workflows/     # GitHub Actions CI/CD
└── data/                  # Local sample data (gitignored except samples/)
```

Connectivity walk-through with screenshots checklist: [docs/05-onelake-access-runbook.md](docs/05-onelake-access-runbook.md).

## Quick start

1. Review [docs/02-architecture.md](docs/02-architecture.md).
2. Provision the test bed using [infra/README.md](infra/README.md).
3. Verify Fabric access: [notebooks/00-fabric-onelake-connectivity.ipynb](notebooks/00-fabric-onelake-connectivity.ipynb).
4. Register Fabric OneLake as an AML datastore: [notebooks/00b-register-onelake-datastore.ipynb](notebooks/00b-register-onelake-datastore.ipynb).
5. Copy data into AML as a versioned MLTable: [notebooks/01a-copy-fabric-to-aml.ipynb](notebooks/01a-copy-fabric-to-aml.ipynb).
6. Train: [notebooks/02-sklearn-training.ipynb](notebooks/02-sklearn-training.ipynb).
7. Deploy: [notebooks/03-deploy-online-endpoint.ipynb](notebooks/03-deploy-online-endpoint.ipynb).
8. Monitor: [notebooks/04-monitoring-setup.ipynb](notebooks/04-monitoring-setup.ipynb).

Full connectivity walk-through (with screenshots checklist): [docs/05-onelake-access-runbook.md](docs/05-onelake-access-runbook.md).
