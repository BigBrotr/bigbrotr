# BigBrotr -- Comprehensive Codebase Review

**Date:** 2026-02-24
**Branch:** `feat/refresher-service` (commit `4e71394`)
**Scope:** Full project -- every source file, test, deployment config, SQL, Docker, CI, and documentation
**Method:** 8 parallel review agents covering models, core, nips, utils, services, deployments, tests, and configuration. All findings verified with exact line numbers and code snippets.

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [Critical Findings](#critical-findings)
- [High Severity Findings](#high-severity-findings)
- [Medium Severity Findings](#medium-severity-findings)
- [Low Severity Findings](#low-severity-findings)
- [Positive Observations](#positive-observations)

---

## Executive Summary

The BigBrotr codebase is **professionally engineered** with high-quality async patterns, consistent conventions, strong test coverage (~2,400 tests, >80% branch coverage), and a clean architectural DAG. No critical bugs exist in the Python production code.

The findings concentrate in three areas:

1. **Deployment gaps** (2 critical): the Refresher service lacks Docker containers and Prometheus scraping in both deployments, and the lilbrotr `.env` is missing required database credentials.
2. **Documentation drift** (2 high, 14 medium): CLAUDE.md and the guide files have accumulated divergences from the actual codebase -- phantom exception hierarchy, wrong function counts, contradictory timeout guidance, missing Refresher documentation.
3. **Data integrity risks in SQL** (2 high): the `supported_nip_counts` materialized view can crash on non-integer NIP values, and `network_stats` produces inflated unique counts by summing per-relay distinct counts.

**Totals:** 2 critical, 9 high, 25 medium, 24 low.

---

## Critical Findings

### C1. Refresher Service Missing from Docker Compose and Prometheus

**Files:**
- `deployments/bigbrotr/docker-compose.yaml`
- `deployments/lilbrotr/docker-compose.yaml`
- `deployments/bigbrotr/monitoring/prometheus/prometheus.yaml`
- `deployments/lilbrotr/monitoring/prometheus/prometheus.yaml`

**Problem:** The Refresher service exists in Python code (`src/bigbrotr/services/refresher/`), is registered in `__main__.py`, has a `ServiceName.REFRESHER` enum value, and has YAML config files in both deployments (`config/services/refresher.yaml`). However, neither `docker-compose.yaml` defines a `refresher` container, and neither Prometheus config scrapes its metrics endpoint.

This means all 11 materialized views (`relay_metadata_latest`, `event_stats`, `relay_stats`, `kind_counts`, `kind_counts_by_relay`, `pubkey_counts`, `pubkey_counts_by_relay`, `network_stats`, `relay_software_counts`, `supported_nip_counts`, `event_daily_counts`) are never refreshed automatically. Dashboard queries and API responses depending on these views will show permanently stale data.

**Solution:** Add a `refresher` service block to both `docker-compose.yaml` files, following the same pattern as the other services (resource limits, health check, network attachment, volume mounts). Add a corresponding scrape job to both `prometheus.yaml` files. Example for `docker-compose.yaml`:

```yaml
  refresher:
    container_name: bigbrotr-refresher
    build:
      context: ../
      dockerfile: deployments/Dockerfile
      args:
        DEPLOYMENT: bigbrotr
    command: ["refresher"]
    environment:
      DB_WRITER_PASSWORD: ${DB_WRITER_PASSWORD}
    volumes:
      - ./config:/app/config:ro
    networks:
      - data
    depends_on:
      pgbouncer:
        condition: service_healthy
    deploy:
      resources:
        limits:
          memory: 256M
          cpus: "0.25"
    restart: unless-stopped
```

---

### C2. LilBrotr `.env` Missing Database Credentials

**File:** `deployments/lilbrotr/.env`

**Problem:** The lilbrotr `.env` file contains only `DB_ADMIN_PASSWORD`, `GRAFANA_PASSWORD`, and `PRIVATE_KEY`. It is missing `DB_WRITER_PASSWORD` and `DB_READER_PASSWORD`, which are referenced by:
- The PostgreSQL init script `01_roles.sh` (creates roles with these passwords)
- The PGBouncer entrypoint (writes these to `userlist.txt`)
- Every service container's environment section in `docker-compose.yaml`
- Every service YAML config (`password_env: DB_WRITER_PASSWORD`)

The bigbrotr `.env` correctly defines both variables. Without them, lilbrotr containers receive empty passwords, PGBouncer writes empty credentials, and services cannot authenticate to the database.

**Solution:** Add the missing variables to `deployments/lilbrotr/.env`:

```
DB_WRITER_PASSWORD=<secure_password>
DB_READER_PASSWORD=<secure_password>
```

---

## High Severity Findings

### H1. SSL Test Returns `ssl_valid=True` with Empty Certificate Data

**File:** `src/bigbrotr/nips/nip66/ssl.py`, lines 222-241

**Problem:** The `_ssl()` static method performs two independent network operations:

```python
result.update(Nip66SslMetadata._extract_certificate_data(host, port, timeout))
result["ssl_valid"] = Nip66SslMetadata._validate_certificate(host, port, timeout)
```

`_extract_certificate_data` opens a raw SSL socket and extracts certificate fields (issuer, expiry, SAN, etc.). If this connection fails (caught at lines 274-278), it returns an empty dict. `_validate_certificate` makes a **separate** connection with standard certificate verification and returns `True` if the handshake succeeds. These two operations are independent -- the extraction can fail while validation succeeds (e.g., transient network issue on the first connection, successful retry on the second).

When this happens, `result` is `{"ssl_valid": True}` with zero certificate detail fields. The `execute()` method at line 353 checks `if data:`, which evaluates to `True` (the dict has the `ssl_valid` key), so `logs["success"] = True` -- marking the operation as fully successful despite having no actual certificate data.

**Solution:** Make validation conditional on successful extraction. If no certificate data was extracted, either skip validation entirely or set `ssl_valid` to `None`/`False`:

```python
@staticmethod
def _ssl(host: str, port: int, timeout: float) -> dict[str, Any]:
    result: dict[str, Any] = {}
    cert_data = Nip66SslMetadata._extract_certificate_data(host, port, timeout)
    result.update(cert_data)
    if cert_data:
        result["ssl_valid"] = Nip66SslMetadata._validate_certificate(host, port, timeout)
    return result
```

---

### H2. DNS Test `tldextract` Exception Not Caught

**File:** `src/bigbrotr/nips/nip66/dns.py`, lines 103, 128-136

**Problem:** The `_dns()` method uses `contextlib.suppress(*_dns_errors)` where `_dns_errors = (OSError, dns.exception.DNSException)`. Inside this suppression block, `tldextract.extract(host)` is called at line 130. The `tldextract` library can raise exceptions outside the suppressed types:

- `FileNotFoundError` or `PermissionError` if its public suffix list cache files are missing or unreadable (these are `OSError` subclasses, so they ARE caught)
- `requests.RequestException` during suffix list HTTP fetch (NOT an `OSError` subclass)
- `ValueError` from malformed input (NOT caught)

If `tldextract` raises a `requests.RequestException`, it propagates through `_dns()`, through `asyncio.to_thread()`, and into `execute()`. The outer `except (OSError, dns.exception.DNSException)` at line 191 does not catch it either, so the exception escapes to `gather(return_exceptions=True)` in `Nip66.create()`, where it is captured as a failed result.

While the failure is contained (the DNS test returns `None` instead of data), the error message is generic and the specific `tldextract` root cause is not logged.

**Solution:** Broaden the suppression to include `Exception` for the tldextract-specific block, or wrap the tldextract call in its own try/except:

```python
with contextlib.suppress(*_dns_errors):
    try:
        ext = tldextract.extract(host)
    except Exception:
        ext = None
    if ext and ext.domain and ext.suffix:
        domain = f"{ext.domain}.{ext.suffix}"
        answers = resolver.resolve(domain, "NS")
        ...
```

---

### H3. RTT Log Validator Inconsistent with BaseLogs

**Files:**
- `src/bigbrotr/nips/nip66/rtt.py`, line 243
- `src/bigbrotr/nips/nip66/logs.py`, lines 66-69
- `src/bigbrotr/nips/base.py`, lines 177-183

**Problem:** Two different validation patterns exist for the `reason` field when `success` is `False`:

**`BaseLogs`** (base.py:182):
```python
if not self.success and not self.reason:
    raise ValueError("reason is required when success is False")
```
Uses `not self.reason` -- falsy check. Rejects both `None` AND empty string `""`.

**`Nip66RttMultiPhaseLogs`** (logs.py:68):
```python
if not self.open_success and self.open_reason is None:
    raise ValueError("open_reason is required when open_success is False")
```
Uses `is None` -- identity check. Rejects only `None`, **accepts** empty string `""`.

Meanwhile, `str(e)` at rtt.py:243 can produce an empty string for some `OSError` subclasses that have no message. When this happens, `BaseLogs` would reject `reason=""` as invalid, but `Nip66RttMultiPhaseLogs` would accept `open_reason=""` as valid -- storing a semantically useless empty reason.

**Solution:** Unify both validators to use the same pattern. The `not self.reason` (falsy) pattern is stricter and more correct -- an empty reason is as useless as no reason:

```python
# In logs.py, change all three phase validators:
if not self.open_success and not self.open_reason:
    raise ValueError("open_reason is required when open_success is False")
if not self.read_success and not self.read_reason:
    raise ValueError("read_reason is required when read_success is False")
if not self.write_success and not self.write_reason:
    raise ValueError("write_reason is required when write_success is False")
```

Additionally, at the call site in rtt.py:243, add a fallback for empty exception strings:

```python
reason = str(e) or type(e).__name__
```

---

### H4. Refresher Service Uses Bare `except Exception`

**File:** `src/bigbrotr/services/refresher/service.py`, line 80

**Problem:** The Refresher service catches `Exception` broadly in its main loop:

```python
for view in views:
    try:
        start = time.monotonic()
        await self._brotr.refresh_materialized_view(view)
        elapsed = round(time.monotonic() - start, 2)
        refreshed += 1
        self._logger.info("view_refreshed", view=view, duration=elapsed)
    except Exception as exc:
        failed += 1
        self._logger.error("view_refresh_failed", view=view, error=str(exc))
```

This violates the project rule: "Never use bare `except Exception` in service code. `run_forever()` is the ONLY intentionally broad exception boundary." The bare catch swallows programming errors (`TypeError`, `AttributeError`, `NameError`) that should propagate to `run_forever()` for proper failure counting and potential shutdown.

The intent is correct -- a single view refresh failure should not prevent other views from refreshing. But the exception scope is too broad.

**Solution:** Narrow the catch to database-related exceptions that represent expected failure modes:

```python
except (asyncpg.PostgresError, OSError) as exc:
    failed += 1
    self._logger.error("view_refresh_failed", view=view, error=str(exc))
```

This matches the exception handling pattern used consistently across all other services (Finder, Validator, Monitor, Synchronizer).

---

### H5. Synchronizer `stagger_delay` Config Is Dead Code

**Files:**
- `src/bigbrotr/services/synchronizer/configs.py`, line 145
- `src/bigbrotr/services/synchronizer/service.py`

**Problem:** The `SynchronizerConcurrencyConfig` defines a `stagger_delay` field:

```python
stagger_delay: tuple[int, int] = Field(
    default=(0, 60), description="Random delay range (min, max) seconds"
)
```

The service docstring at line 24 references it: "The stagger delay (`concurrency.stagger_delay`) randomizes the relay processing order". However, `stagger_delay` is never read or used anywhere in `service.py`. The relay list is shuffled (`random.shuffle(relays)` at line 181), but no per-relay timing delay is applied. Operators who configure `stagger_delay` in their YAML files get no effect.

**Solution:** Either implement the stagger delay or remove it:

**Option A -- Implement it** (add per-relay delay in the sync loop):
```python
async def _sync_single_relay(self, relay: Relay, ...) -> None:
    delay = random.uniform(*self._config.concurrency.stagger_delay)
    await self.wait(delay)
    # ... existing sync logic
```

**Option B -- Remove it** (the cleaner choice if randomization via `shuffle` is sufficient):
Delete the `stagger_delay` field from `SynchronizerConcurrencyConfig` and update the docstring to remove the reference.

---

### H6. LilBrotr Postgres-Exporter Queries Missing LABEL Definitions

**File:** `deployments/lilbrotr/monitoring/postgres-exporter/queries.yaml`, lines 34-51

**Problem:** Two queries are missing LABEL metric definitions that the bigbrotr version has:

**`lilbrotr_relay_by_network`** -- missing `network` LABEL:
```yaml
# lilbrotr (broken)
metrics:
  - count:
      usage: "GAUGE"
      description: "Number of relays per network type"

# bigbrotr (correct)
metrics:
  - network:
      usage: "LABEL"
      description: "Network type (clearnet, tor, i2p, loki, local)"
  - count:
      usage: "GAUGE"
      description: "Number of relays per network type"
```

**`lilbrotr_table_sizes`** -- missing `table_name` LABEL:
```yaml
# lilbrotr (broken)
metrics:
  - total_bytes:
      usage: "GAUGE"
      description: "Total size of table including indexes (bytes)"

# bigbrotr (correct)
metrics:
  - table_name:
      usage: "LABEL"
      description: "Table name"
  - total_bytes:
      usage: "GAUGE"
      description: "Total size of table including indexes (bytes)"
```

Without LABEL definitions, `postgres_exporter` collapses all dimension values into a single time series. Per-network relay counts and per-table size breakdowns become indistinguishable in Prometheus and Grafana.

**Solution:** Add the missing LABEL entries to match bigbrotr's `queries.yaml`.

---

### H7. Monitor Container Mounts Static Directory Read-Write

**Files:**
- `deployments/bigbrotr/docker-compose.yaml`, line 391
- `deployments/lilbrotr/docker-compose.yaml`, line 391

**Problem:** The monitor service mounts the static directory without read-only protection:

```yaml
# Monitor (line 391) -- MISSING :ro
volumes:
  - ./config:/app/config:ro
  - ./static:/app/static        # <-- read-write

# Seeder (line 235) -- correct
volumes:
  - ./config:/app/config:ro
  - ./static:/app/static:ro     # <-- read-only
```

The monitor only reads GeoLite2 `.mmdb` database files from the static directory. It should not have write access. A compromised or buggy monitor process could corrupt the GeoIP databases used by other services.

**Solution:** Add `:ro` to the monitor's static volume mount in both deployments:

```yaml
- ./static:/app/static:ro
```

---

### H8. `supported_nip_counts` Materialized View Crashes on Non-Integer NIPs

**Files:**
- `deployments/bigbrotr/postgres/init/06_materialized_views.sql`, lines 371-381
- `deployments/lilbrotr/postgres/init/06_materialized_views.sql`, lines 371-381

**Problem:** The view casts NIP text values directly to `INTEGER` without validation:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS supported_nip_counts AS
SELECT
    nip_text::INTEGER AS nip,
    COUNT(*) AS relay_count
FROM relay_metadata_latest
CROSS JOIN LATERAL jsonb_array_elements_text(data -> 'supported_nips') AS nip_text
WHERE metadata_type = 'nip11_info'
    AND data ? 'supported_nips'
    AND jsonb_typeof(data -> 'supported_nips') = 'array'
GROUP BY nip_text::INTEGER
ORDER BY relay_count DESC;
```

The `WHERE` clause validates that the `supported_nips` key exists and is a JSON array, but does not validate that each element is a valid integer string. If any relay publishes non-numeric values (e.g., `"NIP-01"`, `""`, `"1a"`), the `::INTEGER` cast raises a PostgreSQL error, failing the `REFRESH MATERIALIZED VIEW CONCURRENTLY` call and blocking the entire `all_statistics_refresh()` chain.

While the Python NIP-11 parser filters for `isinstance(n, int)`, the data is stored as JSONB (the canonical JSON representation), and legacy or manually-inserted data could contain non-integer values.

**Solution:** Add a regex guard to filter out non-integer strings before casting:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS supported_nip_counts AS
SELECT
    nip_text::INTEGER AS nip,
    COUNT(*) AS relay_count
FROM relay_metadata_latest
CROSS JOIN LATERAL jsonb_array_elements_text(data -> 'supported_nips') AS nip_text
WHERE metadata_type = 'nip11_info'
    AND data ? 'supported_nips'
    AND jsonb_typeof(data -> 'supported_nips') = 'array'
    AND nip_text ~ '^\d+$'
GROUP BY nip_text::INTEGER
ORDER BY relay_count DESC;
```

---

### H9. `network_stats` Materialized View Produces Inflated Unique Counts

**Files:**
- `deployments/bigbrotr/postgres/init/06_materialized_views.sql`, lines 312-332
- `deployments/lilbrotr/postgres/init/06_materialized_views.sql`, lines 312-332

**Problem:** The view computes per-relay distinct counts in a CTE, then SUMs them in the outer query:

```sql
WITH relay_events AS (
    SELECT
        er.relay_url,
        COUNT(DISTINCT e.pubkey) AS unique_pubkeys,
        COUNT(DISTINCT e.kind) AS unique_kinds
    FROM event_relay AS er
    LEFT JOIN event AS e ON er.event_id = e.id
    GROUP BY er.relay_url
)
SELECT
    r.network,
    COALESCE(SUM(re.unique_pubkeys), 0)::BIGINT AS unique_pubkeys,
    COALESCE(SUM(re.unique_kinds), 0)::BIGINT AS unique_kinds
FROM relay AS r
LEFT JOIN relay_events AS re ON r.url = re.relay_url
GROUP BY r.network
```

If pubkey `A` posted events to 10 clearnet relays, it contributes `1` to each relay's `unique_pubkeys`, and the SUM counts it `10` times instead of `1`. The column names `unique_pubkeys` and `unique_kinds` are misleading -- they are actually summed per-relay counts, not network-wide distinct counts.

**Solution:** Use `COUNT(DISTINCT ...)` in the outer query directly, joining through `event_relay` to get true network-wide distinct counts:

```sql
CREATE MATERIALIZED VIEW IF NOT EXISTS network_stats AS
SELECT
    r.network,
    COUNT(DISTINCT r.url) AS relay_count,
    COUNT(DISTINCT er.event_id)::BIGINT AS event_count,
    COUNT(DISTINCT e.pubkey)::BIGINT AS unique_pubkeys,
    COUNT(DISTINCT e.kind)::BIGINT AS unique_kinds
FROM relay AS r
LEFT JOIN event_relay AS er ON r.url = er.relay_url
LEFT JOIN event AS e ON er.event_id = e.id
GROUP BY r.network
ORDER BY relay_count DESC;
```

This removes the CTE entirely and computes true distinct counts at the network level. For large datasets, add a covering index `idx_event_relay_relay_url_event_id` to support the join efficiently.

---

## Medium Severity Findings

### M1. `deep_freeze` Leaves Lists Mutable

**File:** `src/bigbrotr/models/_validation.py`, lines 129-135

**Problem:** The `deep_freeze` function wraps dicts in `MappingProxyType` (immutable) but returns lists as regular mutable Python lists:

```python
def deep_freeze(obj: Any) -> Any:
    if isinstance(obj, dict):
        return MappingProxyType({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [deep_freeze(item) for item in obj]  # mutable list
    return obj
```

This means `metadata.data["supported_nips"].append(999)` would succeed, mutating the "frozen" dataclass's internal state.

**Solution:** Return `tuple` instead of `list` for true immutability:

```python
if isinstance(obj, list):
    return tuple(deep_freeze(item) for item in obj)
```

Update tests that compare against `list` values to compare against `tuple`.

---

### M2. `BaseService.run_forever()` Inconsistent `getattr` Fallback

**File:** `src/bigbrotr/core/base_service.py`, lines 235-238

**Problem:**

```python
interval = getattr(self._config, "interval", 300.0)
max_consecutive_failures = getattr(self._config, "max_consecutive_failures", 5)
metrics_enabled = self._config.metrics.enabled  # no fallback
```

Two attributes use defensive `getattr` with fallback defaults, but `metrics.enabled` is accessed directly. Since `ConfigT` is bound to `BaseServiceConfig`, all three attributes are guaranteed to exist. The `getattr` fallbacks are dead code.

**Solution:** Remove the `getattr` wrappers and access all three directly:

```python
interval = self._config.interval
max_consecutive_failures = self._config.max_consecutive_failures
metrics_enabled = self._config.metrics.enabled
```

---

### M3. One-Shot Mode Skips Service Lifecycle Context Manager

**File:** `src/bigbrotr/__main__.py`, lines 91-99

**Problem:** One-shot mode calls `service.run()` directly without entering `async with service:`:

```python
if once:
    try:
        await service.run()       # no async with service:
        ...

# Compare with continuous mode:
async with service:               # calls __aenter__ / __aexit__
    await service.run_forever()
```

`BaseService.__aenter__` clears the shutdown event and logs `"service_started"`. `__aexit__` sets the shutdown event and logs `"service_stopped"`. Both are skipped in one-shot mode, producing inconsistent structured log output.

**Solution:** Wrap one-shot mode in the context manager:

```python
if once:
    try:
        async with service:
            await service.run()
        logger.info(f"{service_name}_completed")
        return 0
    except Exception as e:
        logger.error(f"{service_name}_failed", error=str(e))
        return 1
```

---

### M4. `MetricsServer.stop()` Missing `try/finally`

**File:** `src/bigbrotr/core/metrics.py`, lines 166-174

**Problem:**

```python
async def stop(self) -> None:
    if self._runner:
        await self._runner.cleanup()
        self._runner = None
```

If `cleanup()` raises, `self._runner` is never reset to `None`, breaking the idempotency guarantee.

**Solution:**

```python
async def stop(self) -> None:
    if self._runner:
        try:
            await self._runner.cleanup()
        finally:
            self._runner = None
```

---

### M5. Exception Hierarchy Documented but Nonexistent

**File:** `CLAUDE.md` (Error Handling section)

**Problem:** CLAUDE.md documents an exception hierarchy with 10 exception classes (`BigBrotrError`, `ConfigurationError`, `DatabaseError`, `ConnectionPoolError`, `QueryError`, `ConnectivityError`, `RelayTimeoutError`, `RelaySSLError`, `ProtocolError`, `PublishingError`) and references `core/exceptions.py`. Neither the file nor any of these classes exist anywhere in the codebase. The project uses Python built-in exceptions exclusively (`OSError`, `TimeoutError`, `ValueError`, `asyncpg.PostgresError`, etc.).

**Solution:** Two options:

**Option A -- Implement the hierarchy** as documented, providing the typed error classification benefits described.

**Option B -- Update CLAUDE.md** to document the actual exception strategy (stdlib + library exceptions with catch patterns documented per-service). Remove the exception hierarchy table and `core/exceptions.py` from the Key Files table.

---

### M6. `parse_fields` Rebuilds Dispatch Dict on Every Call

**File:** `src/bigbrotr/nips/parsing.py`, lines 147-151

**Problem:**

```python
def parse_fields(data: dict[str, Any], spec: FieldSpec) -> dict[str, Any]:
    dispatch: dict[str, Callable[[Any], Any]] = {}
    for attr_name, parser in _FIELD_PARSERS:
        for name in getattr(spec, attr_name):
            dispatch[name] = parser
    ...
```

`FieldSpec` is a frozen dataclass with `frozenset` fields -- the dispatch map for a given spec never changes. Rebuilding it for every relay (thousands per cycle) is unnecessary.

**Solution:** Cache the dispatch map on the `FieldSpec` instance using `functools.lru_cache` or a lazy cached property:

```python
@functools.lru_cache(maxsize=8)
def _build_dispatch(spec: FieldSpec) -> dict[str, Callable[[Any], Any]]:
    dispatch: dict[str, Callable[[Any], Any]] = {}
    for attr_name, parser in _FIELD_PARSERS:
        for name in getattr(spec, attr_name):
            dispatch[name] = parser
    return dispatch
```

---

### M7. GeoIP `execute()` Dead Exception Catch

**File:** `src/bigbrotr/nips/nip66/geo.py`, lines 178-183 and 221-233

**Problem:** The `_geo()` static method catches `(geoip2.errors.GeoIP2Error, ValueError)` internally and returns `{}`. The `execute()` classmethod then catches the same exception types around `asyncio.to_thread(cls._geo, ...)`. Since `_geo()` never raises these exceptions (it swallows them), the outer catch is unreachable dead code.

Worse, this means `_geo()` silently returns `{}` on error, and `execute()` produces the generic reason `"no geo data found for IP"` instead of the specific error message that the outer catch would have provided.

**Solution:** Remove the inner catch in `_geo()` and let exceptions propagate to `execute()` where they get a proper reason message:

```python
@staticmethod
def _geo(ip: str, city_reader: ..., geohash_precision: int = 9) -> dict[str, Any]:
    response = city_reader.city(ip)
    return GeoExtractor.extract_all(response, geohash_precision=geohash_precision)
```

---

### M8. HTTP Test Creates SSL Context for Non-TLS Relays

**File:** `src/bigbrotr/nips/nip66/http.py`, lines 107-111

**Problem:**

```python
ssl_context = ssl.create_default_context()
if is_overlay or allow_insecure:
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE
```

`ssl.create_default_context()` loads system CA certificates from disk on every call. This happens even for `ws://` (non-TLS) relays where the SSL context is never used for a handshake.

**Solution:** Only create the context when TLS is needed:

```python
if relay.scheme == "wss":
    ssl_context = ssl.create_default_context()
    if is_overlay or allow_insecure:
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
else:
    ssl_context = False  # aiohttp: disable TLS entirely
```

---

### M9. `fetch_relay_events` Is Dead Code

**File:** `src/bigbrotr/utils/protocol.py`, lines 443-492

**Problem:** The `fetch_relay_events` async generator function is:
- Never imported anywhere in the codebase
- Never called from any production code
- Never tested (zero test references)
- Not exported via `__all__`

The Synchronizer service implements its own event fetching logic in `services/synchronizer/utils.py`. Additionally, `fetch_relay_events` has multiple defects: it uses `create_client` + bare `client.connect()` instead of `connect_relay` (no SSL fallback, no `wait_for_connection`, no `uniffi_set_event_loop`).

**Solution:** Delete `fetch_relay_events` and its docstring reference from the module-level docstring.

---

### M10. Monitor `_publish_if_due` Stores Float Timestamp

**File:** `src/bigbrotr/services/monitor/service.py`, lines 806-818

**Problem:**

```python
now = time.time()
await self._brotr.upsert_service_state([
    ServiceState(
        ...
        state_value={"timestamp": now},     # float (1708790400.123)
        updated_at=int(now),                 # int   (1708790400)
    ),
])
```

Every other service stores timestamps as `int` in `state_value` (e.g., `_persist_results` at line 731 uses `now = int(time.time())`). The mixed float/int creates an inconsistency within the same `ServiceState` record and across service state records.

**Solution:**

```python
now = int(time.time())
state_value={"timestamp": now}
updated_at=now
```

---

### M11. Validator Silent Exception Dropping from `gather`

**File:** `src/bigbrotr/services/validator/service.py`, lines 370-385

**Problem:**

```python
results = await asyncio.gather(*tasks, return_exceptions=True)

for candidate, result in zip(candidates, results, strict=True):
    if isinstance(result, asyncio.CancelledError):
        raise result
    if result is True:
        valid.append(candidate.relay)
    else:
        invalid.append(candidate)
```

When `result` is a non-`CancelledError` exception (e.g., `RuntimeError`, `TypeError`), it falls to the `else` branch. The candidate is silently classified as "invalid" with no logging of the actual exception. Programming errors are swallowed without any trace.

**Solution:** Add explicit exception detection before the `else` branch:

```python
for candidate, result in zip(candidates, results, strict=True):
    if isinstance(result, asyncio.CancelledError):
        raise result
    if isinstance(result, BaseException):
        self._logger.warning(
            "validation_exception", url=candidate.relay.url, error=str(result)
        )
        invalid.append(candidate)
    elif result is True:
        valid.append(candidate.relay)
    else:
        invalid.append(candidate)
```

---

### M12. Monitor Same Silent Exception Dropping Pattern

**File:** `src/bigbrotr/services/monitor/service.py`, lines 408-423

**Problem:** Identical to M11. The `_check_chunk` method uses `gather(return_exceptions=True)` and silently drops non-`CancelledError` exceptions into the `failed` list without logging.

**Solution:** Same pattern as M11 -- add `isinstance(result, BaseException)` check with warning log before the `else` branch.

---

### M13. `_get_publish_relays` Treats Empty List as None

**File:** `src/bigbrotr/services/monitor/service.py`, line 770

**Problem:**

```python
def _get_publish_relays(self, section_relays: list[Relay] | None) -> list[Relay]:
    return section_relays or self._config.publishing.relays
```

The `or` operator treats `[]` as falsy. If an operator explicitly configures `relays: []` for a section (intending to disable publishing for that section), the `or` ignores the empty list and falls back to the global publishing relays.

**Solution:** Use explicit `None` check:

```python
return section_relays if section_relays is not None else self._config.publishing.relays
```

---

### M14. `orphan_event_delete` Is Unbatched

**Files:**
- `deployments/bigbrotr/postgres/init/04_functions_cleanup.sql`, lines 65-82
- `deployments/lilbrotr/postgres/init/04_functions_cleanup.sql`, lines 65-82

**Problem:** `orphan_metadata_delete()` uses a batched loop with `LIMIT p_batch_size` (default 10,000 rows per iteration). `orphan_event_delete()` runs a single unbounded `DELETE`:

```sql
DELETE FROM event e
WHERE NOT EXISTS (
    SELECT 1 FROM event_relay er WHERE er.event_id = e.id
);
```

If a relay with millions of events is deleted, this single DELETE acquires locks on all affected rows simultaneously, generates substantial WAL, and blocks concurrent operations.

**Solution:** Add batching matching `orphan_metadata_delete`:

```sql
CREATE OR REPLACE FUNCTION orphan_event_delete(p_batch_size INTEGER DEFAULT 10000)
RETURNS INTEGER
LANGUAGE plpgsql
AS $$
DECLARE
    v_deleted INTEGER := 0;
    v_batch INTEGER;
BEGIN
    LOOP
        DELETE FROM event e WHERE e.id IN (
            SELECT e2.id FROM event e2
            WHERE NOT EXISTS (
                SELECT 1 FROM event_relay er WHERE er.event_id = e2.id
            )
            LIMIT p_batch_size
        );
        GET DIAGNOSTICS v_batch = ROW_COUNT;
        v_deleted := v_deleted + v_batch;
        EXIT WHEN v_batch < p_batch_size;
    END LOOP;
    RETURN v_deleted;
END;
$$;
```

---

### M15. LilBrotr Missing Critical Indexes for Synchronizer

**File:** `deployments/lilbrotr/postgres/init/08_indexes.sql`

**Problem:** Three indexes required by the Synchronizer service are present in bigbrotr but missing in lilbrotr:

| Index | Table | Purpose |
|-------|-------|---------|
| `idx_event_created_at_id` | `event` | Cursor-based pagination: `WHERE (created_at, id) > ($1, $2) ORDER BY created_at, id` |
| `idx_event_relay_seen_at` | `event_relay` | Recently discovered events: `ORDER BY seen_at DESC` |
| `idx_event_relay_relay_url_seen_at` | `event_relay` | Sync progress per relay: `WHERE relay_url = ? ORDER BY seen_at DESC` |

Additionally, lilbrotr has a redundant `idx_event_relay_event_id` on `event_relay(event_id)` that bigbrotr correctly omits (the composite primary key already provides this index).

**Solution:** Add the three missing indexes to lilbrotr's `08_indexes.sql` and drop the redundant one:

```sql
CREATE INDEX IF NOT EXISTS idx_event_created_at_id
    ON event (created_at ASC, id ASC);

CREATE INDEX IF NOT EXISTS idx_event_relay_seen_at
    ON event_relay (seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_event_relay_relay_url_seen_at
    ON event_relay (relay_url, seen_at DESC);

-- Remove redundant index (PK already covers event_id as leftmost column)
-- DROP INDEX IF EXISTS idx_event_relay_event_id;
```

---

### M16. BigBrotr Grafana `depends_on` Missing Health Check Condition

**File:** `deployments/bigbrotr/docker-compose.yaml`, lines 634-635

**Problem:**

```yaml
# bigbrotr (incomplete)
depends_on:
  - prometheus

# lilbrotr (correct)
depends_on:
  prometheus:
    condition: service_healthy
```

BigBrotr uses the short-form `depends_on` which only waits for container start, not health. LilBrotr correctly uses the long form with `service_healthy` condition.

**Solution:** Update bigbrotr to match:

```yaml
depends_on:
  prometheus:
    condition: service_healthy
```

---

### M17. LilBrotr SQL File Headers Say "Brotr" Instead of "LilBrotr"

**Files:**
- `deployments/lilbrotr/postgres/init/05_views.sql`, line 2
- `deployments/lilbrotr/postgres/init/06_materialized_views.sql`, line 2
- `deployments/lilbrotr/postgres/init/07_functions_refresh.sql`, line 2

**Problem:** These files were copied from bigbrotr without updating the header comment. Files 00-04, 08, 99 correctly use "LilBrotr".

**Solution:** Update all three headers from "Brotr" to "LilBrotr".

---

### M18. CLAUDE.md Refresher Service Not Documented

**File:** `CLAUDE.md`, lines 34, 42, 121-126

**Problem:** Multiple references to "5-service pipeline" and "5 services" need updating:
- Line 34: "Data flows through a 5-service pipeline"
- Line 42: "5 services, each with a precise role"
- Lines 121-126: Service pipeline diagram lists only 5 services
- The Key Files table has no Refresher entry

**Solution:** Update all references to include the Refresher. Change "5-service pipeline" to "6-service pipeline". Add Refresher to the pipeline diagram and key files table. Add a note that Refresher is a maintenance service (materialized view refresh) rather than a pipeline stage.

---

### M19. CLAUDE.md Test Count Outdated

**File:** `CLAUDE.md`, line 231

**Problem:** States "2063 unit tests + 8 integration tests". Actual count is ~2,340 unit tests + ~94 integration tests.

**Solution:** Update to approximate counts that will remain accurate longer: "~2,400 unit tests + ~90 integration tests".

---

### M20. CLAUDE.md `BrotrTimeoutsConfig` Name Wrong

**File:** `CLAUDE.md`, line 255

**Problem:** References `BrotrTimeoutsConfig`. The actual class name is `TimeoutsConfig` (defined in `core/brotr.py` line 78).

**Solution:** Change `BrotrTimeoutsConfig` to `TimeoutsConfig`.

---

### M21. CLAUDE.md Import Path Wrong

**File:** `CLAUDE.md`, line 156

**Problem:** Shows `from bigbrotr.utils.transport import connect_relay, is_nostr_relay`. Both `connect_relay` and `is_nostr_relay` are in `bigbrotr.utils.protocol`, not `transport`.

**Solution:** Change to `from bigbrotr.utils.protocol import connect_relay, is_nostr_relay`.

---

### M22. PostgreSQL Guide Contradicts CLAUDE.md on Timeout Parameters

**Files:**
- `CLAUDE.md`, line 201
- `.claude/guides/postgresql.md`, lines 69, 75-80, 88

**Problem:** CLAUDE.md says "query functions never accept `timeout` parameters". The PostgreSQL guide says "Always pass `timeout=` on all Brotr/Pool method calls" and shows example signatures with `*, timeout: float | None = None`. The actual code confirms CLAUDE.md is correct -- no query function accepts a timeout parameter.

**Solution:** Update `postgresql.md` to match reality. Remove `timeout` from example signatures. Change the guidance to explain that timeouts are config-driven via `TimeoutsConfig` at the Brotr level.

---

### M23. PostgreSQL Guide Function Count Wrong

**File:** `.claude/guides/postgresql.md`, line 32

**Problem:** States "All 21 functions" but CLAUDE.md correctly says 25 (1 utility + 10 CRUD + 2 cleanup + 12 refresh = 25).

**Solution:** Change "21" to "25".

---

### M24. Architecture Guide Mixin Names Outdated

**File:** `.claude/guides/architecture-extensibility.md`, lines 361-378

**Problem:** Lists mixins as `BatchProgressMixin` and `NetworkSemaphoreMixin`. The actual names are `ChunkProgressMixin`, `NetworkSemaphoresMixin` (plural), and `GeoReaderMixin` (not mentioned at all). The init example shows manual `_init_progress()` / `_init_semaphores()` calls, but the cooperative inheritance pattern eliminates these.

**Solution:** Update mixin names and remove the manual init example. Replace with cooperative inheritance pattern from the mixins module docstring.

---

### M25. `Refresher`/`RefresherConfig` Missing from Top-Level Package Exports

**File:** `src/bigbrotr/__init__.py`

**Problem:** All 5 pipeline services and their configs are in `__all__` and `_LAZY_IMPORTS`, but `Refresher` and `RefresherConfig` are omitted despite being exported from `services/__init__.py` and registered in `__main__.py`.

**Solution:** Add to `__all__` and `_LAZY_IMPORTS`:

```python
"Refresher": ("bigbrotr.services", "Refresher"),
"RefresherConfig": ("bigbrotr.services", "RefresherConfig"),
```

---

## Low Severity Findings

### L1. `Relay.raw_url` Participates in Equality

**File:** `src/bigbrotr/models/relay.py`, line 121

**Problem:** `raw_url` has `repr=False` but not `compare=False`. Two relays with different casing (`"WSS://Relay.Example.Com"` vs `"wss://relay.example.com"`) that normalize to the same `url` compare as unequal.

**Solution:** Add `compare=False` to the field: `raw_url: str = field(repr=False, compare=False)`.

---

### L2. `_transpose_to_columns` Uses `strict=False`

**File:** `src/bigbrotr/core/brotr.py`, line 308

**Problem:** Uses `zip(*params, strict=False)` despite the lines above explicitly validating that all rows have equal length. `strict=True` would be the correct defensive choice.

**Solution:** Change to `strict=True`.

---

### L3. `_VALID_PROCEDURE_NAME` Docstring Inaccuracy

**File:** `src/bigbrotr/core/brotr.py`, lines 311, 328

**Problem:** Docstring says "case-insensitive" but the regex `r"^[a-z_][a-z0-9_]*$"` has no `re.IGNORECASE` flag.

**Solution:** Remove "(case-insensitive)" from the docstring.

---

### L4. Logger Double Truncation Path

**File:** `src/bigbrotr/core/logger.py`, lines 82-83, 112-117, 204-209

**Problem:** Values are truncated in `_make_extra()` before being passed to `format_kv_pairs()` which has its own truncation logic. Currently the second truncation is a no-op (default `max_value_length=None`), but the architecture has two redundant truncation points.

**Solution:** Remove truncation from `_make_extra()` and rely solely on `format_kv_pairs()`, or pass `max_value_length=None` explicitly in `StructuredFormatter.format()` to make the intent clear.

---

### L5. `upsert_service_state` Returns Assumed Count

**File:** `src/bigbrotr/core/brotr.py`, lines 798-806

**Problem:** Uses `fetch_result=False` and returns `len(records)` as the upserted count. Unlike all other insert methods that use `fetch_result=True` to get the confirmed count from the database.

**Solution:** Either use `fetch_result=True` for consistency, or add a comment documenting that the return value is the attempted count.

---

### L6. `supported_nips` Not Deduplicated

**File:** `src/bigbrotr/nips/nip11/data.py`, lines 336-341

**Problem:** Duplicate NIP values (e.g., `[1, 1, 11, 11]`) are preserved as-is, causing duplicate `N` tags in Kind 30166 events.

**Solution:** Add deduplication: `result["supported_nips"] = sorted(set(nips))`.

---

### L7. Dict-Based `CertificateExtractor` Methods Are Dead Code

**File:** `src/bigbrotr/nips/nip66/ssl.py`, lines 56-163

**Problem:** `CertificateExtractor.extract_all()` and its helpers (`extract_subject_cn`, `extract_issuer`, `extract_validity`, `extract_san`, `extract_serial_and_version`) are never called from production code. Production uses `extract_all_from_x509()` exclusively. The dict-based methods are only exercised by tests.

**Solution:** Remove the dict-based methods and their tests, or move them to a test utilities module if they serve a testing purpose.

---

### L8. `_StderrSuppressor` Blankets All stderr

**File:** `src/bigbrotr/utils/protocol.py`, lines 131-147

**Problem:** During `is_nostr_relay`, ALL stderr output is redirected to `/dev/null` -- including output from asyncpg, aiohttp, and other libraries. This is a global side-effect that persists across `await` boundaries.

**Solution:** Narrow the suppression to only the specific nostr-sdk calls, or accept the tradeoff with a documented rationale.

---

### L9. `_NostrSdkStderrFilter` Can Get Stuck in Suppression Mode

**File:** `src/bigbrotr/utils/transport.py`, lines 81-92

**Problem:** The filter enters suppression on `"UniFFI:"` or `"Unhandled exception"` and only exits on an empty line. A malformed traceback without a trailing blank line causes permanent suppression of all stderr.

**Solution:** Add a maximum suppressed line count:

```python
_MAX_SUPPRESSED_LINES: int = 50

def write(self, text: str) -> int:
    if "UniFFI:" in text or "Unhandled exception" in text:
        self._suppressing = True
        self._suppressed_count = 0
        return len(text)
    if self._suppressing:
        self._suppressed_count += 1
        if text.strip() == "" or text == "\n" or self._suppressed_count > self._MAX_SUPPRESSED_LINES:
            self._suppressing = False
        return len(text)
    return self._original.write(text)
```

---

### L10. `models_from_dict` Missing `KeyError` in Exception List

**File:** `src/bigbrotr/utils/parsing.py`, lines 67-70

**Problem:** Only catches `(ValueError, TypeError)`. If a factory lambda accesses a missing dict key, `KeyError` propagates unhandled, breaking the entire batch instead of skipping the invalid row.

**Solution:** Add `KeyError` to both `models_from_db_params` and `models_from_dict`:

```python
except (ValueError, TypeError, KeyError):
```

---

### L11. `Synchronizer.insert_batch` Returns Hardcoded 0 for `skipped_events`

**File:** `src/bigbrotr/services/synchronizer/utils.py`, line 259

**Problem:** `return total_inserted, invalid_count, 0` -- the third element is always 0. The `SyncCycleCounters.skipped_events` gauge always reports 0.

**Solution:** Either implement the skipped count or remove it from the return type and counters.

---

### L12. Seeder `parse_seed_file` Only Catches `FileNotFoundError`

**File:** `src/bigbrotr/services/seeder/utils.py`, lines 49-50

**Problem:** `PermissionError`, `IsADirectoryError`, and `UnicodeDecodeError` propagate unhandled.

**Solution:** Widen to `except OSError:` or `except (FileNotFoundError, PermissionError, OSError):`.

---

### L13. `NetworksConfig.get()` Silent Clearnet Fallback

**File:** `src/bigbrotr/services/common/configs.py`, line 165

**Problem:** `getattr(self, network.value, self.clearnet)` silently returns clearnet config for unrecognized network types with no warning.

**Solution:** Add a warning log for unexpected fallbacks:

```python
def get(self, network: NetworkType) -> NetworkTypeConfig:
    config = getattr(self, network.value, None)
    if config is None:
        logger.warning("no config for network=%s, falling back to clearnet", network.value)
        return self.clearnet
    return config
```

---

### L14. `NIP-11 aiohttp.ClientSession` Created Per Request

**File:** `src/bigbrotr/nips/nip11/info.py`, lines 113-114

**Problem:** Each NIP-11 fetch creates a new `aiohttp.ClientSession` with its own `TCPConnector` and DNS cache. For thousands of relays per cycle, this is wasteful.

**Solution:** Accept an optional shared session parameter, or document this as an intentional isolation trade-off.

---

### L15. Missing `Event.from_db_params()` Roundtrip Test

**File:** `tests/unit/models/test_event.py`, lines 436-451

**Problem:** The `TestFromDbParams.test_roundtrip_structure` test checks output types of `to_db_params()` but never calls `Event.from_db_params()`. All other models (Relay, Metadata) have proper roundtrip tests.

**Solution:** Add a true roundtrip test:

```python
def test_roundtrip(self, event):
    params = event.to_db_params()
    reconstructed = Event.from_db_params(params)
    assert reconstructed.id == event.id
    assert reconstructed.created_at == event.created_at
    assert reconstructed.kind == event.kind
```

---

### L16. Delegation Tests Assert Exact Mock Call Counts

**File:** `tests/unit/models/test_event.py`, lines 277-339

**Problem:** Tests assert `assert mock_nostr_event.id.call_count == 3`. These counts are tightly coupled to `__post_init__` implementation details and break when internal validation steps change.

**Solution:** Assert `call_count >= 1` or test return values instead of call counts.

---

### L17. `SyncCycleCounters` Created Twice

**File:** `src/bigbrotr/services/synchronizer/service.py`, line 123 and line 139

**Problem:** `self._counters = SyncCycleCounters()` is called in `__init__` (with an `asyncio.Lock` created outside the event loop), then immediately replaced in `run()`.

**Solution:** Remove the initialization from `__init__`. Initialize only in `run()`.

---

### L18. `services/common/__init__.py` Docstring Says "Five" Services

**File:** `src/bigbrotr/services/common/__init__.py`, line 1

**Problem:** Says "all five pipeline services" -- should be six.

**Solution:** Update to "six".

---

### L19. `pyproject.toml` `asyncpg` in mypy `ignore_missing_imports`

**File:** `pyproject.toml`, lines 205-218

**Problem:** `asyncpg.*` is in the mypy ignore list despite `asyncpg-stubs` being installed as a dev dependency. This suppresses all type-checking benefits from the stubs.

**Solution:** Remove `"asyncpg.*"` from the `ignore_missing_imports` override.

---

### L20. `pyproject.toml` `__main__.*` Blanket `ignore_errors`

**File:** `pyproject.toml`, lines 224-226

**Problem:** `ignore_errors = true` for `__main__.*` silences all mypy errors in the CLI entry point.

**Solution:** Remove the override and fix any surfaced mypy errors with targeted `type: ignore` comments.

---

### L21. Pre-Commit mypy Hook Missing Dependencies

**File:** `.pre-commit-config.yaml`, lines 76-93

**Problem:** The mypy hook's `additional_dependencies` is missing `dnspython`, `tldextract`, and `cryptography`, which can cause `import-not-found` errors in the isolated pre-commit environment.

**Solution:** Add the missing dependencies to match `pyproject.toml`.

---

### L22. PGBouncer Userlist Uses Plaintext Passwords

**Files:**
- `deployments/bigbrotr/pgbouncer/entrypoint.sh`, lines 12-16
- `deployments/lilbrotr/pgbouncer/entrypoint.sh`, lines 12-16

**Problem:** The entrypoint writes plaintext passwords to `/tmp/pgbouncer/userlist.txt`. PGBouncer's `auth_type = scram-sha-256` means passwords should ideally be SCRAM hashes.

**Solution:** Use `auth_query` to delegate authentication to PostgreSQL (eliminating the userlist file entirely), or generate SCRAM-SHA-256 hashes in the entrypoint script.

---

### L23. `domain-model.md` Wrong Field Name

**File:** `.claude/guides/domain-model.md`, line 193

**Problem:** Shows `value={"last_synced_at": ...}`. The correct column name is `state_value`.

**Solution:** Change `value=` to `state_value=`.

---

### L24. Domain Model Guide Missing Refresher in Pipeline

**File:** `.claude/guides/domain-model.md`, line 11

**Problem:** Pipeline diagram shows 5 stages without Refresher.

**Solution:** Add Refresher as a maintenance service alongside the pipeline.

---

## Positive Observations

The review identified numerous strengths that deserve recognition:

1. **Diamond DAG strictly enforced.** No cross-layer import violations. Models have zero `bigbrotr` imports.
2. **Consistent async patterns.** Proper `CancelledError` handling, correct `gather(return_exceptions=True)` usage (with the logged caveats above), clean shutdown via `wait()` and shutdown events.
3. **Content-addressed metadata.** SHA-256 hashing with hash verification on reconstruction from DB -- data integrity by design.
4. **SQL injection prevention.** Regex-validated procedure names, `$1`/`$2` parameterized queries throughout. No f-string SQL anywhere.
5. **Mock targeting is correct.** All `@patch` decorators target the consumer's namespace, never the source module.
6. **Test suite is substantive.** Zero vacuous assertions, no `assert True` or pass-only test bodies. Every test has meaningful checks.
7. **Integration tests are excellent.** Session-scoped testcontainers with per-test schema isolation (DROP CASCADE + recreate).
8. **Graceful shutdown.** All services check `self.is_running` and use `self.wait()` for interruptible sleeps.
9. **Fail-fast validation.** Invalid model instances never escape the constructor.
10. **Cooperative mixin inheritance.** Clean MRO with `super().__init__(**kwargs)` -- no diamond inheritance bugs.
