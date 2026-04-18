# Deployments

This folder contains the concrete deployment packaging shipped with BigBrotr.

It is the operator-facing home for:

- built-in reference deployments;
- deployment-local Docker and infrastructure assets;
- generated PostgreSQL init packages;
- environment-file templates;
- monitoring and connection-pooler configuration.

## Built-in folders

| Folder | Role | Storage profile |
| --- | --- | --- |
| [`bigbrotr/`](bigbrotr/README.md) | Full reference deployment | `full_archive` |
| [`lilbrotr/`](lilbrotr/README.md) | Lightweight reference deployment | `lightweight_archive` |
| `testbrotr/` | Fixture deployment for tests and tooling | internal-only |

`bigbrotr` and `lilbrotr` are the two human-facing reference deployments. They
should stay self-explanatory for operators and for authors creating custom
deployments from them.

## Rules

- Treat each reference deployment folder as a concrete product, not a loose
  pile of config files.
- Keep local deployment `README.md` files accurate when ports, storage
  profiles, enabled services, or operator workflows change.
- Do not hand-edit generated SQL under `*/postgres/init/` and expect it to
  survive regeneration. Change the SQL templates or deployment-specific
  overrides instead, then regenerate the package.
- Prefer differences in config, assets, and SQL-template overrides over
  code-level forks.
