# Code Excellence Standard

## Purpose

This file makes one design commitment explicit:

> the redesign is not complete when the target architecture merely exists;
> it is complete only when the codebase itself reaches a uniformly excellent
> professional standard.

This means the redesign must deliver all of the following together:

- the best final product shape;
- the best final architectural shape;
- the best final naming and boundary shape;
- a library-grade `src/` package surface;
- a repository-wide documentation surface that matches the final system;
- and a codebase that is consistently clean, slim, disciplined, and
  professional.

This file exists so that code quality is never treated as an optional
“polish pass” after the real work.

---

## 1. Final Quality Target

The target is not:

- merely test-green code;
- merely lint-clean code;
- merely type-safe code;
- merely code that implements the new behavior.

The target is:

- semantically honest code;
- minimal code;
- bounded code;
- coherent code;
- readable code;
- maintainable code;
- well-documented code and public APIs;
- usable Python library interfaces;
- coherent repository-wide documentation;
- professional code with consistent standards across the whole repository.

In other words:

- passing checks is necessary;
- architectural correctness is necessary;
- but **code excellence is also necessary**.

---

## 2. What “Excellent Code” Means Here

In the context of this redesign, code excellence means all of the following.

### 2.1 Semantic honesty

Names, modules, configs, and abstractions must say what they really are.

No layer should keep a misleading name just because it is historically
familiar.

### 2.2 Minimality

Every line should earn its existence.

That means:

- no convenience duplication that does not buy real value;
- no speculative abstractions;
- no unnecessary glue layers;
- no overgrown data shapes;
- no needless helper proliferation.

### 2.3 Strong boundaries

Responsibilities must live in the right place.

That includes:

- thin adapters;
- disciplined shared infrastructure;
- no service-to-service leakage;
- no protocol concerns in core layers;
- no private-service convenience structures forced into shared architecture.

### 2.4 Boundedness

The code must behave as if the system is already operating at very large
scale.

That means:

- no hidden full-fetch paths;
- no casual in-memory accumulation on large sets;
- chunked traversal where required;
- resumable heavy work where needed;
- explicit hot-path discipline.

### 2.5 Consistency

Equivalent concepts should be expressed in equivalent ways.

That includes consistency across:

- naming;
- config conventions;
- query conventions;
- model patterns;
- service loops;
- error boundaries;
- test style.

### 2.6 Readability without fluff

The code should be easy to understand because it is well-shaped, not because
it is padded with commentary.

The ideal is:

- straightforward when straightforward is possible;
- explicit where complexity is real;
- never noisy;
- never ornamental.

### 2.7 Testability and proof

Excellent code is provable.

That means:

- important behavior has real tests;
- tests reflect architectural boundaries, not only outputs;
- refactors improve, not erode, the executable specification.

### 2.8 Library-grade public API quality

`src/` is not only internal implementation.
It is also a Python library surface.

That means public package quality matters in a first-class way.

The redesign must therefore produce:

- usable import surfaces;
- coherent module boundaries;
- public APIs that are understandable and unsurprising;
- configuration models and service factories that are pleasant to consume;
- documentation that explains the intended public usage of important modules,
  services, and extension points.

### 2.9 Documentation as part of quality

Documentation is not separate from code quality here.

Important public-facing code should be documented well enough that a serious
consumer or maintainer can understand:

- what the module is for;
- what the public API is;
- what the invariants are;
- what inputs and outputs mean;
- how the component is expected to be used.

The goal is not decorative documentation.
The goal is documentation that makes the repository easier to trust and use.

### 2.10 Repository-wide documentation excellence

Documentation quality is not limited to `src/` docstrings.

The redesign must also raise the quality of:

- repository-level docs;
- folder-level `README.md` files;
- package-level docs;
- deployment/operator docs;
- contributor docs;
- and especially the `docs/` site.

These are all part of the project surface and must meet the same standard of:

- honesty;
- structure;
- clarity;
- consistency;
- professional finish.

### 2.11 Repository-wide project-surface quality

Repository quality is not confined to runtime Python modules.

The redesign must also hold first-class standards for:

- `tests/`
- `tools/`
- `deployments/`
- `docs/`
- `AGENTS.md` files and repository guidance;
- workflow and config files;
- repository-level guidance and operational files.

These are all part of the real project surface and must be treated with the
same expectations of:

- cleanliness;
- consistency;
- intentional structure;
- semantic honesty;
- long-term maintainability.

---

## 3. What The Redesign Must Remove

The redesign should aggressively reduce or eliminate the following classes of
code debt.

### 3.1 Historical naming lies

Examples:

- names that describe old mechanisms instead of current meaning;
- names that encode service convenience instead of canonical semantics;
- names that keep obsolete architecture alive mentally.

### 3.2 Convenience-driven shared structures

The shared architecture must not stay warped around what one current service
finds convenient.

This applies especially to:

- wide current tables;
- convenience projections stored by default;
- shared structures that are really private-compute artifacts.

### 3.3 Mixed conceptual layers

The redesign must remove places where:

- core concerns and protocol concerns are interleaved;
- relation-engine details and public-surface semantics are blurred;
- service-private workflow and canonical domain logic are mixed together.

### 3.4 Unnecessary duplication

This includes:

- duplicated query logic;
- duplicated config semantics;
- repeated ad hoc branching across services;
- repeated representations of the same concept at different layers without a
  good reason.

### 3.5 Unclear extension seams

The redesign should leave:

- clearer deployment seams;
- clearer protocol-adapter seams;
- clearer NIP capability seams;
- clearer read-resource seams.

### 3.6 “Green but ugly” code

A slice is not acceptable merely because:

- tests pass;
- mypy passes;
- lint passes.

If the code remains clearly clumsy, misleading, or overly complex after the
slice, the work is not done.

### 3.7 Under-documented or awkward public surfaces

The redesign should also eliminate public-library weaknesses such as:

- import surfaces that are harder to use than they should be;
- APIs that are technically available but not well explained;
- package/module docs that lag behind the actual intended usage;
- public entry points whose ergonomics are weaker than the implementation
  quality deserves.

### 3.8 Stale or fragmented repository documentation

The redesign should also eliminate:

- stale `docs/` pages that describe old architecture;
- duplicated explanations that drift apart;
- repository files that no longer match the system shape;
- contributor/operator documentation that forces readers to reverse-engineer
  the truth from code.

---

## 4. Quality Ratchet Rule

The redesign should apply a strict quality ratchet:

> whenever a part of the codebase is touched meaningfully, it should come out
> better than it was before, not merely behaviorally changed.

“Better” means at least one of:

- cleaner naming;
- clearer boundary;
- less duplication;
- lower accidental complexity;
- stronger boundedness;
- better tests;
- better documentation of the touched public surface;
- better documentation of the touched repository surface;
- more usable and coherent public API shape;
- more honest config or type shape;
- more coherent public contract.

This does **not** justify unrelated cleanup churn.
It does mean that redesign work must not preserve avoidable ugliness merely
because it already existed.

---

## 5. Definition Of Done For A Work Package

A work package is done only if all of the following are true.

### 5.1 Behavior is correct

- target behavior exists;
- regressions are addressed;
- tests prove the intended behavior.

### 5.2 Architecture is improved or at least cleaner

- the slice moved the code toward the target architecture;
- no new conceptual debt was introduced;
- no wrong-layer workaround was left in place without explicit reason.

### 5.3 Code quality is visibly better

- naming is at least not worse and preferably better;
- complexity is controlled;
- the implementation is slimmer or clearer than the old path;
- no dead temporary scaffolding remains.

### 5.4 Operational discipline is preserved

- boundedness assumptions still hold;
- failure boundaries are still sound;
- runtime behavior remains safe under scale assumptions.

### 5.5 Proof is present

- targeted tests exist or were updated meaningfully;
- full repository verification passes;
- the audit loop did not leave unresolved red flags behind.

### 5.6 Public-library quality is not degraded

When a slice touches `src/` surfaces that behave as library APIs, it must also
leave them in a better or at least not worse public state.

That includes:

- import ergonomics;
- public naming quality;
- module or package documentation where needed;
- API discoverability;
- consistency between code reality and documented usage.

### 5.7 Repository documentation quality is not degraded

When a slice touches repository documentation surfaces, they must come out in a
better state as well.

That includes:

- local folder `README.md` files where the slice changes local meaning;
- `AGENTS.md` and repository guidance files where the slice changes what they
  are supposed to teach;
- better alignment with the real system;
- clearer structure;
- removal of stale explanations;
- stronger consistency with code, config, and tests.

If any of those are false, the work package is not complete.

---

## 6. Definition Of Done For The Whole Redesign

The redesign is complete only when all of the following are true together.

### 6.1 Final architecture is in place

The target architecture exists in code, config, SQL, and deployments.

### 6.2 Old architectural lies are removed

The codebase no longer fundamentally thinks in the old misleading concepts.

### 6.3 The codebase is uniformly professional

The repository should no longer feel like:

- a mixture of old and new architecture;
- a set of clever but uneven local solutions;
- a codebase where some zones are excellent and others are merely tolerated.

It should feel consistently designed.

### 6.4 The repository is easier to extend

Adding a new deployment, protocol adapter, storage profile, or capability
should be cleaner than before.

### 6.5 The repository is easier to trust

It should be materially easier for a future maintainer to answer:

- what this layer is for;
- what this module owns;
- what this config means;
- what this table is supposed to represent;
- what is canonical and what is derived.

### 6.6 The package is easier to use as a Python library

After the redesign, `src/` should be easier to consume as a library than it is
today.

That means:

- cleaner public API shapes;
- better package/module documentation;
- more coherent service/config entry points;
- less guesswork for external or future internal consumers.

### 6.7 The repository is better documented end-to-end

After the redesign, the documentation should no longer feel like a mixture of:

- old project story;
- partial updates;
- scattered tribal knowledge.

It should feel deliberately rewritten around the final project shape.

### 6.8 The whole repository is uniformly excellent

After the redesign, there should no longer be an implicit split between:

- “important code” that gets high standards;
- and “secondary repo files” that are merely tolerated.

The final target is one repository-wide quality level across code, tests,
tools, deployments, docs, workflows, and operational files.

---

## 7. Current Baseline Assessment

The current codebase is **not** low quality.
It already contains a lot of serious, disciplined work.

But it is not yet uniformly at the final target level either.

The most important current gap is not sloppy code in the narrow sense.
The most important gap is:

- uneven semantic cleanliness;
- architectural drift from older concepts;
- mixed levels of abstraction;
- parts of the repository that are technically solid but not yet in their
  cleanest final form.

So the redesign should be read as:

- architectural completion;
- and codebase refinement to a uniformly excellent standard.

---

## 8. Final Rule

The redesign must be executed with this rule in mind:

> do not stop when the project merely works in its new shape;
> stop only when the project also looks and feels like the best version of
> itself in code.

This file should be read together with:

- `16_operational_implementation_plan.md`
- `17_integral_codebase_validation.md`
- `99_definitive_master_plan.md`
