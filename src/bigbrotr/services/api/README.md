# api

HTTP adapter for public readable-resource exposure.

## Main Files

- `service.py`: FastAPI service lifecycle and adapter wiring.
- `routes.py`: route registration for discovery and data endpoints.
- `read_models.py`: HTTP handlers that delegate into the shared read core.
- `configs.py`: adapter configuration and exposure-policy surface.

## Rules

- Preserve the stable `/read-models` transport contract unless a deliberate
  breaking change is approved.
- Keep HTTP adapter logic thin over `services/common`.
