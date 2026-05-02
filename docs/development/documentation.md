# Documentation Maintenance

`docs/` is the only living documentation tree for BigBrotr. If a change affects
architecture, service behavior, configuration, deployment, database shape,
testing, operations, or public APIs, update this site in the same slice.

## Documentation Surfaces

| Surface | Role |
| --- | --- |
| `docs/` | Canonical maintained documentation. |
| `README.md` | Short repository entry point that links into `docs/`. |
| `CHANGELOG.md` | Release history. |
| `.github/*` policy files | GitHub workflow, security, and contribution surfaces. |
| `AGENTS.md` | Local automation guidance, not product documentation. |

Folder README files, the temporary root wiki, and historical planning notes are
not maintained documentation surfaces. Move useful current content into
`docs/` instead of creating a second explanation layer.

## Page Ownership

| Topic | Canonical page |
| --- | --- |
| Product overview | [Project Orientation](../project/index.md) |
| Repository layout | [Repository Map](../project/repository-map.md) |
| Runtime architecture | [Architecture](../user-guide/architecture.md) |
| Data movement | [Data Flow](../project/data-flow.md) |
| Service behavior | [Services](../user-guide/services.md) |
| PostgreSQL schema | [Database](../user-guide/database.md) |
| NIP-85 outputs | [NIP-85 Pipeline](../user-guide/nip85-pipeline.md) |
| Read adapters | [Read Side](../user-guide/read-side.md) |
| Deployment model | [Deployments](../user-guide/deployments.md) |
| Configuration | [Configuration](../user-guide/configuration.md) |
| Monitoring | [Monitoring](../user-guide/monitoring.md) |
| Testing | [Testing](testing.md) |
| SQL generation | [SQL Templates](sql-templates.md) |

## Cross-Reference Standard

Every page that explains behavior should link to adjacent ownership surfaces:

- service pages link to configuration, database state, tests, metrics, and
  Python API reference;
- database pages link to writers, readers, refresh functions, and tests;
- deployment pages link to configuration, backup/restore, monitoring, and
  service ownership;
- development pages link to the repository map and quality gates;
- appendices link back to the current canonical pages they support.

Cross references are part of the maintenance contract. A page that explains a
subsystem but does not point to its owners and dependents is incomplete.

## Update Rules

1. Read the code and tests before changing prose.
2. Update the owning page in `docs/`.
3. Update related pages if links, names, or responsibilities changed.
4. Keep root `README.md` short and point readers to the canonical docs.
5. Do not create new folder README files for current behavior.
6. Do not add historical planning notes as live documentation.
7. Run the documentation and repository gates before committing.

## Required Checks

For documentation-only changes:

```bash
uv run mkdocs build --strict
uv run pre-commit run markdownlint --files <changed markdown files>
uv run pre-commit run codespell --files <changed docs files>
git diff --check
```

For changes that also alter behavior, run the normal repository gates:

```bash
make ci
uv lock --check
```

Related pages:

- [Contributing](contributing.md)
- [Coding Standards](coding-standards.md)
- [Testing](testing.md)
- [Evidence Map](../appendices/evidence-map.md)
