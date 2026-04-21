# tests/system/deployments/lilbrotr

`lilbrotr` deployment-stack baseline certification.

## What Lives Here

- full compose startup/readiness proof for the lightweight deployment profile;
- one-shot `seeder` exit verification alongside continuous-service readiness;
- and runtime artifacts for stack snapshots and container logs.

## Rules

- prove the real `lilbrotr` compose topology, not a reduced synthetic subset;
- treat `seeder` exit semantics as part of startup correctness;
- reject startup regressions that hide behind `config_not_found` or bootstrap
  validation failures;
- and leave enough evidence to audit any failed container after the stack is
  torn down.
