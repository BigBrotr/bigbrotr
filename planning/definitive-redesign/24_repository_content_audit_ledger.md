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
- `2.1` models/utils/NIPs leaf audit, seventh remediation slice:
  - aligned the remaining `tests/unit/utils` package and module docstrings to
    the live `bigbrotr.utils.*` package paths instead of the older shortened
    `utils.*` phrasing;
  - added the missing `tests/unit/models/__init__.py` package marker docstring
    so both leaf unit-test packages now have an intentional local surface
    instead of one empty package file and one under-described one.
- `2.1` models/utils/NIPs leaf audit, eighth remediation slice:
  - removed the unused module-level logger scaffolding from
    `src/bigbrotr/models/service_state.py`, so the leaf models surface no
    longer carries dead code that serves no runtime or debugging purpose;
  - confirmed that the local `README.md` / `CLAUDE.md` duplication in the
    audited `models` / `utils` leaf folders is a broader repository policy
    question, not a safe one-folder cleanup, and therefore remains deferred
    for the later parent/root guidance waves.
- `2.1` models/utils/NIPs leaf audit, ninth remediation slice:
  - inspected the local `CLAUDE.md` guides in `src/bigbrotr/models`,
    `src/bigbrotr/utils`, `tests/unit/models`, and `tests/unit/utils` and
    confirmed they are outside the tracked-manifest scope of this repository
    content audit, so the live tracked slice continues to govern only the
    code, test, and `README.md` surfaces in those folders;
  - left the repo-wide keep/remove decision for `CLAUDE.md` vs `README.md`
    explicitly deferred to the later parent/root guidance waves, where that
    policy can be applied consistently instead of piecemeal.
- `2.1` models/utils/NIPs leaf audit, tenth remediation slice:
  - aligned the remaining tracked human-facing overlay-network wording in the
    `utils.protocol` surface and its paired unit tests so these leaf packages
    consistently say `Lokinet`, while preserving the stable technical enum/TLD
    names `LOKI` and `.loki` in the actual runtime contract;
  - confirmed that this is documentation-level cleanup only, not a domain
    rename of the persisted network identifier.
- `2.1` models/utils/NIPs leaf audit, eleventh remediation slice:
  - aligned the tracked `tests/unit/nips/test_base.py` language with the final
    NIP-layer contract, so the base tests now describe `BaseNipMetadata` as a
    historical-name result container instead of narrating it as the canonical
    persistence model;
  - kept the public compatibility surface intact: no runtime rename was
    introduced, only the human-facing test wording and local variable names
    were tightened.
- `2.1` models/utils/NIPs leaf audit, twelfth remediation slice:
  - aligned the public `bigbrotr.nips` package docstring and the shared
    NIP-66 test fixtures with the final contract, so they now distinguish
    historical-name result containers and probe families from canonical stored
    document families;
  - kept all runtime exports and lazy-import behavior unchanged: this slice
    tightened public/package narrative only.
- `2.1` models/utils/NIPs leaf audit, thirteenth remediation slice:
  - aligned the remaining tracked NIP test wording around Lokinet and
    NIP-66 fixture sections, so the human-facing fixture narrative now says
    `Lokinet` and `result/probe fixtures` while keeping the stable technical
    `.loki` network identifier and `loki_*` helper names unchanged;
  - kept this slice strictly documentation/test-data hygiene: no runtime
    behavior or persisted naming contract changed.
- `2.1` models/utils/NIPs leaf audit, fourteenth remediation slice:
  - introduced a central human-facing network label on
    `bigbrotr.models.constants.NetworkType` and used it for overlay/clearnet
    failure reasons in the tracked `utils` and `nip66` leaves, so runtime
    messages now say `Tor`, `I2P`, and `Lokinet` while preserving the stable
    persisted identifiers like `tor`, `i2p`, and `loki`;
  - strengthened the paired unit tests to lock that distinction in place
    instead of only asserting generic failure substrings.
- `2.1` models/utils/NIPs leaf audit, fifteenth remediation slice:
  - aligned the tracked NIP package README surfaces so `nip85` is described as
    the full public provider-package surface, not just a bag of score/data
    helpers;
  - kept this slice documentation-only while pairing it with the existing
    NIP-85 builder/data tests to guard the live public package contract.
- `2.1` models/utils/NIPs leaf audit, sixteenth remediation slice:
  - added intentional package markers to the tracked `tests/unit/nips`
    subpackages and aligned the `nip85` test README with the final
    provider-package wording, so the local test-package surfaces no longer rely
    on empty `__init__.py` files plus stale helper-oriented narrative;
  - paired the slice with NIP package import and builder/data tests to keep the
    tracked test-package contract honest.
- `2.1` models/utils/NIPs leaf audit, seventeenth remediation slice:
  - aligned the tracked `bigbrotr.models` package surface with the final
    models-vs-NIPs boundary, so the public package docs now describe
    `bigbrotr.nips` as the home of historical-name result containers and
    provider/probe builders rather than a vague bag of helper utilities;
  - mirrored that boundary in the local `models` README so the tracked package
    surface stays consistent for library readers and maintainers.
- `2.1` models/utils/NIPs leaf audit, eighteenth remediation slice:
  - aligned the tracked `bigbrotr.utils` package surface with the final
    split public facade/internal-seam structure, so the public docs now name
    `protocol.py` as the facade, `protocol_*` modules as implementation seams,
    and avoid upward-layer examples in the package docstring;
  - mirrored that boundary in the local utils README and unit-test package
    surfaces so the tracked low-level utility contract stays consistent for
    library readers and maintainers.
- `2.1` models/utils/NIPs leaf audit, nineteenth remediation slice:
  - aligned the tracked root `bigbrotr.nips` narrative and paired parsing test
    surfaces with the live permissive parsing contract, so `parsing.py` is
    described as a parse/report seam rather than only a one-way helper;
  - mirrored that in the root `tests/unit/nips` package narrative so the
    tracked NIP test surface now names result containers, parse/report helpers,
    builders, and registry seams explicitly.
- `2.1` models/utils/NIPs leaf audit, twentieth remediation slice:
  - tightened the tracked `utils` key-loading package narrative so the public
    low-level surface no longer presents higher-level service config wrappers as
    part of the local package contract;
  - kept the practical context about key consumers, but described wrapper
    policy generically so the `utils` package remains documented as a reusable
    low-level library seam.
- `2.1` models/utils/NIPs leaf audit, twenty-first remediation slice:
  - moved `NostrKeysConfig` coverage out of `tests/unit/utils/test_keys.py` and
    into `tests/unit/services/common/test_configs.py`, because the shared
    service-layer config wrapper is not part of the local `utils` leaf contract;
  - tightened `bigbrotr.nips.nip66.rtt` so the tracked NIP leaf surface now
    describes signing dependencies as injected higher-layer inputs rather than
    naming a concrete service config wrapper;
  - corrected the paired RTT test-module inventory so it no longer advertises a
    nonexistent `_validate_network()` surface.
- `2.1` models/utils/NIPs leaf audit, twenty-second remediation slice:
  - removed the remaining typed service-layer leak from
    `bigbrotr.utils.protocol` / `bigbrotr.utils.protocol_manager` by replacing
    the public `NetworksConfig` annotation with a minimal local
    `RelayNetworkPolicy` protocol;
  - strengthened the paired protocol tests to use a small structural policy
    stub rather than an unbounded mock, proving the manager now depends only on
    the generic timeout/proxy contract it actually needs.
- `2.1` models/utils/NIPs leaf audit, twenty-third remediation slice:
  - tightened `bigbrotr.models.service_state` so the shared `state_value`
    payload is serialized as deterministic compact JSON instead of inheriting
    incidental whitespace and formatting from the default `json.dumps()`
    behavior;
  - strengthened the paired model tests to lock that compact deterministic
    contract explicitly and removed the stale type-ignore that still pretended
    plain-string `owner` / `state_type` values were outside the supported
    constructor contract;
  - corrected the remaining `ServiceName` doc wording that still referred to
    `service_state` filtering by “service name” instead of the final `owner`
    vocabulary.
- `2.1` models/utils/NIPs leaf audit, twenty-fourth remediation slice:
  - corrected the remaining false boundary claim on the tracked
    `bigbrotr.models` package surface: the models layer is free of
    higher-level BigBrotr dependencies, but not literally stdlib-only because
    leaf modules legitimately use focused external protocol and URL libraries;
  - aligned the tracked `models/README.md` with that same contract so package
    guidance now documents the real boundary instead of implying a stricter
    rule than the live code follows;
  - corrected the tracked `Relay` module narrative so local relay handling is
    described honestly as a policy distinction between default raw-input
    parsing and explicitly admitted canonical local rows;
  - deferred the paired drift in `docs/user-guide/architecture.md` to the
    later narrative-docs wave, because it sits outside the leaf-package scope
    of `2.1`.
- `2.1` models/utils/NIPs leaf audit, twenty-fifth remediation slice:
  - removed the last concrete `NetworksConfig` reference from the tracked
    `bigbrotr.utils.protocol_manager` public narrative, so the relay-client
    manager now describes only the structural `RelayNetworkPolicy` contract it
    actually depends on;
  - kept the concrete `NetworksConfig` surface where it belongs, in the
    service-common config layer and its own tests, instead of letting that
    wrapper leak back into the low-level utils contract.
- `2.1` models/utils/NIPs leaf audit, twenty-sixth remediation slice:
  - corrected the remaining NIP leaf contracts that still promised
    ``fetch()`` / ``probe()`` would "never raise exceptions", even though the
    live code intentionally propagates cancellation and system-exit style
    exceptions;
  - aligned `bigbrotr.nips`, `BaseNip`, `Nip11InfoMetadata`, `Nip11`,
    `Nip66RttMetadata`, and `Nip66` so they now describe the real contract:
    ordinary operational failures are contained in result objects, while
    cancellation / shutdown signals still escape.
- `2.1` models/utils/NIPs leaf audit, twenty-seventh remediation slice:
  - aligned the tracked `bigbrotr.nips.parsing` docs with the real typed-list
    behavior already enforced by code and tests: invalid list elements are
    filtered, and fully empty list results are dropped rather than preserved;
  - kept the change scoped to the parser contract narrative because the live
    semantics and paired unit coverage were already correct.
- `2.1` models/utils/NIPs leaf audit, twenty-eighth remediation slice:
  - corrected the tracked `bigbrotr.utils.streaming` contract around
    `idle_timeout`: the live algorithm checks for lack of progress between
    fetch/verify iterations, but it does not cancel an already-running
    fetch/verify step mid-flight;
  - added paired unit coverage that locks this behavior in place, so future
    refactors cannot silently reintroduce a harder timeout contract in the
    docs without either changing the runtime or updating the tests.
- `2.1` models/utils/NIPs leaf audit, twenty-ninth remediation slice:
  - corrected the tracked `bigbrotr.nips.nip66.http` note that still claimed
    HTTP header extraction was the only NIP-66 probe supporting both clearnet
    and overlay relays; the live RTT probe already supports overlay relays
    when a proxy is configured;
  - tightened the same note so it attributes the relaxed SSL stance to the
    overlay transport contract, not to the SOCKS proxy itself.
- `2.1` models/utils/NIPs leaf audit, thirtieth remediation slice:
  - corrected the tracked `bigbrotr.nips.nip66.net` notes that still claimed
    IPv6-specific network ranges are always recorded separately; the live code
    already treats that field as conditional on the IPv6 ASN lookup returning
    a network, which is exactly what the paired unit tests cover;
  - kept this slice documentation-only because the runtime behavior and
    existing test coverage were already correct.
- `2.1` models/utils/NIPs leaf audit, thirty-first remediation slice:
  - aligned the remaining tracked overlay-transport SSL wording in
    `bigbrotr.nips.nip11.info` and `bigbrotr.utils.protocol` with the
    repository's final leaf contract: overlay relays still use relaxed SSL
    settings, but the reason is the overlay transport's own privacy/security
    layer, not a simplistic claim that the overlay "provides encryption";
  - kept the slice documentation-only while deliberately matching the wording
    already fixed in `bigbrotr.nips.nip66.http`.
- `2.1` models/utils/NIPs leaf audit, thirty-second remediation slice:
  - corrected the paired `bigbrotr.nips.nip66.data.Nip66NetData` note that
    still promised `net_network_v6` as an always-recorded side channel; the
    live contract is conditional, exactly as the runtime and paired
    `test_net.py` coverage already enforce;
  - kept this slice documentation-only because the implementation and tests
    were already aligned with the final repository behavior.
