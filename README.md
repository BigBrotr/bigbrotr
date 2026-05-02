# BigBrotr

BigBrotr is a storage-first Nostr relay observatory.

It discovers relays across clearnet, Tor, I2P, and Lokinet; validates relay
connectivity; captures NIP-11 and NIP-66 metadata; archives observed events;
refreshes derived facts; computes public NIP-85 scores; publishes trusted
assertions; and exposes public read resources through HTTP and NIP-90.

[![CI](https://img.shields.io/github/actions/workflow/status/BigBrotr/bigbrotr/ci.yml?branch=develop&label=CI&logo=github)](https://github.com/BigBrotr/bigbrotr/actions/workflows/ci.yml)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/BigBrotr/bigbrotr/codeql.yml?branch=develop&label=CodeQL&logo=github)](https://github.com/BigBrotr/bigbrotr/actions/workflows/codeql.yml)
[![Coverage](https://img.shields.io/codecov/c/github/Bigbrotr/bigbrotr?token=LM9D3ABW0L&logo=codecov&label=coverage)](https://codecov.io/gh/Bigbrotr/bigbrotr)
[![Docs](https://img.shields.io/badge/docs-latest-blue?logo=readthedocs&logoColor=white)](https://bigbrotr.github.io/bigbrotr/)
[![Python](https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![PostgreSQL](https://img.shields.io/badge/postgresql-18-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)

## Documentation

The maintained documentation lives in `docs/` and is published with MkDocs:

- [Project Orientation](docs/project/index.md)
- [Repository Map](docs/project/repository-map.md)
- [Architecture](docs/user-guide/architecture.md)
- [Services](docs/user-guide/services.md)
- [Database](docs/user-guide/database.md)
- [NIP-85 Pipeline](docs/user-guide/nip85-pipeline.md)
- [Read Side](docs/user-guide/read-side.md)
- [Deployments](docs/user-guide/deployments.md)
- [Configuration](docs/user-guide/configuration.md)
- [Testing](docs/development/testing.md)
- [Documentation Maintenance](docs/development/documentation.md)

The root README is only an entry point. If project behavior changes, update the
canonical page in `docs/`.

## Runtime Shape

BigBrotr runs ten independent async services against a shared PostgreSQL
database:

| Service | Responsibility |
| --- | --- |
| Seeder | Load initial relay URLs. |
| Finder | Discover candidate relay URLs. |
| Validator | Validate candidates and promote relays. |
| Monitor | Fetch NIP-11, run NIP-66 checks, and publish monitor events. |
| Synchronizer | Archive observed Nostr events. |
| Refresher | Maintain current tables, analytics facts, and NIP-85 facts. |
| Ranker | Compute scores in DuckDB and export public score snapshots. |
| Assertor | Publish NIP-85 provider-package and assertion events. |
| API | Serve readable resources over HTTP. |
| DVM | Serve readable resources over NIP-90. |

See [Services](docs/user-guide/services.md) and
[Data Flow](docs/project/data-flow.md) for the full model.

## Quick Start

```bash
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr
uv sync --group dev --group docs
make ci
uv run mkdocs serve
```

Run the reference Docker deployment:

```bash
cd deployments/bigbrotr
cp .env.example .env
docker compose up -d
```

See [Docker Deploy](docs/how-to/docker-deploy.md) and
[First Deployment](docs/getting-started/first-deployment.md) before operating a
real deployment.

## Development

Core commands:

```bash
make ci
uv lock --check
uv run mkdocs build --strict
```

Development guidance:

- [Setup](docs/development/setup.md)
- [Testing](docs/development/testing.md)
- [Coding Standards](docs/development/coding-standards.md)
- [Contributing](docs/development/contributing.md)
- [SQL Templates](docs/development/sql-templates.md)

## License

MIT. See [LICENSE](LICENSE).
