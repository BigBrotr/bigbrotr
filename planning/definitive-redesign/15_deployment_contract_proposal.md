# Deployment Contract Proposal

## Purpose

This file defines the **final target deployment contract** for BigBrotr.

It answers:

> What should a deployment be, what should a deployment folder contain, and
> how should deployment-specific configuration, storage profile, and protocol
> exposure fit together?

This file does **not** argue for abandoning the current deployment-folder
model.

The opposite is true:

- the current folder-based, YAML-first deployment style is already good;
- the redesign should preserve it;
- what was missing was a clearer formal contract behind it.

---

## 1. Current Code Reality

The project already behaves as if deployments were first-class packages.

Current deployments such as `bigbrotr` and `lilbrotr` already contain:

- deployment-local config;
- deployment-local Docker orchestration;
- deployment-local PostgreSQL init files;
- deployment-local static assets;
- deployment-local monitoring and pgbouncer files;
- deployment-local operational scripts.

This is a strong foundation.

The weakness is not the folder model itself.
The weakness is that the deployment contract is still more implicit than it
should be.

---

## 2. Final Mental Model

The final mental model should be:

> A deployment is a self-contained folder package that defines one concrete
> BigBrotr composition.

That composition includes:

- what storage profile it uses;
- what services it enables;
- what data it stores or does not store;
- what protocols it exposes;
- what each protocol is allowed to expose;
- what runtime and infra policy it uses.

This means a deployment is not merely:

- a docker-compose file;
- a pile of YAML files;
- a one-off folder copied by habit.

It is:

- a concrete product variant of the same core system.

---

## 3. Why The Folder Model Should Stay

The folder-based approach is the right default because it is:

- easy to reason about;
- easy to copy and customize;
- easy to version-control;
- easy to publish and run with container tooling;
- easy for operators to understand without needing Python internals.

This is especially important because future deployments may vary along several
axes at once:

- storage fidelity;
- relay/event scope;
- enabled services;
- public protocol exposure;
- network policy;
- infra policy.

The deployment folder keeps all of that concrete and inspectable.

---

## 4. Final Contract: What A Deployment Means

A deployment should be defined as a composition of:

- **storage profile**
- **enabled service set**
- **protocol exposure policy**
- **runtime and publication policy**
- **deployment-local assets and orchestration**

This is the real meaning of a deployment.

The folder is the packaging form of that composition.

---

## 5. Contract Layers

## 5.1 Deployment root

The deployment root folder is the primary boundary.

It should contain the files and subfolders needed to understand and run one
deployment as a self-contained package.

Typical root-level examples:

- `.env.example`
- `docker-compose.yaml`
- `backup.sh`
- deployment-local notes

## 5.2 Shared runtime config

`config/brotr.yaml` should remain the shared runtime config for the deployment.

It expresses deployment-wide runtime choices that are not owned by a single
service.

## 5.3 Service config layer

`config/services/*.yaml` should remain the service-by-service config surface.

This is where a deployment defines:

- which services are actually configured and enabled;
- service runtime tuning;
- service-local behavior;
- protocol-adapter exposure policy for `api`, `dvm`, and future adapters.

## 5.4 PostgreSQL package

The deployment’s PostgreSQL package should remain local to the deployment.

This includes:

- init SQL;
- init scripts;
- postgres config;
- generated schema files matching that deployment’s storage profile.

This matters because storage profile is not an abstract thought; it has real
schema consequences.

## 5.5 Optional local assets

Deployments may include optional assets such as:

- seed files;
- GeoLite data;
- monitoring config;
- pgbouncer config;
- dumps or backup support files.

These are optional in the abstract contract, but first-class when the
deployment needs them.

---

## 6. Required And Optional Pieces

The future contract should treat the following as the practical minimum for a
first-class deployment folder.

## 6.1 Required

- deployment root folder
- `docker-compose.yaml`
- `.env.example`
- `config/brotr.yaml`
- `config/services/`
- deployment-specific PostgreSQL init/config package

## 6.2 Required only when the deployment enables the corresponding feature

- static seed relay file if `Seeder` is enabled
- GeoLite or similar assets if monitor features require them
- pgbouncer config if pgbouncer is part of the deployment
- monitoring config if monitoring stack is part of the deployment

## 6.3 Optional but recommended

- backup script
- deployment-local `README.md`
- deployment-local notes
- deployment-local helper tooling

---

## 7. Storage Profiles

Storage profile must now be treated as a first-class architectural concept.

`bigbrotr` and `lilbrotr` are not weird exceptions.
They are the first examples of a real axis of variation.

That axis includes choices such as:

- full event payload vs compact event payload;
- whether specific archive relations are stored;
- which subsets of relays or events are retained;
- what fidelity of shared facts is supported downstream.

The important point is:

- future deployments must be allowed to define new storage profiles cleanly;
- those differences must be represented by deployment config and schema, not by
  forking the whole project.

---

## 8. Protocol Exposure Model

The deployment contract must make room for a second boundary after storage:

- first, the deployment decides what data exists;
- then each protocol adapter decides what subset of that data it exposes.

This means:

- `api` config can expose one subset;
- `dvm` config can expose another;
- future `mcp` config can expose another.

The deployment contract therefore includes not only service enablement but also
per-protocol exposure policy.

---

## 9. What Should Not Happen

The future deployment model should **not** turn into:

- a hidden Python composition framework that operators cannot inspect easily;
- a set of half-implicit conventions spread across random directories;
- a single magic manifest that duplicates everything and drifts from the real
  files;
- a deployment system that forces operators to understand code internals just
  to make a variant.

The good property of the current approach is that the deployment is concrete.
That property should be preserved.

---

## 10. Recommended Formalization

The best direction is:

- keep deployment folders;
- keep YAML-first authoring;
- keep deployment-local infra files;
- explicitly document the folder contract;
- require one human-readable deployment-local `README.md` that explains the
  storage profile, enabled services, exposed protocols, and any unusual
  runtime or infra choices;
- scaffold new deployments from a known reference shape;
- validate deployment config structurally where possible.

In other words:

- do not replace the current model;
- formalize it.

---

## 11. The Role Of `bigbrotr` And `lilbrotr`

`bigbrotr` and `lilbrotr` should remain:

- real deployable products;
- reference examples of different storage profiles;
- canonical examples for future deployment authors.

`bigbrotr` in particular can serve as the most complete reference template,
because it already carries the fuller operational shape.

That does not mean every new deployment must copy every file unchanged.
It means:

- `bigbrotr` is the clearest reference deployment folder today.

---

## 12. How A New Deployment Should Be Created

The recommended future workflow is:

1. start from the reference deployment folder;
2. choose the storage profile;
3. choose the enabled services;
4. choose protocol exposure policy for `api`, `dvm`, and any future adapter;
5. adjust runtime, network, and publication policy;
6. adjust deployment-local infra and static assets as needed.

This is intentionally simple and operationally concrete.

---

## 13. What Still Belongs In Config

The guiding rule is:

> everything that is reasonable to configure should be configurable, with sane
> defaults.

That includes, where appropriate:

- service enablement;
- batching and timeout tuning;
- protocol exposure choices;
- page-size or bounded-query policy;
- monitoring/publishing behavior;
- deployment-local infra choices.

What should **not** be pushed into config is the need to reconstruct hidden
architectural meaning that the deployment contract should already make clear.

---

## 14. Final Decision

The final direction is:

- keep the deployment folder model;
- keep YAML-first authoring;
- treat deployments as first-class compositions of storage profile, service
  set, exposure policy, and infra/runtime policy;
- use `bigbrotr` and `lilbrotr` as the first real reference deployments;
- formalize the folder contract instead of inventing a radically new
  deployment system.

This gives BigBrotr the cleanest future path:

- easy to extend;
- easy to operate;
- easy to reason about;
- and still rigorous enough for long-term architectural stability.
