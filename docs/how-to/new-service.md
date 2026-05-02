# Adding a New Service

Create, register, configure, and test a custom BigBrotr service. This guide
uses a hypothetical `RelayReporter` service that logs the current relay count
once per cycle.

---

## Overview

Every built-in BigBrotr service follows the same package-level pattern:

1. A **service package** in `src/bigbrotr/services/<service_name>/`
2. A **config model** extending `BaseServiceConfig`
3. A **service class** extending `BaseService[ConfigT]`
4. A **package export** in `__init__.py`
5. A **registry entry** in `src/bigbrotr/services/registry.py`
6. A **YAML config file** per deployment
7. **Unit tests** in `tests/unit/services/`

If the service becomes a first-class built-in, it should also get:

- a `ServiceName` enum member in `src/bigbrotr/models/constants.py`
- deployment-specific docs and README updates
- any query/config helper modules it needs

---

## Step 1: Create the Service Package

Create a new package:

```text
src/bigbrotr/services/relay_reporter/
├── __init__.py
├── configs.py
└── service.py
```

### `configs.py`

```python
from __future__ import annotations

from pydantic import Field

from bigbrotr.core.base_service import BaseServiceConfig


class RelayReporterConfig(BaseServiceConfig):
    """Configuration for the RelayReporter service."""

    interval: float = Field(
        default=3600.0,
        ge=60.0,
        description="Seconds between relay-count reports",
    )
```

### `service.py`

```python
from __future__ import annotations

from typing import ClassVar

from bigbrotr.core.base_service import BaseService
from bigbrotr.models.constants import ServiceName

from .configs import RelayReporterConfig


class RelayReporter(BaseService[RelayReporterConfig]):
    """Logs the number of canonical relay rows currently stored."""

    SERVICE_NAME: ClassVar[ServiceName] = ServiceName.RELAY_REPORTER
    CONFIG_CLASS: ClassVar[type[RelayReporterConfig]] = RelayReporterConfig

    async def run(self) -> None:
        relay_count = await self._brotr.fetchval("SELECT COUNT(*) FROM relay")
        self._logger.info("cycle_completed", relay_count=int(relay_count or 0))
```

### `__init__.py`

```python
"""RelayReporter service package."""

from .configs import RelayReporterConfig
from .service import RelayReporter

__all__ = ["RelayReporter", "RelayReporterConfig"]
```

!!! warning "Use `CONFIG_CLASS`, not `config_class`"
    The class variable must be uppercase `CONFIG_CLASS` to match the
    `BaseService` contract. Using lowercase `config_class` will silently bypass
    your typed config model.

---

## Step 2: Add the Service Name

Add the new member to `src/bigbrotr/models/constants.py`:

```python
class ServiceName(StrEnum):
    SEEDER = "seeder"
    FINDER = "finder"
    VALIDATOR = "validator"
    MONITOR = "monitor"
    SYNCHRONIZER = "synchronizer"
    REFRESHER = "refresher"
    RANKER = "ranker"
    API = "api"
    DVM = "dvm"
    ASSERTOR = "assertor"
    RELAY_REPORTER = "relay_reporter"
```

If the service is only experimental or deployment-local, you can keep
`SERVICE_NAME` as a plain string, but built-in services should use the enum so
logging, metrics, and service-state usage stay consistent.

---

## Step 3: Register the Service

Add the package to `src/bigbrotr/services/registry.py`:

```python
SERVICE_REGISTRY: dict[str, ServiceEntry] = {
    # ... existing services ...
    "relay_reporter": ServiceEntry(
        service_module="bigbrotr.services.relay_reporter",
        service_class_name="RelayReporter",
        config_path=CONFIG_BASE / "services" / "relay_reporter.yaml",
    ),
}
```

This makes the service runnable through the shared CLI:

```bash
python -m bigbrotr relay_reporter --profile bigbrotr --once
```

---

## Step 4: Add Deployment Config

Create a deployment config such as
`deployments/bigbrotr/config/services/relay_reporter.yaml`:

```yaml
interval: 3600.0

metrics:
  enabled: true
  port: 8010
```

Copy or adapt the config for every deployment that should expose the service.

When running locally, prefer the deployment profile:

```bash
python -m bigbrotr relay_reporter --profile bigbrotr --once
```

For a custom deployment folder, pass explicit config paths:

```bash
python -m bigbrotr relay_reporter \
  --brotr-config deployments/myproject/config/brotr.yaml \
  --config deployments/myproject/config/services/relay_reporter.yaml \
  --once
```

---

## Step 5: Write Unit Tests

Create `tests/unit/services/test_relay_reporter.py`:

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from bigbrotr.models.constants import ServiceName
from bigbrotr.services.relay_reporter import RelayReporter, RelayReporterConfig


class TestRelayReporterConfig:
    def test_defaults(self) -> None:
        config = RelayReporterConfig()
        assert config.interval == 3600.0


class TestRelayReporter:
    async def test_run_logs_relay_count(self, mock_brotr) -> None:
        mock_brotr.fetchval = AsyncMock(return_value=42)
        service = RelayReporter(
            brotr=mock_brotr,
            config=RelayReporterConfig(interval=600.0),
        )
        service._logger.info = MagicMock()

        await service.run()

        mock_brotr.fetchval.assert_awaited_once_with("SELECT COUNT(*) FROM relay")
        service._logger.info.assert_called_once_with("cycle_completed", relay_count=42)

    async def test_service_name(self, mock_brotr) -> None:
        service = RelayReporter(brotr=mock_brotr)
        assert service.SERVICE_NAME is ServiceName.RELAY_REPORTER
```

Adapt the assertions to the real side effects of your service. For services
that write state, publish events, or call external systems, assert the
observable boundary behavior rather than private implementation details.

---

## Step 6: Run Checks

```bash
# Lint and type-check the new package
ruff check src/bigbrotr/services/relay_reporter/ tests/unit/services/test_relay_reporter.py
mypy src/bigbrotr

# Run focused tests first
pytest tests/unit/services/test_relay_reporter.py -v

# Then run the full CI suite
make ci
uv lock --check
```

---

## Step 7: Test the Service Locally

```bash
# One-shot mode
python -m bigbrotr relay_reporter --profile bigbrotr --once --log-level DEBUG

# Continuous mode
python -m bigbrotr relay_reporter --profile bigbrotr --log-level DEBUG
```

---

## Service Lifecycle Reference

`BaseService` provides the following lifecycle automatically:

| Method | Purpose |
|--------|---------|
| `run()` | Override this with one bounded service cycle |
| `run_forever()` | Calls `run()` in a loop with interval sleeping |
| `request_shutdown()` | Signals the service to stop gracefully |
| `is_running` | `True` until shutdown is requested |
| `wait(timeout)` | Interruptible sleep helper |
| `from_yaml(path, brotr)` | Factory: load config from YAML and instantiate |
| `from_dict(data, brotr)` | Factory: load config from a dictionary |

The shared CLI handles:

- config loading
- pool overrides
- metrics server startup
- one-shot vs continuous execution
- graceful shutdown on interruption

---

## Design Checklist

Before considering a new service complete, verify:

- the service has a clear bounded responsibility
- all database access goes through `Brotr` or service query modules
- batch operations remain bounded for very large datasets
- config has strong validation and reasonable defaults
- logs and metrics expose useful operational signals
- tests cover success paths, validation failures, and critical boundaries
- deployment and service docs are updated if the service becomes first-class

---

## Related Documentation

- [Custom Deployment](custom-deployment.md) — add the service to a new deployment
- [Monitoring Setup](monitoring-setup.md) — verify metrics for the new service
- [Troubleshooting](troubleshooting.md) — debug service startup issues
