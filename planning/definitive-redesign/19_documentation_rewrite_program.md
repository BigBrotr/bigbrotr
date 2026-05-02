# Documentation Rewrite Program

## Purpose

This file makes one thing explicit:

> the redesign requires a full documentation rethink and rewrite, not a light
> sync pass.

That includes documentation across the whole repository:

- in-code documentation;
- folder-level `README.md` files;
- package and module documentation;
- repository-level documentation files;
- deployment and operations documentation;
- developer-facing documentation;
- and especially the `docs/` MkDocs site.

The redesign is therefore not complete when the code and architecture are
correct but the documentation still narrates an older project shape.

---

## 1. Why Documentation Must Be Rewritten, Not Merely Patched

The redesign changes too much for incremental wording fixes to be sufficient.

It changes:

- the DB mental model;
- the service ownership model;
- the read-side model;
- the deployment contract;
- the capability and publication model;
- the standards expected from the codebase itself.

So the documentation challenge is not:

- “update a few outdated paragraphs”

It is:

- **reconstruct the project’s narrative so that it matches the final system
  honestly and cleanly**.

---

## 2. Scope Of The Rewrite

The rewrite must cover all relevant documentation surfaces.

### 2.1 In-code documentation

This includes documentation that lives in source files, such as:

- module docstrings;
- class docstrings;
- public function/method docstrings where they matter;
- comments that explain important logic or invariants;
- usage-oriented examples where appropriate.

The goal is not maximum verbosity.
The goal is accurate, useful, library-grade documentation for public code
surfaces.

### 2.2 Package-level repository documentation

This includes repository documentation files such as:

- root-level explanatory documents;
- folder-level `README.md` files;
- package-local guidance files;
- `AGENTS.md` files and repository guidance files;
- command-support documentation where it remains part of the contributor
  workflow;
- architecture notes that are meant to guide contributors;
- deployment-local notes and operational files where relevant.

These documents must match the final project shape, not the pre-redesign
history.

### 2.3 `docs/` site documentation

This includes the full MkDocs site:

- landing pages;
- getting started;
- user guides;
- how-to guides;
- development docs;
- architecture pages;
- configuration and database pages;
- service explanations;
- API reference integration;
- operational and deployment guides.

This is the most important documentation rewrite surface because it is the
project’s clearest public explanation layer.

### 2.4 Folder-level human-oriented documentation

The rewrite must also cover the local documentation that explains what a given
folder is for.

The target direction should be:

- a human-oriented `README.md` for each meaningful maintained project folder;
- explicit exceptions only for trivial, generated, or structurally empty
  folders;
- no important project area that can only be understood by reading code or
  tribal notes first.

### 2.5 Generated and structured reference surfaces

This includes:

- mkdocstrings-backed reference pages;
- reference navigation generation;
- structured page hierarchies and taxonomy;
- discoverability of public Python APIs.

The rewrite must ensure that generated reference and narrative documentation
tell a coherent story together.

---

## 3. Final Documentation Standard

The final documentation standard should be as high as the code standard.

Documentation should be:

- semantically honest;
- well structured;
- easy to navigate;
- aligned with the final architecture;
- aligned with the actual runtime and deployment model;
- useful for operators, contributors, and library consumers;
- free from stale historical framing.

The final documentation should make it materially easier to answer:

- what BigBrotr is now;
- what each service owns;
- what the shared DB means;
- what the public read side is;
- how deployments are defined;
- how to extend the system;
- how to use the Python package surfaces correctly.

---

## 4. What Must Be Rewritten Conceptually

The documentation rewrite must not just rename terms.
It must reframe the project around the final architecture.

### 4.1 Product identity

The project should be described according to the final product identity, not
through an outdated pipeline summary alone.

### 4.2 Data model

The shared DB and derivation model must be explained according to the final
storage-first architecture.

### 4.3 Service ownership

Services must be documented according to their final boundaries, not according
to historical responsibility drift.

### 4.4 Read side

The documentation must explain the protocol-agnostic read core and the role of
adapter-specific exposure policy.

### 4.5 Deployments

Deployments must be documented as first-class compositions, not just as
folders users happen to copy.

### 4.6 Extension model

The docs must explain how the project extends through:

- services;
- deployments;
- storage profiles;
- protocol adapters;
- NIP capabilities.

### 4.7 Code quality expectations

The docs should also reflect the repository’s engineering standard:

- high rigor;
- boundedness discipline;
- strong testing;
- serious review;
- code cleanliness expectations.

---

## 5. Documentation As A First-Class Design Surface

Documentation must be treated as part of the product and architecture, not as
supporting decoration.

That means documentation must satisfy the same broad expectations as code:

- clarity;
- consistency;
- honesty;
- maintainability;
- intentional structure.

The rewrite should therefore remove:

- stale terminology;
- duplicated explanations that drift apart;
- pages that describe old shapes;
- under-explained public APIs;
- accidental complexity in the docs taxonomy itself.

---

## 6. Specific Rewrite Targets

The rewrite should explicitly target at least these repository surfaces.

### 6.1 `docs/index.md`

The home page should be re-authored around the final product identity and
final system shape.

### 6.2 User-guide architecture and service pages

These must be rebuilt around the final:

- data architecture;
- service ownership model;
- read model;
- deployment model.

### 6.3 Configuration and database pages

These must reflect the final shared DB and deployment contract rather than the
old schema story.

### 6.4 Getting-started and how-to flows

These must match the final deployment and operator experience, not just the
current historical layout.

### 6.5 Development docs

Contributor and developer docs must reflect the final engineering workflow,
architecture, and standards.

### 6.6 Folder-level README coverage

The repository should gain a coherent local documentation layer based on
folder-level `README.md` files.

Those local `README.md` files should explain, where relevant:

- what the folder is for;
- what belongs there and what does not;
- the important subfolders or entrypoints;
- how it fits into the wider architecture;
- where to look next.

They are not a replacement for deeper reference docs.
They are the first orientation surface for humans moving through the repo.

### 6.7 Generated API reference strategy

The mkdocstrings/reference layer must be reviewed so that public package
surfaces are actually presented clearly and intentionally.

### 6.8 In-code public docstrings

Public modules and APIs in `src/` should be rewritten where necessary so the
reference docs are worthy of the final package surface.

### 6.9 Contributor and operator guidance files

Repository guidance surfaces such as:

- `AGENTS.md`
- repository workflow guides
- deployment-local guidance notes
- any contributor-facing command or process documentation

must also be rewritten so they match the final system and final engineering
discipline.

### 6.10 README versus `AGENTS.md`

The rewrite should treat these two local-documentation surfaces as
complementary, not interchangeable.

- `README.md` should be the human-oriented local orientation layer.
- `AGENTS.md` should remain the workflow- and implementation-oriented guidance
  layer where that convention already exists.

The redesign should not leave one of them trying to do both jobs badly.

---

## 7. Operational Consequences For The Implementation Plan

The redesign should treat documentation in two ways at once.

### 7.1 Local documentation responsibility

Every work package that changes public semantics must update the touched
documentation surfaces enough to avoid local lies.

That includes:

- code-level docs;
- config docs;
- local repo docs;
- affected `docs/` pages where the slice changes public meaning.

This responsibility also includes package guidance and repository guidance
files when the slice changes what those files are supposed to teach.

When a slice changes the meaning of a maintained folder, it should also update
that folder’s `README.md` or make the absence of one an explicit follow-up
task inside the documentation tranche.

### 7.2 Global rewrite tranche

In addition to local updates, the redesign must include a deliberate
repository-wide documentation rewrite tranche near the end, once the final
architecture is materially in place.

That tranche exists because some documentation can only be rewritten properly
once the final shapes are stable.

---

## 8. Audit Standard For Documentation Work

Documentation work must also be audited seriously.

At minimum, the audit should ask:

- is the documentation now more honest than before;
- does it describe the actual system, not an older one;
- is the structure easier to navigate;
- are examples and workflows realistic;
- does public API documentation help a real consumer;
- do local folder `README.md` files explain the maintained project surfaces
  clearly enough;
- are duplicate explanations still consistent;
- does the `docs/` site now tell the same story as the code and config?

If the answer is no, the documentation slice is not done.

---

## 9. Final Rule

The redesign is not complete when:

- the code is excellent;
- but the documentation still narrates the wrong system.

The redesign is complete only when:

- code,
- config,
- tests,
- deployments,
- and documentation

all describe and embody the same final project.

This file should be read together with:

- `18_code_excellence_standard.md`
- `16_operational_implementation_plan.md`
- `99_definitive_master_plan.md`
