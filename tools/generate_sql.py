#!/usr/bin/env python3
"""Generate SQL init files from Jinja2 templates.

Usage:
    python generate_sql.py              # Generate SQL files
    python generate_sql.py --check      # Verify generated matches existing
"""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_DIR = ROOT / "tools" / "templates" / "sql"

# Base templates rendered by every implementation unless overridden.
# Order matches the execution order in PostgreSQL init (00, 01, ..., 99).
BASE_TEMPLATES: list[str] = [
    "00_extensions",
    "01_functions_utility",
    "02_tables",
    "03_functions_crud",
    "04_functions_cleanup",
    "05_views",
    "06_materialized_views",
    "07_functions_refresh",
    "08_indexes",
    "99_verify",
]

# Per-implementation overrides. Only deviations from the base set are listed.
#   - None  = skip this template entirely
#   - str   = rename the output file (e.g., base 08_indexes -> output 05_indexes)
# Entries not listed inherit the base template name as the output filename.
OVERRIDES: dict[str, dict[str, str | None]] = {
    "bigbrotr": {},
    "lilbrotr": {
        "05_views": None,
        "06_materialized_views": None,
        "07_functions_refresh": None,
        "08_indexes": "05_indexes",
    },
    "_template": {
        "05_views": None,
        "06_materialized_views": None,
        "07_functions_refresh": None,
        "08_indexes": "05_indexes",
    },
}


def _resolve_file_map(impl_name: str) -> dict[str, str]:
    """Resolve effective {base_template: output_filename} mapping."""
    overrides = OVERRIDES[impl_name]
    result: dict[str, str] = {}
    for stem in BASE_TEMPLATES:
        if stem in overrides:
            out = overrides[stem]
            if out is None:
                continue
            result[f"{stem}.sql.j2"] = f"{out}.sql"
        else:
            result[f"{stem}.sql.j2"] = f"{stem}.sql"
    return result


def generate() -> dict[str, str]:
    """Generate all SQL files, return {relative_path: content} dict."""
    env = Environment(  # noqa: S701 -- SQL templates, not HTML; autoescape N/A
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    output: dict[str, str] = {}

    for impl_name in OVERRIDES:
        file_map = _resolve_file_map(impl_name)
        for base_name, out_name in file_map.items():
            # Check for implementation-specific override template
            impl_template = f"{impl_name}/{out_name}.j2"
            impl_template_path = TEMPLATE_DIR / impl_name / f"{out_name}.j2"

            template_path = impl_template if impl_template_path.exists() else f"base/{base_name}"

            rendered = env.get_template(template_path).render()

            rel_path = f"deployments/{impl_name}/postgres/init/{out_name}"
            output[rel_path] = rendered

    return output


def _print_first_diff(existing_content: str, generated_content: str) -> None:
    """Print the first line that differs between two strings."""
    existing_lines = existing_content.splitlines(keepends=True)
    generated_lines = generated_content.splitlines(keepends=True)
    for i, (el, gl) in enumerate(zip(existing_lines, generated_lines, strict=False), start=1):
        if el != gl:
            print(f"  First diff at line {i}:")
            print(f"    existing:  {el.rstrip()!r}")
            print(f"    generated: {gl.rstrip()!r}")
            return
    len_e, len_g = len(existing_lines), len(generated_lines)
    if len_e != len_g:
        print(f"  Line count differs: existing={len_e}, generated={len_g}")


def _check(generated: dict[str, str]) -> None:
    """Verify generated SQL matches files on disk. Exit 1 on drift."""
    mismatches: list[str] = []

    for rel_path, content in sorted(generated.items()):
        existing = ROOT / rel_path
        if not existing.exists():
            mismatches.append(f"MISSING: {rel_path}")
            continue
        existing_content = existing.read_text()
        if existing_content != content:
            mismatches.append(f"MISMATCH: {rel_path}")
            _print_first_diff(existing_content, content)

    # Detect orphaned SQL files not produced by templates
    for impl_name in OVERRIDES:
        init_dir = ROOT / "deployments" / impl_name / "postgres" / "init"
        if not init_dir.exists():
            continue
        for sql_file in sorted(init_dir.glob("*.sql")):
            rel = f"deployments/{impl_name}/postgres/init/{sql_file.name}"
            if rel not in generated:
                mismatches.append(f"ORPHAN: {rel}")

    if mismatches:
        print("SQL drift detected:")
        for m in mismatches:
            print(f"  {m}")
        sys.exit(1)
    print(f"OK: {len(generated)} files match their templates")


def _write(generated: dict[str, str]) -> None:
    """Write generated SQL files to disk."""
    for rel_path, content in sorted(generated.items()):
        out = ROOT / rel_path
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content)
        print(f"  Generated: {rel_path}")
    print(f"\nGenerated {len(generated)} SQL files")


def main() -> None:
    generated = generate()
    if "--check" in sys.argv:
        _check(generated)
    else:
        _write(generated)


if __name__ == "__main__":
    main()
