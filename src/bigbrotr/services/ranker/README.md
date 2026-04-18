# ranker

Private ranking service that exports public score tables.

## Main Files

- `service.py`, `runtime.py`: cycle orchestration and public export seam.
- `store_*.py`: private DuckDB-backed graph and non-user storage flows.
- `queries.py`, `configs.py`, `types.py`, `utils.py`: shared DB reads, config,
  result types, and helpers.

## Rules

- Private ranking state stays private to this package.
- The public contract exported from here is score data, not internal run
  bookkeeping.
