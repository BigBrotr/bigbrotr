# tests/system/pipelines/restart_resume

Runtime certification for restart, resume, and partial-completion behavior
across the composed public pipeline:

- `Refresher`
- `Ranker`
- `Assertor`
- `API`
- `DVM`

The tests here prove that persisted shared state can be consumed incrementally
by downstream services, that restart boundaries do not duplicate outputs where
idempotency is required, and that publish-side failures remain honest until the
pipeline is resumed on a healthy relay path.
