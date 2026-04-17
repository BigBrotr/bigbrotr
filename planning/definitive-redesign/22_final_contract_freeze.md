# Final Contract Freeze

## Purpose

This file freezes the final contract set that should govern redesign
execution.

Its job is to remove the last remaining class of ambiguity where:

- historical planning files still exist;
- multiple final planning files each cover one part of the target shape;
- general repository workflow rules could be misread as overriding the
  redesign-specific execution baseline.

This file is therefore the **contract-freeze companion** for the execution
phase.

It does not replace the detailed planning documents.
It tells execution exactly which decisions are frozen, which files are
authoritative for each area, and how to resolve tension if two documents seem
to pull in different directions.

---

## 1. What Is Now Frozen

The redesign should now treat the following as frozen execution contracts.

### 1.1 Shared DB direction

The shared DB direction is frozen as:

- storage-first;
- minimal and semantically essential;
- huge-DB disciplined;
- narrow current tables;
- score outputs separated from canonical shared facts.

Canonical planning references:

- [12_best_db_schema.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/12_best_db_schema.md)
- [13_db_consolidation_and_remaining_topics.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/13_db_consolidation_and_remaining_topics.md)
- [21_canonical_rename_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/21_canonical_rename_ledger.md)

### 1.2 Read-core direction

The read side is frozen as:

- one protocol-agnostic read core;
- readable resources as the product-facing mental model;
- `Catalog` retained as low-level relation execution substrate;
- thin protocol adapters above the shared read core;
- bounded cursor-first resource traversal on large surfaces.

Canonical planning reference:

- [14_core_read_layer_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/14_core_read_layer_proposal.md)

### 1.3 Deployment-contract direction

The deployment model is frozen as:

- folder-based;
- YAML-first;
- explicit storage profiles;
- explicit per-protocol exposure policy;
- deployment folders treated as first-class product compositions.

Canonical planning reference:

- [15_deployment_contract_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/15_deployment_contract_proposal.md)

### 1.4 Service-boundary direction

The following service-boundary decisions are frozen:

- `Monitor` stays one service with clearer internal sub-boundaries;
- `Refresher` owns canonical shared derivation;
- `Ranker` remains private compute plus minimal public score export;
- `Assertor` owns the full NIP-85 provider package;
- `NIP_REGISTRY` remains static, explicit, and capability-oriented.

Canonical planning references:

- [13_db_consolidation_and_remaining_topics.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/13_db_consolidation_and_remaining_topics.md)
- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [99_definitive_master_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/99_definitive_master_plan.md)

### 1.5 Quality and documentation standards

The redesign-quality bar is frozen as:

- repository-wide code excellence;
- library-grade `src/` quality;
- severe audit loops for every work package;
- full documentation rethink and rewrite;
- folder-level `README.md` coverage for meaningful maintained folders.

Canonical planning references:

- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)

---

## 2. Execution Baseline Freeze

The redesign execution baseline is frozen as:

- the `nip85-hardening` line of work;
- specifically, the preparatory refactor line already represented by the
  `refactor/nip85-hardening-cleanup-performance` branch and its descendants.

This means the redesign must **not** pretend to start from a clean-room
`develop` baseline that ignores those preparatory structural changes.

For redesign execution, the correct branching rule is:

- start from the frozen `nip85-hardening` execution baseline;
- continue work on dedicated redesign feature branches from that baseline or
  from the current redesign execution branch;
- integrate back according to the normal repository workflow later.

So the ordinary repository workflow still matters, but it does not erase the
redesign-specific execution baseline.

---

## 3. Canonical Planning Precedence

If there is ever tension between planning files, use this precedence order.

### 3.1 Execution protocol and status

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)
- [20_redesign_execution_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/20_redesign_execution_ledger.md)

### 3.2 Naming and vocabulary

- [21_canonical_rename_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/21_canonical_rename_ledger.md)

### 3.3 Shared DB contract

- [12_best_db_schema.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/12_best_db_schema.md)
- [13_db_consolidation_and_remaining_topics.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/13_db_consolidation_and_remaining_topics.md)

### 3.4 Read-core contract

- [14_core_read_layer_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/14_core_read_layer_proposal.md)

### 3.5 Deployment contract

- [15_deployment_contract_proposal.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/15_deployment_contract_proposal.md)

### 3.6 Validation, quality, and docs

- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)

### 3.7 Distilled top-level summary

- [99_definitive_master_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/99_definitive_master_plan.md)

Historical and exploratory files such as:

- `01_iteration_1.md`
- `02_iteration_2.md`
- `03_iteration_3.md`
- `10_review_objects_and_open_questions.md`

remain useful context, but they are **not** authoritative if they conflict
with the canonical files above.

---

## 4. Reopen Rule

The frozen contracts above should not be reopened casually.

They may be revised only if a later work package uncovers one of the
following:

- a concrete contradiction with the real codebase that was not captured in
  `17_integral_codebase_validation.md`;
- a practical impossibility discovered during implementation;
- a major protocol or correctness issue that makes the frozen contract wrong
  rather than merely inconvenient.

“This would be easier if we drifted back toward the old shape” is **not** a
valid reason to reopen the contract.

If a frozen contract truly must be revisited, the work package must:

1. document the contradiction explicitly;
2. explain why the current contract fails;
3. update the affected canonical planning files;
4. update the execution ledger before continuing.

---

## 5. Freeze Use Rule

The redesign should be considered contract-frozen when all of the following are
true:

- execution baseline is unambiguous;
- canonical vocabulary is centralized;
- canonical planning-file precedence is explicit;
- shared DB, read-core, deployment, and service-boundary directions are frozen;
- later implementation tranches can proceed without reopening first-order
  design questions.

This file is therefore the compact contract statement that closes the
architecture-planning phase and authorizes the implementation phase.
