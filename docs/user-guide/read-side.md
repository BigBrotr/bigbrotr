# Read Side

How BigBrotr exposes public data without turning the product into a raw schema
browser.

---

## Overview

BigBrotr's public read surface is built around a **shared, protocol-agnostic
read core**.

The internal contract is:

- a catalog-backed view of readable relations;
- a registry of **readable resources**;
- adapter-specific exposure policy;
- bounded query execution with stable pagination contracts.

The external transport contract is intentionally more conservative:

- the HTTP API still exposes `/read-models`;
- the NIP-90 adapter still accepts the `read_model` parameter;
- deployment YAML still uses the `read_models` key for exposure policy.

That compatibility layer is deliberate. The project no longer treats raw
tables as the public product surface, but it also does not break established
transport contracts unless there is a strong reason to do so.

## Core Concepts

### Readable Resources

A **readable resource** is the canonical public read-side unit inside the
runtime.

Each resource describes:

- which relation it reads from;
- which fields are part of the public contract;
- whether it has stable identity columns;
- which adapters may expose it;
- what pagination capabilities it supports.

The current transports still call these things *read models*, but internally
the system now reasons in terms of readable resources.

### ReadCore

`ReadCore` is the shared runtime boundary used by the public adapters.

It owns:

- discovery of catalog-backed resources;
- enablement checks against adapter exposure policy;
- normalized request validation;
- bounded execution;
- discovery payload generation;
- consistent not-found and contract errors.

This keeps the HTTP and NIP-90 layers aligned without forcing them to duplicate
their own read-side logic.

### Adapter Exposure Policy

Deployments decide what data exists. Each public adapter then decides what
subset of that data is exposed and under what limits.

Today the shipped adapters are:

- `API` for HTTP;
- `DVM` for NIP-90 over Nostr.

Each adapter has its own exposure policy, but both policies are normalized
through the same shared contract.

## HTTP API

The HTTP API is a transport adapter over `ReadCore`.

Important characteristics:

- the stable discovery path remains `/api/v1/read-models`;
- list and detail routes are generated from the enabled readable resources;
- resources with stable identity default to cursor pagination;
- offset pagination is treated as a compatibility fallback, not the ideal path;
- `include_total` is opt-in because totals are extra work on large datasets.

The HTTP API therefore remains easy to consume without letting the public
surface drift into arbitrary schema browsing.

## NIP-90 DVM

The DVM is the Nostr transport adapter over the same read core.

Important characteristics:

- the request parameter remains `read_model` for compatibility;
- the DVM uses the same readable-resource contract as the HTTP API;
- cursor semantics mirror the HTTP API where the target resource supports
  stable identity;
- adapter-local pricing is enforced through exposure policy.

The DVM is not a separate read implementation. It is the same public data
surface, exposed through a different protocol.

## Boundedness Rules

The read side assumes the dataset can be very large.

That leads to hard design rules:

- no unbounded full-fetch behavior in the normal path;
- cursor pagination first for large identity-bearing resources;
- offset only where the resource contract explicitly allows it;
- explicit page-size ceilings;
- totals only when requested;
- no raw SQL or arbitrary relation exposure through the public adapters.

These rules are part of the product contract, not just implementation detail.

## Relationship To The Database

The shared database is still the source of truth, but the public read surface
is **not** the same thing as “all tables that exist”.

The progression is:

1. the deployment defines the storage profile and enabled service set;
2. the database contains the resulting storage and derived relations;
3. the read core describes which of those relations are readable resources;
4. each adapter exposes only the resources allowed by its protocol policy.

This separation is what keeps the public surface stable even while internal
schema details continue to evolve.

## Related Documentation

- [Architecture](architecture.md)
- [Services](services.md)
- [Deployments](deployments.md)
- [Configuration](configuration.md)
