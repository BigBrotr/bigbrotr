# API Reference

Auto-generated API documentation from source code docstrings.

## Package Structure

```
bigbrotr/
├── core/       Pool, Brotr, BaseService, Exceptions, Logger, Metrics
├── models/     Frozen dataclasses: Relay, Event, Metadata, ServiceState
├── nips/       NIP-11 (relay info) and NIP-66 (monitoring metadata)
├── utils/      DNS, keys, transport (WebSocket/HTTP)
└── services/   Pipeline: Seeder, Finder, Validator, Monitor, Synchronizer
```

## Modules

| Module | Description |
|--------|-------------|
| [Core](core.md) | Connection pool, database facade, base service, exceptions, logging, metrics |
| [Models](models.md) | Pure frozen dataclasses with zero I/O -- relay, event, metadata, service state |
| [NIPs](nips.md) | NIP-11 relay information document, NIP-66 relay monitoring metadata |
| [Utils](utils.md) | DNS resolution, Nostr key management, WebSocket/HTTP transport |
| [Services](services.md) | Business logic -- the five-service processing pipeline |
