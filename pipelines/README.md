# Pipelines

AML job/pipeline YAML definitions. Populated in a later phase.

Planned:

- `train.yml` — declarative AML command job that runs `python -m src.train` on the registered MLTable asset.
- `deployment.yml` — managed online deployment definition (model, instance type, environment).
- `monitoring-schedule.yml` — `MonitoringSchedule` resource for drift / data quality.
- `train-register-deploy.yml` — end-to-end pipeline (data prep → train → register → deploy).

These are the targets of the GitHub Actions workflow in [`../.github/workflows/train-register-deploy.yml`](../.github/workflows/train-register-deploy.yml).
