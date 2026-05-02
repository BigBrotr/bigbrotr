# Glossary

This glossary defines the terms used across the documentation and source.

| Term | Meaning | Related docs |
| --- | --- | --- |
| Relay | A validated Nostr relay URL stored in `relay`. | [Database](../user-guide/database.md#relay) |
| Candidate | A discovered relay URL awaiting validation, stored in `service_state`. | [Validator](../user-guide/services.md#validator) |
| Observation | A fact that an event was seen at a relay at a specific time. | [Database](../user-guide/database.md#event_observation) |
| Document | Content-addressed JSON payload, usually NIP-11 or NIP-66 check output. | [Database](../user-guide/database.md#document) |
| Current table | Narrow winner-map table maintained by Refresher. | [Database](../user-guide/database.md#schema-map) |
| Analytics table | Refresh-maintained summary table for read-side and operational use. | [Database](../user-guide/database.md#schema-map) |
| Readable resource | Public read-side resource exposed by API and DVM. | [Read Side](../user-guide/read-side.md) |
| ReadCore | Protocol-agnostic read engine shared by API and DVM. | [Read Side](../user-guide/read-side.md) |
| NIP-85 fact | Derived fact used to build trusted assertions. | [NIP-85 Pipeline](../user-guide/nip85-pipeline.md) |
| Score table | Public PostgreSQL score snapshot exported by Ranker. | [NIP-85 Pipeline](../user-guide/nip85-pipeline.md) |
| Provider package | NIP-85 publication package emitted by Assertor. | [Assertor](../user-guide/services.md#assertor) |
| Storage profile | Deployment-level storage shape, such as full archive or lightweight archive. | [Deployments](../user-guide/deployments.md) |
| Service state | Shared PostgreSQL key/value table for small operational state. | [Database](../user-guide/database.md#service_state) |
| DuckDB rank store | Ranker's private analytical database file. | [Ranker](../user-guide/services.md#ranker) |

Related pages:

- [Project Orientation](index.md)
- [Repository Map](repository-map.md)
- [Data Flow](data-flow.md)
