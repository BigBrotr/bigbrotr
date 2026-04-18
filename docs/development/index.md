# Development

Resources for setting up, testing, extending, and reviewing the BigBrotr
codebase and repository.

---

<div class="grid cards" markdown>

-   :material-laptop:{ .lg .middle } **[Setup](setup.md)**

    ---

    Prerequisites, installation, IDE configuration, project structure, and
    core verification commands.

-   :material-test-tube:{ .lg .middle } **[Testing](testing.md)**

    ---

    Test configuration, running tests, shared fixtures, mock patterns, async patterns, and coverage requirements.

-   :material-format-list-checks:{ .lg .middle } **[Coding Standards](coding-standards.md)**

    ---

    Ruff linting, mypy strict mode, pre-commit hooks, import conventions, and
    documentation standards.

-   :material-database-cog:{ .lg .middle } **[SQL Templates](sql-templates.md)**

    ---

    Jinja2 template system for generating deployment-specific database initialization files.

-   :material-source-pull:{ .lg .middle } **[Contributing](contributing.md)**

    ---

    Branching, commit discipline, review expectations, and pull request
    process.

</div>

!!! note "Quick verification"
    After completing the [setup](setup.md), verify everything works:

    ```bash
    make ci
    ```
