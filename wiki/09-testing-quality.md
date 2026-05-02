# Testing And Quality

## Required Gates

The repository expects:

```bash
make ci
```

This runs linting, formatting checks, strict type checking, tests, SQL drift
checks, and security/dependency audit targets according to the current
Makefile.

Useful focused commands:

```bash
ruff check src/ tests/
mypy src/bigbrotr
pytest tests/ --ignore=tests/integration/ -v
uv run mkdocs build --strict
```

## Test Layers

| Layer | Role |
| --- | --- |
| Unit | Model validation, config validation, service cycles, helpers, query wrappers, NIP builders. |
| Integration | Real PostgreSQL schema/functions, cascade behavior, NIP-85 pipeline, Ranker/Assertor persistence. |
| System | Compose contracts, runtime parity, monitoring parity, relay harness behavior. |
| Live smoke | Narrow live-environment checks. |

## High-Risk Change Areas

| Area | Required care |
| --- | --- |
| SQL templates | Update generated SQL and integration tests. |
| Models | Preserve fail-fast validation and DB param contracts. |
| Service registry | Update enum, registry, configs, deployment, tests, docs. |
| Read models | Keep API and DVM behavior consistent. |
| NIP-85 | Validate Refresher, Ranker, Assertor, event builders, and publication state together. |
| Secrets/config | Check deployment examples, docs, and startup validation. |

## Review Checklist

- Does the change follow existing package boundaries?
- Are stored functions and Python query wrappers aligned?
- Are public read resource names stable?
- Are metrics and logs sufficient to operate the change?
- Are error boundaries scoped and intentional?
- Are tests added at the lowest layer that proves the behavior?
- Does MkDocs build with generated Python reference pages?

## Known Residual Risks

- The database is the coupling point; schema drift has broad blast radius.
- API/DVM exposure depends on configuration discipline and catalog validation.
- Nostr publication services depend on stable key management and relay behavior.
- Ranker introduces private state outside PostgreSQL, so restore procedures must
  account for it.
- Lightweight event storage necessarily uses fallbacks for metrics that require
  full tag payloads.
