# tests — Test Suite

~2,700 unit tests + ~216 integration tests. pytest with `asyncio_mode = "auto"`, global timeout
120s, branch coverage ≥80%.

## Directory Structure

```
tests/
├── conftest.py                    # Root: mocks, sample data, markers, plugin registration
├── fixtures/
│   └── relays.py                  # Shared relay fixtures (via pytest_plugins)
├── unit/
│   ├── test_lazy_imports.py
│   ├── core/                      # 6 files: pool, brotr, logger, yaml, base_service, metrics
│   ├── models/                    # 8 files: relay, event, metadata, event_relay, relay_metadata, service_state, constants, validation
│   ├── nips/
│   │   ├── test_parsing.py
│   │   ├── nip11/                 # 4 files + conftest: nip11, info, data, logs
│   │   └── nip66/                 # 9 files + conftest: nip66, rtt, ssl, geo, net, dns, http, data, logs
│   ├── utils/                     # 6 files: protocol, keys, parsing, transport, dns
│   └── services/                  # 15 files: seeder, finder, validator, monitor, synchronizer, refresher, api, dvm, main + common/
└── integration/
    ├── conftest.py                # Testcontainers PostgreSQL factory
    ├── base/                      # Shared schema tests (bigbrotr deployment)
    └── lilbrotr/                   # LilBrotr-specific tests
```

## Root Conftest (`tests/conftest.py`)

### Mock Fixtures

| Fixture | Scope | Provides |
|---------|-------|----------|
| `mock_private_key` | function | Sets `NOSTR_PRIVATE_KEY` env var |
| `mock_db_password` | function | Sets `DB_ADMIN_PASSWORD` env var |
| `mock_connection` | function | AsyncMock asyncpg connection (fetch, fetchrow, fetchval, execute, transaction) |
| `mock_asyncpg_pool` | function | AsyncMock pool with `acquire()` context manager |
| `mock_pool` | function | Real `Pool` with mocked internal `_pool` |
| `mock_brotr` | function | `Brotr` backed by `mock_pool` |

### Sample Data Fixtures

| Fixture | Returns |
|---------|---------|
| `sample_event()` | `EventRelay` (Nostr event + relay) |
| `sample_relay()` | Clearnet relay |
| `sample_tor_relay()` | `.onion` relay |
| `sample_i2p_relay()` | `.i2p` relay |
| `sample_loki_relay()` | `.loki` relay |
| `sample_metadata()` | `RelayMetadata` with NIP-11 info |
| `sample_events_batch()` | 10 `EventRelay` objects |
| `sample_relays_batch()` | 10 `Relay` objects |

### Helper Functions

- `make_mock_event(id, pubkey, kind, tags, content, sig)`: creates mock `nostr_sdk.Event`
- `create_mock_record(data_dict)`: converts dict to mock asyncpg Record

### Auto-Marking

Tests in `tests/integration/` → `@pytest.mark.integration`.
Tests in `tests/unit/` → `@pytest.mark.unit`.

## Shared Fixtures (`tests/fixtures/relays.py`)

Registered via `pytest_plugins = ["tests.fixtures.relays"]` in root conftest.

| Fixture | Description |
|---------|-------------|
| `relay_clearnet` | `wss://` clearnet relay |
| `relay_clearnet_with_port` | `wss://relay.example.com:8443` |
| `relay_clearnet_ws` | `ws://` (non-TLS) |
| `relay_tor` | `.onion` (56-char v3) |
| `relay_i2p` | `.i2p` relay |
| `relay_loki` | `.loki` relay |
| `relay_ipv6` | IPv6 with port `[2607:f8b0:4000::1]:8080` |
| `relay_overlay` | Parametrized: tor/i2p/loki (3 test runs) |
| `relay_batch` | 10 clearnet relays |

No import needed — use as function parameters directly.

## NIP-66 Conftest (`tests/unit/nips/nip66/conftest.py`)

Complete fixture suite for all 6 NIP-66 health check types.

**Per-type fixtures** (RTT, SSL, Geo, Net, DNS, HTTP): `complete_*_data()`, `complete_*_logs()`,
`complete_*_metadata()`.

**RTT-specific**: `rtt_all_success_logs()`, `rtt_open_failed_logs()` (cascading failure).

**Composite**: `nip66_full()` (all 6 types), `nip66_rtt_only()`, `nip66_dns_only()`.

**Mocks**: `mock_keys`, `mock_event_builder`, `mock_read_filter`, `mock_nostr_client`,
`mock_city_reader`, `mock_asn_reader`, `mock_geoip_response`, `mock_asn_response`,
`mock_certificate_binary`, `mock_dns_a_response`, `mock_dns_aaaa_response`.

## NIP-11 Conftest (`tests/unit/nips/nip11/conftest.py`)

**Relay fixtures**: 8 variants (clearnet, port, path, port+path, tor, i2p, loki, ipv6).

**Raw data**: `complete_nip11_data()`, `minimal_nip11_data()`, `unicode_nip11_data()`.

**Model instances**: `limitation()`, `retention_entry()`, `fee_entry()`, `fees()`, `info_data()`,
`info_data_empty()`, `info_logs_success()`, `info_logs_failure()`, `info_metadata()`,
`info_metadata_failed()`.

**Full Nip11**: `nip11()`, `nip11_failed()`, `nip11_no_info()`.

**HTTP mocks**: `mock_http_response_success()`, `mock_http_response_404()`,
`mock_http_response_invalid_content_type()`, `mock_http_response_invalid_json()`,
`mock_session_factory()`.

## Integration Tests

### Setup (`tests/integration/conftest.py`)

**`pg_container`** (session-scoped): spawns ephemeral PostgreSQL 16-alpine via testcontainers (~3s startup).

**`pg_dsn`** (session-scoped): extracts host/port/database/user/password from container.

**`make_brotr(pg_dsn, deployment)`**: async generator that creates schema once per deployment,
then truncates all tables for subsequent tests (~200x faster than DROP/CREATE per test). Loads
`deployments/{deployment}/postgres/init/*.sql` on first call, yields connected `Brotr`.

### Deployment Conftest Files

| Path | Deployment |
|------|-----------|
| `integration/base/conftest.py` | bigbrotr |
| `integration/lilbrotr/conftest.py` | lilbrotr |

Each provides a `brotr` fixture backed by the appropriate deployment schema.

## Test Conventions

### File Organization

- One test file per source module
- Class per logical unit: `TestPoolConnect`, `TestPoolRetry`, `TestBrotrInsert`
- Method naming: `test_<method>_<scenario>` (e.g., `test_insert_empty_batch`, `test_connect_retry_exhausted`)

### Required Test Paths

Every feature must test: happy path, empty input, error/exception path, edge cases.

### Async Tests

`asyncio_mode = "auto"` — use `async def test_...` directly, no `@pytest.mark.asyncio` needed.

### Mock/Patch Rules

Mock at the **consumer's** namespace, not the source:

```python
# CORRECT
@patch("bigbrotr.services.validator.is_nostr_relay")

# WRONG
@patch("bigbrotr.utils.transport.is_nostr_relay")
```

Service tests mock query functions at service module namespace:
```python
with patch("bigbrotr.services.finder.service.insert_relays_as_candidates", new_callable=AsyncMock):
```

### Parametrized Tests

Use `@pytest.mark.parametrize` for multiple inputs:
```python
@pytest.mark.parametrize(("port", "expected"), [(0, ">=1"), (65536, "<=65535")])
def test_port_validation(self, port, expected):
    with pytest.raises(ValidationError, match=expected):
        DatabaseConfig(port=port)
```

## pytest Configuration (from `pyproject.toml`)

```
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = ["-v", "--strict-markers", "--strict-config", "-ra", "--tb=short", "--timeout=120"]
```

**Coverage**: `source = ["src/bigbrotr"]`, `branch = true`, `fail_under = 80`.

**Excluded from coverage**: `pragma: no cover`, `if TYPE_CHECKING:`, `def __repr__`, `@abstractmethod`.

## Running Tests

```bash
pytest tests/ -v                                    # All (~2,955)
pytest tests/ --ignore=tests/integration/ -v        # Unit only (~2,739)
pytest tests/integration/ -v                        # Integration only (~216)
pytest tests/unit/core/test_pool.py -v              # Single file
pytest -k "health_check" -v                         # Pattern match
pytest tests/ --cov=src/bigbrotr --cov-report=html  # Coverage report
```
