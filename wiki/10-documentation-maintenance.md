# Documentation Maintenance

## Documentation Surfaces

| Surface | Audience | Notes |
| --- | --- | --- |
| `README.md` | First-time project readers | High-level overview and quick start. |
| `docs/` | Public MkDocs site | User guide, how-to guides, development, generated Python reference. |
| `wiki/` | Internal orientation | Code-first map for maintainers. |
| Local `README.md` files | Package/folder navigation | Should describe local ownership and rules. |

## Generated Python Reference

`docs/gen_ref_pages.py` generates reference pages under `reference/` at build
time. The MkDocs nav should make this explicit as the Python API reference.

The generated pages only reflect modules present in the active checkout. If a
branch lacks a service module, that service will not appear in generated
Python reference output.

## Drift Prevention

When changing a runtime service:

1. update service source and tests;
2. update deployment config examples;
3. update user-guide service/config docs;
4. update monitoring docs if metrics or alerts changed;
5. update this wiki if ownership, flow, or data contracts changed.

When changing schema:

1. update SQL templates;
2. regenerate deployment SQL;
3. update database docs;
4. update read models and service queries;
5. update integration tests.

When changing public read behavior:

1. update read model registry;
2. update API/DVM docs together;
3. verify pagination/filter/sort/error behavior;
4. check DVM response size and public exposure.

## Naming Rules

Use current branch terminology:

| Current | Avoid in current docs unless discussing history |
| --- | --- |
| `event_observation` | `event_relay` |
| `document` | `metadata` |
| `relay_document` | `relay_metadata` |
| `owner` in `service_state` | `service_name` for the database column |
| public scores | rank snapshots when referring to exported public tables |

## Documentation Checks

Run:

```bash
uv run mkdocs build --strict
uv run pre-commit run markdownlint --files README.md $(find docs wiki -name '*.md' -print)
uv run pre-commit run codespell --files README.md mkdocs.yml $(find docs wiki -type f -print)
```

Then inspect the rendered Python API reference and service pages in a browser
if navigation changed.
