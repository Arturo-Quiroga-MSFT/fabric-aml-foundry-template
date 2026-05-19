# Documentation index

![POC architecture — Fabric OneLake → Azure ML → Managed Online Endpoint (blue/green)](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-1778167039900-gpt54-low.png)

> Architecture diagram generated with the
> [Azure Architecture Diagram Builder](https://github.com/<github-user>/azure-architecture-diagram-builder).
> See [AZURE-DIAGRAM-BUILDER-ARTIFACTS/](AZURE-DIAGRAM-BUILDER-ARTIFACTS/) for
> the full set of exports (PNG, SVG, drawio, PPTX, JSON) and the prompt used
> to generate them.

## Documents

| #   | Document                                                              | Purpose                                                                                          |
|-----|-----------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| 00  | [Suggested datasets](00-suggested-datasets.md)                        | Candidate Fabric/Open Datasets evaluated for the POC                                             |
| 01  | [Engagement context](01-engagement-context.md)                        | Partner background, Project Phoenix, POC scope, success criteria, open questions                 |
| 02  | [Architecture](02-architecture.md)                                    | Test-bed architecture diagram + data flow                                                        |
| 03  | [Test bed resources](03-test-bed-resources.md)                        | Authoritative resource list and cost notes                                                       |
| 04  | [Meeting decisions — 6 May 2026](04-meeting-decisions-2026-05-06.md)  | Confirmed scope, technical decisions, roles, timeline                                            |
| 05  | [OneLake access runbook](05-onelake-access-runbook.md)                | Step-by-step Fabric ⇄ AML connectivity (<author>'s track)                                          |
| 06  | [Deployment journey & roadblock log](06-deployment-journey.md)        | Every issue we hit on 2026-05-06 + the exact fix; reproducible end-to-end recipe                 |
| 07  | [Internal status — 7 May 2026](07-internal-status-2026-05-07.md)      | Internal team TL;DR snapshot                                                                     |
| 08  | [Notebook sequence](08-notebook-sequence.md)                          | Mermaid map of `00 → 04` notebooks plus parallel NYC Taxi (`01b`) track and what each one proves |
| 09  | [Add NYC Taxi to Fabric](09-add-nyctaxi-to-fabric.md)                 | One-time runbook to load `nyctaxi_yellow` into the lakehouse for the second-dataset demo         |
| 11  | [Tickets ML specification](11-ticket-ml-specification.md)             | ML spec for the synthetic support-tickets SLA-breach classifier                                  |
| 12  | [Partner walkthrough & demo runbook](12-partner-walkthrough-runbook.md) | Single script one PSA can follow to walk a partner through the repo and run live demos         |

## Architecture artifacts

The [AZURE-DIAGRAM-BUILDER-ARTIFACTS/](AZURE-DIAGRAM-BUILDER-ARTIFACTS/) folder
contains the architecture diagram in every format the builder app exports, so
the same artifact can be reused across docs, slide decks, and edits.

| Artifact                                                                                                                | Use it for                                                |
|-------------------------------------------------------------------------------------------------------------------------|-----------------------------------------------------------|
| [`...gpt54-low.png`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-1778167039900-gpt54-low.png)                         | Embed in markdown / READMEs                               |
| [`...gpt54-low.svg`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-1778167042425-gpt54-low.svg)                         | Lossless scaling for high-res docs                        |
| [`...gpt54-low.drawio`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-1778167044516-gpt54-low.drawio)                   | Open in <https://app.diagrams.net> for further edits      |
| [`...slide-...gpt54-low.pptx`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-slide-1778167061748-gpt54-low.pptx)        | Drop straight into a partner-facing deck                  |
| [`...gpt54-low.json`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-diagram-1778166763956-gpt54-low.json)                       | Re-import into the Diagram Builder app to iterate         |
| [`...html`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/contoso-poc-fabric-onelake-azure-ml-managed-online-endpoint-bluegreen.html) | Standalone interactive viewer                             |
| [`azure-cost-...all-formats.zip`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/azure-cost-1778167031987-gpt54-low-eastus2-all-formats.zip) | Multi-region cost breakdown (CSV/JSON/TXT) for East US 2 |
| [`diagram-builder-prompt.md`](AZURE-DIAGRAM-BUILDER-ARTIFACTS/diagram-builder-prompt.md)                                | The exact LLM prompt used to generate the diagram         |

## Future docs

- `11-sklearn-walkthrough.md` — narrated training run + results review.
- `12-monitoring-runbook.md` — drift detection + alert validation procedure.
- `13-handover.md` — handover guide for Contoso engineers.
