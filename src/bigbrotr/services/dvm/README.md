# dvm

NIP-90 adapter for public readable-resource queries over Nostr.

## Main Files

- `service.py`: adapter lifecycle and read-core integration.
- `jobs.py`, `subscriptions.py`: request ingestion and subscription handling.
- `publishing.py`, `utils.py`: result-event and feedback construction.
- `configs.py`: relay, pricing, and exposure-policy configuration.

## Rules

- Preserve the stable `read_model` request parameter for transport
  compatibility.
- Keep NIP-90 transport concerns here and shared read semantics in
  `services/common`.
