# Definitive Redesign Planning Set

This directory contains the full iterative planning set for the definitive
BigBrotr redesign.

The file order is intentional.

## Files

### `00_context_and_constraints.md`

Shared ground truth:

- product identity;
- freedoms;
- constraints;
- protocol anchors;
- evaluation criteria.

Read this first.

### `01_iteration_1.md`

First wide iteration:

- aspect-by-aspect analysis;
- first option space;
- first candidate architecture;
- first internal audit.

### `02_iteration_2.md`

Second iteration:

- concrete schema philosophy;
- extension surface model;
- stronger architecture;
- second internal audit.

### `03_iteration_3.md`

Third iteration:

- workstreams;
- phase order;
- risk analysis;
- acceptance criteria;
- final internal audit before plan freeze.

### `10_review_objects_and_open_questions.md`

Discussion objects grouped by topic:

- schema;
- service boundaries;
- read layer;
- extensibility;
- execution strategy.

This file is most useful for explicit decision review.

### `11_target_architecture_schema.md`

Target-shape architecture overview:

- data bands;
- service ownership;
- public surfaces;
- deployment composition;
- extension model.

### `12_best_db_schema.md`

Final best-effort shared DB schema proposal:

- canonical storage tables;
- shared operational state;
- current tables;
- shared analytics;
- score outputs;
- views and partitioning guidance.

### `13_db_consolidation_and_remaining_topics.md`

Current planning status after the DB discussion was closed:

- what is now considered consolidated on schema and efficiency;
- what is now also effectively fixed outside the DB block;
- what remains only as final focused design closure.

### `14_core_read_layer_proposal.md`

Proposed final shape of the protocol-agnostic read core:

- internal read engine;
- readable-resource model;
- protocol adapter boundaries;
- bounded generic query policy;
- relationship to the current `Catalog`.

This is the definitive planning note for how the existing read-model surface
should evolve without losing the good generic machinery already present today.

### `15_deployment_contract_proposal.md`

Proposed final deployment contract:

- folder-based deployment model;
- required and optional files;
- storage profile and service-set meaning;
- protocol exposure policy;
- how to add a new deployment cleanly.

This is the definitive planning note for how deployment folders, YAML config,
storage profiles, and per-protocol exposure should fit together.

### `16_operational_implementation_plan.md`

Detailed operational execution plan:

- tranche order;
- per-package audit loop;
- test and commit gates;
- stop conditions;
- disciplined implementation protocol for the full redesign.

This is the working execution companion for turning the architectural decisions
into an implementation program.

### `17_integral_codebase_validation.md`

Integral validation of the redesign plan against the real current codebase:

- what the codebase strongly confirms;
- what had to be sharpened after reading the real code;
- why the read-core and DB migration must be treated as true migrations;
- why the plan can now be considered validated enough to execute seriously.

### `18_code_excellence_standard.md`

Explicit code-excellence target for the redesign:

- what “excellent code” means in this repository;
- what debt classes the redesign must eliminate;
- quality-ratchet rule for touched code;
- definition of done for work packages and for the redesign as a whole.

### `19_documentation_rewrite_program.md`

Explicit documentation-overhaul program for the redesign:

- full rewrite scope across in-code docs, repo docs, and `docs/`;
- coherent folder-level `README.md` coverage across meaningful maintained
  project surfaces;
- documentation as first-class design surface;
- rewrite targets across user, operator, contributor, and library-consumer
  documentation;
- local-update responsibility plus one deliberate global rewrite tranche.

### `20_redesign_execution_ledger.md`

Canonical execution-status ledger for the redesign:

- tranche-by-tranche status;
- work-package checklist;
- commit/audit/follow-up tracking;
- explicit memory of what is done, what changed, and what still remains.

### `21_canonical_rename_ledger.md`

Canonical target-vocabulary ledger for the redesign:

- old term -> canonical term mapping;
- schema/read/deployment naming decisions in one place;
- explicit keep/rename/conceptual-only status;
- vocabulary contract for later implementation tranches.

### `22_final_contract_freeze.md`

Final contract-freeze companion for execution:

- frozen execution baseline;
- canonical planning-file precedence;
- frozen DB/read-core/deployment/service-boundary contracts;
- explicit reopen rule for any future contradiction.

### `23_repository_content_audit_program.md`

Post-closeout whole-repository audit program:

- read the content of every tracked file;
- do it leaf-to-root;
- classify every file as keep/update/remove/add;
- and run a final repository cleanup pass against the actual tracked state.

This is the definitive planning note for the full file-content audit that
should happen after redesign execution is closed and before final integration.

### `24_repository_content_audit_ledger.md`

Execution ledger for the whole-repository content audit:

- manifest freeze;
- wave-by-wave status;
- audit findings;
- remediation commits;
- deferred watch points.

### `25_repository_content_audit_manifest.txt`

Exact frozen tracked-file manifest for the repository-content audit baseline.

This is the literal `git ls-tree` snapshot of the redesign closeout state under
audit.

### `26_repository_content_audit_untouched_manifest.txt`

Exact list of final tracked files that were untouched during the redesign
execution range.

This is historical-context data for the whole-repository content audit, not a
trust model. All tracked files remain high-suspicion audit targets.

### `27_repository_content_audit_traversal_map.md`

Concrete wave-by-wave traversal map for the whole-repository content audit:

- baseline counts;
- touched vs untouched distribution;
- exact folder scopes by wave;
- paired-surface watch points.

### `99_definitive_master_plan.md`

Final distilled plan resulting from the three iterations and their audits.

## How To Read The Set

Recommended order:

1. `00_context_and_constraints.md`
2. `01_iteration_1.md`
3. `02_iteration_2.md`
4. `03_iteration_3.md`
5. `99_definitive_master_plan.md`
6. `17_integral_codebase_validation.md`
7. `18_code_excellence_standard.md`
8. `19_documentation_rewrite_program.md`
9. `16_operational_implementation_plan.md`
10. `20_redesign_execution_ledger.md`
11. `21_canonical_rename_ledger.md`
12. `22_final_contract_freeze.md`
13. `23_repository_content_audit_program.md`
14. `24_repository_content_audit_ledger.md`
15. `25_repository_content_audit_manifest.txt`
16. `26_repository_content_audit_untouched_manifest.txt`
17. `27_repository_content_audit_traversal_map.md`

The iteration files are intentionally more verbose and analytical. The final
plan is intentionally more decisive and executable.

Execution baseline note:

- the redesign is intended to begin from the `nip85-hardening` line of work,
  not from a pretend baseline that ignores the preparatory refactors already
  landed there.

At this point, the highest-value “current truth” files in this directory are:

- `12_best_db_schema.md`
- `13_db_consolidation_and_remaining_topics.md`
- `14_core_read_layer_proposal.md`
- `15_deployment_contract_proposal.md`
- `17_integral_codebase_validation.md`
- `18_code_excellence_standard.md`
- `19_documentation_rewrite_program.md`
- `16_operational_implementation_plan.md`
- `20_redesign_execution_ledger.md`
- `21_canonical_rename_ledger.md`
- `22_final_contract_freeze.md`
- `23_repository_content_audit_program.md`
- `24_repository_content_audit_ledger.md`
- `27_repository_content_audit_traversal_map.md`
- `99_definitive_master_plan.md`

## Canonical Topic Map

When the implementation starts, these are the canonical files to consult for
each major topic.

- shared DB target and naming:
  `12_best_db_schema.md`
- what is already consolidated and should not be reopened casually:
  `13_db_consolidation_and_remaining_topics.md`
- protocol-agnostic read core:
  `14_core_read_layer_proposal.md`
- deployment contract, storage profiles, and deployment authoring:
  `15_deployment_contract_proposal.md`
- tranche order, work-package loop, audit protocol, and stop conditions:
  `16_operational_implementation_plan.md`
- validation of the plan against the real current codebase:
  `17_integral_codebase_validation.md`
- code-quality and repository-excellence target:
  `18_code_excellence_standard.md`
- full documentation rewrite program:
  `19_documentation_rewrite_program.md`
- current redesign progress, completed work, and remaining work:
  `20_redesign_execution_ledger.md`
- canonical target vocabulary and rename mapping:
  `21_canonical_rename_ledger.md`
- frozen execution baseline and planning-file precedence:
  `22_final_contract_freeze.md`
- post-closeout whole-repository content audit:
  `23_repository_content_audit_program.md`
- status ledger for that audit:
  `24_repository_content_audit_ledger.md`
- frozen manifest baseline for that audit:
  `25_repository_content_audit_manifest.txt`
- untouched-file baseline for that audit:
  `26_repository_content_audit_untouched_manifest.txt`
- concrete wave-to-folder traversal map for that audit:
  `27_repository_content_audit_traversal_map.md`
- distilled top-level redesign direction:
  `99_definitive_master_plan.md`
