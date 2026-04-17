# Redesign Execution Ledger

## Purpose

This file is the operational memory of the redesign.

It exists so that execution never depends on:

- memory;
- scattered notes;
- reconstructing progress from git history after the fact;
- vague impressions of what is “basically done”.

This ledger should be updated whenever a work package is closed.

The update must reflect the real final state of the slice, including:

- what was completed;
- what was changed;
- what audit findings were raised;
- what was fixed before closure;
- what remains deliberately open;
- what the next intended step is.

This file complements the execution protocol in:

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)

It is not a substitute for git history.
It is the canonical human-readable status and progress checklist for the
redesign itself.

---

## Status Vocabulary

Use these statuses consistently:

- `not started`
- `in progress`
- `blocked`
- `auditing`
- `done`

If a work package is `done`, its ledger row should also make clear:

- which commit closed it;
- whether any follow-up remains;
- whether any risks or watch points carry forward.

---

## Program Summary

Execution baseline:

- the redesign is expected to start from the `nip85-hardening` line of work;
- that branch carries preparatory refactors that are part of the real starting
  point, not disposable side history.

| Tranche | Status | Notes |
|---------|--------|-------|
| 0. Integral codebase validation and assumption audit | done | Planning-time validation completed; execution baseline explicitly fixed to the `nip85-hardening` line of work |
| 1. Contract freeze and rename ledger | not started | |
| 2. SQL and shared-schema foundation | not started | |
| 3. Python domain-model and `Brotr` alignment | not started | |
| 4. Shared derivation and maintenance pipeline alignment | not started | |
| 5. Service-boundary alignment | not started | |
| 6. Score/output and NIP capability alignment | not started | |
| 7. Protocol-agnostic read-core implementation | not started | |
| 8. Deployment-contract normalization | not started | |
| 9. Repository-wide documentation rewrite | not started | |
| 10. Final cleanup, rename sweep, and closeout audit | not started | |

---

## Work-Package Checklist

### Tranche 0 — Integral Codebase Validation And Assumption Audit

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 0.1 Integral architecture validation | done | planning-only | Captured in `17_integral_codebase_validation.md` |
| 0.2 Migration-risk ledger | done | planning-only | Reflected in `16_operational_implementation_plan.md` and `17_integral_codebase_validation.md`; execution baseline fixed to `nip85-hardening` |
| 0.3 Redesign execution ledger bootstrap | done | planning-only | This file initializes the execution ledger/checklist |

### Tranche 1 — Contract Freeze And Rename Ledger

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 Canonical rename ledger | not started | | |
| 1.2 Final contract freeze | not started | | |

### Tranche 2 — SQL And Shared-Schema Foundation

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Shared schema target implementation | not started | | |
| 2.2 SQL function and current-table alignment | not started | | |
| 2.3 Shared analytics and score-output alignment | not started | | |
| 2.4 SQL/triggers/tests/fixtures audit loop | not started | | |

### Tranche 3 — Python Domain-Model And `Brotr` Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 Python model rename and semantic alignment | not started | | |
| 3.2 `Brotr` API alignment with the new shared schema | not started | | |
| 3.3 Domain-facing tests and fixtures alignment | not started | | |

### Tranche 4 — Shared Derivation And Maintenance Pipeline Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 `Refresher` ownership alignment | not started | | |
| 4.2 Current-table maintenance alignment | not started | | |
| 4.3 Shared analytics and interaction maintenance alignment | not started | | |
| 4.4 Refresh pipeline audit and boundedness pass | not started | | |

### Tranche 5 — Service-Boundary Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 `Monitor` boundary hardening | not started | | |
| 5.2 `Synchronizer` boundary hardening | not started | | |
| 5.3 `Assertor` package-complete publication alignment | not started | | |
| 5.4 `Ranker` boundary hardening | not started | | |

### Tranche 6 — Score/Output And NIP Capability Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 Public score-output alignment | not started | | |
| 6.2 Capability-oriented `NIP_REGISTRY` alignment | not started | | |
| 6.3 NIP publication and metadata consistency audit | not started | | |

### Tranche 7 — Protocol-Agnostic Read-Core Implementation

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 7.1 Readable-resource contract introduction | not started | | |
| 7.2 Shared read-core evolution from current read-model stack | not started | | |
| 7.3 `API` adapter alignment | not started | | |
| 7.4 `DVM` adapter alignment | not started | | |
| 7.5 Read-core boundedness and contract audit | not started | | |

### Tranche 8 — Deployment-Contract Normalization

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 8.1 Deployment folder contract normalization | not started | | |
| 8.2 Storage-profile normalization | not started | | |
| 8.3 Protocol exposure policy normalization | not started | | |
| 8.4 Deployment docs and local operator guidance alignment | not started | | |

### Tranche 9 — Repository-Wide Documentation Rewrite

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 9.1 In-code documentation and public API docs rewrite | not started | | |
| 9.2 MkDocs information architecture and narrative rewrite | not started | | |
| 9.3 Folder-level `README.md` and local guidance rewrite | not started | | |
| 9.4 Deployment/operator/contributor docs rewrite | not started | | |
| 9.5 Final reference alignment pass | not started | | |

### Tranche 10 — Final Cleanup, Rename Sweep, And Closeout Audit

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 10.1 Final compatibility-layer removal | not started | | |
| 10.2 Dead-code and stale-shape sweep | not started | | |
| 10.3 Final repository-wide design-hygiene audit | not started | | |
| 10.4 Final verification and release-readiness gate | not started | | |

---

## Open Follow-Ups And Watch Points

Use this section to capture intentionally deferred items that survive a closed
work package.

Each entry should include:

- the originating work package;
- why it was deferred;
- what future tranche should absorb it;
- whether it is a risk, an improvement, or a hard blocker.

At initialization time there are no additional execution-time follow-ups beyond
the planned work packages above.

---

## Update Rule

Whenever a work package closes:

1. update its row in the checklist above;
2. update the tranche summary if the tranche status changed;
3. append or revise any open follow-up or watch point that remains;
4. record the closing commit once it exists;
5. make sure the ledger matches the real final state of the slice before
   starting the next work package.
