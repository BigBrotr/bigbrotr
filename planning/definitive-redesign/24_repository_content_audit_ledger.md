# Repository Content Audit Ledger

## Purpose

This file is the operational memory for the repository-wide leaf-to-root
content audit defined in:

- [23_repository_content_audit_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/23_repository_content_audit_program.md)

It exists so that the audit never depends on:

- memory;
- scattered notes;
- vague impressions of what has “basically been read”;
- or reconstructing scope from git history after the fact.

Every audit wave should update this ledger with the real state of progress,
findings, remediation, and remaining work.

This ledger is also where the audit must keep explicit track of one especially
important distinction:

- files already touched by the redesign execution program;
- files never touched by that program and therefore still potentially carrying
  old assumptions by inertia.

---

## Status Vocabulary

Use these statuses consistently:

- `not started`
- `in progress`
- `auditing`
- `blocked`
- `done`

---

## Baseline Inventory Freeze

Fill this section when the audit actually starts.

- Manifest command:
  `git ls-tree -r --name-only 9dc6cc35 | sort`
- Frozen tracked-file count:
  `542`
- Untouched-file count at audit start:
  `227`
- Frozen date:
  `2026-04-18`
- Notes:
  Baseline frozen from redesign closeout commit `9dc6cc35`. Untouched-file
  count is computed against the redesign execution range
  `c016ec08^..9dc6cc35`, intersected with the final closeout manifest so
  historical renamed/removed paths do not inflate the touched count.

---

## Program Summary

| Wave | Status | Notes |
|------|--------|-------|
| 0. Inventory freeze and traversal map | done | Baseline frozen from redesign closeout commit `9dc6cc35`: full manifest in `25_repository_content_audit_manifest.txt`, untouched manifest in `26_repository_content_audit_untouched_manifest.txt`, and concrete folder/wave mapping in `27_repository_content_audit_traversal_map.md`. Final-manifest counts at audit start: `542` tracked files, `315` redesign-touched final files, `227` untouched final files |
| 1. Deepest non-Python leaves | not started | Read and classify deepest config/support leaves such as workflows, issue templates, deployment service YAML, SQL init packages, monitoring assets, snippets, and static support files against the final desired repository shape |
| 2. Python leaf packages | not started | Read and classify the deepest implementation packages across models, utils, NIPs, core, services, and `services/common`, paying special attention to untouched live code surfaces |
| 3. Tools and tests leaves | not started | Read and classify SQL templates, tooling leaves, fixtures, and the deepest unit/integration test folders against the final repository contract |
| 4. Parent package and folder surfaces | not started | Read and classify parent `README.md`, package exports, and parent-level local guidance only after children are understood |
| 5. Narrative docs and planning surfaces | not started | Re-read MkDocs pages, root guides, and planning/reference documents against the final repository state and identify missing/additional surfaces |
| 6. Root contract and build/CI surfaces | not started | Re-read root config/build/legal/reference surfaces and close any remaining contract drift, including on files the redesign never previously touched |
| 7. Repository-wide gap remediation and closeout | not started | Apply the final keep/update/remove/add decisions, including newly required files, then run the full closeout gate and summarize any consciously deferred items |

---

## Work-Package Checklist

### Wave 0 — Inventory Freeze And Traversal Map

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 0.1 Freeze tracked manifest | done | `docs: bootstrap repository content audit baseline` | Baseline manifest frozen from redesign closeout commit `9dc6cc35` into `25_repository_content_audit_manifest.txt`; exact final closeout repository count is `542` tracked files |
| 0.2 Build leaf-to-root traversal map | done | `docs: bootstrap repository content audit baseline` | Concrete wave/folder sequencing, top-level counts, and paired-surface watch points recorded in `27_repository_content_audit_traversal_map.md` |
| 0.3 Mark untouched tracked files | done | `docs: bootstrap repository content audit baseline` | Untouched final-manifest files identified in `26_repository_content_audit_untouched_manifest.txt`; count at audit start is `227`, using intersection with the final closeout manifest rather than raw diff-path counts |
| 0.4 Initialize decision ledger | done | `docs: bootstrap repository content audit baseline` | This ledger now contains the frozen baseline metadata, Wave 0 completion state, and the execution checklist for the remaining audit waves |

### Wave 1 — Deepest Non-Python Leaves

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 `.github` leaf audit | not started | — | Issue templates, workflows, and other deepest maintained GitHub automation surfaces |
| 1.2 Deployment service-config leaf audit | not started | — | `deployments/*/config/services/` plus paired local guidance and service-config truthfulness |
| 1.3 Deployment SQL/monitoring/support leaf audit | not started | — | `postgres/init`, monitoring assets, pgbouncer, static/support scripts, and paired docs |
| 1.4 Docs asset/snippet/override leaf audit | not started | — | `_snippets`, assets, overrides, and other deepest docs-support surfaces |

### Wave 2 — Python Leaf Packages

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Models/utils/NIPs leaf audit | not started | — | `models`, `utils`, and NIP leaf packages with paired local docs/tests |
| 2.2 Core/services leaf audit | not started | — | `core`, each concrete service package, and `services/common` |

### Wave 3 — Tools And Tests Leaves

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 3.1 SQL-template and tooling leaf audit | not started | — | `tools/` utilities plus SQL-template leaves and generator pairings |
| 3.2 Tests and fixtures leaf audit | not started | — | Unit/integration leaf folders plus fixtures and contract realism |

### Wave 4 — Parent Package And Folder Surfaces

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 4.1 Parent package/export audit | not started | — | Parent Python packages, package exports, and parent-level local guidance |
| 4.2 Parent folder local-guidance audit | not started | — | `README.md` surfaces across `deployments`, `docs`, `tests`, `tools`, `planning`, `.github`, and `src` |

### Wave 5 — Narrative Docs And Planning Surfaces

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 5.1 MkDocs page and IA audit | not started | — | Page content, cross-links, and narrative honesty across the docs tree |
| 5.2 Root references and planning-surface audit | not started | — | Root guides, long-form references, and planning files against the final repository state |

### Wave 6 — Root Contract And Build/CI Surfaces

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 6.1 Root config/build/legal surface audit | not started | — | `pyproject.toml`, `uv.lock`, `Makefile`, MkDocs/CI/pre-commit/config/legal files |
| 6.2 Root entry-surface audit | not started | — | `README.md`, `AGENTS.md`, `CONTRIBUTING.md`, and other root current-state entry surfaces |

### Wave 7 — Repository-Wide Gap Remediation And Closeout

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 7.1 Gap-remediation sweep | not started | — | Apply the full keep/update/remove/add decisions discovered during the audit, including files that were never touched during the redesign itself |
| 7.2 Final repository content-audit gate | not started | — | Run the full closeout verification and record the final residual watch points |

---

## Findings And Deferred Items

Use this section during execution for:

- concrete residual drift findings;
- files to remove or add;
- contradictions against the settled contract;
- untouched files that turn out to need real change despite never being in the
  redesign path;
- consciously deferred items with explicit justification.

No entries yet.
