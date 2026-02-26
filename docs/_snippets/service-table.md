| Service | Role | Mode |
|---------|------|------|
| **Seeder** | Bootstraps initial relay URLs from a seed file | One-shot |
| **Finder** | Discovers new relays from events and external APIs | Continuous |
| **Validator** | Verifies URLs are live Nostr relays via WebSocket | Continuous |
| **Monitor** | Runs NIP-11 + NIP-66 health checks, publishes kind 10166/30166 events | Continuous |
| **Synchronizer** | Collects events from relays using cursor-based pagination | Continuous |
| **Refresher** | Refreshes materialized views for analytics queries | Continuous |
