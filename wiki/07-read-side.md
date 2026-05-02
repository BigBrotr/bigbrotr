# Read Side

BigBrotr exposes data through a shared read core used by both API and DVM.

## Components

| Component | Purpose |
| --- | --- |
| `read_model_registry.py` | Defines public readable resource metadata. |
| `catalog_discovery.py` | Discovers backing database resources. |
| `catalog_planner.py` | Validates query shape and builds safe query plans. |
| `catalog_execution.py` | Executes read plans. |
| `catalog.py` | Public read facade used by adapters. |
| `api/routes.py` | HTTP route surface. |
| `dvm/jobs.py` | NIP-90 request parsing and job execution. |

## API Adapter

API is FastAPI-based and exposes read-only endpoints for configured public
resources. It should remain an adapter, not the owner of query semantics.

## DVM Adapter

DVM exposes the same catalog through NIP-90 request events. It handles Nostr
subscription flow, request targeting, optional pricing behavior, feedback
events, and response publication.

## Read Model Principles

- Public resource IDs are stable API concepts.
- Internal table names can differ from public resource names.
- Query operators, sort fields, filters, and pagination are validated.
- Database exceptions are not leaked as raw client errors.
- API and DVM should stay consistent because they share the catalog.

## Public Surface Risk

Read exposure is configured by deployment. Before enabling a resource:

1. confirm the backing table/view does not expose private operational data;
2. confirm pagination and indexes match expected cardinality;
3. confirm DVM response size remains bounded;
4. add or update docs and tests for the public shape.
