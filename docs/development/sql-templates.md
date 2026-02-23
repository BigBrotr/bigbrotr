# SQL Templates

How the SQL template system generates deployment-specific database initialization files
from shared Jinja2 templates.

---

## Overview

BigBrotr uses Jinja2 templates to generate PostgreSQL init scripts for each deployment
variant (bigbrotr, lilbrotr, _template). A base set of templates defines the complete
schema; each deployment overrides specific Jinja2 blocks to customize its database
without duplicating the shared structure.

---

## Directory Layout

```text
tools/
+-- generate_sql.py              # Generator script
+-- templates/sql/
    +-- base/                    # 10 base templates (complete schema)
    +-- bigbrotr/                # Override templates (empty: uses base for all)
    +-- lilbrotr/                # Override templates (lightweight event table)
    +-- _template/               # Override templates (customization guide)

deployments/
+-- bigbrotr/postgres/init/      # 10 generated SQL files (DO NOT EDIT DIRECTLY)
+-- lilbrotr/postgres/init/      # 7 generated SQL files
+-- _template/postgres/init/     # 7 generated SQL files
```

!!! warning
    Never edit the `.sql` files in `deployments/*/postgres/init/` directly. They are
    generated from templates. Edit the Jinja2 templates in `tools/templates/sql/` instead.

---

## Base Templates

The 10 base templates define the full BigBrotr schema:

| Template | Purpose |
|----------|---------|
| `00_extensions.sql.j2` | PostgreSQL extensions (btree_gin, pg_stat_statements) |
| `01_functions_utility.sql.j2` | Utility function: `tags_to_tagvalues()` |
| `02_tables.sql.j2` | Core tables: relay, event, event_relay, metadata, relay_metadata, service_state |
| `03_functions_crud.sql.j2` | 10 CRUD functions (inserts, upserts, cascade operations) |
| `04_functions_cleanup.sql.j2` | 3 cleanup functions (orphan deletion, retention) |
| `05_views.sql.j2` | Regular views (placeholder for future use) |
| `06_materialized_views.sql.j2` | 7 materialized views for analytics |
| `07_functions_refresh.sql.j2` | 8 refresh functions for materialized views |
| `08_indexes.sql.j2` | Performance indexes for tables and materialized views |
| `99_verify.sql.j2` | Post-init verification script (schema summary) |

---

## Override Mechanism

### Jinja2 Block Inheritance

Base templates define named blocks. Deployment-specific templates extend the base
and override only the blocks they need to customize:

```jinja2
{# lilbrotr/02_tables.sql.j2 #}
{% extends "base/02_tables.sql.j2" %}

{% block header_comment %}
 * LilBrotr - 02_tables.sql
 * Lightweight schema: events store only essential fields.
{% endblock %}

{% block events_table %}
CREATE TABLE IF NOT EXISTS event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tagvalues TEXT []
);
{% endblock %}
```

Blocks not overridden are inherited from the base template unchanged.

### Skip and Rename

The `OVERRIDES` dict in `generate_sql.py` controls per-deployment behavior:

- **Skip**: Set to `None` to exclude a template entirely (e.g., lilbrotr skips
  materialized views and refresh functions)
- **Rename**: Set to a different stem to change the output filename (e.g., `_template`
  outputs base `08_indexes` as `05_indexes.sql`)

---

## Commands

```bash
# Regenerate all SQL files from templates
make sql-generate

# Verify generated files match templates (used in CI)
make sql-check
```

`make sql-check` detects three types of drift:

- **MISSING**: A template produces a file that doesn't exist on disk
- **MISMATCH**: A generated file differs from what the template produces
- **ORPHAN**: A `.sql` file exists in `deployments/*/postgres/init/` that no template produces

---

## Adding a New SQL File

1. Create `tools/templates/sql/base/NN_name.sql.j2` with Jinja2 blocks for customization
2. Add `"NN_name"` to `BASE_TEMPLATES` in `tools/generate_sql.py`
3. If any deployment needs to skip or rename it, add an entry to `OVERRIDES`
4. Create override templates in `tools/templates/sql/{deployment}/` as needed
5. Run `make sql-generate` to generate the new files
6. Run `make sql-check` to verify
7. Commit both the template and the generated `.sql` files

## Modifying an Existing Template

1. Edit the base or override template in `tools/templates/sql/`
2. Run `make sql-generate` to regenerate
3. Review the generated SQL diff with `git diff deployments/`
4. Run `make sql-check` to verify consistency
5. Commit both template changes and regenerated files

## Adding a New Deployment

1. Add an entry to `OVERRIDES` in `tools/generate_sql.py` with only the deltas from base
2. Create a directory `tools/templates/sql/{deployment}/`
3. Add override templates for any blocks that need customization
4. Run `make sql-generate`
5. Create the deployment directory structure: `deployments/{deployment}/`

---

## Related Documentation

- [Setup](setup.md) -- Makefile targets including `sql-generate` and `sql-check`
- [Coding Standards](coding-standards.md) -- SQL formatting conventions
