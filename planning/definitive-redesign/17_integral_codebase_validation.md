# Integral Codebase Validation

## Purpose

This file records the **integral validation pass of the redesign plan against
the real current codebase**.

It exists to answer a very practical question:

> Does the final redesign plan still hold once we stop reasoning from planning
> documents and instead read the actual Python code, SQL templates,
> deployment folders, and executable tests?

This file is therefore not another speculative planning note.
It is the bridge between:

- the final architectural vision;
- and the codebase that will actually have to be changed.

---

## 1. Scope Of Validation

The validation pass reviewed the current codebase across all major
architectural surfaces.

### 1.1 Runtime and registry surfaces reviewed

- `src/bigbrotr/__main__.py`
- `src/bigbrotr/services/registry.py`
- `src/bigbrotr/nips/registry.py`
- `src/bigbrotr/core/base_service.py`
- `src/bigbrotr/core/service_runtime.py`
- `src/bigbrotr/core/brotr.py`
- `src/bigbrotr/core/pool.py`

### 1.2 Shared model and persistence surfaces reviewed

- `src/bigbrotr/models/constants.py`
- `src/bigbrotr/models/relay.py`
- `src/bigbrotr/models/event.py`
- `src/bigbrotr/models/metadata.py`
- `src/bigbrotr/models/event_relay.py`
- `src/bigbrotr/models/relay_metadata.py`
- `src/bigbrotr/models/service_state.py`

### 1.3 Shared read-layer surfaces reviewed

- `src/bigbrotr/services/common/catalog.py`
- `src/bigbrotr/services/common/catalog_planner.py`
- `src/bigbrotr/services/common/read_models.py`
- `src/bigbrotr/services/common/read_model_registry.py`
- `src/bigbrotr/services/common/read_model_requests.py`
- `src/bigbrotr/services/common/configs.py`
- `src/bigbrotr/services/common/state_store.py`

### 1.4 Service surfaces reviewed

- `src/bigbrotr/services/api/service.py`
- `src/bigbrotr/services/api/configs.py`
- `src/bigbrotr/services/dvm/service.py`
- `src/bigbrotr/services/dvm/configs.py`
- `src/bigbrotr/services/monitor/service.py`
- `src/bigbrotr/services/monitor/publishing.py`
- `src/bigbrotr/services/refresher/service.py`
- `src/bigbrotr/services/refresher/configs.py`
- `src/bigbrotr/services/refresher/queries.py`
- `src/bigbrotr/services/ranker/service.py`
- `src/bigbrotr/services/ranker/configs.py`
- `src/bigbrotr/services/ranker/queries.py`
- `src/bigbrotr/services/ranker/utils.py`
- `src/bigbrotr/services/assertor/service.py`
- `src/bigbrotr/services/assertor/configs.py`
- `src/bigbrotr/services/assertor/publishing.py`
- `src/bigbrotr/services/finder/service.py`
- `src/bigbrotr/services/validator/service.py`
- `src/bigbrotr/services/synchronizer/service.py`
- `src/bigbrotr/services/seeder/service.py`

### 1.5 Protocol and event-builder surfaces reviewed

- `src/bigbrotr/nips/event_builders.py`
- `src/bigbrotr/nips/nip85/data.py`

### 1.6 SQL and deployment surfaces reviewed

- `tools/templates/sql/base/02_tables_core.sql.j2`
- `tools/templates/sql/base/03_tables_current.sql.j2`
- `tools/templates/sql/base/04_tables_analytics.sql.j2`
- `tools/templates/sql/base/08_functions_refresh_current.sql.j2`
- `tools/templates/sql/base/09_functions_refresh_analytics.sql.j2`
- `deployments/bigbrotr/*`
- `deployments/lilbrotr/*`

### 1.7 Executable-spec tests reviewed

- `tests/unit/services/test_api.py`
- `tests/unit/services/test_dvm.py`
- `tests/integration/base/test_derived_tables.py`
- `tests/integration/base/test_refresher.py`
- `tests/integration/base/test_ranker.py`
- `tests/integration/base/test_assertor.py`
- `tests/integration/base/test_nip85_pipeline.py`

---

## 2. Final Validation Result

The redesign plan **does hold** against the real codebase.

The code review did **not** uncover a hidden architectural reality that
invalidates the final direction.

What it did uncover is something more important for execution:

- several parts of the plan are directionally right but must be described more
  concretely as **migrations from the actual current seams**;
- the DB redesign is more invasive than a naming cleanup because current SQL,
  models, tests, and deployments are deeply shaped around the old schema;
- the implementation order must respect those real seams instead of pretending
  the current code already matches the target vocabulary.

So the result is:

- **go** on the redesign direction;
- **tighten** the migration framing;
- **do not** underestimate the amount of coordinated work in SQL, Python,
  tests, config, and deployments.
- **start execution from the real `nip85-hardening` baseline**, not from an
  imaginary clean-room starting point that discards the preparatory refactors
  already carried by that line of work.

---

## 3. What The Codebase Strongly Confirmed

### 3.1 `Refresher` already is the canonical shared-derivation owner

The current code and tests confirm that `Refresher` already owns:

- current-state tables;
- analytics summary tables;
- NIP-85 fact tables;
- checkpointed incremental refresh;
- periodic reconcile jobs.

This strongly validates the redesign decision that canonical shared derivation
should remain centered in `Refresher`.

### 3.2 `Ranker` already is private compute plus public export

The current `Ranker`:

- uses DuckDB as private working storage;
- syncs shared facts from PostgreSQL;
- computes ranks privately;
- exports public rank snapshots back to PostgreSQL.

This strongly validates the redesign principle:

- private compute stays private;
- only public outputs belong in the shared DB.

### 3.3 `Monitor` is already one real composite service

The current `Monitor` does not just probe relays.
It already also coordinates publication flows for:

- profile publication;
- relay-list publication;
- announcement publication;
- discovery publication.

This confirms that the right future direction is:

- keep `Monitor` unified;
- clarify its internal sub-boundaries;
- do not split it casually into extra services just for aesthetic purity.

### 3.4 `Assertor` is the right owner for the full NIP-85 provider package

The current code already shows that:

- assertion publication is owned by `Assertor`;
- provider Kind 0 profile publication is already wired there;
- the `10040` trusted-provider-list builder already exists in the codebase.

What is missing is not conceptual ownership.
What is missing is complete wiring.

So the redesign decision remains correct:

- `Assertor` should own the full provider publication package.

### 3.5 `NIP_REGISTRY` already exists in the right direction

The current `NIP_REGISTRY` is already:

- static;
- explicit;
- capability-oriented;
- free from plugin magic.

So the redesign should not second-guess its existence.
It should strengthen and formalize it further.

### 3.6 Deployments already behave as first-class deployment packages

The real deployment folders already contain:

- `docker-compose.yaml`;
- `.env.example`;
- `config/brotr.yaml`;
- `config/services/*.yaml`;
- deployment-local PostgreSQL init packages;
- deployment-local infra such as monitoring and pgbouncer config;
- static assets where needed.

This confirms that the correct deployment direction is:

- keep the folder model;
- formalize it;
- do not replace it with a more abstract but less concrete system.

### 3.7 Current quality baseline is strong but not yet uniformly final-form

The current codebase is already serious and professional in many places.

Strong examples include:

- the core runtime/service loop discipline;
- typed config models;
- the private/public split already present in the ranker;
- the seriousness of the test suite.

But the codebase is not yet uniformly in its cleanest final shape.

The main gap is not crude sloppiness.
The main gap is:

- residual historical vocabulary;
- mixed conceptual layers in some surfaces;
- schema and read-side shapes that are still too close to older architecture;
- uneven semantic cleanliness across the repository.

So the redesign must be read not only as an architecture program, but also as
the program that brings the whole repository to a uniformly excellent level.

### 3.8 `src/` must be treated as library surface, not only internal runtime

The validation pass also reinforces one important practical point:

- much of `src/` is not just private implementation detail;
- it functions as a Python library surface with importable models, configs,
  services, and extension seams.

So the redesign must hold library-grade standards for:

- public API shape;
- module/package documentation;
- import ergonomics;
- consistency between documented and intended usage.

### 3.9 Repository surfaces outside `src/` already materially shape the project

The validation pass also confirms that repository quality cannot be scoped only
to `src/`.

Important project truth also lives in:

- `tests/`
- `tools/`
- `deployments/`
- `docs/`
- `mkdocs.yml`
- repository-level guidance files

So the redesign must treat the whole repository as project surface, not only
runtime code.

### 3.10 `docs/` specifically requires a real rewrite

The current documentation site is substantial enough that it should be treated
as a redesign workstream in its own right.

Because the redesign changes the system story materially, `docs/` should not
be handled as a last-minute sync pass.

It requires a deliberate rewrite of:

- narrative framing;
- page structure;
- user/operator flows;
- architecture and database explanation;
- contributor and development guidance;
- reference alignment with public APIs.

---

## 4. What Had To Be Sharpened After Reading The Code

### 4.1 The read-side migration is not “Catalog-first only”

The read side today is not just `Catalog`.

The real current seam is:

- `Catalog`
- `ReadModelSurface`
- `READ_MODEL_REGISTRY`
- request parsers and query normalization
- adapter-local YAML `read_models` exposure policy
- tests that already encode the canonical public read-model names

So the redesign must not be described as:

- “replace `Catalog` with a better read core”

The real migration is:

- evolve the current read-model stack into a protocol-agnostic read core;
- preserve the adapter whitelisting model;
- keep public resource naming and exposure policy explicit;
- move the conceptual center upward without throwing away proven generic
  machinery.

### 4.2 The DB redesign is a real migration, not a cosmetic rename

Current code, SQL, and tests are deeply committed to the old shared schema:

- `metadata`
- `event_relay`
- `relay_metadata`
- wide current tables
- materialized contact graph tables
- rich rank tables with `algorithm_id`, `raw_score`, `rank`, `computed_at`

Therefore the redesign must be treated as a **coordinated migration** across:

- SQL templates;
- Python models;
- `Brotr` APIs;
- services;
- tests;
- deployment init SQL;
- documentation.

Any implementation plan that treats it as a light rename sweep would be
incorrect.

### 4.3 Public read exposure is already adapter-configured today

The current `api` and `dvm` configs already whitelist exposed read models.

This confirms the future model:

- deployments define what data can exist;
- adapters define what subset they expose.

So the redesign should preserve this strong idea and generalize it, rather
than replace it with something more implicit.

### 4.4 The deployment contract should be described as formalization, not invention

After reading the real deployment folders, the deployment plan should be read
as:

- formalizing the current best pattern;
- making it explicit and validateable;
- not inventing a different deployment system from scratch.

---

## 5. What The Codebase Did Not Overturn

The integral validation pass did **not** overturn the following major
decisions.

### 5.1 Storage-first redesign

Still correct.

### 5.2 Huge-DB discipline

Still correct and even more important after reading the real refresh and query
surfaces.

### 5.3 Shared derivation in PostgreSQL, private compute where justified

Still correct.

### 5.4 Unified `Monitor`

Still correct.

### 5.5 `Assertor` owning a complete NIP-85 provider publication package

Still correct.

### 5.6 Static formal `NIP_REGISTRY`

Still correct.

### 5.7 Protocol-agnostic read core under `api`, `dvm`, and future adapters

Still correct.

### 5.8 Folder-based YAML-first deployment contract

Still correct.

---

## 6. Implementation Consequences

The validation pass changes how the implementation should be staged.

### 6.1 An explicit validation tranche is justified

Before major refactor work begins, the implementation plan should acknowledge
an explicit pre-refactor validation tranche that:

- audits the real code seams;
- confirms migration assumptions;
- freezes rename and contract ledgers against real code rather than abstract
  language alone.

This is not optional ceremony.
It is the discipline required to keep the redesign honest.

### 6.2 Tranche 7 must migrate from the current read-model stack, not around it

The read-core work must explicitly account for:

- `ReadModelSurface`;
- `READ_MODEL_REGISTRY`;
- current public IDs;
- adapter config whitelists;
- API and DVM tests that already define part of the public contract.

### 6.3 Tranche 8 must treat `bigbrotr` and `lilbrotr` as real reference deployments

Deployment normalization should start from the real existing folder pattern,
not from an imaginary clean-room deployment abstraction.

### 6.4 SQL and test migration must be planned as one body of work

Because the schema and refresh model are heavily codified by integration
tests, the DB refactor must always be treated as:

- SQL change;
- Python boundary change;
- test-spec change;
- deployment init change;

all together.

---

## 7. Remaining Risk Shape

After the integral validation pass, the remaining risk is **not** that the
architecture is wrong.

The remaining risk is execution quality.

That means:

- ordering mistakes;
- migration slices that are too broad or too blurry;
- underestimating how many tests encode the old contracts;
- partial rename work that leaves mixed semantics;
- adapter or deployment drift during the read-core migration.

So the redesign is now less a matter of “finding the right direction” and
more a matter of **executing the right direction with rigor**.

---

## 8. Final Decision

The redesign plan remains valid after an integral codebase validation pass.

The correct reading is:

- the architecture is solid enough to proceed;
- the migration must stay grounded in the real current seams;
- the implementation plan must remain strict, auditable, and tranche-driven;
- the first implementation moves must respect the fact that the codebase is
  already mature enough to punish loose refactors.

This file should therefore be read together with:

- `14_core_read_layer_proposal.md`
- `15_deployment_contract_proposal.md`
- `16_operational_implementation_plan.md`
- `99_definitive_master_plan.md`

It is the validation record that says:

> the plan is not just internally coherent;
> it is also coherent with the codebase we actually have to change.
