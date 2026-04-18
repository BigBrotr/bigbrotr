# utils

Shared low-level helpers for transport, DNS, keys, HTTP, and streaming.

## Main Files

- `protocol.py`: public Nostr client facade for connection, validation,
  sessions, and publication.
- `protocol_*.py`, `transport.py`: split implementation seams for client
  construction, connection fallback, sessions, manager logic, validation, and
  publication.
- `dns.py`, `http.py`, `keys.py`: external I/O support helpers.
- `streaming.py`: bounded event-stream helpers used by archive flows.

## Rules

- Keep this package generic and reusable.
- Domain ownership should stay in higher layers; these helpers should not
  encode service-specific workflow decisions.
- Do not introduce upward `core` or `services` dependencies into this package
  surface.
