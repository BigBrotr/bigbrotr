# Repository-Wide Leaf-To-Root Content Audit Program

## Purpose

The redesign execution program is closed.
That does **not** mean the repository should now be trusted blindly.

Before PR preparation and final integration, BigBrotr should go through one
more rigorous program:

- read the real content of every tracked file;
- do it in a deliberate leaf-to-root order;
- classify every file against the final desired repository shape after the
  redesign;
- decide what must be kept, updated, removed, or added;
- and close the resulting cleanup slices with the same audit discipline used
  for the redesign itself.

This means the audit is not merely descriptive.
It is normative.

For every tracked file, the question is not only:

- “is this file locally acceptable?”

It is also:

- “does this file still deserve to exist in the final repository we want?”
- “if the redesign had touched this file directly, would we still leave it in
  this shape?”
- “is there a missing counterpart that the final repository should now have?”

This program exists to catch the class of issues that a successful redesign can
still leave behind:

- a file that still exists but no longer earns its place;
- a folder whose local guidance is now incomplete or dishonest;
- an implementation surface whose paired docs or generated artifacts drifted;
- a root reference that still narrates a historical shape;
- a generated or mirrored surface that should be removed or rebuilt;
- a missing file that should now exist in the final repository shape;
- a subtle omission such as views, cleanup semantics, dashboards, or local
  guidance no longer being documented as the code actually behaves.

The purpose is not to reopen settled architecture casually.
The purpose is to validate the **actual repository contents** against the
settled architecture and quality bar.

This program complements, but does not replace:

- [16_operational_implementation_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/16_operational_implementation_plan.md)
- [17_integral_codebase_validation.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/17_integral_codebase_validation.md)
- [18_code_excellence_standard.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/18_code_excellence_standard.md)
- [19_documentation_rewrite_program.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/19_documentation_rewrite_program.md)
- [20_redesign_execution_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/20_redesign_execution_ledger.md)
- [22_final_contract_freeze.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/22_final_contract_freeze.md)
- [99_definitive_master_plan.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/99_definitive_master_plan.md)

---

## Why This Program Is Necessary

The redesign program already improved architecture, naming, documentation, and
repository hygiene very substantially.

But a repository can still carry residual weakness even after a successful
program, for example:

- files whose content is technically valid but no longer necessary;
- files that were never touched by the redesign program and therefore still
  encode older assumptions;
- duplicated surfaces that now survive only because nobody re-read them after
  their neighbors changed;
- tracked generated artifacts whose source-of-truth relationship is unclear;
- support files that still point at old assumptions;
- folder-level docs that are locally reasonable but globally incomplete;
- cleanup or retention surfaces whose implementation and explanation drifted;
- SQL/view/reporting surfaces that are present but under-described;
- test/support files that no longer reflect the current contract;
- reference documents that are individually fine but collectively inconsistent.

This program therefore assumes:

- the redesign contract is mostly right;
- the repository may still contain residual content drift;
- untouched files are **especially likely** to contain drift because most of
  the previous work necessarily concentrated on the critical slices;
- only a literal content read of the tracked files can answer that honestly.

---

## Scope

### 1. Canonical scope

The audit scope is:

- every tracked file returned by `git ls-files` at audit start;
- any new tracked file intentionally added during the audit itself;
- every maintained folder that should have local guidance or a clear entry
  surface;
- the relationships between source-of-truth and derived/tracked artifacts;
- the gap between the current repository contents and the final repository
  shape the redesign implies.

As of the current baseline, the tracked repository surface is approximately:

- `542` tracked files.

That count is informative only.
The audit must freeze a fresh manifest at execution start.

### 2. Included repository bands

The audit explicitly includes:

- root repository files and long-form references;
- `.github/`;
- `deployments/`;
- `docs/`;
- `planning/`;
- `src/`;
- `tests/`;
- `tools/`;
- tracked SQL generation outputs inside built-in deployments;
- tracked dashboards, alerting rules, and operator files.

### 3. Excluded local/runtime bands

The audit does **not** treat local runtime, cache, or ignored output as first
class content unless it is tracked.

Examples normally out of scope unless tracked:

- `.git/`
- `.venv/`
- `site/`
- `dist/`
- `htmlcov/`
- cache folders
- local deployment data and dumps

The exclusion is not because these folders are unimportant operationally.
It is because this program is about the tracked repository contract.

---

## Non-Negotiable Rules

### 1. Read file content, do not infer from neighbors

No file should be marked “fine” because:

- a sibling file looks fine;
- the folder seems coherent;
- the tests pass;
- or a nearby README appears up to date.

Every tracked file in scope must be read as content.

This rule is especially important for files that were not modified by the
redesign execution program.
“Untouched” is not evidence of correctness.
It is often the opposite: a reason to look harder.

### 2. Leaves first, then parents

The traversal order must be leaf-to-root:

- inspect the deepest maintained folders first;
- close child-folder understanding before auditing the parent folder;
- do not finalize top-level synthesis while child directories remain unread.

This matters because parent docs, package exports, and root guides should be
judged only after the concrete leaves they summarize are fully understood.

### 3. Every file gets a decision

Each file must be classified as one of:

- `keep`
- `update`
- `remove`
- `split`
- `merge`
- `replace`
- `add counterpart`

The audit is incomplete if a file was read but no decision was recorded.

It is also incomplete if the decision is based only on current local
correctness.
The decision must be based on whether the file belongs in the **final**
repository shape.

### 4. Keep only what earns its bytes

A tracked file should survive only if it has a live reason to exist.

Files should not remain merely because:

- they are harmless;
- they existed before;
- they are historical but not labeled as such;
- they duplicate another better surface.

Likewise, a missing file should be added if the final repository shape now
requires it, even if the redesign program never previously touched that area.

### 5. Do not reopen settled design casually

The audit may find:

- implementation drift;
- documentation drift;
- obsolete files;
- missing local guidance;
- stale naming;
- dead duplication.

It should not casually reopen already-settled core contracts unless the file
audit discovers a real contradiction against the live repository state.

If a settled contract must be questioned, the contradiction must be recorded
explicitly with concrete file evidence.

### 6. Every remediation slice follows the redesign discipline

When the audit finds a real issue, the resulting change package must still use
the redesign-quality loop:

- bounded scope;
- targeted validation;
- severe audit;
- fix loop;
- full gate;
- commit;
- ledger update.

---

## File Decision Rubric

For each file, answer these questions explicitly.

### 1. Identity and purpose

- What is this file for?
- Is that purpose still live in the final project?
- Is this the right location and shape for that purpose?
- If this file had been freshly designed today from the final architecture,
  would we still create it in this form?

### 2. Architectural honesty

- Does the file describe or implement the current architecture honestly?
- Does it still narrate or encode a historical shape?
- Does it hide compatibility behavior as if it were the core contract?

### 3. Quality and maintainability

- Is the file clean, bounded, and professional?
- Is the naming semantically correct?
- Is the level of duplication acceptable?
- Would a new maintainer understand why the file exists?

### 4. Paired-surface alignment

- Does this file have a source-of-truth partner?
- Is it derived from another surface?
- Does it document another surface?
- Is the pairing explicit and correct?
- Does the final repository shape require another counterpart file that is
  missing today?

### 5. Documentation truthfulness

- If the file is documentation, is it honest and complete enough?
- If the file is code/config, is the nearby documentation accurate?
- Is a missing local `README.md` or guide now justified?

### 6. Final action

At the end of review, record one action:

- keep as is;
- update in place;
- delete;
- merge into another surface;
- split into clearer surfaces;
- add missing counterpart docs/tests/config;
- escalate as a genuine contract contradiction.

---

## Paired-Surface Watch List

These relationships must be audited together because drift is likely there even
when each file looks plausible in isolation.

### 1. SQL templates, generated SQL, runtime, docs

Audit together:

- `tools/templates/sql/**`
- `deployments/*/postgres/init/**`
- `src/bigbrotr/core/brotr.py`
- relevant model files
- database/user/deployment docs

Special attention:

- views/reporting surfaces;
- cleanup/retention semantics;
- grants/init scripts;
- storage-profile divergence;
- whether the current docs describe what the generated SQL actually contains.

### 2. Deployment config, runtime contracts, deployment docs

Audit together:

- `deployments/*/config/**`
- deployment READMEs
- `src/bigbrotr/core/deployments.py`
- service config models
- user/operator deployment docs

Special attention:

- exposure policy;
- storage profile;
- service enablement assumptions;
- which files are authoritative versus generated or copied.

### 3. Metrics, dashboards, monitoring docs

Audit together:

- Grafana dashboards
- Prometheus rules
- Alertmanager config
- exporter queries
- metrics emitted by code
- monitoring docs

Special attention:

- removed or renamed metrics;
- orphan alerts;
- panels referring to dead concepts;
- service count and runtime shape drift.

### 4. Public read-side contracts

Audit together:

- `src/bigbrotr/services/common/**`
- API adapter files
- DVM adapter files
- read-side docs
- deployment exposure config
- tests asserting read behavior

Special attention:

- readable-resource vs compatibility seam clarity;
- pagination and boundedness claims;
- filter/sort exposure;
- stable public `read_model` transport seam vs internal naming.

### 5. Local guidance surfaces

Audit together:

- folder-level `README.md`
- `AGENTS.md`
- package docstrings
- MkDocs section pages
- contributor/operator guides

Special attention:

- whether local guidance is honest;
- whether it duplicates or contradicts a stronger source;
- whether a maintained folder is still missing the right local entry surface.

---

## Execution Order

The audit should proceed in waves.

Each wave closes only when:

- every file in its scope was read;
- every file has a recorded action decision;
- any required remediation slice for that wave is implemented, audited, and
  committed;
- the repository-wide content-audit ledger is updated.

### Wave 0 — Inventory Freeze And Traversal Map

1. freeze the tracked-file manifest from `git ls-files`;
2. sort by depth descending, then path ascending;
3. map files to maintained folders;
4. mark which files are generated companions, narrative docs, runtime config,
   code, tests, or support assets;
5. mark which tracked files were untouched by the redesign execution program,
   because they should be treated as high-suspicion drift candidates;
6. initialize the audit ledger with actual scope;
7. write the concrete Wave 0 artifacts:
   - `25_repository_content_audit_manifest.txt`
   - `26_repository_content_audit_untouched_manifest.txt`
   - `27_repository_content_audit_traversal_map.md`

No content judgment starts before this inventory is frozen.

### Wave 1 — Deepest Non-Python Leaves

Audit the deepest maintained leaves first:

- `.github/ISSUE_TEMPLATE/`
- `.github/workflows/`
- `docs/_snippets/`
- `docs/assets/`
- `docs/overrides/`
- `deployments/*/config/services/`
- `deployments/*/monitoring/**` leaf folders
- `deployments/*/postgres/init/`
- `deployments/*/pgbouncer/`
- `deployments/*/static/`
- other tracked leaf support folders

These folders often hide drift because they are configuration-heavy,
copy-oriented, and easy to stop reading once they “look fine”.

### Wave 2 — Python Leaf Packages

Audit the deepest Python implementation leaves:

- `src/bigbrotr/models/`
- `src/bigbrotr/utils/`
- `src/bigbrotr/nips/nip11/`
- `src/bigbrotr/nips/nip66/`
- `src/bigbrotr/nips/nip85/`
- `src/bigbrotr/core/`
- each concrete service package under `src/bigbrotr/services/`
- `src/bigbrotr/services/common/`

This wave should read:

- implementation modules;
- package-local `README.md`;
- package exports;
- package docstrings;
- local tests paired to the touched surfaces.

### Wave 3 — Tools And Tests Leaves

Audit:

- `tools/templates/sql/base/`
- `tools/templates/sql/lilbrotr/`
- `tools/templates/sql/testbrotr/`
- `tools/` leaf utilities
- `tests/unit/**` leaf folders
- `tests/integration/**` leaf folders
- `tests/fixtures/`

This wave must answer:

- whether the test surface still matches the real current contract;
- whether helper/tools files remain necessary and honest;
- whether test-only SQL/template surfaces still earn their complexity.

### Wave 4 — Parent Package And Folder Surfaces

After children are closed, audit parents:

- `src/`
- `src/bigbrotr/`
- `src/bigbrotr/nips/`
- `src/bigbrotr/services/`
- `tests/`
- `tools/`
- `docs/` local non-page guidance
- `deployments/`
- `.github/`
- `planning/`

This is where package exports, parent README files, and parent-level guidance
are validated against the fully read children.

### Wave 5 — Narrative Docs And Planning Surfaces

Audit all narrative and coordination surfaces:

- MkDocs pages
- root guides
- long-form reference documents
- planning files
- contributor/operator docs

This wave should ask:

- do the docs describe the final repository honestly;
- is any document obsolete, duplicated, or missing;
- are historical files clearly marked as historical;
- does the planning set still match the actual repository state after
  redesign completion.

### Wave 6 — Root Contract And Build/CI Surfaces

Audit:

- `README.md`
- `AGENTS.md`
- `CONTRIBUTING.md`
- `PROJECT_GUIDE.md`
- `PROJECT_VISION_AND_REDESIGN_PLAN.md`
- `BIGBROTR_REPOSITORY_BIBLE.md`
- `NOSTR_NIPS_DEEP_ANALYSIS.md`
- `pyproject.toml`
- `uv.lock`
- `Makefile`
- `mkdocs.yml`
- `.pre-commit-config.yaml`
- `.gitignore`
- `.dockerignore`
- `codecov.yml`
- root legal and support files

This is the final root synthesis wave, and it should only happen after the
children are already understood.

### Wave 7 — Repository-Wide Gap Remediation And Closeout

This final wave exists to close what the file reading discovered:

- delete files that no longer earn their place;
- add missing local guidance or companion files;
- add any newly necessary tracked file that the final repository shape now
  requires;
- rewrite or tighten under-described docs;
- close paired-surface drift;
- remove stale reference language;
- re-run the complete gate;
- and produce a final audit summary of what changed and what, if anything,
  remains intentionally deferred.

---

## Required Ledger Discipline

This program must maintain its own explicit progress record in:

- [24_repository_content_audit_ledger.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/24_repository_content_audit_ledger.md)

Wave 0 should also materialize the frozen baseline in companion artifacts:

- [25_repository_content_audit_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/25_repository_content_audit_manifest.txt)
- [26_repository_content_audit_untouched_manifest.txt](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/26_repository_content_audit_untouched_manifest.txt)
- [27_repository_content_audit_traversal_map.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/planning/definitive-redesign/27_repository_content_audit_traversal_map.md)

The ledger should record:

- the frozen manifest baseline;
- wave status;
- folder scope;
- file decisions;
- whether a file was previously untouched by the redesign execution program;
- remediation commits;
- findings and how they were closed;
- deferred items and their justification.

No wave is complete until the ledger is updated.

---

## Validation Gates

### 1. Per-wave minimum

After each remediation slice:

```bash
make ci
uv lock --check
```

If SQL/generator/deployment surfaces were touched:

```bash
python tools/generate_sql.py --check
```

If docs or local guidance were touched:

```bash
uv run pre-commit run markdownlint --files <touched-doc-files>
uv run pre-commit run codespell --files <touched-doc-files>
uv run mkdocs build --strict
```

### 2. Final closeout gate

At the end of the full repository content audit:

- `make ci`
- `uv lock --check`
- `python tools/generate_sql.py --check`
- `mkdocs build --strict`
- explicit deployment-aware smoke verification for built-in deployments
- explicit grep/sweep checks for known drift classes discovered during the audit

---

## Completion Criteria

The repository-wide content audit is complete only when:

- every tracked file in the frozen manifest was read as content;
- every file has an explicit keep/update/remove/add-class decision;
- every untouched tracked file was explicitly judged against the final desired
  repository shape rather than implicitly trusted;
- all required remediation slices are implemented and committed;
- paired surfaces have been revalidated together;
- the repository is clean and fully green;
- the audit ledger reflects the real final state;
- and there is a final summary of any consciously deferred items.

At that point, the repository can be considered not just redesigned, but also
fully re-read, re-justified, and re-cleaned against its actual tracked
contents.
