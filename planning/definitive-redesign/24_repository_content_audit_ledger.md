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
- `2.1` models/utils/NIPs leaf audit, hundred-and-third remediation slice:
  - `Nip66NetMetadata._net()` now lets dual-stack IPv6 data backfill
    `net_asn_org` only when IPv4 already identified the same ASN number but
    left the organization blank, preserving IPv4 ASN priority without
    needlessly dropping confirmed organization data;
  - paired `nip66/net` tests now pin both sides of that contract: matching
    IPv6 ASN may fill the org name, mismatched IPv6 ASN must not.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fourth remediation slice:
  - `resolve_host()` now spends one shared timeout budget across IPv4 and
    IPv6 resolution instead of accidentally granting each family the full
    caller timeout;
  - `Nip66GeoMetadata.probe()` and `Nip66NetMetadata.probe()` now propagate
    the remaining budget across hostname resolution and the follow-up GeoIP or
    ASN lookup, so their public `timeout` parameter is finally an honest
    end-to-end bound;
  - paired DNS, `nip66/geo`, and `nip66/net` tests now pin the reduced
    remaining-time behavior directly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifth remediation slice:
  - shared-session helpers now reject empty relay batches before allocating a
    client or attempting a zero-relay connect, keeping the public
    multi-relay-session contract honest;
  - paired `protocol_sessions` and `protocol` tests now pin the fail-fast
    behavior for both the low-level helper and the `NostrClientManager`
    facade.
- `2.1` models/utils/NIPs leaf audit, hundred-and-sixth remediation slice:
  - `Nip11InfoMetadata.fetch()` now spends one shared timeout budget across
    the verified HTTPS attempt and any insecure SSL fallback instead of
    accidentally giving each attempt the full caller timeout;
  - paired `nip11/test_info.py` coverage now pins the reduced remaining-time
    behavior on the fallback path directly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-seventh remediation slice:
  - the RTT write phase now spends one shared timeout budget across publish
    and verification instead of accidentally allowing the verification fetch
    to spend the full caller timeout a second time;
  - paired `nip66/test_rtt.py` coverage now pins the reduced remaining-time
    budget passed into `_verify_write()`.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eighth remediation slice:
  - `_connect_overlay_relay()` no longer relies on a broad `except
    Exception` boundary just to release a partial client; it now performs the
    best-effort shutdown in `finally`, so the overlay connect seam keeps the
    cleanup guarantee without a dishonest catch-all;
  - paired `protocol_connections` coverage now pins that even an unexpected
    post-connect failure, such as relay-handle lookup exploding after the
    handshake, still releases the partial client and preserves the original
    error.
- `2.1` models/utils/NIPs leaf audit, hundred-and-ninth remediation slice:
  - `NostrClientManager.connect_session()` no longer relies on a broad
    `except Exception` boundary just to tear down a partial shared-session
    client; the cleanup now lives in `finally`, so the manager preserves the
    same release guarantee without a catch-all seam;
  - paired `protocol` coverage now pins that even an unexpected failure after
    `connect_client_relays()` succeeds, such as session materialization
    exploding, still releases the partial client and preserves the original
    error.
- `2.1` models/utils/NIPs leaf audit, hundred-and-tenth remediation slice:
  - `create_connected_client()` no longer relies on a broad `except
    Exception` boundary just to release a partial shared-session client; the
    cleanup now lives in `finally`, so the low-level helper keeps the same
    release guarantee without a catch-all seam;
  - paired `protocol_sessions` coverage now pins that even an unexpected
    helper failure, such as `connect_client_relays()` exploding after client
    allocation, still releases the partial client and preserves the original
    error.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eleventh remediation slice:
  - `_ScopedStderrSuppressor()` no longer uses broad exception boundaries
    around pure file-descriptor setup; it now treats only FD-level failures
    as rollback cases and suppresses rollback noise without masking the
    original `dup2` failure;
  - paired `transport` coverage now pins that setup state is reset, the saved
    descriptor is still closed best-effort, and the primary `dup2` error is
    preserved even when `os.close()` complains during rollback.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twelfth remediation slice:
  - `_ScopedStderrSuppressor()` now still unwinds correctly when `sys.stderr`
    is a non-file-backed stream whose `fileno()` raises `UnsupportedOperation`
    or another fd-setup error outside plain `OSError`, so the stricter
    boundary from the previous slice does not leak `/dev/null` handles or
    stale suppressor state on alternate stderr implementations;
  - paired `transport` coverage now pins that a `fileno()` failure closes the
    temporary devnull handle, resets suppressor state, and preserves the
    original exception.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirteenth remediation slice:
  - `bigbrotr.nips.nip66.ssl.Nip66SslMetadata._ssl()` no longer treats
    certificate extraction and certificate validation as two separate
    full-timeout phases; both steps now share one end-to-end timeout budget,
    matching the final boundedness standard already enforced on other
    multi-phase relay probes;
  - paired `ssl` coverage now pins that the validation phase receives only the
    remaining timeout budget and that the probe aborts before validation when
    extraction has already exhausted the caller-provided deadline.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fourteenth remediation slice:
  - `bigbrotr.nips.nip66.ssl.Nip66SslMetadata._extract_certificate_data()`
    now treats malformed DER payloads as certificate-parse degradation rather
    than as a hard probe failure, so the SSL probe still preserves the
    negotiated TLS info and SHA-256 fingerprint already observed on the live
    socket;
  - paired `ssl` coverage now pins that malformed DER input drops only the
    X.509-derived fields while keeping the fingerprint and negotiated TLS
    metadata intact.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifteenth remediation slice:
  - `bigbrotr.nips.nip66.http.Nip66HttpMetadata._http()` now treats handshake
    response headers with the correct HTTP case-insensitive semantics instead
    of converting them to a plain dict and then performing case-sensitive
    lookups for `Server` and `X-Powered-By`;
  - paired `http` coverage now pins that both lowercase and mixed-case header
    spellings still hydrate the canonical `http_server` and
    `http_powered_by` fields.
- `2.1` models/utils/NIPs leaf audit, hundred-and-sixteenth remediation slice:
  - `bigbrotr.nips.nip66.dns.Nip66DnsMetadata._dns()` no longer leaves
    IPv6-only relays without reverse-DNS coverage; PTR lookup now uses the
    canonical primary resolved IP address, preferring IPv4 when present but
    falling back to IPv6 when it is the only family available;
  - paired `dns` coverage now pins that PTR lookup still follows the stable
    canonical IPv4 address when both families exist and correctly falls back
    to the canonical IPv6 address when no A record is available.
- `2.1` models/utils/NIPs leaf audit, hundred-and-seventeenth remediation slice:
  - `bigbrotr.nips.nip66.dns.Nip66DnsMetadata._dns()` now shares one timeout
    budget across A/AAAA/CNAME/NS/PTR collection instead of accidentally
    giving each record family the full public timeout again inside the sync
    resolver thread;
  - paired `dns` coverage now pins that per-record resolver `lifetime`
    values shrink with the remaining budget and that later record families
    are skipped once the shared DNS deadline is exhausted.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eighteenth remediation slice:
  - `bigbrotr.nips.nip66.dns.Nip66DnsMetadata._dns()` now treats shared-budget
    exhaustion as a real timeout outcome instead of degrading it into an empty
    DNS result that `probe()` would misreport as `no DNS records found`;
  - paired `dns` coverage now pins both sides of the contract: the sync probe
    raises `TimeoutError` once the shared deadline is exhausted, and the async
    `probe()` surface reports that timeout reason verbatim.
- `2.1` models/utils/NIPs leaf audit, hundred-and-nineteenth remediation slice:
  - `bigbrotr.nips.parsing.FieldSpec` now rejects duplicate field names across
    parser categories instead of letting `_build_dispatch()` resolve them
    silently by declaration order;
  - paired parsing coverage now pins that ambiguous specs fail fast at
    construction time, keeping shared NIP parsing contracts explicit and
    deterministic.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twentieth remediation slice:
  - `bigbrotr.nips.parsing.parse_fields_report()` now keeps the shared
    defensive parsing contract even for non-dict top-level input instead of
    crashing on `.items()` before it can emit a parse report;
  - paired parsing coverage now pins both entrypoints: `parse_fields()` degrades
    invalid top-level input to `{}`, while `parse_fields_report()` records the
    explicit `invalid_input` issue at the root payload boundary.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-first remediation
  slice:
  - `bigbrotr.utils.dns.resolve_host()` now has an opt-in `raise_on_timeout`
    boundary so callers that care about real shared-budget exhaustion can
    distinguish timeout from ordinary no-record resolution failure without
    breaking the default permissive helper contract;
  - `Nip66GeoMetadata.probe()` and `Nip66NetMetadata.probe()` now request that
    timeout-preserving mode explicitly, so their existing
    `timeout resolving hostname` result path matches runtime reality instead of
    relying on a dead branch;
  - paired coverage now pins both the shared helper contract and the fact that
    the geo/net probes opt into timeout-preserving resolution.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-second remediation
  slice:
  - `Nip11InfoData` and its nested fee/retention entry parsers now preserve
    explicit empty lists that the constructor path already accepts, instead of
    dropping them and emitting spurious `expected non-empty list[...]` issues;
  - this closes a real parse-path vs model-path mismatch on `supported_nips`,
    the set-like string lists, `retention`, fee category lists, and nested
    `kinds` lists inside fee/retention entries;
  - paired coverage now pins both outcomes: `parse()` keeps canonical empty
    lists, and `parse_report()` no longer reports them as invalid dropped data.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-third remediation
  slice:
  - `UserAssertion.from_db_row()` no longer treats an explicit empty
    `activity_hours=[]` array as if the row had omitted the field entirely;
  - the NIP-85 hydration path now preserves the project rule that malformed
    stored data must stay visible to the frozen model boundary, so an empty
    heatmap raises the same `24 hourly buckets` validation error as any other
    wrong-length payload instead of being silently rewritten to all-zeroes;
  - paired coverage now pins the distinction between the missing-field default
    path and the explicit-empty-list invalid-data path.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-fourth remediation
  slice:
  - `IdentifierAssertion` no longer accepts scalar strings on the public
    `k_tags` boundary, so `"isbn"` is no longer normalized accidentally into
    character tags `("b", "i", "n", "s")`;
  - `IdentifierAssertion.from_db_row()` now preserves the same fail-fast rule
    instead of masking malformed stored `k_tags` values through permissive
    iteration/defaulting logic;
  - paired coverage now pins both surfaces: direct construction and row
    hydration both reject scalar-string `k_tags` inputs explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-fifth remediation
  slice:
  - `UserAssertion.from_db_row()` no longer collapses malformed
    `topic_counts` payloads such as `[]` into the same empty-topic outcome as a
    genuinely missing field;
  - the NIP-85 hydration path now requires `topic_counts` to be a real mapping
    before it can derive stable top-topic output, which keeps bad stored data
    visible instead of silently treating it as “no topics”;
  - paired coverage now pins the distinction between `topic_counts=None` as the
    empty default path and non-mapping payloads as explicit invalid input.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-sixth remediation
  slice:
  - `EventAssertion` and `AddressableAssertion` now reject non-string
    `author_pubkey` values at the frozen dataclass boundary instead of letting
    `None` survive until `tags_hash()` crashes later;
  - the same fail-fast rule now holds on row hydration, so malformed stored
    `author_pubkey` values are surfaced immediately instead of becoming latent
    runtime failures in builder or hashing paths;
  - paired coverage now pins both surfaces for both assertion families:
    direct construction and `from_db_row()` reject non-string
    `author_pubkey` explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-seventh
  remediation slice:
  - `UserAssertion.from_db_row()` no longer treats malformed
    `top_topics_limit` values such as `None` or negative integers as an
    implicit “take all topics” slice;
  - the NIP-85 hydration path now requires `top_topics_limit` to be a real
    non-negative integer when the field is present, while still keeping the
    missing-field default of `5`;
  - paired coverage now pins both invalid paths explicitly, so bad stored
    limits surface at hydration time instead of silently altering output shape.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-eighth remediation
  slice:
  - `TrustedProviderDeclaration` now validates its typed boundary eagerly, so
    malformed provider declarations no longer survive with values like
    `tag_name=None`, `service_pubkey=None`, or `relay_hint=None` until the
    NIP-85 event builders emit invalid tag vectors;
  - `result_kind` is now required to be a real non-negative integer as well,
    instead of quietly accepting stringly-typed input;
  - paired coverage now pins these declaration-boundary failures directly on
    the dataclass constructor.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-ninth remediation
  slice:
  - the four NIP-85 assertion subject identifiers now fail fast at the frozen
    dataclass boundary: `UserAssertion.pubkey`, `EventAssertion.event_id`,
    `AddressableAssertion.event_address`, and `IdentifierAssertion.identifier`
    must all be strings instead of allowing `None` or other non-text values to
    leak toward the public event builders;
  - the same rule now holds on row hydration, so malformed stored assertion
    subjects surface immediately instead of becoming latent runtime failures in
    tag-building paths;
  - paired coverage now pins both surfaces for all four assertion families:
    direct construction and `from_db_row()` reject non-string subject
    identifiers explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirtieth remediation
  slice:
  - hardened the remaining direct-constructor collection boundaries in the
    NIP-85 data models: `UserAssertion.top_topics` now rejects scalar strings
    and mixed-type topic collections before `tags_hash()` or the public event
    builders can crash on non-string topics;
  - aligned `IdentifierAssertion.k_tags` with the same fail-fast standard, so
    mixed-type tag collections now raise a typed boundary error instead of
    leaking a sorter-dependent `TypeError` from the internal normalization
    step;
  - paired coverage now pins the scalar-string and mixed-type failures
    explicitly on the affected constructors.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-first remediation
  slice:
  - aligned `IdentifierAssertion.from_db_row()` with the hardened constructor
    boundary so hydrated `k_tags` values must also be real string sequences,
    instead of silently coercing mixed-type stored values like `[1, "book"]`
    into tag strings;
  - kept the intentional `None -> ()` compatibility path for missing stored
    `k_tags`, but removed the remaining malformed-input coercion from the
    hydration seam;
  - paired coverage now pins the mixed-type hydration failure explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-second remediation
  slice:
  - hardened `UserAssertion.from_db_row()` so `topic_counts` now enforces the
    contract it already claimed: topic keys must be strings and count values
    must be real non-negative integers, while still accepting integer-shaped
    JSONB strings such as `"10"`;
  - removed the remaining silent coercions where malformed values like
    `True` or `1.5` could slip through as topic counts and alter output
    ordering or selection semantics;
  - paired coverage now pins the non-string-key and malformed-count failures
    explicitly on the hydration seam.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-third remediation
  slice:
  - hardened `UserAssertion.activity_hours` on both constructor and hydration
    paths so the 24-slot heatmap now requires real non-negative integer
    buckets, instead of silently truncating malformed values like `True`,
    `1.5`, or `-1` through `int(...)` coercion;
  - kept the existing 24-bucket length contract intact, but removed the last
    implicit numeric coercion from this NIP-85 event-count seam;
  - paired coverage now pins boolean, float, and negative-hour failures
    explicitly for both direct construction and `from_db_row()`.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-fourth remediation
  slice:
  - hardened all four `bigbrotr.nips.nip85.data` subject models so their
    metric/count fields now require real non-negative integers on the direct
    constructor path instead of accepting malformed values like `True`, `1.5`,
    or `-1` through missing validation;
  - aligned every `from_db_row()` hydration seam with the same contract by
    removing the remaining permissive `int(...)` coercions for score/count/zap
    metrics and routing those DB-row values through typed non-negative integer
    checks;
  - paired coverage now pins representative boolean, float, and negative-value
    failures for `UserAssertion`, `EventAssertion`, `AddressableAssertion`,
    and `IdentifierAssertion` on both constructor and hydration paths.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-fifth remediation
  slice:
  - aligned the live NIP-85 score boundary with its own documented contract:
    all four assertion subject models now require `score` to stay within the
    normalized inclusive range `0-100` on the direct constructor path instead
    of accepting values like `101`;
  - hardened the paired `from_db_row()` hydration seams so stored score values
    also respect that same normalized range rather than bypassing the model
    contract through row-level numeric hydration;
  - paired coverage now pins the out-of-range `score=101` failure explicitly
    for `UserAssertion`, `EventAssertion`, `AddressableAssertion`, and
    `IdentifierAssertion` on both constructor and hydration paths.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-sixth remediation
  slice:
  - hardened the remaining temporal seam on `UserAssertion`: the optional
    `first_created_at` and `last_event_at` fields now require real
    non-negative integer timestamps instead of accepting malformed values like
    `True`, `1.5`, or `-1`;
  - aligned the constructor and `from_db_row()` paths on chronology as well,
    so a reversed activity window (`last_event_at < first_created_at`) is now
    rejected explicitly instead of being silently masked by `days_active`;
  - paired coverage now pins invalid timestamp types, negative values, and
    reversed activity windows on both direct construction and hydration.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-seventh
  remediation slice:
  - hardened the mandatory NIP-85 subject identifiers so `UserAssertion.pubkey`,
    `EventAssertion.event_id`, `AddressableAssertion.event_address`, and
    `IdentifierAssertion.identifier` now reject empty strings instead of
    letting obviously invalid subjects reach tag hashing and public event
    builders;
  - kept optional surfaces such as `author_pubkey` untouched in this slice,
    but aligned both direct construction and `from_db_row()` hydration for the
    required subject identifiers;
  - paired coverage now pins the empty-string failure explicitly for all four
    subject families on both constructor and hydration paths.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-eighth
  remediation slice:
  - hardened the `TrustedProviderDeclaration` boundary for public kind `10040`
    declarations so `tag_name`, `service_pubkey`, and `relay_hint` must now be
    real non-empty strings rather than permitting empty values that serialize
    to malformed public declaration tags;
  - kept the existing typed validation split intact (`TypeError` for
    non-strings, `ValueError` for empty strings), but aligned the live model
    with the event-builder contract that always emits a `<kind:tag>`,
    provider pubkey, and relay hint triple;
  - paired coverage now pins the empty-string failures explicitly on all three
    declaration fields.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-ninth remediation
  slice:
  - tightened `TrustedProviderDeclaration` from a merely non-empty tuple
    carrier into a semantic kind `10040` boundary: `result_kind` must now be
    one of the supported NIP-85 assertion kinds, `tag_name` no longer accepts
    embedded `:`, and `service_pubkey` must be a real 32-byte hex key;
  - aligned the relay surface with the rest of the repository by parsing
    `relay_hint` through the shared `Relay` model, so provider declarations
    now emit canonical relay URLs instead of preserving arbitrary caller
    strings;
  - paired coverage now pins the new malformed-kind, malformed-tag,
    malformed-pubkey, and malformed-relay-hint failures, plus the canonical
    normalization of a valid declaration.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fortieth remediation
  slice:
  - aligned the remaining NIP-85 hex subject seams with the contract already
    documented by the live models: `UserAssertion.pubkey`,
    `EventAssertion.event_id`, and the optional `author_pubkey` surfaces on
    event and addressable assertions now require real 32-byte hex identifiers
    instead of accepting arbitrary non-empty strings;
  - canonicalized accepted hex inputs to lowercase at the frozen model
    boundary, so equivalent uppercase/lowercase caller input no longer creates
    distinct public assertion identities or hash inputs;
  - paired coverage now pins malformed constructor and `from_db_row()`
    hydration payloads for all affected subject surfaces, plus the lowercase
    normalization path for required hex identifiers.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-first remediation
  slice:
  - tightened the `AddressableAssertion.event_address` seam so kind `30384`
    subjects are now real canonical `kind:pubkey:d` coordinates instead of
    arbitrary non-empty strings; the model now rejects malformed arity,
    non-canonical kinds, out-of-range kinds, malformed pubkeys, and empty
    `d` values;
  - canonicalized the embedded pubkey to lowercase at the frozen model
    boundary so equivalent uppercase input no longer creates distinct
    addressable subject identities;
  - paired coverage now pins malformed constructor and `from_db_row()`
    hydration payloads for all of those failure modes, plus the successful
    lowercase normalization path.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-second remediation
  slice:
  - tightened the same `AddressableAssertion.event_address` seam one step
    further so the leading kind must now be a real NIP-33 addressable kind
    (`30000-39999`), not merely any canonical event kind inside the global
    Nostr range;
  - aligned the direct-construction and `from_db_row()` hydration paths on
    that stronger contract, so non-addressable coordinates like
    `1:<pubkey>:<d>` are now rejected before they can reach public kind
    `30384` builder output;
  - paired coverage now pins the malformed non-addressable-kind case on both
    constructor and hydration boundaries.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-third remediation
  slice:
  - tightened `IdentifierAssertion.identifier` from a generic non-empty text
    field into the NIP-73 shape the rest of the repo already assumes, so kind
    `30385` subjects must now be canonical `scheme:value` strings with both
    scheme and value present;
  - aligned both direct construction and `from_db_row()` hydration on that
    stronger contract, so malformed subjects like bare `isbn`, empty schemes,
    or empty values are rejected before they can reach public `d` / `i` tags;
  - paired coverage now pins those malformed identifier cases on both
    constructor and hydration boundaries.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-fourth remediation
  slice:
  - tightened the remaining NIP-85 collection seams that still accepted
    malformed public tag values: `UserAssertion.top_topics` now rejects empty
    topics and duplicate topics, while `IdentifierAssertion.k_tags` now
    rejects empty tag strings instead of silently normalizing them through to
    public `t` / `k` tags;
  - kept the intentional set-like normalization for `k_tags`, but aligned the
    constructor and `from_db_row()` hydration boundaries so malformed empty
    entries fail fast before they can reach builders or `tags_hash()`;
  - paired coverage now pins the empty-topic, duplicate-topic, and empty-tag
    cases on the direct-construction and hydration paths that matter.
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
- `2.1` models/utils/NIPs leaf audit, thirty-third remediation slice:
  - corrected the remaining module-level note in
    `bigbrotr.nips.nip11.info`, which still lagged behind the already-fixed
    fetch-path wording and talked about overlay relays as if they simply
    "provided encryption";
  - kept this slice documentation-only because the runtime behavior and the
    previously-audited fetch contract were already correct.
- `2.1` models/utils/NIPs leaf audit, thirty-fourth remediation slice:
  - corrected the `bigbrotr.utils` package surface, which still described
    `utils.dns` as if it performed CNAME-aware DNS collection for NIP-66 DNS
    tests; the live leaf contract is narrower and cleaner: `utils.dns`
    provides only system-resolver A/AAAA hostname resolution, while the full
    DNS record collector lives in `bigbrotr.nips.nip66.dns`;
  - deferred the matching narrative drift in `docs/user-guide/architecture.md`
    to the later narrative-docs wave instead of broadening this leaf slice.
- `2.1` models/utils/NIPs leaf audit, thirty-fifth remediation slice:
  - tightened the leaf contract of `bigbrotr.utils.protocol_lifecycle` so the
    module now states clearly that teardown is best-effort and includes wiping
    any client-local `nostr_sdk` database state exposed by the SDK;
  - added direct unit coverage for `_await_if_needed()` and `shutdown_client()`,
    including async and sync SDK-style APIs plus failure-tolerant cleanup
    sequencing, because this leaf previously had no dedicated test surface.
- `2.1` models/utils/NIPs leaf audit, thirty-sixth remediation slice:
  - corrected the public contract of `broadcast_events()` so it no longer
    implies an over-strong client-wide success notion; the helper counts
    clients that retain at least one relay successful across all builders,
    which is exactly how the implementation already behaved;
  - added explicit unit coverage for that intersection-based counting rule so
    the leaf semantics stay pinned in future refactors.
- `2.1` models/utils/NIPs leaf audit, thirty-seventh remediation slice:
  - corrected `bigbrotr.utils.protocol_factory` so proxy hostname resolution
    no longer stops at IPv4-only `socket.gethostbyname()`; the factory now
    falls back to IPv6 `getaddrinfo()` and therefore matches the repository's
    broader A/AAAA resolution discipline;
  - added explicit unit coverage proving that IPv6-only proxy hostnames still
    produce a working numeric proxy target instead of failing spuriously.
- `2.1` models/utils/NIPs leaf audit, thirty-eighth remediation slice:
  - corrected the `protocol_sessions` / `protocol_manager` contract language so
    `ClientSession` is no longer described as if every named session were
    fully connected; the live repository already uses session objects whose
    `connect_result.connected` set may be empty while failures are preserved
    for callers;
  - added direct unit coverage pinning that `connect_session()` still returns
    and caches a session when the normalized connect outcome contains only
    failures, because higher layers are responsible for deciding whether that
    session is usable.
- `2.1` models/utils/NIPs leaf audit, thirty-ninth remediation slice:
  - corrected the `protocol_validation` leaf contract so it now says plainly
    that `auth-required` during connect still counts as successful relay
    validation, instead of implying that only a fully completed fetch path can
    prove protocol support;
  - added a dedicated leaf test surface for `validate_relay_protocol()`,
    covering the success path, `auth-required` success, timeout failure, and
    best-effort shutdown semantics that were previously only exercised through
    the higher-level facade tests.
- `2.1` models/utils/NIPs leaf audit, fortieth remediation slice:
  - hardened the public documentation of `bigbrotr.utils.protocol` and the
    underlying publish helpers so the exported helper set is described
    completely and the normalization contracts are explicit: multi-builder
    success is an intersection per client, aggregate success is a union across
    clients, and failure maps preserve per-relay error state;
  - kept this slice documentation-only because the runtime semantics were
    already pinned by the existing publish/session test coverage.
- `2.1` models/utils/NIPs leaf audit, forty-first remediation slice:
  - corrected the `bigbrotr.utils` package boundary narrative so it no longer
    claims overlay relay flows always force the custom insecure transport;
    that was conflating the protocol facade's proxy-based WebSocket path with
    separate HTTP fetchers that make their own TLS-context decisions;
  - kept this slice documentation-only because the runtime distinction was
    already covered by existing overlay/proxy test surfaces.
- `2.1` models/utils/NIPs leaf audit, forty-second remediation slice:
  - corrected the tracked `bigbrotr.utils.keys` contract so it names the real
    public error family from `nostr_sdk` (`NostrSdkError`) instead of the stale
    `NostrError` wording;
  - tightened the paired unit coverage to assert the concrete SDK error family
    and message for malformed key material, removing the remaining
    `pytest.raises(BaseException)` escape hatch from this leaf test surface.
- `2.1` models/utils/NIPs leaf audit, forty-third remediation slice:
  - corrected the remaining tracked `NetworkType` narrative in
    `bigbrotr.models.constants`, which still reduced overlay relay handling to
    “encryption handled by the overlay” instead of the more precise repository
    contract already used elsewhere;
  - aligned that leaf wording so clearnet/overlay scheme policy now talks
    consistently about privacy/security coming from the overlay transport
    layer rather than relay TLS.
- `2.1` models/utils/NIPs leaf audit, forty-fourth remediation slice:
  - corrected the top-level `bigbrotr.nips` package surface, which still
    claimed overlay NIP fetches always use an insecure SSL context;
  - aligned that export-level narrative with the actual repository contract:
    overlay flows are proxy-aware, while any relaxed TLS decision belongs to
    the specific helper surface (`nip11.info`, `nip66.http`, etc.), not to the
    package summary itself.
- `2.1` models/utils/NIPs leaf audit, forty-fifth remediation slice:
  - tightened `bigbrotr.nips.nip66.Nip66.probe()` so the post-`gather()`
    isolation boundary now swallows only ordinary `Exception` results after
    re-raising cancellation and shutdown signals, instead of the broader
    `BaseException`;
  - added paired unit coverage proving that `KeyboardInterrupt` and
    `SystemExit` still propagate through the fan-in path just like the already
    covered `CancelledError`.
- `2.1` models/utils/NIPs leaf audit, forty-sixth remediation slice:
  - tightened `bigbrotr.utils.transport.InsecureWebSocketAdapter.close_connection()`
    so the best-effort close path now suppresses only realistic close-time
    failures (`aiohttp`/runtime/OS/timeout), instead of the broader
    `Exception`;
  - aligned the paired unit coverage to those realistic runtime failures while
    preserving the intended guarantee that a failed WebSocket close does not
    block session cleanup.
- `2.1` models/utils/NIPs leaf audit, forty-seventh remediation slice:
  - corrected `bigbrotr.nips.nip11.info.Nip11InfoMetadata.fetch()` so overlay
    relays now follow the honest `http://` + `ssl=False` path that matches the
    canonical `Relay` contract, instead of being lumped into a dead overlay
    TLS branch;
  - aligned the module/fetch contract wording and paired unit coverage so the
    leaf surface now says plainly that overlay relays are canonical `ws://`
    entries and therefore do not use an SSL context for NIP-11 fetches.
- `2.1` models/utils/NIPs leaf audit, forty-eighth remediation slice:
  - tightened `bigbrotr.utils.protocol_lifecycle` so the optional client-local
    database wipe is resolved structurally through a dedicated helper instead
    of relying on a `type: ignore[attr-defined]` call site;
  - added paired unit coverage that locks in the final contract: if the SDK
    exposes a callable `wipe()` it is used, and if no wipe handle is exposed
    the shutdown helper still completes the rest of the best-effort teardown.
- `2.1` models/utils/NIPs leaf audit, forty-ninth remediation slice:
  - corrected `bigbrotr.nips.nip66.http.Nip66HttpMetadata._http()` so overlay
    relays follow the canonical `ws://` + `ssl=False` path instead of being
    lumped into a dead `CERT_NONE` branch;
  - aligned the module note and paired unit coverage so `CERT_NONE` is now
    pinned only to clearnet `wss://` flows with `allow_insecure=True`, while
    overlay proxy handshakes stay on plain WebSocket transport with no SSL
    context.
- `2.1` models/utils/NIPs leaf audit, fiftieth remediation slice:
  - replaced the broad `except Exception` around registered-domain extraction
    in `bigbrotr.nips.nip66.dns` with an explicit `_registered_domain()` seam
    that degrades only for plausible `tldextract` parser/configuration
    failures (`LookupError`, `UnicodeError`, `ValueError`);
  - aligned the paired unit coverage so NS resolution is still skipped on
    realistic parser failure, empty-suffix hosts still return no registered
    domain, and unexpected extractor failures are now proven to propagate
    instead of being silently hidden.
- `2.1` models/utils/NIPs leaf audit, fifty-first remediation slice:
  - corrected `bigbrotr.utils.protocol_factory.build_client()` so proxied
    clients now target `ConnectionTarget.ALL` instead of the onion-only mode;
    the shared proxy path is used for Tor, I2P, and Lokinet overlays, so the
    previous target leaked an onion-centric assumption into the final repo;
  - added direct unit coverage for the factory seam so future refactors cannot
    silently collapse the shared overlay proxy contract back to onion-only
    targeting.
- `2.1` models/utils/NIPs leaf audit, fifty-second remediation slice:
  - hardened the shared-session boundary in
    `bigbrotr.utils.protocol_sessions`: multi-relay client sessions now reject
    overlay relay sets explicitly and early at the relay-registration seam,
    instead of relying on downstream proxy failures or silently pretending a
    shared client can encode per-network proxy policy;
  - aligned the public `bigbrotr.utils.protocol` wording and paired unit
    coverage so both `create_connected_client()` and
    `NostrClientManager.connect_session()` now pin the same final contract:
    shared multi-relay sessions are clearnet-only, must never cache invalid
    overlay sessions, and must fail before any relay registration or connect
    attempt is made.
- `2.1` models/utils/NIPs leaf audit, fifty-third remediation slice:
  - removed the broad `contextlib.suppress(Exception)` teardown boundary from
    `bigbrotr.utils.protocol_lifecycle.shutdown_client()`: the helper now
    tolerates only plausible transport/SDK cleanup failures
    (`OSError`, `RuntimeError`, `TimeoutError`, `NostrSdkError`) instead of
    swallowing arbitrary bugs;
  - preserved the best-effort cleanup contract by continuing through the
    remaining teardown steps, but now re-raising the first unexpected
    exception after the cleanup attempt so logic errors are surfaced instead
    of being silently buried.
- `2.1` models/utils/NIPs leaf audit, fifty-fourth remediation slice:
  - cleaned the residual `catalog` wording from the shared model surface
    (`Document`, `RelayDocument`, `ServiceState`), which was still carrying
    pre-final mental models into the docstrings of the live boundary;
  - the model contract now talks plainly about built-in enum values and
    vocabularies, which matches the final repository language without
    pretending those tokens form a separate schema browser or catalog layer.
- `2.1` models/utils/NIPs leaf audit, fifty-fifth remediation slice:
  - realigned the shared NIP parsing boundary so `bigbrotr.nips.base` and
    `bigbrotr.nips.parsing` now describe the actual final contract:
    report-oriented parsing via `ParseReport`/`ParseIssue`, with `parse()`
    kept as the convenience wrapper that returns only the parsed payload;
  - added paired base-layer coverage proving `BaseData.parse_report()`
    preserves the parsed subset while recording invalid and unknown fields,
    so future refactors cannot regress back to the older “silent drop only”
    mental model.
- `2.1` models/utils/NIPs leaf audit, fifty-sixth remediation slice:
  - aligned the `bigbrotr.nips.nip11` package surface and top-level data-model
    prose with the real final parsing contract, so the package no longer
    claims to be “silent drop only” now that `parse_report()` is part of the
    live boundary;
  - added direct unit coverage proving `Nip11InfoData.parse_report()` keeps
    the parsed subset while recording unknown top-level fields and nested
    invalid values, closing a real gap between the runtime behavior and the
    package-level test surface.
- `2.1` models/utils/NIPs leaf audit, fifty-seventh remediation slice:
  - aligned the `bigbrotr.nips.nip66` package and data-module prose with the
    report-oriented parsing contract, removing one more package-level claim
    that NIP-66 parsing was merely “silent drop only”;
  - added direct unit coverage proving `Nip66RttData.parse_report()` keeps the
    parsed subset while recording invalid and unknown fields, so the shared
    NIP-66 data layer now has an explicit package-local test for the same
    report contract enforced elsewhere in the runtime.
- `2.1` models/utils/NIPs leaf audit, fifty-eighth remediation slice:
  - tightened the `bigbrotr.utils.streaming` boundary wording so
    `_to_domain_events()` no longer claims a contradictory “silently dropped
    with a debug log” contract; the helper now states plainly that invalid or
    oversized events are dropped and debug-logged;
  - added direct unit coverage for the oversize-event debug path, so the
    operator-facing signal around dropped oversized events is now pinned by a
    package-local test instead of being left implicit.
- `2.1` models/utils/NIPs leaf audit, fifty-ninth remediation slice:
  - aligned the shared publish contract in `bigbrotr.utils.protocol_publish`
    and the public `bigbrotr.utils.protocol` facade so they now state
    explicitly that a `BroadcastClientResult` is emitted only when every
    builder send for that client completes with relay-level SDK output;
  - added direct unit coverage proving that if a later builder send fails at
    the transport boundary, the helper logs the failure and drops the partial
    client state instead of pretending the earlier relay-level result was a
    complete normalized outcome.
- `2.1` models/utils/NIPs leaf audit, sixtieth remediation slice:
  - aligned `bigbrotr.utils.protocol_manager.NostrClientManager.disconnect()`
    with the rest of the shared protocol teardown contract by suppressing
    `NostrSdkError` alongside the already expected transport/runtime shutdown
    failures;
  - added paired unit coverage proving that cached sessions and relay clients
    are still cleared even when the injected shutdown helper raises expected
    SDK teardown errors, while keeping truly unexpected exceptions outside the
    suppression set.
- `2.1` models/utils/NIPs leaf audit, sixty-first remediation slice:
  - hardened the overlay connection path in
    `bigbrotr.utils.protocol_connections` so a client created for Tor/I2P/
    Lokinet relays is now released best-effort if `add_relay()`, `connect()`,
    `wait_for_connection()`, or relay-handle validation fails before the
    connection is confirmed;
  - added paired unit coverage proving that mid-handshake overlay failures now
    call the injected shutdown helper and still re-raise the original
    connection error instead of leaking a partially initialized client.
- `2.1` models/utils/NIPs leaf audit, sixty-second remediation slice:
  - aligned `bigbrotr.utils.protocol_validation.validate_relay_protocol()`
    with the rest of the shared teardown contract by treating `NostrSdkError`
    as an expected shutdown failure during relay validation cleanup;
  - added paired unit coverage proving that a successful validation result is
    preserved even when the injected shutdown helper reports an SDK-level
    teardown failure after the fetch path completes.
- `2.1` models/utils/NIPs leaf audit, sixty-third remediation slice:
  - moved shared-session relay validation ahead of client creation in
    `bigbrotr.utils.protocol_sessions.create_connected_client()` so
    unsupported overlay relay sets fail before allocating a client they cannot
    safely use;
  - added paired unit coverage on both the leaf helper and the public
    `bigbrotr.utils.protocol.create_connected_client()` facade to lock that
    contract in place.
- `2.1` models/utils/NIPs leaf audit, sixty-fourth remediation slice:
  - moved overlay-session validation ahead of client creation in
    `bigbrotr.utils.protocol_manager.NostrClientManager.connect_session()` so
    named shared sessions follow the same fail-fast contract as the leaf
    shared-session helper;
  - tightened paired manager coverage so rejected overlay session requests no
    longer instantiate an unusable shared client.
- `2.1` models/utils/NIPs leaf audit, sixty-fifth remediation slice:
  - hardened the shared-session failure path in
    `bigbrotr.utils.protocol_manager.NostrClientManager.connect_session()` so
    a client allocated for a named session is released best-effort when the
    shared connect step raises before any session is cached;
  - added paired coverage proving the original connect failure still wins when
    shutdown reports only expected SDK teardown noise.
- `2.1` models/utils/NIPs leaf audit, sixty-sixth remediation slice:
  - hardened `bigbrotr.utils.protocol_sessions.create_connected_client()` so
    the leaf shared-session helper releases an allocated client when
    `connect_client_relays()` fails before returning a normalized result;
  - added paired coverage on both the leaf helper and the public
    `bigbrotr.utils.protocol.create_connected_client()` facade to lock the
    cleanup contract in place.
- `2.1` models/utils/NIPs leaf audit, sixty-seventh remediation slice:
  - aligned the clearnet branch of
    `bigbrotr.utils.protocol_connections.connect_relay()` with the rest of
    the shared teardown contract so expected shutdown noise no longer
    overrides the primary verified-connect or insecure-fallback failure;
  - added paired unit coverage proving both clearnet failure paths still
    surface their original connection error when the injected shutdown helper
    reports only expected SDK teardown noise.
- `2.1` models/utils/NIPs leaf audit, sixty-eighth remediation slice:
  - aligned `bigbrotr.utils.protocol_sessions.create_connected_client()` with
    the rest of the shared session and relay-connect cleanup boundaries so
    expected teardown noise no longer overrides the primary multi-relay
    connect failure;
  - tightened paired unit coverage on both the leaf helper and the public
    `bigbrotr.utils.protocol.create_connected_client()` facade so the shared
    session helper now preserves the original connect error when cleanup
    reports only expected SDK shutdown noise.
- `2.1` models/utils/NIPs leaf audit, sixty-ninth remediation slice:
  - aligned `bigbrotr.utils.protocol_manager.NostrClientManager.get_relay_client()`
    with the ordinary transport-failure contract of the rest of the relay
    connection layer so SDK connect failures are cached as failed relays
    instead of leaking through the manager boundary;
  - added paired unit coverage on the public manager facade proving
    `NostrSdkError` now degrades to `None` plus failed-relay caching rather
    than aborting relay-scoped client acquisition.
- `2.1` models/utils/NIPs leaf audit, seventieth remediation slice:
  - aligned `bigbrotr.utils.protocol_validation.validate_relay_protocol()`
    with the rest of the relay-validation boundary so ordinary SDK connect and
    fetch failures degrade to an invalid-relay outcome instead of leaking
    through the helper and the public `is_nostr_relay()` facade;
  - added paired unit coverage on both `protocol_validation` and
    `bigbrotr.utils.protocol.is_nostr_relay()` proving `NostrSdkError` now
    maps to `False` while still preserving the existing auth-required success
    contract and best-effort shutdown behavior.
- `2.1` models/utils/NIPs leaf audit, seventy-first remediation slice:
  - aligned `bigbrotr.utils.protocol_publish.broadcast_events_detailed()`
    with the rest of the shared protocol boundaries so ordinary SDK send
    failures are treated like other dropped-client publish outcomes instead of
    leaking through the broadcast helper;
  - added paired unit coverage proving both `broadcast_events()` and
    `broadcast_events_detailed()` now skip the failed client, drop any partial
    relay-level state for that client, and log the SDK send failure as the
    expected publish-boundary warning.
- `2.1` models/utils/NIPs leaf audit, seventy-second remediation slice:
  - tightened `bigbrotr.utils.protocol_publish.normalize_send_output()` so the
    public relay-success tuple is now genuinely normalized: deduplicated and
    sorted instead of inheriting arbitrary SDK iteration order;
  - added paired unit coverage proving the helper now returns a stable
    success tuple even when the SDK output arrives out of order or with
    duplicate relay entries.
- `2.1` models/utils/NIPs leaf audit, seventy-third remediation slice:
  - tightened `bigbrotr.nips.parsing.parse_fields_report()` so typed list
    fields now distinguish between wrong-type input, empty lists, and
    lists that were fully filtered after permissive validation;
  - added paired unit coverage proving the report layer now records
    `filtered_items` when every list element is invalid and uses an explicit
    non-empty expectation for empty typed lists.
- `2.1` models/utils/NIPs leaf audit, seventy-fourth remediation slice:
  - tightened `bigbrotr.utils.protocol_sessions.connect_client_relays()` so
    the `ClientConnectResult.connected` tuple is genuinely normalized:
    deduplicated and sorted instead of inheriting raw SDK iteration order;
  - added paired unit coverage on both the leaf shared-session helper and the
    public `bigbrotr.utils.protocol.create_connected_client()` facade to lock
    the stable connected-relay ordering contract in place.
- `2.1` models/utils/NIPs leaf audit, seventy-fifth remediation slice:
  - tightened `bigbrotr.utils.protocol_manager.NostrClientManager.connect_session()`
    so named shared-session identity is keyed by the normalized relay set
    rather than the caller's input order;
  - added paired unit coverage proving the manager now reuses an existing
    named session when the same relay set is requested in a different order
    while still rejecting genuinely different relay sets.
- `2.1` models/utils/NIPs leaf audit, seventy-sixth remediation slice:
  - tightened `bigbrotr.nips.nip66.data.Nip66DnsData` so the set-like DNS
    fields (`dns_ips`, `dns_ips_v6`, `dns_ns`) are deduplicated and sorted at
    the model boundary instead of inheriting resolver iteration order;
  - added paired unit coverage proving both direct model construction and the
    public DNS probe path now emit stable DNS lists for identical answers
    even when the underlying resolver returns them out of order or with
    duplicates.
- `2.1` models/utils/NIPs leaf audit, seventy-seventh remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoData` so `supported_nips`
    is normalized to a deduplicated ascending order at the model boundary
    instead of relying only on the permissive parse path to do that cleanup;
  - added paired unit coverage proving both direct model construction and the
    public NIP-11 fetch path now emit stable `supported_nips` values even
    when the source document lists them out of order or with duplicates.
- `2.1` models/utils/NIPs leaf audit, seventy-eighth remediation slice:
  - tightened `bigbrotr.nips.nip66.data.Nip66SslData` so `ssl_san` is
    normalized to a deduplicated, sorted order at the model boundary instead
    of inheriting certificate extraction order directly;
  - added paired unit coverage proving both direct model construction and the
    public SSL probe path now emit stable SAN lists even when the extracted
    certificate names arrive out of order or with duplicates.
- `2.1` models/utils/NIPs leaf audit, seventy-ninth remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoDataFeeEntry` so fee-entry
    `kinds` are normalized to a deduplicated ascending order in both the
    parse helper and the model boundary instead of inheriting document order
    directly;
  - added paired unit coverage proving both direct fee-entry parsing and the
    public NIP-11 fetch path now emit stable fee-kind scopes even when the
    source document lists them out of order or with duplicates.
- `2.1` models/utils/NIPs leaf audit, eightieth remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoData` so the set-like
    string-list fields `relay_countries`, `language_tags`, `tags`, and
    `attributes` are normalized to deduplicated ascending order in both the
    parse helper and the model boundary instead of inheriting document order
    directly;
  - added paired unit coverage proving both direct NIP-11 parsing and the
    public fetch path now emit stable string-list surfaces even when the
    source document lists them out of order or with duplicates.
- `2.1` models/utils/NIPs leaf audit, eighty-first remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoDataRetentionEntry` so
    mixed `kinds` scopes are normalized to a deduplicated stable order in
    both the custom parse helper and the model boundary instead of
    inheriting document order directly;
  - added paired unit coverage proving both direct retention-entry parsing
    and the public NIP-11 fetch path now emit stable retention scopes even
    when the source document lists ints and ranges out of order or with
    duplicates.
- `2.1` models/utils/NIPs leaf audit, eighty-second remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoData` so the nested
    `retention` entry list is normalized to a stable order in both the
    top-level parse helper and the model boundary instead of inheriting
    document order directly;
  - added paired unit coverage proving both direct NIP-11 parsing and the
    public fetch path now emit stable retention-entry ordering even when the
    source document lists equivalent policy entries out of order.
- `2.1` models/utils/NIPs leaf audit, eighty-third remediation slice:
  - tightened `bigbrotr.nips.nip11.data.Nip11InfoDataFees` so each nested
    fee-entry list is normalized to a stable order in both the category parse
    helper and the model boundary instead of inheriting document order
    directly;
  - added paired unit coverage proving both direct fee parsing and the public
    NIP-11 fetch path now emit stable fee-entry ordering even when the source
    document lists equivalent fee policies out of order.
- `2.1` models/utils/NIPs leaf audit, eighty-fourth remediation slice:
  - tightened `bigbrotr.nips.nip85.data.UserAssertion.from_db_row()` so
    `top_topics` are ordered by descending numeric count with lexical
    tie-breaking instead of inheriting equal-count topic order from the raw
    JSONB mapping;
  - added paired unit coverage proving equal-count topic sets now produce a
    stable canonical ordering instead of drifting with dictionary key order.
- `2.1` models/utils/NIPs leaf audit, eighty-fifth remediation slice:
  - tightened `bigbrotr.nips.nip85.data.IdentifierAssertion` so ``k_tags``
    are normalized as a deduplicated lexical set at the model boundary
    instead of trusting raw DB or fixture order directly;
  - added paired unit and builder coverage proving identifier assertion tags
    no longer drift or duplicate when the input row provides repeated or
    unsorted ``k`` tags.
- `2.1` models/utils/NIPs leaf audit, eighty-sixth remediation slice:
  - tightened `bigbrotr.nips.nip85.data.UserAssertion` so ``activity_hours``
    is validated and normalized at the model boundary instead of allowing an
    invalid bucket count to fail later inside heatmap window helpers;
  - added paired unit coverage proving direct construction accepts 24-slot
    list input but rejects malformed heatmaps from both constructor and DB-row
    paths.
- `2.1` models/utils/NIPs leaf audit, eighty-seventh remediation slice:
  - tightened `bigbrotr.services.ranker.queries.IdentifierStatFact` so
    internal identifier fact rows normalize ``k_tags`` as a deduplicated
    lexical set instead of trusting raw PostgreSQL array order;
  - added paired service-layer coverage proving both direct fact
    construction and ``fetch_identifier_stats()`` now emit canonical
    ``k_tags`` when the source row is repeated or unsorted.
- `2.1` models/utils/NIPs leaf audit, eighty-eighth remediation slice:
  - tightened `bigbrotr.nips.nip85.data.IdentifierAssertion.from_db_row()`
    so DB-row hydration stops duplicating ``k_tags`` canonicalization that
    already belongs to the frozen model boundary itself;
  - kept the existing paired NIP-85 coverage green to prove the public
    constructor and DB-row path still emit the same canonical ``k_tags``
    without needing a second normalization site.
- `2.1` models/utils/NIPs leaf audit, eighty-ninth remediation slice:
  - tightened `bigbrotr.nips.registry` lookup helpers so they return
    canonical ascending NIP tuples instead of inheriting whatever insertion
    order the static registry dict happens to use;
  - added paired registry coverage that scrambles `NIP_REGISTRY` and proves
    service/capability lookups still emit the same stable order.
- `2.1` models/utils/NIPs leaf audit, ninetieth remediation slice:
  - tightened `bigbrotr.utils.protocol_publish` so `failed_relays` maps are
    normalized to stable lexical relay-url order everywhere the publish layer
    emits or aggregates relay-level outcomes;
  - added paired publish coverage proving detailed results, aggregate
    summaries, and raw send-output normalization no longer inherit failure-map
    insertion order from the SDK or intermediate updates.
- `2.1` models/utils/NIPs leaf audit, ninety-first remediation slice:
  - tightened `bigbrotr.utils.protocol_sessions` so `ClientConnectResult`
    now canonicalizes failed relay maps as well as successful relay tuples,
    instead of returning half-normalized connect outcomes;
  - added paired leaf and facade coverage proving shared-session connect
    helpers no longer inherit failure-map insertion order from nostr-sdk
    outputs.
- `2.1` models/utils/NIPs leaf audit, ninety-second remediation slice:
  - tightened `bigbrotr.nips.base.BaseData.parse()` so successful permissive
    parse results are canonicalized through the frozen model boundary instead
    of leaving field-validator normalization to a later constructor step;
  - kept `parse()` non-raising by falling back to the raw parsed payload when
    model validation rejects post-parse semantics, and added paired base/NIP-66
    coverage proving the contract now emits canonical list payloads without
    breaking permissive parse behavior.
- `2.1` models/utils/NIPs leaf audit, ninety-third remediation slice:
  - aligned the live NIP package/module docstrings (`bigbrotr.nips.base`,
    `bigbrotr.nips.nip11`, `bigbrotr.nips.nip11.data`,
    `bigbrotr.nips.nip66`, `bigbrotr.nips.nip66.data`) with the new
    `BaseData.parse()` contract;
  - documented explicitly that `parse()` now returns constructor-ready
    canonical payloads when model validation can normalize them safely,
    while `parse_report()` remains the issue-preserving permissive path.
- `2.1` models/utils/NIPs leaf audit, ninety-fourth remediation slice:
  - tightened `bigbrotr.nips.event_builders` so set-like public declaration
    builders no longer inherit caller ordering for equivalent inputs:
    relay-list tags, trusted-provider declarations, and monitor network tags
    are now emitted in stable deduplicated order;
  - added paired event-builder coverage proving these public tag sets no
    longer drift when the caller passes duplicates or reordered inputs.
- `2.1` models/utils/NIPs leaf audit, ninety-fifth remediation slice:
  - removed the remaining custom `parse()` overrides in
    `bigbrotr.nips.nip11.data` that were bypassing the shared
    constructor-ready canonical parsing contract;
  - tightened the `Nip11InfoData.parse()` boundary so canonical payloads now
    expose internal field names such as `self_pubkey`, while `to_dict()`
    remains the explicit JSON-facing alias surface for external NIP-11 output.
- `2.1` models/utils/NIPs leaf audit, ninety-sixth remediation slice:
  - tightened `BaseData` canonical dumping so `parse()` no longer materializes
    omitted model defaults while still preserving explicit default-valued
    inputs that survived permissive parsing;
  - made `Nip11InfoData.parse()` idempotent on its own canonical
    `self_pubkey` payload by teaching the custom parser to accept the internal
    field name as well as the external NIP-11 alias `self`.
- `2.1` models/utils/NIPs leaf audit, ninety-seventh remediation slice:
  - tightened `bigbrotr.utils.protocol_manager.NostrClientManager` so
    `get_relay_clients()` treats repeated relay URLs as a set-like input and
    no longer returns the same connected client multiple times;
  - added paired manager coverage proving duplicate relay URLs no longer
    trigger duplicate connect attempts or duplicate publish-path clients.
- `2.1` models/utils/NIPs leaf audit, ninety-eighth remediation slice:
  - tightened the shared-session helpers so duplicate relay URLs are removed
    before `add_relay()` registration, while preserving first-seen caller
    order for the distinct relay set;
  - aligned `NostrClientManager.connect_session()` with the same contract and
    added paired helper/manager coverage proving duplicate session inputs no
    longer trigger duplicate relay registration work.
- `2.1` models/utils/NIPs leaf audit, ninety-ninth remediation slice:
  - tightened `bigbrotr.utils.transport._ScopedStderrSuppressor` so the
    narrow suppression window now redirects the real process stderr file
    descriptor at the outermost boundary instead of only swapping the Python
    `sys.stderr` object;
  - aligned the paired transport tests so enter/exit and nested suppression
    now prove fd-level redirect/restore happens exactly once per outermost
    scope, which matches the live contract claimed by the transport layer.
- `2.1` models/utils/NIPs leaf audit, hundredth remediation slice:
  - tightened `bigbrotr.nips.nip66.dns.Nip66DnsMetadata._dns()` so the
    set-like A/AAAA/NS answers are canonicalized before later probe logic
    consumes them, instead of relying on the model boundary alone;
  - aligned PTR lookup with that contract so reverse DNS now follows the
    canonical primary IPv4 address rather than whichever A record the resolver
    happened to yield first, and added paired DNS coverage that locks this
    behavior down.
- `2.1` models/utils/NIPs leaf audit, hundred-and-first remediation slice:
  - fixed `bigbrotr.nips.nip66.geo.GeoExtractor.extract_country()` so
    `geo_is_eu` falls back to `registered_country` together with country code
    and name, instead of silently dropping EU-membership information on the
    registered-country fallback path;
  - aligned the paired geo extractor coverage so the fallback contract is
    locked down explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-second remediation slice:
  - fixed `bigbrotr.nips.nip66.geo.Nip66GeoMetadata.probe()` so GeoIP lookup
    now really prefers IPv4 but falls back to IPv6 when the preferred lookup
    fails or returns no data, instead of stopping at the first candidate;
  - kept that retry path bounded by the original timeout budget and aligned the
    paired geo coverage so both failure-fallback and empty-data fallback are
    locked down explicitly.
- `2.1` models/utils/NIPs leaf audit, hundred-and-third remediation slice:
  - aligned the Assertor Kind 10040 checkpoint hash with the actual public
    provider-package contract by canonicalizing trusted-provider declarations
    before both change detection and event building, instead of hashing the raw
    helper output while the builder silently normalized it later;
  - added paired Assertor coverage proving duplicate or reordered declaration
    helper output no longer triggers a spurious trusted-provider-list publish
    when the emitted public event would be unchanged.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fourth remediation slice:
  - narrowed the live `NIP-85` user-assertion payload boundary so
    `UserAssertion` and the Assertor user query no longer carry dead fact-table
    fields (`reaction_count_sent`, `repost_count_recd`, `repost_count_sent`,
    `following_count`) that never reach public tags or change detection;
  - aligned paired data-model and Assertor fixtures with the stricter boundary
    so the `30382` publication surface now reflects only the metrics the
    provider package actually emits.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifth remediation slice:
  - fixed `UserAssertion.tags_hash()` so the `first_created_at` component now
    distinguishes `None` from the Unix epoch `0`, instead of collapsing both
    states into the same checkpoint hash even though the public `30382` builder
    emits the timestamp tag only when the value is actually present;
  - added paired `NIP-85` model and Assertor coverage proving a persisted
    no-timestamp checkpoint no longer suppresses publication when the live row
    changes to `first_created_at=0`.
- `2.1` models/utils/NIPs leaf audit, hundred-and-sixth remediation slice:
  - fixed `UserAssertion.tags_hash()` and `IdentifierAssertion.tags_hash()` so
    ordered `top_topics` and set-like `k_tags` are hashed as structured
    payloads instead of delimiter-joined strings, eliminating aliasing when
    tag values themselves contain commas or other separators;
  - added paired `NIP-85` model and Assertor coverage proving delimiter-rich
    topic or `k`-tag changes no longer get skipped by checkpoint reuse when
    the emitted public tags would actually differ.
- `2.1` models/utils/NIPs leaf audit, hundred-and-seventh remediation slice:
  - hardened `bigbrotr.services.common.read_model_requests` so the shared
    public query parser now rejects non-string cursor values with a normalized
    `ReadModelQueryError` and handles boolean `include_total` values
    intentionally instead of risking an internal `AttributeError` on the DVM
    pre-parsed job path;
  - added paired `services/common` and `dvm/jobs` coverage proving malformed
    pre-parsed job params now become client-safe rejections while explicit
    boolean `include_total=True` survives into the executed read query.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eighth remediation slice:
  - hardened the shared public numeric parsing path so boolean `limit` and
    `offset` values on pre-parsed read requests no longer slip through Python's
    `bool`-is-`int` coercion as silent `1`/`0` aliases, and are now rejected
    as normalized client input errors instead;
  - aligned the DVM pricing gate with that stricter contract so boolean `bid`
    inputs are treated like invalid/missing bids rather than accidental
    one-millisat offers, and added paired `services/common`, `dvm/utils`, and
    `dvm/jobs` coverage proving malformed boolean numerics now fail safely.
- `2.1` models/utils/NIPs leaf audit, hundred-and-ninth remediation slice:
  - tightened the shared public pagination parser so `limit` must be strictly
    positive and `offset` must be non-negative, instead of silently relying on
    catalog-level clamping that could turn malformed client input like
    `limit=0` or `offset=-1` into live data queries;
  - added paired `services/common`, HTTP API, and DVM coverage proving invalid
    pagination bounds now fail fast as client-safe errors on both adapter
    surfaces rather than being normalized behind the caller's back.
- `2.1` models/utils/NIPs leaf audit, hundred-and-tenth remediation slice:
  - aligned shared read-request normalization so blank or whitespace-only
    `sort` values are treated as absent across both HTTP and DVM, instead of
    leaking through as bogus sort fields on one adapter while the other path
    behaved differently;
  - hardened the pre-parsed DVM job path so malformed non-string `sort` and
    compact `filter` values are rejected as normalized client errors instead
    of being silently ignored, and added paired `services/common`, API, and
    `dvm/jobs` coverage proving both adapter surfaces now follow the same
    transport contract.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eleventh remediation slice:
  - tightened compact read-side filter parsing so malformed non-empty filter
    fragments are no longer silently skipped on the DVM path, which previously
    allowed client typos like `network=clearnet,invalid` to broaden the live
    query instead of failing fast;
  - kept empty comma fragments harmless for human-authored inputs, and added
    paired `services/common` plus `dvm/jobs` coverage proving malformed
    compact-filter payloads now become client-safe rejections rather than
    partially applied queries.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twelfth remediation slice:
  - aligned the `NIP-90` request boundary so whitespace-padded `read_model`
    values are normalized before DVM validation, logging, and execution,
    instead of bypassing the shared public-parameter cleanup already applied
    to the rest of the read query surface;
  - added paired `dvm/utils` and `dvm/jobs` coverage proving human-authored
    requests like `"  relays  "` now resolve to the canonical resource rather
    than failing as a spurious disabled-read-model error.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirteenth remediation slice:
  - hardened the `NIP-90` request boundary so non-string `read_model` values
    from pre-parsed or patched job inputs are normalized into client-safe
    disabled-read-model rejections instead of risking internal attribute
    errors during DVM preparation;
  - added paired `dvm/utils` and `dvm/jobs` coverage proving malformed
    non-string resource selectors now fail safely and are logged through the
    same normalized request path as ordinary invalid read-model requests.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fourteenth remediation slice:
  - tightened `NIP-90` tag parsing so `param` keys are normalized before they
    enter the DVM request payload, instead of letting human-authored keys like
    `" read_model "` or `" limit "` bypass the same public-input cleanup we
    already apply to values further down the read-side stack;
  - added paired `dvm/utils` and `dvm/jobs` coverage proving whitespace-padded
    param keys now resolve to the canonical request fields while blank keys are
    ignored rather than creating unusable payload entries.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifteenth remediation slice:
  - tightened the shared HTTP read parser so direct filter field names are
    normalized before validation, instead of letting whitespace-padded keys
    become spurious unsupported-field errors or blank keys leak through as
    opaque malformed requests;
  - added paired `services/common` and API coverage proving whitespace-padded
    HTTP filter keys now resolve to the canonical field names while blank keys
    fail fast as explicit client-safe filter-field errors.
- `2.1` models/utils/NIPs leaf audit, hundred-and-sixteenth remediation slice:
  - aligned the shared HTTP filter-value path with the compact DVM filter
    parser so direct query-parameter values are normalized before validation
    too, instead of keeping whitespace-padded values that human-authored
    requests on the `NIP-90` path would already trim away;
  - added paired `services/common` and API coverage proving whitespace-padded
    HTTP filter values now resolve to the canonical catalog filter payload
    rather than diverging from the equivalent compact-filter request.
- `2.1` models/utils/NIPs leaf audit, hundred-and-seventeenth remediation slice:
  - tightened the shared HTTP read parser so reserved public query keys are
    normalized before dispatch too, instead of letting human-authored keys like
    `" limit "` or `" include_total "` fall through into the filter path and
    behave worse than the already-normalized `NIP-90` request surface;
  - added paired `services/common` and API coverage proving whitespace-padded
    reserved HTTP query keys now resolve to the canonical pagination/sort/total
    contract instead of degrading into spurious filter-field behavior.
- `2.1` models/utils/NIPs leaf audit, hundred-and-eighteenth remediation slice:
  - tightened the shared public pagination boundary so offsets above the
    catalog's hard anti-abuse ceiling no longer get silently clamped behind the
    caller's back, and now fail fast as normalized client errors on both HTTP
    and `NIP-90` request surfaces;
  - added paired `services/common`, API, and DVM coverage proving oversized
    public offsets are rejected before query execution instead of degrading
    into an implicit `100000` offset at the catalog layer.
- `2.1` models/utils/NIPs leaf audit, hundred-and-nineteenth remediation slice:
  - aligned the DVM pre-parsed request boundary with the already-normalized
    tag-parsing path so whitespace-padded parameter keys like `" read_model "`
    or `" limit "` no longer bypass shared validation and execution semantics
    when job params are injected or patched before `parse_job_params`;
  - added paired `dvm/utils` and `dvm/jobs` coverage proving the pre-parsed
    path now resolves canonical query fields and request logging exactly like
    the live `NIP-90` transport path instead of degrading to defaults or bogus
    disabled-read-model errors.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twentieth remediation slice:
  - aligned the DVM pre-parsed payment boundary with the live `NIP-90` tag
    parser so numeric-string bids like `"5000"` no longer degrade to a missing
    bid when job params are injected or patched before transport parsing;
  - added paired `dvm/utils` and `dvm/jobs` coverage proving pre-parsed bid
    values now follow the same payment-required vs executable-query contract as
    the live tag-based request path.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-first remediation
  slice:
  - aligned the shared `read_model_query_from_job_params()` helper with the
    already-normalized DVM adapter boundary so whitespace-padded pre-parsed
    `NIP-90` keys like `" limit "`, `" sort "`, or `" filter "` no longer
    bypass the helper's own public normalization contract when called directly;
  - added paired `services/common` coverage proving the shared job-query helper
    now resolves canonical reserved/filter keys exactly like the live DVM
    transport path instead of silently dropping them.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-second remediation
  slice:
  - hardened the shared `read_model_query_from_job_params()` key-normalization
    seam so malformed non-string pre-parsed keys no longer raise accidental
    attribute errors when callers use the exported helper directly, and are now
    ignored like they already are on the DVM wrapper path;
  - added paired `services/common` coverage proving the shared helper now keeps
    canonical reserved keys while dropping non-string or blank key noise
    instead of crashing before query validation.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-third remediation
  slice:
  - tightened the shared public integer parsing boundary so pre-parsed `NIP-90`
    numerics like `limit=1.5` or `offset=1.5` are no longer truncated through
    `int(...)`, and now fail the same client-safe validation contract expected
    by the live transport-facing adapters;
  - added paired `services/common` and `dvm/jobs` coverage proving malformed
    float numerics are rejected before query execution instead of silently
    widening or reshaping the requested page.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-fourth remediation
  slice:
  - hardened the shared HTTP query-normalization seam so exported helper calls
    with malformed non-string keys or filter values no longer raise accidental
    attribute errors, and now fail with the same client-safe parse contract as
    the rest of the public read-side boundary;
  - added paired `services/common` coverage proving the HTTP helper now rejects
    invalid key/value shapes explicitly instead of crashing before shared query
    validation can run.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-fifth remediation
  slice:
  - tightened the shared `service_state` hydration boundary so checkpoint,
    cursor, and validator-candidate codecs no longer coerce corrupted payloads
    through `int(...)` or `str(...)`, and now fall back or skip exactly at the
    typed persistence seam instead of silently reshaping bad state;
  - added paired `services/common` and `validator` coverage proving malformed
    persisted payloads now default cleanly or get skipped, while valid typed
    state still hydrates unchanged.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-sixth remediation
  slice:
  - tightened the shared catalog cursor boundary so malformed opaque cursors no
    longer leak type errors or defer typed corruption down to the DB-cast
    layer, and now fail immediately when the cursor payload shape or value
    types do not match the requested page order;
  - added paired `services/common` coverage proving non-string cursors and
    tampered cursor values are rejected as client-safe catalog errors before
    query execution.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-seventh remediation
  slice:
  - tightened the shared catalog cursor version contract so boolean payload
    versions like `v=true` no longer pass the opaque cursor guard through
    Python truthiness and are now rejected as invalid cursors before query
    execution;
  - added paired `services/common` coverage proving tampered keyset cursors
    must carry the exact typed version marker instead of merely a truthy
    surrogate.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-eighth remediation
  slice:
  - tightened the shared public pagination boundary so `limit` values above the
    configured `max_page_size` are no longer accepted and silently clamped by
    the catalog layer, and now fail immediately with the same client-safe
    validation contract already used for invalid offsets;
  - added paired `services/common`, `api`, and `dvm` coverage proving
    oversized public limits are rejected at the parser boundary instead of
    being transparently reshaped during query execution.
- `2.1` models/utils/NIPs leaf audit, hundred-and-twenty-ninth remediation
  slice:
  - tightened the shared keyset cursor boundary so tampered `date` and
    `timestamp` cursor payloads are no longer treated as merely string-shaped
    and allowed to drift down to the SQL cast layer, and now fail immediately
    as invalid cursor values before query execution;
  - added paired `services/common` coverage proving malformed temporal cursor
    scalars are rejected at decode/build time instead of surfacing later as
    generic query execution failures.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirtieth remediation
  slice:
  - tightened the Finder and Synchronizer persisted-cursor scheduling boundary
    so malformed stored `timestamp` and `id` values no longer rely on raw SQL
    casts or leak corrupted ordering semantics into worker selection, and now
    degrade cleanly to the canonical sentinel cursor at the query and
    hydration seam;
  - added paired `finder` and `synchronizer` coverage proving corrupted
    persisted cursor payloads are sanitized before ordering and default
    cleanly during row hydration instead of crashing or skewing least-progress
    scheduling.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-first remediation
  slice:
  - tightened the Validator persisted-candidate planning boundary so malformed
    stored `failures` and `timestamp` values no longer rely on raw SQL casts
    during cleanup, filtering, and ordering, and now degrade cleanly to the
    same numeric defaults already expected by the shared typed state seam;
  - added paired `validator` coverage proving candidate cleanup/count/fetch
    queries sanitize malformed numeric payloads before scheduling, while
    typed hydration still skips invalid persisted candidate rows instead of
    crashing the validation planner.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-second remediation
  slice:
  - tightened the Monitor persisted-checkpoint scheduling boundary so malformed
    stored `timestamp` values no longer rely on raw SQL casts during due-relay
    filtering, ordering, and keyset paging, and now degrade cleanly to the
    canonical `0` checkpoint semantics already used for never-monitored
    relays;
  - added paired `monitor` coverage proving monitor count/fetch/page queries
    sanitize malformed persisted timestamps before scheduling instead of
    surfacing generic query failures or skewing least-recently-monitored
    ordering.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-third remediation
  slice:
  - tightened the Refresher incremental checkpoint boundary so malformed
    persisted `timestamp` payloads no longer flow through permissive
    `int(...)` coercion and distort the refresh resume watermark, and now
    degrade cleanly to the typed default checkpoint expected by the shared
    `service_state` seam;
  - added paired `refresher` coverage proving corrupted persisted checkpoints
    resume from `0` instead of being silently reshaped into non-canonical
    watermarks during incremental target planning.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-fourth remediation
  slice:
  - tightened the shared catalog filter boundary so malformed typed public
    filters for numeric, boolean, and temporal columns no longer rely on SQL
    cast failures for validation, and now fail immediately at planner build
    time with client-safe column-specific errors before any query executes;
  - added paired `services/common` coverage proving non-string and invalid
    typed filter values are rejected before touching the database, while the
    catalog still converts unexpected asyncpg data errors into the same safe
    public error contract during execution.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-fifth remediation
  slice:
  - tightened the shared catalog identity-lookup boundary so malformed typed
    primary-key parameters for temporal, numeric, boolean, and integer-backed
    resources no longer rely on SQL casts during `get_by_pk`, and now fail
    immediately with client-safe parameter errors before any lookup query
    executes;
  - added paired `services/common` and `api` coverage proving invalid typed
    PK path values are rejected at the shared lookup seam before the database
    is touched, while bytea hex validation keeps the existing explicit public
    contract.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-sixth remediation
  slice:
  - tightened the shared Seeder/Finder candidate-registration boundary so
    duplicate relay URLs already present in one input batch no longer survive
    the DB-side "new relay" filter and produce duplicate validator candidate
    upserts, and now collapse to a first-seen canonical order before
    persistence;
  - added paired `services/common` coverage proving the helper now deduplicates
    repeated new relays deterministically even when the database returns the
    allowed URL set in a different order than the caller-provided batch.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-seventh remediation
  slice:
  - tightened the shared catalog keyset boundary so tampered `numeric` cursor
    payloads with non-finite values like `NaN` or `Infinity` no longer pass
    type checks merely because they are Python floats, and now fail
    immediately as invalid cursor values before query execution;
  - added paired `services/common` coverage proving both direct cursor
    coercion and full query planning reject non-finite numeric cursor values
    at the shared typed boundary instead of deferring them to runtime or
    database behavior.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-eighth remediation
  slice:
  - tightened the shared catalog keyset sort contract so semantically
    equivalent sort strings no longer diverge just because the caller changes
    direction casing (`desc` vs `DESC`), and now canonicalize to one stable
    cursor payload form before follow-up page matching;
  - added paired `services/common` coverage proving both direct sort
    canonicalization and full cursor-pagination follow-ups accept equivalent
    sort casing without breaking the keyset boundary.
- `2.1` models/utils/NIPs leaf audit, hundred-and-thirty-ninth remediation
  slice:
  - tightened the shared catalog keyset numeric boundary so follow-up cursors
    no longer reuse the already rounded public `float` rendering of `numeric`
    columns, and now carry an exact hidden numeric representation for cursor
    comparison while keeping the public row payload unchanged;
  - added paired `services/common` coverage proving numeric keyset follow-up
    pages now bind exact cursor values and reject malformed non-finite numeric
    cursor payloads at the same shared typed boundary.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fortieth remediation slice:
  - tightened the shared compact read-filter boundary so repeated filter keys
    in one public `filter=` string no longer overwrite each other via silent
    last-write-wins parsing, and now fail immediately as ambiguous client
    input at the shared request seam;
  - added paired `services/common` coverage proving duplicate compact filter
    keys are rejected both by the low-level parser and by the normalized
    `read_model_query_from_job_params()` DVM/job path before query validation
    continues.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-first remediation
  slice:
  - tightened the shared public query-key normalization boundary so HTTP and
    DVM/job inputs whose raw keys collapse to the same normalized field name
    after trimming no longer overwrite each other via silent last-write-wins
    parsing, and now fail immediately as invalid query input;
  - added paired `services/common` coverage proving duplicate normalized
    reserved keys and duplicate normalized HTTP filter keys are rejected
    before pagination, filter validation, or read-model execution proceeds.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-second remediation
  slice:
  - tightened the DVM `NIP-90` request-parameter boundary so duplicate `param`
    keys or duplicate `bid` tags that collapse to the same normalized key no
    longer overwrite each other via silent last-write-wins parsing, and now
    fail immediately as ambiguous client input on both live-tag and pre-parsed
    job paths;
  - added paired `dvm` coverage proving duplicate normalized request keys are
    rejected by `parse_job_params()`, surfaced as client-safe rejections by
    `prepare_job_request()`, and converted into ordinary DVM error responses
    by `process_request_event()` before query execution begins.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-third remediation
  slice:
  - tightened the shared HTTP query-parameter boundary so duplicate public
    query keys carried by the real `QueryParams` transport no longer collapse
    silently via mapping-style last-write-wins before shared validation, and
    now fail immediately as ambiguous client input;
  - added paired `services/common` and `api` coverage proving duplicate
    transport-level reserved keys and filter keys are rejected from true HTTP
    `QueryParams` objects before pagination parsing or catalog execution
    begins.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-fourth remediation
  slice:
  - tightened the Finder API-source extraction boundary so a configured
    JMESPath expression that no longer resolves to a list in the live JSON
    payload no longer degrades silently to "zero relays fetched", and now
    fails as a recoverable source error instead of advancing the API
    checkpoint;
  - added paired `finder` coverage proving non-list extraction results are
    rejected both at the low-level `fetch_api()` seam and at the
    `find_from_api()` runtime layer before success counters or checkpoint
    persistence can advance.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-fifth remediation
  slice:
  - tightened the Finder API-source config boundary so duplicate source URLs
    can no longer coexist under one `ApiConfig`, which previously let the
    service fetch the same source multiple times in one cycle while still
    sharing a single checkpoint identity keyed only by URL;
  - added paired `finder` coverage proving duplicate URLs are rejected both
    by the direct `ApiConfig` constructor and by nested `FinderConfig`
    validation before any runtime fetch scheduling can begin.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-sixth remediation
  slice:
  - tightened the Finder API-source config boundary so malformed endpoint
    URLs no longer survive until `aiohttp` runtime failures, and now require
    non-blank absolute `http://` or `https://` URLs with a real host before
    the service can start a fetch cycle;
  - added paired `finder` coverage proving valid URLs are normalized by
    trimming surrounding whitespace, while blank values, missing schemes,
    wrong schemes, and missing hosts are rejected at config validation time.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-seventh remediation
  slice:
  - tightened the Finder API persistence boundary so per-source checkpoints
    no longer advance before candidate insertion succeeds, which previously
    could lose one fetch cycle by persisting cooldown state even when relay
    candidate insertion failed afterward;
  - added paired `finder` runtime/service coverage proving API batches now
    persist relay candidates before checkpoints on success, and preserve both
    in-memory buffers and pending checkpoints unchanged when insertion fails.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-eighth remediation
  slice:
  - tightened the shared validator-candidate hydration and scheduling
    boundary so persisted candidate rows missing `timestamp`, `network`, or
    `failures` no longer degrade silently into fresh default candidates, and
    are now rejected before they can re-enter validation ordering;
  - added paired `services/common` and `validator` coverage proving missing
    required candidate payload fields are rejected by typed decode, and that
    the shared validator query contract now excludes malformed candidate rows
    before count/fetch scheduling proceeds.
- `2.1` models/utils/NIPs leaf audit, hundred-and-forty-ninth remediation
  slice:
  - tightened the shared validator-candidate numeric boundary so persisted
    candidates with negative `timestamp` or `failures` values no longer pass
    through typed decode or SQL scheduling as legitimate work, which
    previously let impossible states outrank fresh candidates;
  - added paired `services/common` and `validator` coverage proving negative
    candidate numerics are rejected by typed hydration and skipped by the
    shared validator fetch path before retry ordering begins.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fiftieth remediation
  slice:
  - tightened the shared `CandidateCheckpoint` constructor boundary so
    invalid relay keys, non-canonical relay URLs, network/key mismatches, and
    impossible direct-construction numerics no longer survive until the
    validator worker path, which previously let malformed candidate state pick
    the wrong routing/proxy behavior before failing late;
  - added paired `services/common` and `validator` coverage proving direct
    candidate construction now enforces the real relay contract, and that the
    shared validator fetch path skips both malformed relay keys and
    network-mismatched candidate rows before validation scheduling begins.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-first remediation
  slice:
  - tightened the shared cursor boundary so `FinderCursor`, `SyncCursor`, and
    generic typed cursor hydration now require non-negative timestamps,
    canonical 32-byte hex event IDs, and canonical relay keys where the
    runtime really expects relay-backed cursor state;
  - aligned the `finder` and `synchronizer` query-side cursor fallback so
    malformed persisted cursor pairs no longer diverge between sanitized SQL
    ordering and the Python object handed to runtime code, and invalid IDs now
    collapse to sentinel values while valid timestamps are preserved when safe;
  - added paired `services/common`, `finder`, and `synchronizer` coverage
    proving uppercase cursor IDs are canonicalized, negative or malformed
    persisted cursor state is rejected or sanitized before runtime use, and
    finder/synchronizer fetch paths now return only canonical cursor objects.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-second remediation
  slice:
  - tightened the shared checkpoint boundary so generic `Checkpoint`
    construction and typed checkpoint hydration no longer accept negative
    timestamps, which previously let malformed persisted state survive into
    refresher watermarks and other checkpoint-backed defaults instead of
    collapsing to the zero sentinel;
  - aligned the `monitor` SQL-side checkpoint sanitization with the same
    non-negative contract so corrupted persisted monitor timestamps no longer
    outrank default-zero relays in due-order planning;
  - added paired `services/common`, `finder`, `monitor`, and `refresher`
    coverage proving negative checkpoint payloads now default to zero at the
    shared fetch/decode boundary, refresher incremental runs restart from
    zero on malformed persisted state, and monitor query SQL only treats
    non-negative persisted timestamps as valid.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-third remediation
  slice:
  - tightened the `validator` candidate fetch boundary so malformed persisted
    candidate rows can no longer consume the whole SQL `LIMIT` window and make
    a non-empty workset appear empty after typed decode, which previously could
    stop a validation cycle before reaching valid candidates ordered later in
    the same queue;
  - added paired `validator` coverage proving candidate fetch now continues
    scanning past invalid leading rows with stable ordering and offset
    progression until it fills the requested logical page or exhausts the raw
    workset.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-fourth remediation
  slice:
  - tightened the `validator` cleanup boundary so malformed persisted
    candidate rows no longer live forever beside exhausted candidates, which
    previously let unprocessable validator tombstones block rediscovery of the
    same relay because `Finder` only checks for raw `service_state` presence;
  - added paired `validator` coverage proving cleanup SQL now purges invalid
    `failures`, `timestamp`, and `network` payloads in the same pass that
    removes exhausted candidates.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-fifth remediation
  slice:
  - tightened the `validator` service cleanup boundary so candidate rows with
    invalid relay keys or relay/network mismatches no longer survive forever
    just because their numerics are well-typed, which previously left
    unprocessable validator tombstones in `service_state` even though the
    runtime would skip them forever;
  - added paired `validator` query/service coverage proving cleanup now
    deletes typed-decode-invalid candidate rows even when threshold-based
    exhausted cleanup is disabled, so malformed candidate state stops blocking
    later rediscovery of the same relay URL.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-sixth remediation
  slice:
  - tightened the shared `service_state` hydration boundary so non-mapping
    JSON payloads are skipped instead of crashing `Brotr.get_service_state()`,
    which previously let one corrupted persisted row take down unrelated
    `assertor`, `refresher`, or cleanup read paths before service-specific
    typed decoding could even run;
  - tightened the `validator` raw cleanup seam so candidate purge now reads
    persisted rows directly and deletes tombstones whose JSON payload is not
    even a mapping, which previously survived forever because generic
    `ServiceState` hydration failed before the invalid-candidate cleanup could
    inspect them.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-seventh remediation
  slice:
  - tightened the `ranker` local-checkpoint boundary so legacy JSON and DuckDB
    checkpoint rows no longer pass through broad `int(...)` / `str(...)`
    coercions, which previously could turn corrupted persisted values into a
    lexicographically wrong graph-sync checkpoint and silently skip follow-graph
    work;
  - added paired `ranker` store coverage proving malformed legacy checkpoint
    payloads now fall back to the canonical zero checkpoint, and malformed
    DuckDB checkpoint rows are automatically repaired back to that same
    canonical state during initialization.
- `2.1` models/utils/NIPs leaf audit, hundred-and-fifty-eighth remediation
  slice:
  - tightened the typed `ranker` graph-sync checkpoint contract so
    `GraphSyncCheckpoint` no longer accepts negative timestamps, empty pubkeys
    after positive progress, or non-canonical pubkey identifiers, which
    previously let impossible checkpoint values survive in memory and drive the
    lexicographic sync window from a bogus follower boundary;
  - added paired `ranker` query/store coverage proving canonical uppercase
    pubkeys normalize to lowercase while malformed checkpoint values now fail
    fast before they can influence contact-list pagination or local checkpoint
    persistence.
