# `lilbrotr/config`

This folder is the shared configuration entrypoint for the `lilbrotr`
reference deployment.

## Contents

- [`brotr.yaml`](brotr.yaml) defines the shared Brotr runtime config for the
  deployment, especially database location plus batch, timeout, and pool
  defaults.
- [`services/`](services/README.md) contains the per-service runtime YAML
  files.

## Rules

- Keep the database name and deployment-specific shared settings aligned with
  the deployment contract.
- Put cross-service defaults in `brotr.yaml`; put service-specific behavior in
  `services/*.yaml`.
- When operator-facing meaning changes, update this README together with the
  config itself.
