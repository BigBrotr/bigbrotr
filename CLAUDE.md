# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

BigBrotr is a modular Nostr relay data archiving and monitoring system. It discovers relays, validates connectivity, monitors health (NIP-11/NIP-66), and synchronizes events into PostgreSQL. Python 3.11+, fully async, strict mypy. Version 4.0.0. All code lives under the `bigbrotr` package namespace (`src/bigbrotr/`).

## Commands

```bash
# Tests
pytest tests/ -v                                    # all tests (~1900)
pytest tests/unit/core/test_pool.py -v              # single file
pytest tests/unit/core/test_pool.py::TestPool -v    # single class
pytest -k "health_check" -v                         # pattern match
pytest tests/ --cov=src/bigbrotr --cov-report=html  # coverage (85% minimum)

# Linting & formatting
ruff check src/ tests/                  # lint
ruff check src/ tests/ --fix            # lint + auto-fix
ruff format src/ tests/                 # format
mypy src/bigbrotr                       # type check (strict mode)

# All pre-commit hooks at once
pre-commit run --all-files

# Run a service (from a deployment directory)
cd deployments/bigbrotr
python -m bigbrotr seeder --once
python -m bigbrotr finder --log-level DEBUG
```

## Architecture

Diamond DAG, five packages. Imports flow downward only:

```
         services       src/bigbrotr/services/ — business logic (seeder, finder, validator, monitor, synchronizer)
        /   |   \       src/bigbrotr/services/common/ — shared constants, mixins, SQL queries, configs
     core  nips  utils  src/bigbrotr/core/ — pool, brotr, base_service, logger, yaml, metrics
        \   |   /       src/bigbrotr/nips/ — NIP-11/NIP-66 protocol implementations (I/O, parsing)
         models         src/bigbrotr/utils/ — dns, keys, transport
                        src/bigbrotr/models/ — frozen dataclasses (pure, zero I/O, zero deps)
```

**Models layer is pure** — zero I/O, zero package dependencies. Uses `import logging` + `logging.getLogger()`, not `bigbrotr.core.logger.Logger`. The `nips/` package was extracted from `models/` to separate protocol I/O from pure data.

### Key components

- **Pool** (`src/bigbrotr/core/pool.py`): async PostgreSQL connection pool via asyncpg with retry/backoff
- **Brotr** (`src/bigbrotr/core/brotr.py`): high-level DB facade wrapping stored procedures. Generic -- zero domain SQL. Services call `self._brotr.fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `transaction()`
- **BaseService** (`src/bigbrotr/core/base_service.py`): abstract base with `run()` cycle, `run_forever()` loop, graceful shutdown, factory methods (`from_yaml`, `from_dict`)
- **yaml** (`src/bigbrotr/core/yaml.py`): YAML loading utilities (moved from utils to core)
- **nips** (`src/bigbrotr/nips/`): NIP protocol implementations -- `nip11/` (relay info document fetch/parse), `nip66/` (relay monitoring metadata: dns, geo, http, net, rtt, ssl). Contains I/O and parsing logic, depends on models/utils/core
- **services/common/** (`src/bigbrotr/services/common/`): `constants.py` (ServiceName, DataType StrEnums), `mixins.py` (BatchProgress, semaphores), `queries.py` (13 domain SQL functions), `configs.py` (network Pydantic models)

### Service pipeline

Seeder (one-shot, seeds URLs) -> Finder (discovers more) -> Validator (tests connectivity, promotes to relays table) -> Monitor (NIP-11/NIP-66 health checks) -> Synchronizer (collects events via aiomultiprocess)

### Deployments

Deployment configurations live in `deployments/{bigbrotr,lilbrotr,_template}/` (renamed from `implementations/`). Each deployment contains:
- `config/brotr.yaml` -- core Brotr configuration
- `config/services/*.yaml` -- per-service configuration (flattened from former `yaml/` directory)
- `postgres/init/*.sql` -- database schema and stored procedures
- `static/seed_relays.txt` -- seed relay URLs
- `docker-compose.yml` -- Docker orchestration

## Import Conventions

```python
# Inside same package: relative
from .logger import Logger
from .common.constants import DataType, ServiceName

# Cross-package: absolute with bigbrotr prefix
from bigbrotr.core.logger import Logger
from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.core.yaml import load_yaml
from bigbrotr.models.constants import NetworkType
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.nips.nip66 import Nip66
from bigbrotr.utils.dns import resolve_host
from bigbrotr.utils.transport import is_nostr_relay

# Models layer: stdlib logging only (zero deps)
import logging
logger = logging.getLogger(__name__)

# Tests: src/ is on sys.path via conftest.py
from bigbrotr.core.logger import Logger, format_kv_pairs
from bigbrotr.models.event import Event
from bigbrotr.nips.nip11 import Nip11
```

## Database Conventions

- metadata table column: `value` (NOT `metadata`)
- relay_metadata column: `metadata_type` (NOT `type`)
- No CHECK constraints -- validation in Python enum layer
- Hash computed in Python (no pgcrypto)
- All mutations via stored procedures with bulk array params (`relays_insert`, `events_insert`, `metadata_insert`, etc.)
- Cascade functions: `events_relays_insert_cascade`, `relay_metadata_insert_cascade`
- `Brotr._pool` is private -- services never access pool directly

## Model Patterns

- ALL models are `@dataclass(frozen=True)` -- immutable
- ALL models cache `to_db_params()` in `__post_init__` via `_db_params` field
- Pattern: `_compute_db_params()` (private) -> cached in `self._db_params` -> `to_db_params()` returns it
- NetworkType lives in `src/bigbrotr/models/constants.py` (not utils)
- MetadataType lives in `src/bigbrotr/models/metadata.py`
- Models package is pure -- zero I/O, no nips subpackage. NIP protocol logic lives in `bigbrotr.nips`

## Testing Patterns

- pytest with `asyncio_mode = "auto"` -- no need for `@pytest.mark.asyncio`
- conftest.py provides: `mock_pool`, `mock_brotr`, `mock_connection`, `sample_event`, `sample_relay`, `sample_metadata`, etc.
- Mock targets use `bigbrotr.` prefix: `@patch("bigbrotr.services.validator.is_nostr_relay")`
- Service tests mock query functions at the service module namespace (NOT `bigbrotr.core.queries.*`)
- `time.monotonic()` for durations, `time.time()` for Unix timestamps

## Code Style

- **ruff** for linting + formatting, line length 100, target Python 3.11
- **mypy strict** on `src/bigbrotr`
- Conventional commits: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- ruff format auto-runs on commit via pre-commit -- re-stage after format changes
- `debug-statements` pre-commit hook uses Python 3.9 AST -- NO `match/case` in hook scripts
- `ban-relative-imports = "parents"` -- only sibling-relative imports allowed
- `known-first-party = ["bigbrotr"]`

## Service Registry

- Entry point: `bigbrotr.__main__:cli` (console_scripts: `bigbrotr = "bigbrotr.__main__:cli"`)
- CLI: `python -m bigbrotr <service> [options]`
- `ServiceEntry` NamedTuple in `src/bigbrotr/__main__.py` -- access via `entry.cls`, `entry.config_path`
- Registry keys use `ServiceName.SEEDER`, etc.
- Config paths: `config/brotr.yaml`, `config/services/<service>.yaml`
- Config: `BrotrConfig` has 2 fields: `batch` (BatchConfig), `timeouts` (BrotrTimeoutsConfig)
- Lifecycle: `async with brotr:` then `async with service:`

## Closed Design Issues (won't-fix)

- Logger can't use `__slots__` -- breaks `unittest.mock.patch.object()`
- Relay.from_db_params always re-parses URL in `__post_init__` -- by design for safety
- `_parse_delete_result` parses asyncpg `'DELETE N'` strings -- no structured alternative
- Monitor keys validation at config load time via `model_validator` -- fail-fast by design
- Type annotations on generic subclasses -- necessary for mypy type narrowing
