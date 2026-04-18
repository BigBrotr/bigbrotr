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

This ledger is also where the audit must keep explicit track of one important
historical distinction:

- files already touched by the redesign execution program;
- files never touched by that program and therefore still potentially carrying
  old assumptions by inertia.

That distinction is informative only.
It must never be used as a shortcut for trust.
All tracked files are high-suspicion audit targets.

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
| 0. Inventory freeze and traversal map | done | Baseline frozen from redesign closeout commit `9dc6cc35`: full manifest in `25_repository_content_audit_manifest.txt`, touched/untouched historical-context manifest in `26_repository_content_audit_untouched_manifest.txt`, and concrete folder/wave mapping in `27_repository_content_audit_traversal_map.md`. Final-manifest counts at audit start: `542` tracked files, `315` redesign-touched final files, `227` untouched final files. All `542` remain first-class high-suspicion audit targets |
| 1. Deepest non-Python leaves | done | `.github`, deployment leaves, monitoring/support leaves, and docs-support leaves are now audited and corrected against the final repository contract |
| 2. Python leaf packages | in progress | Models/utils/NIP leaves are under active audit; the first remediation slice has already removed legacy score-alias drift and tightened public package/docstring contracts in `models` and `nips` |
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
| 0.3 Mark untouched tracked files | done | `docs: bootstrap repository content audit baseline` | Historical touched/untouched context captured via `26_repository_content_audit_untouched_manifest.txt`; untouched final-manifest count at audit start is `227`, using intersection with the final closeout manifest rather than raw diff-path counts. This classification is contextual only; it does not lower suspicion on redesign-touched files |
| 0.4 Initialize decision ledger | done | `docs: bootstrap repository content audit baseline` | This ledger now contains the frozen baseline metadata, Wave 0 completion state, and the execution checklist for the remaining audit waves |

### Wave 1 — Deepest Non-Python Leaves

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 1.1 `.github` leaf audit | done | `chore: align github automation surfaces` | Audited all tracked `.github` leaf surfaces and corrected real drift: added `.github/AGENTS.md` and `.github/workflows/AGENTS.md` as maintained local guidance, removed stale local `CLAUDE.md` leftovers from the live tree, aligned issue-template contact paths with the public docs/security surfaces, tightened the PR template to the actual contributor contract, and strengthened `release.yml` so the validation gate now runs pre-commit plus the repository contract gate (`make ci`, `uv lock --check`, and docs build) instead of only narrating a stronger standard. Targeted YAML/markdown/spelling checks, full `make ci`, and `uv lock --check` all passed before closure |
| 1.2 Deployment service-config leaf audit | done | `chore: align deployment service-config guidance` | Audited the per-service deployment YAML leaves and their paired `config/services/README.md` files against the live service config models. Corrected the misleading leaf contract that claimed every file only contained non-default overrides, removed dead references to nonexistent `brotr/config/services/*.yaml` paths, and rewrote the local guidance so these files are described honestly as deployment-local overlays that may also restate important defaults for operator clarity. The slice intentionally leaves broader parent-level deployment guidance, including the missing `deployments/AGENTS.md` surface, to the later parent-folder audit. Targeted YAML/markdown/spelling checks, full `make ci`, and `uv lock --check` must pass before closure |
| 1.3 Deployment SQL/monitoring/support leaf audit | done | `chore: align deployment sql and monitoring leaf surfaces` | Audited the deployment SQL-init leaves, monitoring assets, pgbouncer configs, static leaves, and paired docs against the final repository contract. The slice found real drift even after the redesign execution program: built-in `07_views_reporting.sql` was still described too generically even though the built-in deployments intentionally ship no regular reporting views; built-in PgBouncer configs still claimed `auth_query`-based auth even though the containers generate a SCRAM userlist at startup; API/DVM dashboards still labeled `readable_resources_exposed` as “Tables Exposed”; the overview dashboards still omitted `ranker` and `assertor` summary rows; and monitoring/docs surfaces still mixed old metric naming (`service_counter`) with the actual Prometheus counter family name (`service_counter_total`). The slice corrected the SQL template plus generated init files, tightened Prometheus alert wording for DuckDB-local failed-run tracking, expanded both overview dashboards to include ranker/assertor summary rows, renamed read-side dashboard cards to “Readable Resources Exposed”, and aligned the paired monitoring/database docs and root references. Targeted pre-commit checks, `uv run python tools/generate_sql.py --check`, `uv run mkdocs build --strict`, full `make ci`, and `uv lock --check` all passed before closure |
| 1.4 Docs asset/snippet/override leaf audit | done | `docs: align docs support leaf surfaces` | Audited `_snippets`, docs-support markdown leaves, theme-support assets, and the MkDocs override seam against the final docs contract. The slice found that the support layer still carried a few real weaknesses: the pipeline/service snippets still used pre-final public naming (`Api`, `Dvm`) and did not show the shared `ReadCore`; the root docs local guide only existed as an untracked `docs/CLAUDE.md` leftover instead of an intentional repo-local guidance file; the empty `docs/overrides/main.html` no longer earned its bytes; and MkDocs was relying on warning-prone implicit nav omission for local support markdown. The slice added a real tracked `docs/README.md`, updated the shared snippets to reflect `API`, `DVM`, and the protocol-agnostic read core, removed the empty theme override plus `custom_dir`, and formalized docs-support exclusions via `mkdocs.yml:exclude_docs` so local guidance/snippet files no longer collide with the public site. Targeted pre-commit checks and `uv run mkdocs build --strict` passed before closure |

### Wave 2 — Python Leaf Packages

| Work package | Status | Commit | Notes |
|--------------|--------|--------|-------|
| 2.1 Models/utils/NIPs leaf audit | in progress | — | `models`, `utils`, and NIP leaf packages with paired local docs/tests. Initial wide read and first remediation slice closed public docstring drift (`API`/`DVM`, static capability-registry wording, NIP-85 package framing) plus the residual `rank` alias in `nip85.data`; the full leaf-package audit remains open until the remaining files and paired tests are fully judged |
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
- touched files that still need real change despite prior redesign work;
- untouched files that turn out to need real change despite never being in the
  redesign path;
- consciously deferred items with explicit justification.

- `1.1` `.github` slice, resolved in `chore: align github automation surfaces`:
  - added maintained `.github/AGENTS.md` / `.github/workflows/AGENTS.md`
    guidance;
  - removed stale local `.github/**/CLAUDE.md` leftovers from the live tree;
  - aligned issue-template docs/security contact links with the final public
    support surfaces;
  - tightened the PR template and release validation workflow to the actual
    contributor/repository contract.
- Deferred to later waves:
  - many other `CLAUDE.md` local-guidance files still exist outside `.github`;
    they must be judged folder by folder against the final repository shape
    rather than removed mechanically in the `.github` slice.
  - the parent-level `deployments/AGENTS.md` guidance surface is still missing
    even though the root repository contract points to it; handle that in the
    parent-folder guidance wave rather than mixing it into the service-config
    leaf slice.
- `1.3` deployment leaf slice, resolved in `chore: align deployment sql and monitoring leaf surfaces`:
  - clarified that the built-in SQL package intentionally ships no regular
    reporting views, and regenerated the built-in `07_views_reporting.sql`
    files from the corrected template;
  - fixed dishonest built-in PgBouncer comments that still described
    `auth_query` even though container startup generates a SCRAM userlist;
  - expanded the built-in overview dashboards so `ranker` and `assertor` are
    represented alongside the other continuous services instead of existing
    only as dedicated dashboards;
  - renamed API/DVM cards from “Tables Exposed” to “Readable Resources
    Exposed” so the monitoring surface matches the final read-core contract;
  - aligned monitoring/database docs with the actual Prometheus counter name
    (`service_counter_total`) and the empty built-in reporting-view slot.
- `1.4` docs-support leaf slice, resolved in `docs: align docs support leaf surfaces`:
  - replaced the untracked `docs/CLAUDE.md` leftover with a real tracked
    `docs/README.md` local guide;
  - updated shared docs snippets so the public vocabulary now uses `API`,
    `DVM`, and `ReadCore`;
  - removed the empty MkDocs theme override that no longer earned its place;
  - formalized support-file exclusion via `mkdocs.yml:exclude_docs` so local
    guidance and snippet fragments stop relying on implicit nav warnings.
- Deferred to later waves:
  - some narrative docs outside the support-layer slice still use public
    service casing such as `Api` / `Dvm`; handle that during the narrative-docs
    and root-reference waves instead of broadening the leaf-support slice.
- `2.1` models/utils/NIPs leaf audit, first remediation slice:
  - tightened public `models`/`nips` docstring wording so leaf-package prose
    uses the final `API`/`DVM` adapter framing and the static capability
    registry language rather than older public wording;
  - corrected `bigbrotr.nips.nip85` so the package surface is described
    honestly as shared between `Ranker` and `Assertor`, not as an
    Assertor-only facade;
  - removed the residual `rank` fallback from `nip85.data.from_db_row()`
    helpers so leaf-package data models now consume the final shared
    `score` contract only;
  - added unit coverage that proves legacy `rank`-only rows no longer feed
    NIP-85 assertion models.
- `2.1` models/utils/NIPs leaf audit, second remediation slice:
  - tightened the NIP-layer prose so historical `*Metadata` class names are
    described honestly as result containers, while the selected outputs are
    framed as NIP document/probe families that later become shared
    `document` / `relay_document` records;
  - aligned the top-level NIP package/module docs and paired NIP-66 test
    fixture prose with that final-repository contract, without reopening
    compatibility-heavy class renames.
- `2.1` models/utils/NIPs leaf audit, third remediation slice:
  - aligned the top-level `nip66` orchestration surface and paired tests with
    the final contract, so the module now describes short fields as probe
    result containers that later serialize into `document` /
    `relay_document` records instead of implying that `metadata` is still the
    canonical repository-level storage concept;
  - tightened helper names, comments, and registry-test wording to match that
    result-family framing.
- `2.1` models/utils/NIPs leaf audit, fourth remediation slice:
  - applied the same contract hardening to the top-level `nip11` surface and
    paired tests, keeping the historical `Nip11InfoMetadata` class name for
    compatibility while describing it honestly as a result container whose
    persisted shape is a stored `document` plus `relay_document` association.
- `2.1` models/utils/NIPs leaf audit, fifth remediation slice:
  - cleaned up the remaining single-probe `nip66` test names and docstrings
    that still implied `metadata` was the canonical output shape, so the leaf
    test surface now talks consistently about result containers.
- `2.1` models/utils/NIPs leaf audit, sixth remediation slice:
  - removed the stale `models.nips` module-path wording from the remaining
    NIP-66 unit-test module docstrings and the `tests/unit/nips` package
    surface, so the leaf test tree now names the live `bigbrotr.nips`
    package honestly;
  - corrected `src/bigbrotr/nips/nip11/README.md` so the top-level NIP-11
    seam is described as fetch orchestration plus document serialization,
    rather than the older ambiguous `fetch/probe` wording.
