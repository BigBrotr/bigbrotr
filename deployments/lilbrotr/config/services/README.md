# `lilbrotr/config/services`

This folder contains the per-service runtime YAML files for the `lilbrotr`
reference deployment.

Each file combines:

- the service's database role and pool sizing;
- service-specific runtime policy;
- public exposure policy where relevant.
- deployment-local identity or operator choices where relevant.

## Files

- [`api.yaml`](api.yaml): HTTP listener, pagination, and protocol exposure
  policy for public readable resources.
- [`assertor.yaml`](assertor.yaml): NIP-85 publication settings.
- [`dvm.yaml`](dvm.yaml): NIP-90 relay set, pricing, and protocol exposure
  policy.
- [`finder.yaml`](finder.yaml): discovery source and archived-event scan
  behavior.
- [`monitor.yaml`](monitor.yaml): relay health probing, relay-document capture,
  geo metadata, and publication behavior.
- [`ranker.yaml`](ranker.yaml): private ranking storage, sync, staging, export,
  and cleanup behavior.
- [`refresher.yaml`](refresher.yaml): shared current-table, analytics, and
  periodic refresh orchestration.
- [`seeder.yaml`](seeder.yaml): seed-file bootstrap behavior.
- [`synchronizer.yaml`](synchronizer.yaml): relay fetch filters, concurrency,
  and archival batching.
- [`validator.yaml`](validator.yaml): candidate validation and network-policy
  behavior.

## Rules

- Treat these YAML files as deployment-local overlays over the service config
  models, not as full snapshots of every available option.
- It is acceptable to restate important defaults when that improves operator
  clarity, but the file comments must stay honest about that choice.
- Keep `api.yaml` and `dvm.yaml` aligned with the deployment's intended public
  exposure policy.
- Treat `read_models` in those files as adapter-local exposure policy, not as a
  free-form table whitelist.
- When pointing readers to the full config contract, use
  `docs/user-guide/services.md` and the corresponding
  `src/bigbrotr/services/<service>/configs.py` module rather than nonexistent
  generated base YAML paths.
- Update this README when services become first-class, disappear, or change
  their operator-facing role.
