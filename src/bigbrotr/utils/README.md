# utils

Shared low-level helpers for transport, DNS, keys, HTTP, and streaming.

## Main Files

- `protocol*.py`, `transport.py`: Nostr transport, client lifecycle, and
  publication helpers.
- `dns.py`, `http.py`, `keys.py`: external I/O support helpers.
- `streaming.py`: bounded event-stream helpers used by archive flows.

## Rules

- Keep this package generic and reusable.
- Domain ownership should stay in higher layers; these helpers should not
  encode service-specific workflow decisions.
