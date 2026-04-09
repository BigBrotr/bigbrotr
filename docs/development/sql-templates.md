# SQL Templates

How the SQL template system generates deployment-specific database initialization files
from shared Jinja2 templates.

---

## Overview

BigBrotr uses Jinja2 templates to generate PostgreSQL init scripts for each deployment
variant (bigbrotr, lilbrotr). A base set of templates defines the shared schema; each
deployment can extend the base via Jinja2 block overrides to customize
deployment-specific objects without duplicating the shared structure.

---

## Directory Layout

```text
tools/
+-- generate_sql.py              # Generator script
+-- templates/sql/
    +-- base/                    # Base templates (shared schema)
    +-- lilbrotr/                # Override templates (lightweight event table)

deployments/
+-- bigbrotr/postgres/init/      # Generated SQL files (DO NOT EDIT DIRECTLY)
+-- lilbrotr/postgres/init/      # Generated SQL files
```

!!! warning
    Never edit the `.sql` files in `deployments/*/postgres/init/` directly. They are
    generated from templates. Edit the Jinja2 templates in `tools/templates/sql/` instead.

---

## Base Templates

The base templates define the Brotr schema shared by all deployments:

| Template | Purpose |
|----------|---------|
| `00_extensions.sql.j2` | PostgreSQL extensions (btree_gin, pg_stat_statements) |
| `01_functions_utility.sql.j2` | Tag and event-address utility functions |
| `02_tables_core.sql.j2` | Core tables: relay, event, event_relay, metadata, relay_metadata, service_state |
| `03_tables_current.sql.j2` | Current-state tables |
| `04_tables_analytics.sql.j2` | Analytics and NIP-85 rank tables |
| `05_functions_crud.sql.j2` | CRUD, cascade, and service-state functions |
| `06_functions_cleanup.sql.j2` | Cleanup functions (orphan metadata + orphan event deletion) |
| `07_views_reporting.sql.j2` | Reporting views |
| `08_functions_refresh_current.sql.j2` | Current-state refresh functions |
| `09_functions_refresh_analytics.sql.j2` | Analytics, contact-graph, and periodic refresh functions |
| `10_indexes_core.sql.j2` | Core table indexes |
| `11_indexes_current.sql.j2` | Current-state indexes |
| `12_indexes_analytics.sql.j2` | Analytics and rank indexes |
| `99_verify.sql.j2` | Post-init verification script (schema summary) |

---

## Override Mechanism

### Jinja2 Block Inheritance

Base templates define named blocks with `extra_*` extension points. Deployment-specific
templates extend the base and override only the blocks they need to customize:

```jinja2
{# lilbrotr/02_tables.sql.j2 -- only overrides events_table block #}
{% extends "base/02_tables.sql.j2" %}
{% block events_table %}
CREATE TABLE IF NOT EXISTS event (
    id BYTEA PRIMARY KEY,
    pubkey BYTEA NOT NULL,
    created_at BIGINT NOT NULL,
    kind INTEGER NOT NULL,
    tags JSONB,
    tagvalues TEXT [] NOT NULL,
    content TEXT,
    sig BYTEA
);
{% endblock %}
```

Blocks not overridden are inherited from the base template unchanged.

### Extension Points

Base templates expose focused override blocks. LilBrotr currently overrides only
the lightweight event table, event insertion behavior, and deployment-specific
verification text; the rest of the current-state, analytics/rank, refresh, and
index schema is inherited from base templates:

| Block | Defined in | Content |
|-------|------------|---------|
| `extra_extensions` | `00_extensions` | Optional deployment-specific extensions |
| `events_table` | `02_tables_core` | Event table shape |
| `relay_metadata_check_types_comment` | `02_tables_core` | Deployment-specific relay metadata comments |
| `events_insert_body` | `05_functions_crud` | Event insert behavior |
| `events_insert_description` | `05_functions_crud` | Event insert documentation |
| `service_data_functions` | `05_functions_crud` | Service-state helper functions |
| `verify_body` | `99_verify` | Deployment verification output |

All deployments generate the same SQL file set. The `OVERRIDES` dict in
`generate_sql.py` is empty for all deployments (no skip, no rename).

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
3. Create override templates in `tools/templates/sql/{deployment}/` as needed
4. Run `make sql-generate` to generate the new files
5. Run `make sql-check` to verify
6. Commit both the template and the generated `.sql` files

## Modifying an Existing Template

1. Edit the base or override template in `tools/templates/sql/`
2. Run `make sql-generate` to regenerate
3. Review the generated SQL diff with `git diff deployments/`
4. Run `make sql-check` to verify consistency
5. Commit both template changes and regenerated files

## Adding a New Deployment

1. Add an entry to `OVERRIDES` in `tools/generate_sql.py`
2. Create a directory `tools/templates/sql/{deployment}/` (only if overrides are needed)
3. Add override templates for any blocks that need customization
4. Run `make sql-generate`
5. Create the deployment directory structure: `deployments/{deployment}/`

---

## Related Documentation

- [Setup](setup.md) -- Makefile targets including `sql-generate` and `sql-check`
- [Coding Standards](coding-standards.md) -- SQL formatting conventions
