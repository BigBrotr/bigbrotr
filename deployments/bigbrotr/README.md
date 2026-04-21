# `bigbrotr` Deployment

`bigbrotr` is the canonical full-archive reference deployment.

Use it when you want the fullest built-in storage profile:

- event tags are stored;
- event content is stored;
- event signatures are stored;
- the deployment SQL package is the default full-archive package.

## Quick orientation

- [`.env.example`](.env.example) defines the required secrets and the default
  host metrics-port range (`800x`).
- [`docker-compose.yaml`](docker-compose.yaml) is the full container
  composition for this reference deployment.
- [`config/`](config/README.md) contains the shared Brotr config and the
  per-service YAML files.
- [`postgres/`](postgres/README.md) contains `postgresql.conf` plus the
  generated database bootstrap package for this deployment.
- [`static/`](static/README.md) contains operator-managed static inputs such as
  the seed relay file and GeoIP assets.
- [`monitoring/`](monitoring/) contains Prometheus, Alertmanager, Grafana, and
  exporter configuration.
- [`pgbouncer/`](pgbouncer/) contains the connection-pooler configuration used
  by the services.

## Operational notes

- Copy `.env.example` to `.env`, fill in the required passwords and optional
  stable Nostr keys, then keep `.env` local to the deployment.
- Default host-side ports are centered on the `bigbrotr` range:
  - PostgreSQL: `5432`
  - PgBouncer: `6432`
  - Tor SOCKS5: `9050`
  - service metrics: `8001` through `8009`
- The deployment ships the full service set and is the clearest starting point
  for custom deployments.
- If you change the schema, edit the SQL template source and regenerate the
  deployment package; do not maintain `postgres/init/` by hand.

## When copying this deployment

If you clone `deployments/bigbrotr` into a custom deployment:

- update this local `README.md` for the new deployment purpose;
- keep [`config/README.md`](config/README.md) and
  [`config/services/README.md`](config/services/README.md) honest if you change
  configuration meaning or exposure policy;
- record any SQL-template overrides, protocol-exposure limits, or unusual
  operational differences near the deployment they affect.
