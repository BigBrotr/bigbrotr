# `lilbrotr/data`

Reserved bind-mount root for persistent runtime state in the `lilbrotr`
deployment.

## What Lives Here

- `postgres/`: created by Docker Compose for the PostgreSQL data directory
  mounted at `./data/postgres:/var/lib/postgresql/data`.
- `ranker/`: created by Docker Compose for the Ranker private store mounted at
  `./data/ranker:/app/data`.
- `.gitkeep`: keeps the empty root directory tracked until runtime state is
  created locally.

## Rules

- Treat this folder as deployment-local runtime state, not as curated source
  assets.
- Do not commit live database or Ranker state back into the repository from a
  real deployment.
