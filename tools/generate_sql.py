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


ROOT = Path(__file__).resolve().parent
TEMPLATE_DIR = ROOT / "templates" / "sql"

# Implementation name -> {base_template_name: output_filename}
# Maps base template filenames to the output filenames for each implementation.
# When an implementation uses a different output filename (e.g., lilbrotr's
# 05_indexes.sql maps from base 08_indexes.sql.j2), the override template
# handles the mapping via its own filename.
IMPLEMENTATIONS: dict[str, dict[str, str]] = {
    "bigbrotr": {
        "00_extensions.sql.j2": "00_extensions.sql",
        "01_functions_utility.sql.j2": "01_functions_utility.sql",
        "02_tables.sql.j2": "02_tables.sql",
        "03_functions_crud.sql.j2": "03_functions_crud.sql",
        "04_functions_cleanup.sql.j2": "04_functions_cleanup.sql",
        "05_views.sql.j2": "05_views.sql",
        "06_materialized_views.sql.j2": "06_materialized_views.sql",
        "07_functions_refresh.sql.j2": "07_functions_refresh.sql",
        "08_indexes.sql.j2": "08_indexes.sql",
        "99_verify.sql.j2": "99_verify.sql",
    },
    "lilbrotr": {
        "00_extensions.sql.j2": "00_extensions.sql",
        "01_functions_utility.sql.j2": "01_functions_utility.sql",
        "02_tables.sql.j2": "02_tables.sql",
        "03_functions_crud.sql.j2": "03_functions_crud.sql",
        "04_functions_cleanup.sql.j2": "04_functions_cleanup.sql",
        "05_indexes.sql.j2": "05_indexes.sql",
        "06_materialized_views.sql.j2": None,  # Produces empty output, skip
        "07_functions_refresh.sql.j2": None,  # Produces empty output, skip
        "99_verify.sql.j2": "99_verify.sql",
    },
}


def generate() -> dict[str, str]:
    """Generate all SQL files, return {relative_path: content} dict."""
    env = Environment(  # noqa: S701 -- SQL templates, not HTML; autoescape N/A
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    output: dict[str, str] = {}

    for impl_name, file_map in IMPLEMENTATIONS.items():
        for base_name, out_name in file_map.items():
            if out_name is None:
                continue

            # Check for implementation-specific override template
            impl_template = f"{impl_name}/{out_name}.j2"
            impl_template_path = TEMPLATE_DIR / impl_name / f"{out_name}.j2"

            template_path = impl_template if impl_template_path.exists() else f"base/{base_name}"

            rendered = env.get_template(template_path).render()

            # Skip files that render to empty/whitespace-only
            if not rendered.strip():
                continue

            rel_path = f"deployments/{impl_name}/postgres/init/{out_name}"
            output[rel_path] = rendered

    return output


def main() -> None:
    check_mode = "--check" in sys.argv
    generated = generate()

    if check_mode:
        mismatches: list[str] = []
        for rel_path, content in sorted(generated.items()):
            existing = ROOT / rel_path
            if not existing.exists():
                mismatches.append(f"MISSING: {rel_path}")
                continue
            existing_content = existing.read_text()
            if existing_content != content:
                mismatches.append(f"MISMATCH: {rel_path}")
                # Show first difference for debugging
                existing_lines = existing_content.splitlines(keepends=True)
                generated_lines = content.splitlines(keepends=True)
                for i, (el, gl) in enumerate(
                    zip(existing_lines, generated_lines, strict=False), start=1
                ):
                    if el != gl:
                        print(f"  First diff at line {i}:")
                        print(f"    existing:  {el.rstrip()!r}")
                        print(f"    generated: {gl.rstrip()!r}")
                        break
                else:
                    len_e = len(existing_lines)
                    len_g = len(generated_lines)
                    if len_e != len_g:
                        print(f"  Line count differs: existing={len_e}, generated={len_g}")
        if mismatches:
            print("SQL drift detected:")
            for m in mismatches:
                print(f"  {m}")
            sys.exit(1)
        print(f"OK: {len(generated)} files match their templates")
    else:
        for rel_path, content in sorted(generated.items()):
            out = ROOT / rel_path
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(content)
            print(f"  Generated: {rel_path}")
        print(f"\nGenerated {len(generated)} SQL files")


if __name__ == "__main__":
    main()
