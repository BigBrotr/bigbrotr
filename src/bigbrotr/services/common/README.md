# services/common

Shared service-layer infrastructure used by multiple runtime services.

## Main Files

- `catalog*.py`: schema discovery, query planning, and safe execution for the
  read side.
- `read_models.py`, `read_model_registry.py`, `read_model_requests.py`:
  `ReadCore`, readable-resource registry, and compatibility seams.
- `configs.py`, `paging.py`, `mixins.py`, `state_store.py`: shared config,
  bounded traversal helpers, concurrency mixins, and service-state access.
- `discovery_queries.py`, `types.py`, `utils.py`: shared query and helper
  primitives.

## Rules

- Put logic here only when it is genuinely shared by multiple services.
- The read side should evolve here first, then be consumed by API and DVM as
  thin adapters.
