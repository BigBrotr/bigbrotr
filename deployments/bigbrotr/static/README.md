# `bigbrotr/static`

Operator-managed static inputs for the `bigbrotr` full-archive deployment.

## What Lives Here

- [`seed_relays.txt`](seed_relays.txt): starting relay list used by Seeder.
- `GeoLite2-City.mmdb`, `GeoLite2-ASN.mmdb`: GeoLite2 databases used by
  Monitor geo/net checks when the files are present locally.

## Rules

- Keep `seed_relays.txt` as plain text with one relay URL per line.
- GeoLite2 files are runtime assets, not source code; refresh them
  intentionally and keep filesystem permissions compatible with the container
  user when bind-mounting `static/`.
- If deployment-specific static inputs change meaning, update this README with
  the operator contract.
