# Canonical Rename Ledger

## Purpose

This file freezes the **canonical target vocabulary** for the definitive
redesign.

Its job is to stop rename decisions from remaining implicit, scattered, or
reopened casually across later tranches.

This file should be used whenever work touches:

- SQL schema and templates;
- Python models and APIs;
- service code;
- tests and fixtures;
- repository documentation;
- deployment-facing configuration or guidance.

If another planning file mentions target names, this file is the canonical
cross-check for what the target vocabulary should be.

---

## 1. Rename-Ledger Rules

The ledger follows these rules:

- only record names that are architecturally important enough to govern later
  implementation;
- distinguish clearly between:
  - current/repository terms;
  - canonical future terms;
  - migration status;
- do not preserve a misleading current name merely because it is familiar;
- do not invent a more “elegant” future name unless it clearly improves
  semantic honesty and long-term readability.

Status vocabulary:

- `keep`
- `rename`
- `conceptual-only`

`conceptual-only` means:

- the future architecture should think in those terms;
- but no immediate literal code or schema rename is necessarily required in the
  first migration slice.

---

## 2. Shared DB Vocabulary

| Current term | Canonical term | Status | Scope | Why |
|--------------|----------------|--------|-------|-----|
| `metadata` | `document` | rename | shared DB, models, docs | The concept is deduplicated JSONB more general than “metadata” |
| `event_relay` | `event_observation` | rename | shared DB, models, docs | The relation means that an event was observed on a relay |
| `relay_metadata` | `relay_document` | rename | shared DB, models, docs | The relation attaches a document to a relay rather than storing “metadata” as the semantic center |
| `d_tag` | `d_value` | rename | schema, models, docs | The field stores the value of the `d` tag; `d_value` is clearer and still faithful to NIP-01 |
| `raw_score` | `score` | rename | score outputs, docs | The persisted essential value is the score itself |
| stored ordinal `rank` | derived order only | conceptual-only | score outputs, docs | Ordinal rank should not be stored by default when it is derivable |

---

## 3. Timestamp And Relation Vocabulary

| Current / possible term | Canonical term | Status | Scope | Why |
|-------------------------|----------------|--------|-------|-----|
| generic relation timestamp on relay-document history | `associated_at` | rename | shared DB, models, docs | It says exactly when a document became associated with a relay |
| archive-entry timestamp on canonical relay rows | `stored_at` | keep | shared DB, docs | On `relay`, the row meaning is archive entry into the canonical relay pool |
| generic “update” timestamp in shared operational state | no generic timestamp by default | conceptual-only | shared DB | `service_state` should not grow vague bookkeeping fields unless they are semantically needed |

Important note:

- `stored_at` is **not** a general naming pattern to be spread everywhere.
- It is retained only where the row semantics truly justify it.

---

## 4. Read-Side Vocabulary

| Current term | Canonical term | Status | Scope | Why |
|--------------|----------------|--------|-------|-----|
| `read model` as the architectural center | `readable resource` | rename | public read architecture, docs | The future center is approved readable resources, not a thin alias over relations |
| `Catalog` as the conceptual identity of the read side | `relation engine` / `relation execution substrate` | conceptual-only | read-core docs and design | `Catalog` remains important, but as infrastructure under the read core rather than the product-facing concept |
| shared surface above adapters | `read core` | keep | read architecture, docs | This is the clearest name for the protocol-agnostic semantic layer |

Important note:

- migration-only code names such as `ReadModelSurface` and
  `READ_MODEL_REGISTRY` were temporary and have now been removed;
- request helpers that still use `read_model` remain only where they preserve
  the deliberate stable public transport seam;
- but the target mental model is centered on `readable resources` and the
  shared `read core`.

---

## 5. Scoring And Downstream Output Vocabulary

| Current term | Canonical term | Status | Scope | Why |
|--------------|----------------|--------|-------|-----|
| `*_rank` tables when storing only numeric algorithm output | `*_score` tables | rename | shared DB, docs | These tables store score outputs, not ordinal rank materialization |
| `Ranker` | `Ranker` | keep | service boundary | The name is acceptable enough; the key correction is to document it as private compute plus public score export |

Important note:

- the future architecture should describe `Ranker` as a private scoring
  pipeline, not merely as “the place where ranks are computed”;
- but the service name itself does not need to change in the first contract
  freeze.

---

## 6. Deployment And Public-Surface Vocabulary

| Current term | Canonical term | Status | Scope | Why |
|--------------|----------------|--------|-------|-----|
| deployment folder as a convenience packaging detail | deployment as first-class composition | conceptual-only | deployment docs and guidance | The folder is the packaging form of a real product composition |
| per-protocol read whitelists | protocol exposure policy | conceptual-only | deployment and adapter docs | This is the right future name for what `api`, `dvm`, and future adapters control |
| `bigbrotr` / `lilbrotr` as ad hoc deploys | reference deployments with storage profiles | conceptual-only | deployment docs | They are the first concrete examples of a first-class deployment axis |

---

## 7. Terms Explicitly Kept

The redesign is aggressive about fixing misleading names, but it should also
record where the current name is good enough and does **not** need churn just
for aesthetic symmetry.

These are explicitly kept as stable names:

- `relay`
- `event`
- `service_state`
- `Monitor`
- `Refresher`
- `Assertor`
- `NIP_REGISTRY`
- `storage profile`
- `deployment`

The rule is:

- rename when the current name lies;
- keep the name when the meaning is already sufficiently honest.

---

## 8. Migration Use Rule

Later implementation tranches should use this ledger in the following way:

1. if a touched slice still uses an old name that the ledger marks `rename`,
   the work package must either:
   - migrate it;
   - or document explicitly why that rename is deferred;
2. if documentation introduces new vocabulary, it must match this ledger;
3. if code introduces a new important public or schema-facing name, this file
   should be updated before the slice is considered closed.

This ledger is therefore not only reference.
It is part of the execution contract of the redesign.
