# Contributing to BigBrotr

Guidelines for contributing to BigBrotr with the same standards the project
expects from its own codebase and documentation.

---

## Code of Conduct

This project adheres to the
[Contributor Covenant Code of Conduct](https://github.com/BigBrotr/bigbrotr/blob/main/.github/CODE_OF_CONDUCT.md).
By participating, you are expected to uphold this code.

---

## Working Standards

BigBrotr expects a high bar from every contribution:

- understand the current code before changing it;
- keep each change narrow, coherent, and reviewable;
- prefer honest naming and clean boundaries over compatibility drift;
- update tests and documentation as part of the same slice;
- do not merge a slice that is merely "green enough".

In practice that means:

- no half-implemented behavior;
- no stale docs left behind after code changes;
- no SQL changes without template alignment;
- no public API changes without library/documentation review.

---

## Development Setup

### Prerequisites

- Python 3.11 or higher
- Git
- Docker and Docker Compose for integration tests and local deployments

### Quick Start

```bash
# Clone the repository
git clone https://github.com/BigBrotr/bigbrotr.git
cd bigbrotr

# Install uv (one-time)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install development + docs dependencies and pre-commit hooks
make install

# Verify the checkout
make ci
uv lock --check
```

If you plan to work on the documentation site, also run:

```bash
make docs
```

---

## Before You Start Coding

### Read the canonical guidance

BigBrotr keeps living documentation in `docs/` and local automation guidance in
`AGENTS.md` files.

Before editing a package or major directory, read the relevant:

- `AGENTS.md`
- canonical docs page that explains the local contract
- nearby code and tests that prove the behavior

This is especially important for:

- `src/bigbrotr/services/`
- `src/bigbrotr/core/`
- `src/bigbrotr/models/`
- `tools/`
- `deployments/`
- `tests/`
- `docs/`

### Understand the actual surface you are changing

Before editing:

- identify which configs, tests, docs, or SQL templates the change affects;
- verify whether the repo already has a utility or pattern for that problem;
- make sure the intended delta is narrow and explicit.

---

## Branching and Commit Discipline

Create branches from `develop` with a descriptive prefix:

```bash
git checkout develop
git pull origin develop
git checkout -b <type>/<description>
```

Examples:

```text
feat/add-score-resource
fix/refresher-watermark-lag
refactor/read-core-pagination
docs/rewrite-operator-guides
test/add-ranker-restore-coverage
chore/update-dependencies
```

Follow [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use case |
|--------|----------|
| `feat:` | New behavior or surface |
| `fix:` | Bug fix |
| `refactor:` | Structural improvement without behavior change |
| `docs:` | Documentation-only changes |
| `test:` | Test-only changes |
| `chore:` | Tooling, dependency, or maintenance work |

Good commit messages explain **why the slice exists**, not just what files
changed.

---

## Quality Gates

### Minimum final gate before a commit

Every contribution should end with:

```bash
make ci
uv lock --check
```

### Additional gates when relevant

If you touched generated SQL or deployment SQL packages:

```bash
python tools/generate_sql.py --check
```

If you touched repository or site documentation:

```bash
make docs
```

If you changed integration-heavy runtime behavior, run the most relevant
integration tests in addition to the default CI gate.

### Focused validation first

Before the full gate, run the narrowest useful checks for your slice:

- affected unit tests;
- service-local tests;
- focused lint/typecheck when iterating on one subsystem;
- docs or SQL checks when those are the primary surface.

This keeps feedback fast without weakening the final gate.

---

## Documentation Responsibilities

Documentation is part of the contribution, not follow-up cleanup.

Update documentation when you change:

- public APIs or import surfaces;
- service ownership or operational behavior;
- configuration fields or defaults;
- deployment workflows;
- database schema or SQL-template behavior;
- contributor expectations;
- project surfaces that now need different documentation.

That includes, when relevant:

- `docs/` pages;
- root-level docs like `README.md` and `CONTRIBUTING.md`;
- local `AGENTS.md` files that describe maintained contracts.

---

## Pull Requests

### Before submitting

Make sure the branch is:

- based on `develop`;
- scoped to one coherent slice or feature set;
- fully green locally;
- documented honestly.

Recommended checklist:

- [ ] Focused tests for the touched area pass
- [ ] `make ci` passes
- [ ] `uv lock --check` passes
- [ ] `make docs` passes if docs changed
- [ ] `python tools/generate_sql.py --check` passes if SQL/deployment packages changed
- [ ] Documentation and local guidance are updated where needed
- [ ] `CHANGELOG.md` is updated for shipped user-visible changes

### Submitting

1. Push your branch to your fork or remote.
2. Open a Pull Request targeting `develop`.
3. Explain the architectural intent of the change, not just the file list.
4. Call out any operational risks, migration notes, or follow-ups explicitly.
5. Address review findings before merging.

---

## Questions and Coordination

- Open a [Discussion](https://github.com/BigBrotr/bigbrotr/discussions) for design or usage questions.
- Open an [Issue](https://github.com/BigBrotr/bigbrotr/issues) for bugs or feature requests.
- Check existing issues and discussions before creating new ones.

When in doubt, prefer asking a focused architecture or workflow question over
guessing and creating drift.
