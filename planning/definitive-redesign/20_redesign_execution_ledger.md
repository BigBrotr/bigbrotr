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
| 1. Contract freeze and rename ledger | done | Canonical rename vocabulary and final contract-freeze companion are now both closed |
| 2. SQL and shared-schema foundation | done | Relay archive-entry semantics, document storage rename, relay-document history rename, event-observation rename, the core-storage closure audit, slim shared current tables, shared analytics/score-output alignment, and the storage-retention/orphan-cleanup audit are all closed |
| 3. Python domain-model and `Brotr` alignment | done | `DocumentType` rename, service-state owner vocabulary alignment, and the domain-facing fixture/test pass are all closed |
| 4. Shared derivation and maintenance pipeline alignment | done | `Refresher` ownership, source-watermark checkpointing, bounded incremental windows, and backlog reporting are all closed |
| 5. Service-boundary alignment | done | `Monitor`, offline `Refresher` ownership, `Assertor` package-complete publication, and `Ranker` boundary hardening are all closed |
| 6. Score/output and NIP capability alignment | in progress | The static capability registry and NIP-85 builder/publication alignment are now closed; the deeper score-vocabulary sweep remains pending |
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
| 1.1 Canonical rename ledger | done | `docs: add canonical rename ledger` | Captured in `21_canonical_rename_ledger.md`; target vocabulary is now centralized |
| 1.2 Final contract freeze | done | `docs: freeze redesign execution contracts` | Captured in `22_final_contract_freeze.md`; planning-file precedence and redesign baseline are now explicit |

### Tranche 2 — SQL And Shared-Schema Foundation

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1a Relay archive-entry semantics | done | `refactor: align relay archive-entry semantics` | Renamed the canonical relay archive-entry field from `discovered_at` to `stored_at` across schema templates, generated SQL, Python models, monitor/runtime surfaces, fixtures, and tests; targeted tests plus full `make ci` and `uv lock --check` passed before closure |
| 2.1b Document storage rename | done | `refactor: rename metadata storage to document` | Renamed the content-addressed storage surface from `metadata` to `document` across SQL templates, generated SQL, Python models, `Brotr`, read-model exposure, deployment config, fixtures, and integration/unit tests; closure audit caught and fixed an accidental `nostr_sdk.Metadata` alias drift in `event_builders.py`; targeted tests, full `make ci`, and `uv lock --check` all passed before closure |
| 2.1c Relay-document history rename | done | `refactor: rename relay metadata history to relay document` | Renamed the relay-to-document history surface from `relay_metadata` to `relay_document` across SQL templates, generated SQL, Python models, NIP serialization, monitor/refresher query and config surfaces, deployment config, dashboards/alerts, fixtures, and unit/integration tests; closure audit fixed over-eager bulk-renamed `generated_at` assertions so NIP result timestamps stayed semantic while relation rows use `associated_at`; targeted unit suites, targeted integration suites, full `make ci`, and `uv lock --check` all passed before closure |
| 2.1d Event-observation rename | done | `refactor: rename event relay history to event observation` | Renamed the event-to-relay observation history surface from `event_relay` to `event_observation` across SQL templates, generated SQL, Python models, `Brotr`, finder/synchronizer/refresher query and runtime surfaces, read-model exposure, docs, fixtures, and unit/integration tests; closure audit fixed watermark helper and enum drift, corrected over-eager rename fallout in `tools/migrate_relay_urls.py`, and verified the slice with targeted tests, full `make ci`, and `uv lock --check` before closure |
| 2.1e Core-storage closure audit | done | `refactor: close core storage contract audit` | Closed the post-rename storage-contract audit across root guidance, README, user-guide docs, monitoring alerts, refresher config descriptions, test fixtures, and support references so the canonical shared-storage vocabulary is now consistently `relay`/`event`/`event_observation`/`document`/`relay_document`; closure audit also fixed the central `sample_relay_document` fixture naming drift, tightened the database reference around the compound `(document_id, role) -> document(id, type)` foreign key, and verified the slice with targeted tests, full `make ci`, and `uv lock --check` before closure |
| 2.2 SQL function and current-table alignment | done | `refactor: slim shared current tables` | Renamed the shared winner-map tables to `replaceable_event_current` and `addressable_event_current`, slimmed `replaceable_event_current`, `addressable_event_current`, and `relay_document_current` down to canonical winner references, and aligned refresh SQL, indexes, read-model exposure, deployment config, generated SQL, docs, and tests to the new narrow shapes; closure audit removed redundant uniqueness declarations, fixed residual planning drift, and recorded the explicit operational exception that `contact_lists_current` and `contact_list_edges_current` stay materialized for now because ranker sync and `nip85_follower_count_refresh()` still consume them; targeted tests, `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` all passed before closure |
| 2.3 Shared analytics and score-output alignment | done | `refactor: align shared analytics and score outputs` | Aligned shared analytics naming to the event-centric contract (`*_count`, `first_event_created_at`, `last_event_created_at`) across SQL templates, generated SQL, docs, and integration coverage; replaced public `nip85_*_ranks` tables with `pubkey_score`, `event_score`, `addressable_score`, and `identifier_score`; kept `algorithm_id` in the shared score-table keys and exported only the final public `score`, dropping shared `raw_score`, stored ordinal `rank`, and `computed_at`; updated ranker export queries, assertor joins, user-facing docs, README surfaces, and integration tests; closure audit caught only a formatting drift in `test_derived_tables.py`, fixed it, and revalidated the slice with targeted integration tests, targeted unit tests, `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` before closure |
| 2.4 SQL/triggers/tests/fixtures audit loop | done | `refactor: remove orphan cleanup assumptions` | Removed the shared-schema orphan cleanup contract from `Brotr`, SQL templates, generated init SQL, tests, and user-facing docs so storage retention no longer assumes `event` rows must keep `event_observation` children or `document` rows must keep `relay_document` children; replaced the old cleanup integration coverage with explicit storage-retention tests, rewrote the `new-service` guide to match the real service package/registry/CLI structure, aligned remaining score-table terminology and migration tooling phase labels, and revalidated the slice with targeted tests, `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` before closure |

### Tranche 3 — Python Domain-Model And `Brotr` Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 Python model rename and semantic alignment | done | `refactor: rename metadata types to document types` | Renamed the public model enum from `MetadataType` to `DocumentType` across the package root, model exports, NIP registry wiring, monitor utilities, tests, and the touched user/developer docs; closure audit cleaned remaining metadata-centric wording in `Document`, `RelayDocument`, NIP docstrings, and monitor helper docs, fixed the top-level `bigbrotr.__all__` ordering drift caught by `test_dir_returns_all`, fixed the sorted-`__all__` drift caught by `make ci`, and revalidated the slice with targeted unit/integration coverage, full `make ci`, and `uv lock --check` before closure |
| 3.2 `Brotr` API alignment with the new shared schema | done | `refactor: align service-state owner vocabulary` | Aligned the `service_state` contract to the final schema-facing `owner` vocabulary across the `ServiceState` model, `ServiceStateDbParams`, `Brotr` query/delete surfaces, shared `ServiceStateStore`, direct service queries, rebuild/migration tooling, SQL templates, generated deployment init SQL, touched user-guide docs, and the affected unit/integration/API/DVM test surfaces; closure audit confirmed there is no remaining live `service_name` drift in the service-state path, regenerated SQL stayed in sync, and the slice revalidated with a large targeted suite (`854 passed`), full `make ci`, and `uv lock --check` before closure |
| 3.3 Domain-facing tests and fixtures alignment | done | `test: align domain-facing document fixtures` | Aligned the remaining domain-facing test and fixture vocabulary for already-closed shared-storage renames so audited surfaces now use `document`, `document_type`, and `d_value` instead of stale `metadata` / `meta_type` / helper-level `d_tag`; closure audit confirmed no live metadata drift remains in the touched fixtures and integration suites, and revalidated the slice with a targeted `148 passed` suite, full `make ci`, and `uv lock --check` before closure |

### Tranche 4 — Shared Derivation And Maintenance Pipeline Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 `Refresher` ownership alignment | done | `refactor: align refresher ownership boundaries` | Reclassified `contact_lists_current` and `contact_list_edges_current` out of the narrow current winner target set and into shared analytics/operational facts, then aligned refresher target enums, dependency validation, deployment configs, SQL templates/generated init assets, rebuild tooling, repo guidance, user docs, and refresher tests to the new ownership boundary; targeted refresher + NIP-85 pipeline tests, `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` all passed before closure |
| 4.2 Shared analytics maintenance alignment | done | `fix: align refresher source watermark checkpointing` | Aligned incremental refresher checkpointing with the true consumed source maxima by advancing `event_observation` and `relay_document` watermarks to `MAX(observed_at)` / `MAX(associated_at)` instead of wall-clock time, eliminating a skip window for delayed source rows between cycles; added targeted unit coverage for the new semantics plus paired integration regressions proving delayed `event_observation` and `relay_document` rows are still consumed on the next run, and revalidated the slice with targeted refresher suites (`52 passed`), `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` before closure |
| 4.3 Heavy-derivation boundedness | done | `refactor: bound refresher incremental source windows` | Added an explicit bounded incremental-source window to the refresher processing contract so one target slice no longer has to consume an arbitrarily large backlog in a single cycle; watermark queries now bound the upper checkpoint against the earliest pending source timestamp, the service passes the configured source window through both event and document source paths, deployment defaults and user docs now advertise the bounded behavior, and new unit/integration coverage proves both bounded slicing and multi-cycle resume semantics before closure with targeted refresher suites (`55 passed`), full `make ci`, and `uv lock --check` |
| 4.4 Refresh pipeline audit and boundedness pass | done | `refactor: expose refresher backlog reporting` | Completed the refresher pipeline audit by making bounded backlog state explicit in the service’s reporting surface: cycle results now expose event/document backlog booleans derived from watermark lag, emitted metrics now include dedicated backlog gauges, `refresh_completed` logs now carry lag and backlog state, and monitoring docs were updated so operators can distinguish “cycle completed” from “fully caught up”; targeted refresher suites (`56 passed`), full `make ci`, and `uv lock --check` all passed before closure |

### Tranche 5 — Service-Boundary Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 `Monitor` internal restructuring | done | `refactor: isolate monitor discovery publication` | Clarified the internal `Monitor` boundary without splitting the service: per-relay workers now perform probing only, relay-document persistence remains the authoritative chunk-boundary write phase, and kind `30166` discovery publishing now runs as a separate post-persistence best-effort phase. This prevents discovery broadcast failures from reclassifying a healthy relay as a monitor failure or discarding already-computed health results, while keeping publication bounded through the existing concurrent stream machinery. The slice also introduced an explicit control-plane publication phase for kind `0` / `10002` / `10166`, updated monitor docs, and closed the remaining ledger drift so Tranche 5/6 names match the canonical operational plan. Targeted monitor suites (`215 passed`), `python3 tools/generate_sql.py --check`, full `make ci`, and `uv lock --check` passed before closure |
| 5.2 `Refresher` authoritative ownership | done | `refactor: align refresher maintenance ownership` | Hardened the `Refresher` ownership boundary outside the long-running service itself by renaming the offline rebuild surface from `tools/rebuild_analytics.py` to `tools/rebuild_refresher_state.py`, renaming the exported rebuild entrypoint accordingly, and updating relay-URL migration tooling plus repository/user documentation so maintenance flows now clearly describe Refresher-owned shared derivation state instead of a separate “analytics rebuild” subsystem. This keeps offline replay, checkpoint alignment, and downstream assertor invalidation anchored to the same target registry the `Refresher` owns at runtime. Targeted tooling suites (`10 passed`), full `make ci`, and `uv lock --check` passed before closure |
| 5.3 `Assertor` package-complete publication alignment | done | `refactor: publish assertor trusted provider lists` | Completed the Assertor provider-package boundary by wiring optional Kind `10040` trusted-provider-list publication into the same cycle orchestration, checkpoint namespace, change detection, metrics surface, deployment config, monitoring surfaces, and user-facing docs already used for trusted assertions and the Kind `0` provider profile. The new publication path derives canonical provider declarations from the enabled assertion kinds plus configured tag names, uses an explicit or first-relay hint as the advertised relay, and persists its own `10040` checkpoint without leaking ownership outside Assertor. Targeted assertor + NIP-85 pipeline suites (`87 passed`), full `make ci` (`3272 passed`), `python3 tools/generate_sql.py --check`, and `uv lock --check` all passed before closure |
| 5.4 `Ranker` boundary hardening | done | `refactor: harden ranker public score boundary` | Removed DuckDB-private run bookkeeping from the public `RankCycleResult` surface so `Ranker.rank()` now returns operational progress plus exported score counts without leaking local run ids or failed-run counters; kept the DuckDB housekeeping metrics private to runtime emission, renamed score-write logs and gauges to `*_scores_written`, aligned dashboards/docs/config wording to the score contract, and revalidated the slice with targeted ranker unit/integration suites, full `make ci`, and `uv lock --check` before closure |

### Tranche 6 — Score/Output And NIP Capability Alignment

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 Formalize the static capability registry | done | `refactor: formalize static nip capability registry` | Strengthened `NIP_REGISTRY` into a more formal static capability surface by replacing loose strings with `NipCapability`, renaming `metadata_types` to `document_types`, adding explicit `service_names`, and exposing static lookup helpers for service, document type, event kind, and capability resolution. The slice also expanded the lazy public `bigbrotr.nips` surface accordingly, added targeted registry/lazy-import coverage, and updated architecture/developer docs so `nips/` is now described as the NIP-aware layer that includes the static registry plus NIP-85 builder/data helpers rather than only the NIP-11/NIP-66 runtime implementations. Targeted NIP + lazy-import suites, full `make ci`, and `uv lock --check` passed before closure |
| 6.2 Align NIP-85 event builders and publication paths | done | `refactor: align nip85 builders with assertor publication` | Aligned the NIP-85 provider-package surface so the Assertor now imports its assertion and provider-package builders from `bigbrotr.nips.nip85` instead of the generic top-level builder module, exported the NIP-85 builders directly from that package, and tightened builder semantics so event/addressable assertions emit canonical author `p` tags while identifier assertions emit the canonical `i` subject tag. The slice also updated assertion change-detection hashes to track author-tag changes, expanded unit/integration coverage to assert the new public tags and package exports, and revalidated the work with targeted NIP-85/assertor suites, full `make ci`, and `uv lock --check` before closure |
| 6.3 Align score-output naming and usage | not started | | |

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

- Originating work package: `2.3 Shared analytics and score-output alignment`
- Deferred item: `addressable_score` still keys the subject as canonical
  `event_address TEXT` rather than the future decomposed
  `(pubkey, kind, d_value)` shape described in the target schema
- Why deferred: the current `Ranker`, `Assertor`, tests, and NIP-85 fact tables
  already operate on canonical address strings, so decomposing the key here
  would have forced a larger cross-tranche refactor than this slice should
  absorb
- Future tranche: revisit during the later NIP/publication alignment work if
  the public score contract is narrowed further
- Classification: improvement / watch point, not blocker

- Originating work package: `5.4 Ranker boundary hardening`
- Deferred item: the private DuckDB store and helper types still use
  `raw_score` / `rank` for internal intermediates and deterministic export
  ordering
- Why deferred: the slice hardened the public/service boundary first by
  removing DuckDB run bookkeeping from the public cycle result and by
  realigning score-facing logs, gauges, and docs; a deeper private naming sweep
  belongs with the later cross-surface score vocabulary pass
- Future tranche: `6.3 Align score-output naming and usage`
- Classification: improvement / watch point, not blocker

- Originating work package: `3.1 Python model rename and semantic alignment`
- Follow-up status: resolved in `3.2 Brotr API alignment with the new shared schema`
- Outcome: the service-state path now uses the final schema-facing `owner`
  vocabulary across model, `Brotr`, SQL, shared queries, tooling, touched docs,
  and the audited test surface
- Classification: closed follow-up

---

## Update Rule

Whenever a work package closes:

1. update its row in the checklist above;
2. update the tranche summary if the tranche status changed;
3. append or revise any open follow-up or watch point that remains;
4. record the closing commit once it exists;
5. make sure the ledger matches the real final state of the slice before
   starting the next work package.
