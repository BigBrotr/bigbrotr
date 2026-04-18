# Repository Content Audit Traversal Map

## Baseline

This traversal map freezes the concrete repository-content-audit baseline for
the post-redesign repository state.

- Repository state under audit:
  closeout commit `9dc6cc35` (`chore: close redesign release-readiness gate`)
- Redesign execution range used to mark touched vs untouched files:
  `c016ec08^..9dc6cc35`
- Frozen full manifest:
  [25_repository_content_audit_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/25_repository_content_audit_manifest.txt)
- Frozen touched/untouched historical-context manifest:
  [26_repository_content_audit_untouched_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/26_repository_content_audit_untouched_manifest.txt)

## Counts

- Final tracked files in the closeout repository state: `542`
- Final tracked files touched during redesign execution:
  `315`
- Final tracked files untouched during redesign execution:
  `227`

Important note:

- the raw redesign diff contains `319` unique paths, but that number includes
  historical paths later renamed or removed;
- the `315` value above is the **intersection** of that diff with the final
  closeout manifest, which is the honest number for the repository-content
  audit.

## Top-Level Distribution

| Surface | Final tracked files | Touched by redesign execution | Untouched by redesign execution |
|---------|---------------------|-------------------------------|---------------------------------|
| `src/` | `167` | `104` | `63` |
| `tests/` | `136` | `74` | `62` |
| `deployments/` | `114` | `55` | `59` |
| `docs/` | `40` | `30` | `10` |
| `tools/` | `25` | `20` | `5` |
| `planning/` | `20` | `20` | `0` |
| `.github/` | `16` | `3` | `13` |
| repo-root and singleton support files | `24` | `9` | `15` |

## Historical-Context Distribution

All tracked files are high-suspicion audit targets.

The untouched counts below are retained only as historical context about where
the redesign program did not actively rewrite the final repository surface:

- `src/`: `63` untouched files
- `tests/`: `62` untouched files
- `deployments/`: `59` untouched files
- repo-root and singleton support files: `15` untouched files
- `.github/`: `13` untouched files
- `docs/`: `10` untouched files
- `tools/`: `5` untouched files

`planning/` has `0` untouched files because the redesign program already
worked there exhaustively, but that does not grant planning files any free
pass in the content audit.

## Traversal Order

The audit should proceed from leaves to parents.

Each wave below should be treated as complete only after:

- all listed files/folders were read as content;
- every file received a keep/update/remove/add-style decision;
- required remediation slices were committed;
- the ledger was updated.

## Wave 1 — Deepest Non-Python Leaves

Primary leaf scopes:

- `.github/ISSUE_TEMPLATE/`
- `.github/workflows/`
- `docs/_snippets/`
- `docs/assets/images/`
- `docs/assets/stylesheets/`
- `docs/overrides/`
- `deployments/bigbrotr/config/services/`
- `deployments/lilbrotr/config/services/`
- `deployments/bigbrotr/monitoring/alertmanager/`
- `deployments/bigbrotr/monitoring/grafana/provisioning/dashboards/`
- `deployments/bigbrotr/monitoring/grafana/provisioning/datasources/`
- `deployments/bigbrotr/monitoring/postgres-exporter/`
- `deployments/bigbrotr/monitoring/prometheus/rules/`
- `deployments/bigbrotr/monitoring/prometheus/`
- `deployments/lilbrotr/monitoring/alertmanager/`
- `deployments/lilbrotr/monitoring/grafana/provisioning/dashboards/`
- `deployments/lilbrotr/monitoring/grafana/provisioning/datasources/`
- `deployments/lilbrotr/monitoring/postgres-exporter/`
- `deployments/lilbrotr/monitoring/prometheus/rules/`
- `deployments/lilbrotr/monitoring/prometheus/`
- `deployments/bigbrotr/postgres/init/`
- `deployments/lilbrotr/postgres/init/`
- `deployments/bigbrotr/pgbouncer/`
- `deployments/lilbrotr/pgbouncer/`
- `deployments/bigbrotr/static/`
- `deployments/lilbrotr/static/`

Special audit pairs:

- SQL init files <-> SQL templates <-> DB docs
- dashboards/rules/exporter queries <-> emitted metrics <-> monitoring docs
- deployment service YAML <-> service config models <-> deployment READMEs

## Wave 2 — Python Leaf Packages

Primary implementation leaves:

- `src/bigbrotr/models/`
- `src/bigbrotr/utils/`
- `src/bigbrotr/nips/nip11/`
- `src/bigbrotr/nips/nip66/`
- `src/bigbrotr/nips/nip85/`
- `src/bigbrotr/core/`
- `src/bigbrotr/services/api/`
- `src/bigbrotr/services/assertor/`
- `src/bigbrotr/services/common/`
- `src/bigbrotr/services/dvm/`
- `src/bigbrotr/services/finder/`
- `src/bigbrotr/services/monitor/`
- `src/bigbrotr/services/ranker/`
- `src/bigbrotr/services/refresher/`
- `src/bigbrotr/services/seeder/`
- `src/bigbrotr/services/synchronizer/`
- `src/bigbrotr/services/validator/`

Special audit pairs:

- package code <-> local README <-> package exports
- live code <-> paired tests
- public API surfaces <-> in-code docs

## Wave 3 — Tools And Tests Leaves

Primary leaf scopes:

- `tools/templates/sql/base/`
- `tools/templates/sql/lilbrotr/`
- `tools/templates/sql/testbrotr/`
- `tools/` tracked utility leaves
- `tests/fixtures/`
- `tests/unit/core/`
- `tests/unit/models/`
- `tests/unit/nips/nip11/`
- `tests/unit/nips/nip66/`
- `tests/unit/nips/nip85/`
- `tests/unit/services/common/`
- `tests/unit/services/`
- `tests/unit/tools/`
- `tests/unit/utils/`
- `tests/integration/base/`
- `tests/integration/lilbrotr/`

Special audit pairs:

- template leaves <-> generated deployment SQL
- test helpers <-> real runtime contracts
- integration tests <-> built-in deployment contracts

## Wave 4 — Parent Package And Folder Surfaces

Primary parent scopes:

- `src/`
- `src/bigbrotr/`
- `src/bigbrotr/nips/`
- `src/bigbrotr/services/`
- `tests/`
- `tools/`
- `docs/` local non-page guidance surfaces
- `deployments/`
- `.github/`
- `planning/`

This wave validates parent-level guidance only after child content is already
understood.

## Wave 5 — Narrative Docs And Planning Surfaces

Primary narrative scopes:

- MkDocs page tree under `docs/`
- root guides and long-form references
- planning files, especially canonical vs historical notes
- contributor and operator guidance

Special audit pairs:

- MkDocs pages <-> local folder guidance
- long-form references <-> current live code/contracts
- planning documents <-> actual repository state after redesign completion

## Wave 6 — Root Contract And Build/CI Surfaces

Primary root scopes:

- `README.md`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `PROJECT_GUIDE.md`
- `PROJECT_VISION_AND_REDESIGN_PLAN.md`
- `BIGBROTR_REPOSITORY_BIBLE.md`
- `NOSTR_NIPS_DEEP_ANALYSIS.md`
- `pyproject.toml`
- `uv.lock`
- `Makefile`
- `mkdocs.yml`
- `.pre-commit-config.yaml`
- `.gitignore`
- `.dockerignore`
- `codecov.yml`
- `.editorconfig`
- `.yamllint`
- `.trivyignore`
- `.secrets.baseline`
- `CHANGELOG.md`
- `LICENSE`
- `MANIFEST.in`
- `CNAME`
- `.vscode/settings.json`

This is the final root synthesis wave and should only happen after all lower
layers are already understood.

## Wave 7 — Repository-Wide Gap Remediation And Closeout

This wave is not a reading-only pass.
It exists to close whatever the prior waves discovered:

- remove files that no longer earn their place;
- update or split weak files;
- add missing companion files;
- add any newly necessary tracked surface implied by the final repository
  shape;
- close paired-surface drift;
- run the full closeout gate.
