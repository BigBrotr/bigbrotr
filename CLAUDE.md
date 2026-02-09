# CLAUDE.md

Guidance for Claude Code when working with this repository.

## Project

BigBrotr is a Nostr relay discovery, monitoring, and event archiving system. Five async services form a pipeline: Seeder -> Finder -> Validator -> Monitor -> Synchronizer. Python 3.11+, PostgreSQL 16, asyncpg, strict mypy. All code under `src/bigbrotr/`.

## Commands

```bash
# Quality (or use `make ci` to run all)
ruff check src/ tests/                              # lint (zero errors expected)
ruff format src/ tests/                             # format
mypy src/bigbrotr                                   # strict type check

# Tests
pytest tests/ -v                                    # all tests (~2050)
pytest tests/ --ignore=tests/integration/ -v        # unit only
pytest tests/unit/core/test_pool.py -v              # single file
pytest -k "health_check" -v                         # pattern match
pytest tests/ --cov=src/bigbrotr --cov-report=html  # coverage (80% minimum)

# Makefile shortcuts
make lint / make format / make typecheck / make test / make test-fast / make coverage / make ci

# Pre-commit
pre-commit run --all-files

# Run a service (from a deployment directory)
cd deployments/bigbrotr
python -m bigbrotr seeder --once
python -m bigbrotr finder --log-level DEBUG
```

## Architecture

Diamond DAG. Imports flow strictly downward:

```
              services         src/bigbrotr/services/
             /   |   \
          core  nips  utils    src/bigbrotr/{core,nips,utils}/
             \   |   /
              models           src/bigbrotr/models/
```

- **models**: Pure frozen dataclasses. Zero I/O, zero `bigbrotr` imports. Uses `import logging` + `logging.getLogger()`.
- **core**: Pool, Brotr, BaseService, Exceptions, Logger, Metrics, YAML loader. Depends only on models.
- **nips**: NIP-11 (relay info fetch/parse), NIP-66 (RTT, SSL, DNS, Geo, Net, HTTP). Has I/O. Depends on models, utils, core.
- **utils**: DNS resolution, Nostr key management, WebSocket/HTTP transport, SOCKS5 proxy. Depends only on models.
- **services**: Business logic. Depends on core, nips, utils, models.

### Key Files

| File | Role |
|------|------|
| `core/pool.py` | asyncpg connection pool with retry/backoff, health-checked acquisition |
| `core/brotr.py` | High-level DB facade. Wraps stored procedures via `_call_procedure()`. Generic query methods: `fetch()`, `fetchrow()`, `fetchval()`, `execute()`, `transaction()` |
| `core/base_service.py` | Abstract base: `run()` cycle, `run_forever()` loop, graceful shutdown, `from_yaml()`/`from_dict()` factories |
| `core/exceptions.py` | `BigBrotrError` hierarchy: `ConfigurationError`, `DatabaseError` (`ConnectionPoolError`, `QueryError`), `ConnectivityError` (`RelayTimeoutError`, `RelaySSLError`), `ProtocolError`, `PublishingError` |
| `core/logger.py` | Structured key=value logging. JSON output mode with timestamp/level/service. `format_kv_pairs()` utility. |
| `core/metrics.py` | Prometheus `/metrics` endpoint. 4 metric types: `SERVICE_INFO`, `SERVICE_GAUGE`, `SERVICE_COUNTER`, `CYCLE_DURATION_SECONDS` |
| `models/relay.py` | URL validation (rfc3986), network detection (clearnet/tor/i2p/loki/local), local IP rejection |
| `models/metadata.py` | Content-addressed metadata. SHA-256 hash, canonical JSON, `MetadataType` enum (7 types) |
| `models/service_state.py` | `ServiceState`, `ServiceStateKey`, `StateType` (StrEnum), `EventKind` (IntEnum). Moved from services/common for DAG compliance. |
| `services/monitor.py` | Health check orchestration (~600 lines) |
| `services/monitor_publisher.py` | Nostr event broadcasting: kind 0, 10166, 30166 (~230 lines) |
| `services/monitor_tags.py` | NIP-66 tag building for kind 30166 events (~280 lines) |
| `services/common/queries.py` | 13 domain SQL query functions |
| `services/common/constants.py` | `ServiceName`, `DataType` StrEnums |
| `services/common/mixins.py` | `BatchProgress` dataclass |
| `services/common/configs.py` | Network config Pydantic models (clearnet/tor/i2p/loki) |
| `utils/transport.py` | `connect_relay()`, `is_nostr_relay()`, `create_client()`, `InsecureWebSocketTransport` |
| `utils/keys.py` | `load_keys_from_env()`, `KeysConfig` Pydantic model |
| `__main__.py` | CLI entry point. Service registry with `ServiceEntry` NamedTuples. |

### Service Pipeline

```
Seeder (one-shot) -> Finder (discovers from events + APIs) -> Validator (WebSocket test, promotes to relay table)
-> Monitor (NIP-11 + NIP-66 health checks, publishes kind 10166/30166) -> Synchronizer (event collection, cursor-based)
```

### Deployments

Directory: `deployments/{bigbrotr,lilbrotr,_template}/`

Each deployment contains:
- `config/brotr.yaml` -- Pool, batch, timeouts
- `config/services/*.yaml` -- Per-service config
- `postgres/init/*.sql` -- 10 SQL files, 22 stored functions (all `SECURITY INVOKER`)
- `docker-compose.yaml` -- Full stack with resource limits, 2 networks (data + monitoring)
- `monitoring/` -- Prometheus config + alerting rules + Grafana provisioning

Single parametric Dockerfile: `deployments/Dockerfile` with `ARG DEPLOYMENT`

## Import Conventions

```python
# Same package: relative
from .logger import Logger
from .common.constants import DataType, ServiceName

# Cross-package: absolute
from bigbrotr.core.logger import Logger
from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.core.exceptions import ConnectivityError, RelayTimeoutError
from bigbrotr.models.constants import NetworkType
from bigbrotr.models.service_state import ServiceState, EventKind, StateType
from bigbrotr.nips.nip11 import Nip11
from bigbrotr.utils.transport import connect_relay, is_nostr_relay

# Models layer: stdlib only
import logging
logger = logging.getLogger(__name__)

# Tests
from bigbrotr.core.logger import Logger
from bigbrotr.models.event import Event
```

**Rules**: `ban-relative-imports = "parents"` (only sibling-relative allowed). `known-first-party = ["bigbrotr"]`.

## Database

- **Tables**: `relay`, `event`, `event_relay`, `metadata`, `relay_metadata`, `service_state`
- **Column names**: metadata table uses `payload` (NOT `value`). relay_metadata uses `metadata_type` (NOT `type`).
- **No CHECK constraints** -- validation in Python enum layer
- **Hash** computed in Python (SHA-256, no pgcrypto)
- **All mutations** via stored procedures with bulk array parameters
- **22 functions**: 1 utility (`tags_to_tagvalues`), 10 CRUD, 3 cleanup (batched), 8 refresh. All `SECURITY INVOKER`.
- **7 materialized views**: `relay_metadata_latest`, `event_stats`, `relay_stats`, `kind_counts`, `kind_counts_by_relay`, `pubkey_counts`, `pubkey_counts_by_relay`
- **Cascade functions**: `event_relay_insert_cascade` (relay + event + junction), `relay_metadata_insert_cascade` (relay + metadata + junction)
- **`Brotr._pool` is private** -- services use Brotr methods, never pool directly

## Model Patterns

- ALL models `@dataclass(frozen=True, slots=True)` -- immutable
- ALL models cache `to_db_params()` in `__post_init__` via `_db_params` field
- Pattern: `_compute_db_params()` -> cached `_db_params` -> `to_db_params()` returns it
- `object.__setattr__` in `__post_init__` (frozen workaround)
- `from_db_params()` classmethod reconstructs from DB params
- `NetworkType` in `models/constants.py`, `MetadataType` in `models/metadata.py`
- `ServiceState`, `ServiceStateKey`, `StateType`, `EventKind` in `models/service_state.py`

## Testing

- pytest with `asyncio_mode = "auto"` -- no `@pytest.mark.asyncio`
- Global timeout: `--timeout=120` in addopts
- Coverage threshold: `fail_under = 80` (branch coverage)
- Shared fixtures: `tests/fixtures/relays.py` registered via `pytest_plugins = ["tests.fixtures.relays"]`
- Root conftest provides: `mock_pool`, `mock_brotr`, `mock_connection`, `sample_event`, `sample_relay`, `sample_metadata`, etc.
- Mock targets use `bigbrotr.` prefix: `@patch("bigbrotr.services.validator.is_nostr_relay")`
- Service tests mock query functions at service module namespace
- `time.monotonic()` for durations, `time.time()` for Unix timestamps
- 2049 unit tests + 8 integration tests (testcontainers PostgreSQL)

## Code Style

- **ruff**: lint + format, line-length 100, target py311
- **mypy**: strict on `src/bigbrotr`
- **Commits**: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`
- Pre-commit auto-formats on commit -- re-stage after changes
- `debug-statements` hook uses Python 3.9 AST -- no `match/case` in hook scripts

## CLI

- Entry point: `bigbrotr.__main__:cli`
- `python -m bigbrotr <service> [--config PATH] [--brotr-config PATH] [--log-level LEVEL] [--once]`
- Config defaults: `config/brotr.yaml`, `config/services/<service>.yaml`
- `BrotrConfig`: `batch` (BatchConfig), `timeouts` (BrotrTimeoutsConfig: query=60s, batch=120s, cleanup=90s, refresh=None)
- Lifecycle: `async with brotr:` then `async with service:` then `service.run_forever()` or `service.run()`

## Closed Design Issues

- Logger can't use `__slots__` -- breaks `unittest.mock.patch.object()`
- `Relay.from_db_params` always re-parses URL in `__post_init__` -- by design for safety
- `_parse_delete_result` parses asyncpg `'DELETE N'` strings -- no structured alternative
- Monitor keys validation at config load via `model_validator` -- fail-fast by design
- Type annotations on generic subclasses -- necessary for mypy type narrowing
