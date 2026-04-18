# Deployments

How BigBrotr defines, ships, and extends deployment compositions.

---

## Overview

In BigBrotr, a deployment is a **first-class composition**, not just a folder
someone happened to copy.

Each deployment brings together:

- a storage profile;
- a service set;
- a configuration tree;
- a generated SQL package;
- protocol exposure policy;
- operator-facing local guidance.

The built-in deployments are reference compositions that show how those pieces
fit together.

## Built-In Reference Deployments

BigBrotr currently ships with two reference deployments:

| Deployment | Storage profile | Purpose |
|------------|-----------------|---------|
| `bigbrotr` | `full_archive` | Full archive profile with complete event storage |
| `lilbrotr` | `lightweight_archive` | Lightweight archive profile with reduced event payload retention |

These are not two different products. They are two built-in compositions over
the same codebase and the same core architectural contracts.

## Deployment Folder Contract

A deployment directory is expected to provide a coherent operator surface.

At minimum, a built-in or serious custom deployment should include:

- `docker-compose.yaml`;
- `.env.example`;
- `config/brotr.yaml`;
- `config/services/*.yaml`;
- `postgres/init/*.sql`;
- deployment-local `README.md`;
- local guidance in the `config/` tree where operators actually work.

The checked-in SQL package under `postgres/init/` is generated artifact, not
freehand source of truth. If the schema shape must change, the change belongs
in the SQL template system first.

## Storage Profiles

Storage profiles are an explicit architectural concept.

They define the broad storage behavior of a deployment, including questions
such as:

- whether the deployment keeps the full event archive payload;
- whether it keeps only the lightweight event form;
- how much of the shared schema is meaningful for that deployment.

Today the built-in profiles are:

- `full_archive`
- `lightweight_archive`

More profiles can be added later, but they should stay modeled as explicit
contracts rather than ad-hoc folder conventions.

## Service Set And Runtime Shape

A deployment also defines which services are enabled in practice and how they
connect to the database, relays, and public protocols.

Examples of deployment-local variation include:

- relay scope;
- event filter scope;
- monitor compute/store policy;
- whether and how the public adapters are exposed;
- whether a custom deployment adds or removes protocol-facing services.

The key principle is that deployments should vary through configuration and
explicit composition, not by forking the codebase into incompatible shapes.

## Public Exposure Policy

Deployments implicitly constrain what data can be read by determining what data
is stored in the first place.

On top of that, each public adapter has its own **protocol exposure policy**.
That means:

- the deployment decides the maximum data surface that can exist;
- `api.yaml` decides what the HTTP adapter exposes;
- `dvm.yaml` decides what the NIP-90 adapter exposes and at what price.

This separation keeps the deployment model clean:

- storage and compute shape are deployment concerns;
- transport exposure is adapter policy.

## Custom Deployments

The normal path for a custom deployment is:

1. start from the closest built-in reference deployment;
2. keep the local `README.md` files accurate as the deployment diverges;
3. update config and operator notes honestly;
4. only add SQL generator support if the schema package genuinely diverges.

That makes the custom deployment understandable to future operators without
forcing the project to bless every variation as a built-in profile.

## Related Documentation

- [Getting Started](../getting-started/index.md)
- [Custom Deployment](../how-to/custom-deployment.md)
- [Configuration](configuration.md)
- [Database](database.md)
