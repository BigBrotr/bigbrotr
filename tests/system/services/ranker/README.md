# tests/system/services/ranker

Real runtime certification for the DuckDB-backed `Ranker` service.

## What Lives Here

- composed-stack execution of the shipped `ranker` container for `bigbrotr` and `lilbrotr`;
- live PostgreSQL assertions for exported `30382`/`30383`/`30384`/`30385` score outputs;
- host-side inspection of the private DuckDB store and canonical graph checkpoint after runtime cycles;
- restart/resume proof across persisted runtime data;
- and storage-failure proof with observable container exit and zero partial score export.

## Rules

- seed only the authored upstream tables the ranker actually reads;
- inspect the private store only after the runtime container has fully stopped for that phase;
- keep profile proof focused on shipped deployment differences, not synthetic config forks;
- and capture score/store/container artifacts for every certified run.
