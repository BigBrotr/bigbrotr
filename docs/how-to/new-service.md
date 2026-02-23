# Adding a New Service

Create, register, and test a custom BigBrotr service. This guide walks through the full process using a hypothetical "Pruner" service that removes stale data.

---

## Overview

Every BigBrotr service follows the same pattern:

1. A **config class** (Pydantic model extending `BaseServiceConfig`)
2. A **service class** (extending `BaseService[ConfigT]`)
3. A **registry entry** in `__main__.py`
4. A **YAML config file** per deployment
5. **Tests** in `tests/unit/services/`

## Step 1: Create the Service Module

Create `src/bigbrotr/services/pruner.py`:

```python
"""Pruner service -- removes stale relay metadata on a schedule."""

from bigbrotr.core.base_service import BaseService, BaseServiceConfig
from bigbrotr.models.constants import ServiceName

from pydantic import Field


class PrunerConfig(BaseServiceConfig):
    """Configuration for the Pruner service."""

    interval: float = Field(default=86400.0, ge=60.0)
    max_age_days: int = Field(default=90, ge=1, le=365)
    batch_size: int = Field(default=1000, ge=100, le=10000)
    dry_run: bool = False


class Pruner(BaseService[PrunerConfig]):
    """Removes relay metadata older than a configured threshold."""

    SERVICE_NAME = ServiceName.PRUNER
    CONFIG_CLASS = PrunerConfig

    async def run(self) -> None:
        """Execute one pruning cycle."""
        self._logger.info(
            "cycle_started",
            max_age_days=self._config.max_age_days,
            dry_run=self._config.dry_run,
        )

        deleted = await self._brotr.execute(
            "SELECT relay_metadata_delete_expired($1, $2)",
            self._config.max_age_days,
            self._config.batch_size,
        )

        self._logger.info("cycle_completed", deleted=deleted)
```

!!! warning "Use `CONFIG_CLASS`, not `config_class`"
    The class variable must be uppercase `CONFIG_CLASS` to match the `BaseService` declaration. Using lowercase `config_class` will silently fail -- the service will use default `BaseServiceConfig` values instead of your custom config.

## Step 2: Add the Service Name

Add the new name to `src/bigbrotr/models/constants.py`:

```python
class ServiceName(StrEnum):
    SEEDER = "seeder"
    FINDER = "finder"
    VALIDATOR = "validator"
    MONITOR = "monitor"
    SYNCHRONIZER = "synchronizer"
    PRUNER = "pruner"  # new
```

## Step 3: Register in `__main__.py`

Add the import and registry entry to `src/bigbrotr/__main__.py`:

```python
from bigbrotr.services.pruner import Pruner

SERVICE_REGISTRY: dict[str, ServiceEntry] = {
    # ... existing entries ...
    ServiceName.PRUNER: ServiceEntry(
        Pruner, CONFIG_BASE / "services" / "pruner.yaml"
    ),
}
```

## Step 4: Create the YAML Config File

Create `deployments/bigbrotr/config/services/pruner.yaml`:

```yaml
interval: 86400.0          # Run once per day

max_age_days: 90            # Remove metadata older than 90 days
batch_size: 1000            # Delete in batches of 1000
dry_run: false              # Set true to log without deleting

metrics:
  enabled: true
  port: 8005
```

!!! tip
    Copy the config to every deployment that needs the service. The `_template` deployment should contain a fully commented version of all defaults.

## Step 5: Write Tests

Create `tests/unit/services/test_pruner.py`:

```python
"""Tests for the Pruner service."""

from unittest.mock import AsyncMock

import pytest

from bigbrotr.services.pruner import Pruner, PrunerConfig


class TestPrunerConfig:
    """Test PrunerConfig validation."""

    def test_defaults(self):
        config = PrunerConfig()
        assert config.interval == 86400.0
        assert config.max_age_days == 90
        assert config.batch_size == 1000
        assert config.dry_run is False

    def test_interval_minimum(self):
        with pytest.raises(Exception):
            PrunerConfig(interval=10.0)

    def test_max_age_days_range(self):
        config = PrunerConfig(max_age_days=30)
        assert config.max_age_days == 30


class TestPruner:
    """Test Pruner service logic."""

    async def test_run_executes_delete(self, mock_brotr):
        mock_brotr.execute = AsyncMock(return_value="DELETE 500")
        config = PrunerConfig(max_age_days=30)
        service = Pruner(brotr=mock_brotr, config=config)

        await service.run()

        mock_brotr.execute.assert_called_once()

    async def test_service_name(self, mock_brotr):
        service = Pruner(brotr=mock_brotr)
        assert service.SERVICE_NAME == "pruner"
```

## Step 6: Run Checks

```bash
# Lint and type-check
ruff check src/bigbrotr/services/pruner.py
mypy src/bigbrotr

# Run your tests
pytest tests/unit/services/test_pruner.py -v

# Run the full CI suite
make ci
```

## Step 7: Test the Service Locally

```bash
cd deployments/bigbrotr

# One-shot mode
python -m bigbrotr pruner --once --log-level DEBUG

# Continuous mode
python -m bigbrotr pruner --log-level DEBUG
```

## Service Lifecycle Reference

`BaseService` provides the following lifecycle automatically:

| Method | Purpose |
|--------|---------|
| `run()` | Override this -- your main logic for one cycle |
| `run_forever()` | Calls `run()` in a loop with interval sleeping |
| `request_shutdown()` | Signals the service to stop gracefully |
| `is_running` | Property: `True` until shutdown is requested |
| `wait(timeout)` | Interruptible sleep (use instead of `asyncio.sleep`) |
| `from_yaml(path, brotr)` | Factory: load config from YAML and instantiate |
| `from_dict(data, brotr)` | Factory: load config from a dictionary |

The `run_forever()` loop also tracks Prometheus metrics (cycle counts, durations, failure counters) and enforces `max_consecutive_failures`.

---

## Related Documentation

- [Custom Deployment](custom-deployment.md) -- add the service to a new deployment
- [Monitoring Setup](monitoring-setup.md) -- verify metrics for the new service
- [Troubleshooting](troubleshooting.md) -- debug service startup issues
