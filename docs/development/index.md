# Development

Resources for setting up, testing, and contributing to the BigBrotr project.

---

<div class="grid cards" markdown>

-   :material-laptop:{ .lg .middle } **[Setup](setup.md)**

    ---

    Prerequisites, installation, IDE configuration, project structure, and Makefile targets.

-   :material-test-tube:{ .lg .middle } **[Testing](testing.md)**

    ---

    Test configuration, running tests, shared fixtures, mock patterns, async patterns, and coverage requirements.

-   :material-format-list-checks:{ .lg .middle } **[Coding Standards](coding-standards.md)**

    ---

    Ruff linting, mypy strict mode, pre-commit hooks, import conventions, and documentation standards.

-   :material-database-cog:{ .lg .middle } **[SQL Templates](sql-templates.md)**

    ---

    Jinja2 template system for generating deployment-specific database initialization files.

-   :material-source-pull:{ .lg .middle } **[Contributing](contributing.md)**

    ---

    Code of conduct, branch and commit conventions, and pull request process.

</div>

!!! note "Quick verification"
    After completing the [setup](setup.md), verify everything works:

    ```bash
    make ci
    ```
