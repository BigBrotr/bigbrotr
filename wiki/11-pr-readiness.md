# PR Readiness

## Branch Shape

The PR target is `develop`. The working branch is
`refactor/definitive-redesign-execution`.

Local inspection before PR preparation showed:

- `develop` and `origin/develop` are aligned;
- the branch is ahead of `develop` by the redesign execution series;
- the final local delta adds this root `wiki/` and makes the generated Python
  package reference explicit in the public docs navigation.

## Review Strategy

This PR is intentionally broad. Review should start from:

1. `README.md` for the public product contract;
2. `wiki/README.md` for the internal orientation map;
3. `wiki/appendices/evidence-index.md` for source evidence;
4. service-specific source, SQL templates, deployment assets, and tests for
   behavioral verification.

The wiki is not a replacement for source review. It is a navigation layer for
the current branch state.

## Ranker Finding

The Ranker is correctly implemented as a private DuckDB-backed analytical
service:

- PostgreSQL remains the canonical source for contact-list facts, NIP-85 facts,
  and public score outputs;
- DuckDB stores the ranker's local graph, graph-sync checkpoint, PageRank
  working tables, local run records, non-user staging tables, and local current
  rank snapshots;
- each run synchronizes only changed followers from PostgreSQL into DuckDB;
- each completed compute phase recomputes PageRank over the full local DuckDB
  graph;
- the Docker deployments bind `/app/data` to `deployments/*/data/ranker/`, so
  `ranker.duckdb` is host-persistent deployment state, not a Docker named
  volume.

No `service_state` change is recommended for Ranker. The graph and rank working
state are too large and analytical for `service_state`, and mirroring the
DuckDB checkpoint into PostgreSQL would create an ambiguous second source of
truth. If `ranker.duckdb` is lost, the correct recovery behavior is to rebuild
the local graph from PostgreSQL.

## PR Risks

| Risk | Mitigation |
| --- | --- |
| Large diff surface | Use this wiki and evidence index as review entrypoints. |
| Generated SQL drift | Run `tools/generate_sql.py --check` through `make ci`. |
| Documentation drift | Run MkDocs strict build and targeted Markdown checks. |
| Hidden attribution artifacts | Repository-wide text scan before commit and PR. |
| Ranker local-state misunderstanding | Document DuckDB persistence and rebuild semantics. |
| CI unit matrix collecting non-unit suites | Keep the GitHub Actions unit-test command aligned with `make ci` by excluding integration, system, and live-smoke suites. |

## Required Gates

Before pushing the PR branch:

```bash
uv run mkdocs build --strict
uv run pre-commit run markdownlint --files README.md docs/index.md $(find wiki -name '*.md' -print)
uv run pre-commit run codespell --files README.md mkdocs.yml docs/index.md $(find wiki -type f -print)
git diff --check
make ci
uv lock --check
```

The branch should be pushed only after these gates pass.

## CI Unit Matrix Finding

The GitHub Actions `Unit Test` matrix is intended to be the cross-version unit
gate. It must not collect `tests/system/` or `tests/live_smoke/`, because those
suites are not part of the local `make ci` unit contract and can depend on
runtime behavior that is unsuitable for the unit matrix. The unit command should
therefore match the local gate by ignoring:

- `tests/integration/`;
- `tests/system/`;
- `tests/live_smoke/`.
