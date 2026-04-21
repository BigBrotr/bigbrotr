# `lilbrotr` Deployment

`lilbrotr` is the canonical lightweight-archive reference deployment.

Use it when you want the compact built-in storage profile:

- event tags stay nullable and unpopulated;
- event content stays nullable and unpopulated;
- event signatures stay nullable and unpopulated;
- the deployment SQL package comes from the lightweight archive template
  namespace.

The deployment still keeps the same shared architecture and service set, but it
trades event-payload fidelity for a smaller archive footprint.

## Quick orientation

- [`.env.example`](.env.example) defines the required secrets and the default
  host metrics-port range (`900x`).
- [`docker-compose.yaml`](docker-compose.yaml) is the full container
  composition for this reference deployment.
- [`config/`](config/README.md) contains the shared Brotr config and the
  per-service YAML files.
- [`postgres/`](postgres/README.md) contains `postgresql.conf` plus the
  generated database bootstrap package for the lightweight archive profile.
- [`static/`](static/README.md) contains operator-managed static inputs such as
  the seed relay file.
- [`monitoring/`](monitoring/) contains Prometheus, Alertmanager, Grafana, and
  exporter configuration.
- [`pgbouncer/`](pgbouncer/README.md) contains the connection-pooler
  configuration used by the services.

## Operational notes

- Copy `.env.example` to `.env`, fill in the required passwords and optional
  stable Nostr keys, then keep `.env` local to the deployment.
- Default host-side ports are centered on the `lilbrotr` range:
  - PostgreSQL: `5433`
  - PgBouncer: `6433`
  - Tor SOCKS5: `9051`
  - service metrics: `9001` through `9009`
- Choose this deployment when you want the lightweight archive profile without
  changing the overall service topology.
- If you change the schema, edit the SQL template source and regenerate the
  deployment package; do not maintain `postgres/init/` by hand.

## When copying this deployment

If you clone `deployments/lilbrotr` into a custom deployment:

- update this local `README.md` for the new deployment purpose;
- keep [`config/README.md`](config/README.md) and
  [`config/services/README.md`](config/services/README.md) honest if you change
  configuration meaning or exposure policy;
- record any SQL-template overrides, protocol-exposure limits, or unusual
  operational differences near the deployment they affect.
