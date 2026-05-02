# BigBrotr Internal Wiki

This wiki is a code-first orientation guide for the current
`refactor/definitive-redesign-execution` branch. It summarizes the repository as
implemented: source code, tests, generated SQL, deployment assets, and the
MkDocs site.

## Reading Order

1. [Current State](01-current-state.md)
2. [Repository Map](02-repository-map.md)
3. [Architecture](03-architecture.md)
4. [Data Model](04-data-model.md)
5. [Services](05-services.md)
6. [NIP-85 Pipeline](06-nip85-pipeline.md)
7. [Read Side](07-read-side.md)
8. [Deployment And Operations](08-deployment-operations.md)
9. [Testing And Quality](09-testing-quality.md)
10. [Documentation Maintenance](10-documentation-maintenance.md)
11. [PR Readiness](11-pr-readiness.md)

Appendix:

- [Evidence Index](appendices/evidence-index.md)

## Source-Of-Truth Rule

When prose and code disagree, use this precedence order:

1. executable code under `src/bigbrotr/`;
2. tests under `tests/`;
3. SQL templates under `tools/templates/sql/`;
4. generated deployment SQL under `deployments/*/postgres/init/`;
5. deployment YAML, Compose, Prometheus, Grafana, and shell assets;
6. public docs under `docs/`;
7. this wiki.

The wiki should help navigation and review. It is not a replacement for reading
the code before changing behavior.
