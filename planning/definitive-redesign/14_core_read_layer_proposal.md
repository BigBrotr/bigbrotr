# Core Read Layer Proposal

## Purpose

This file defines the **final target shape of BigBrotr’s protocol-agnostic
read core**.

It exists because the current codebase already contains strong generic read
machinery, but its conceptual center is still too close to:

- schema introspection;
- table/view exposure;
- read-model IDs that are mostly aliases of catalog relations.

The redesign direction is not to throw that machinery away.
The redesign direction is to **reposition and formalize it correctly**.

This file answers:

> How should the current `Catalog`-based read side evolve into one semantic
> read core that can sit under `api`, `dvm`, and future adapters such as
> `mcp`?

---

## 1. Current Code Reality

The current read side already has very valuable building blocks.

### 1.1 `Catalog`

`Catalog` already provides:

- runtime discovery of tables, views, and materialized views;
- discovered column metadata;
- primary-key and unique-index awareness;
- safe parameterized list queries;
- safe primary-key lookups;
- generic offset and keyset pagination;
- generic filter and sort parsing with whitelist-by-construction behavior.

This is strong infrastructure and should not be discarded.

### 1.2 `ReadModelRegistry`

`ReadModelRegistry` currently maps public read-model IDs to catalog-backed
relations.

This is useful, but today it is still conceptually close to:

- “read-model ID -> catalog relation name”.

### 1.3 `ReadModelSurface`

`ReadModelSurface` already acts as a shared wrapper for:

- discovery;
- policy resolution;
- public-surface enablement;
- execution through the catalog.

This is already very close to the right direction.

### 1.4 Request normalization

`read_model_requests.py` already provides a valuable shared query contract for:

- limit/offset;
- cursor;
- filters;
- sort;
- include-total.

This also should survive conceptually.

### 1.5 Where the current model is still too weak

The weakness is mostly conceptual, not technical.

The current center is still too close to:

- catalog-backed relations;
- built-in read-model IDs;
- public exposure that still smells like schema-backed listing.

That is what the redesign must fix.

### 1.6 Current migration constraints

The real current public contract is already stronger than a plain `Catalog`
wrapper.

Today the effective stack is:

- `Catalog`
- `ReadModelSurface`
- `READ_MODEL_REGISTRY`
- shared request parsing and query normalization
- per-adapter YAML `read_models` exposure policy
- tests that already enforce canonical public read-model IDs

That means the redesign cannot be implemented as if only `Catalog` mattered.

The migration must explicitly respect:

- the current shared surface object;
- the current registry-backed public naming;
- the adapter-local exposure policy model;
- the existing test suite as part of the public contract.

---

## 2. What The Final Read Side Must Achieve

The final read side must satisfy all of the following at once.

### 2.1 Protocol agnosticism

The read core must not be an HTTP design or a DVM design.

It must be the shared semantic layer underneath:

- `api`
- `dvm`
- future `mcp`
- any later protocol adapter

### 2.2 Deployment-scoped availability

A deployment decides what data exists and therefore what can even be readable.

So the read core must work against a deployment-specific readable universe,
not assume one global static surface for every deployment.

### 2.3 Protocol-scoped exposure policy

Each protocol adapter must be able to decide:

- what subset to expose;
- how to expose it;
- with what limits;
- with what discovery behavior;
- with what pricing or access rules if needed later.

### 2.4 Bounded generic querying

The system should support generic reusable query mechanics, but always in a
bounded and controlled way.

The target is:

- reusable read infrastructure;
- not a pseudo-SQL public surface.

### 2.5 Future extensibility

The read side must be extensible for:

- new deployments;
- new protocol adapters;
- new readable datasets;
- occasional handler-backed resources that are not just plain tables.

---

## 3. Final Mental Model

The final mental model should be this:

1. **deployments define what readable data can exist**
2. **the read core resolves named readable resources**
3. **protocol adapters expose selected resources under their own policy**

That means the conceptual center is no longer:

- “catalog-backed read models”

It becomes:

- **deployment-approved readable resources over one shared read core**

`Catalog` survives underneath this, but it is no longer the conceptual center.

---

## 4. Target Architecture

## 4.1 `Catalog` remains the low-level relation engine

The future `Catalog` should keep doing relation-oriented work such as:

- relation discovery;
- relation schema loading;
- safe list execution for relation-backed resources;
- safe identity lookup;
- generic pagination primitives;
- generic filter and sort enforcement against discovered schema.

In other words:

- keep it;
- trust it;
- narrow its conceptual role.

It becomes the **relation execution substrate**, not the product-facing read
identity of the project.

## 4.2 Add a readable-resource layer above it

The next layer should be a formal registry of readable resources.

Each readable resource should describe things like:

- stable resource ID;
- semantic name;
- backing relation or handler;
- schema/discovery metadata;
- identity fields if any;
- stable default traversal order;
- stable cursor key shape if cursor pagination is supported;
- allowed filters;
- allowed sorts;
- pagination capabilities;
- default page size and max page size;
- optional protocol-specific visibility defaults.

This is the layer that should replace the old mental model of “built-in public
read model registry”.

## 4.3 Add a shared read-core service/object

Above the resource descriptors, the project should have one shared read-core
object or subsystem that owns:

- resolving readable resources;
- validating public read requests;
- choosing the correct execution path;
- delegating relation-backed resources into `Catalog`;
- delegating handler-backed resources into specialized handlers;
- normalizing results and shared error behavior.

This is the real protocol-agnostic read core.

## 4.4 Keep protocol adapters thin

Each protocol adapter should only be responsible for:

- turning protocol-specific inputs into the shared read-query contract;
- selecting enabled resources according to adapter policy;
- formatting protocol-specific outputs;
- exposing discovery endpoints or equivalents in the adapter’s native style.

The adapter should not redefine data semantics.

## 4.5 Migration principle

The implementation path should therefore be:

1. evolve the current `ReadModelSurface` into the new shared read core;
2. evolve `READ_MODEL_REGISTRY` into a more explicit readable-resource
   registry;
3. keep `Catalog` as the low-level relation engine;
4. keep adapter configuration as the place where exposure policy is declared;
5. preserve public resource IDs and public bounded-query behavior until a
   deliberate public-contract migration is explicitly chosen.

This is important because the current codebase already has real read-side
contracts encoded in:

- adapter configs;
- route and query behavior;
- API and DVM tests.

---

## 5. Resource Types

The read core should support at least two resource families.

## 5.1 Relation-backed resources

These are the default and should cover most cases.

They are backed by:

- tables;
- views;
- materialized views.

These resources can use generic `Catalog` execution directly.

Examples:

- `relays`
- `events`
- `relay-stats`
- `daily-counts`
- `replaceable-events-current`

## 5.2 Handler-backed resources

These should exist only when a resource is not well represented as a plain
relation read.

Examples might include:

- future richer aggregate resources;
- protocol-shaped projections that need custom joins or preprocessing;
- bounded synthetic discovery resources.

The important point is:

- the read core should support them cleanly;
- they should be the exception, not the default.

---

## 6. Query Policy

The shared read core should keep generic query mechanics, but within a hard
bounded policy.

## 6.1 Allowed primitives

The generic contract should continue to support:

- `limit`
- `cursor`
- `filters`
- `sort`
- optional `offset` only for resources that explicitly opt into it;
- optional `include_total` only for resources that explicitly allow it

That is already close to the existing good design.

## 6.2 Resource-level allowlists

Each resource should be able to declare:

- which filters are allowed;
- which sort fields are allowed;
- whether cursor pagination is supported;
- whether offset pagination is supported;
- whether total counts are allowed;
- max page size.

This prevents the public surface from becoming a schema browser.

## 6.3 Hard boundedness

The read core should assume very large datasets.

So the default posture must be:

- cursor-first traversal on large relations;
- bounded page sizes;
- no unbounded list reads;
- no hidden full scans as a normal path;
- stable cursor semantics where possible;
- relation indexes that support the promised traversal shape.

## 6.4 Generic internally, controlled publicly

The correct final balance is:

- generic internal read mechanics;
- controlled public resource exposure.

This is not anti-genericity.
It is anti-leaky-genericity.

---

## 7. Deployment And Protocol Interaction

## 7.1 Deployment decides the maximum readable universe

If a deployment does not store or derive something, it cannot expose it.

So the deployment is the first exposure boundary.

## 7.2 The read core resolves only what the deployment makes available

The read core should work from the deployment’s available readable resources.

That may be derived from:

- discovered relations;
- deployment resource config;
- resource descriptors known to the runtime.

## 7.3 Each protocol adapter applies its own exposure policy

Then:

- `api` may expose one subset;
- `dvm` may expose another subset;
- a future `mcp` adapter may expose a third subset;
- the shape, discovery, and policy can differ by adapter.

This is the right place for per-protocol differences.

---

## 8. What Should Happen To The Current `ReadModel` Vocabulary

The current `read model` vocabulary is understandable historically, but it is
starting to get in the way conceptually.

Why:

- it suggests handcrafted product-specific models everywhere;
- in the code it often really means “catalog-backed readable relation”;
- it obscures the fact that the important shared abstraction is broader than
  HTTP or DVM read models.

The future direction should therefore be:

- center the architecture on **readable resources** and a **shared read core**;
- keep the old `read model` term only where it is useful for migration or
  backward mental continuity;
- avoid making “explicit read models” the center of future design language.

This is a conceptual cleanup, not a rejection of the current implementation.

---

## 9. Recommended Evolution Path From The Current Code

The clean evolution path is:

### Step 1

Keep the existing `Catalog` as the relation engine.

### Step 2

Refactor `READ_MODEL_REGISTRY` into something closer to a readable-resource
registry with richer descriptors.

### Step 3

Move surface resolution away from “built-in public read models” and toward:

- deployment-aware readable resources;
- per-adapter exposure policy.

### Step 4

Keep the shared query contract from `read_model_requests.py`, but rename and
reposition it as the generic read-query contract of the read core.

### Step 5

Let `api` and `dvm` become thinner adapter layers over the same read-core
resolution and execution path.

### Step 6

Add a future third adapter such as `mcp` without inventing new data semantics.

---

## 10. Concrete Design Proposal

If we had to describe the final shape very concretely, it would look like
this.

### 10.1 Relation engine

Keep:

- `Catalog`

Role:

- relation discovery;
- safe generic execution;
- PK-aware lookup;
- pagination mechanics.

### 10.2 Readable-resource registry

Introduce or evolve toward:

- `ReadableResourceEntry`
- `ReadableResourceRegistry`

Role:

- define readable resources;
- declare allowed query features;
- declare stable traversal and cursor semantics;
- bind resources to relations or handlers;
- provide resource-level discovery metadata.

### 10.3 Shared read core

Introduce or evolve toward:

- `ReadCore`

Role:

- resolve resources available in one deployment;
- resolve resources enabled for one protocol adapter;
- validate and execute read requests;
- normalize shared error behavior.

### 10.4 Protocol adapters

Keep separate:

- `api`
- `dvm`
- future `mcp`

Role:

- parse protocol-native request shape;
- call `ReadCore`;
- format protocol-native responses.

---

## 11. Final Decision

The final direction is:

- keep the current `Catalog` infrastructure;
- stop treating it as the conceptual center of the public read surface;
- evolve the read side into a deployment-aware, protocol-agnostic read core;
- formalize readable resources above relation discovery;
- let protocol adapters apply exposure policy on top of that common core.

This is the shape that best preserves what is already strong in the codebase
while aligning the design with the future architecture.
