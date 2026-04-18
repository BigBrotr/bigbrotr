# core

Shared runtime infrastructure for the service layer and library consumers.

## Main Files

- `pool.py`, `pool_config.py`: async PostgreSQL pool and configuration.
- `brotr.py`, `brotr_config.py`: shared database facade and config.
- `base_service.py`, `service_runtime.py`: service lifecycle and CLI/runtime
  helpers.
- `deployments.py`: built-in deployment and storage-profile contracts.
- `logger.py`, `metrics.py`, `yaml.py`: structured logging, metrics, and config
  loading.

## Rules

- Keep this layer free of service-specific business logic.
- Public runtime contracts belong here only when they are genuinely shared.
