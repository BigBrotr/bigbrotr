# `lilbrotr/static`

Operator-managed static inputs for the `lilbrotr` lightweight-archive
deployment.

## What Lives Here

- [`seed_relays.txt`](seed_relays.txt): starting relay list used by Seeder.

## Rules

- Keep `seed_relays.txt` as plain text with one relay URL per line.
- Add other static runtime assets here only when the lightweight deployment
  genuinely needs them, and document the contract locally when you do.
- If deployment-specific static inputs change meaning, update this README with
  the operator contract.
