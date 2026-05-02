#!/usr/bin/env python3
"""Generate deployment SQL init files from storage-profile-backed templates.

Usage:
    python generate_sql.py              # Generate SQL files
    python generate_sql.py --check      # Verify generated matches existing
"""

from __future__ import annotations

import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from bigbrotr.core.deployments import (  # noqa: E402
    BUILTIN_DEPLOYMENT_PROFILES,
    builtin_deployment_spec,
    storage_profile_spec,
)


TEMPLATE_DIR = ROOT / "tools" / "templates" / "sql"

# Base templates rendered by every implementation unless overridden.
# Order matches the execution order in PostgreSQL init (00, 01, ..., 99).
BASE_TEMPLATES: list[str] = [
    "00_extensions",
    "01_functions_utility",
    "02_tables_core",
    "03_tables_current",
    "04_tables_analytics",
    "05_functions_crud",
    "06_functions_cleanup",
    "07_views_reporting",
    "08_functions_refresh_current",
    "09_functions_refresh_analytics",
    "10_indexes_core",
    "11_indexes_current",
    "12_indexes_analytics",
    "99_verify",
]

# Deployment init packages to generate. Each entry maps to one built-in
# deployment folder under ``deployments/<name>/``.
GENERATED_DEPLOYMENTS: tuple[str, ...] = BUILTIN_DEPLOYMENT_PROFILES

# Optional deployment-local output overrides: None = skip template,
# str = rename output file. Keep this deployment-scoped so new deployments can
# still vary output shape even when they share the same storage profile.
OUTPUT_OVERRIDES: dict[str, dict[str, str | None]] = {
    deployment_name: {} for deployment_name in GENERATED_DEPLOYMENTS
}


def _resolve_file_map(deployment_name: str) -> dict[str, str]:
    """Resolve effective {base_template: output_filename} mapping."""
    overrides = OUTPUT_OVERRIDES[deployment_name]
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


def _resolve_template_path(deployment_name: str, base_name: str, out_name: str) -> str:
    """Resolve the Jinja template path for one generated SQL output file."""
    profile = storage_profile_spec(builtin_deployment_spec(deployment_name).storage_profile)
    if profile.sql_template_namespace is not None:
        profile_template = f"{profile.sql_template_namespace}/{out_name}.j2"
        profile_template_path = TEMPLATE_DIR / profile.sql_template_namespace / f"{out_name}.j2"
        if profile_template_path.exists():
            return profile_template
    return f"base/{base_name}"


def generate() -> dict[str, str]:
    """Generate all SQL files, return {relative_path: content} dict."""
    env = Environment(  # noqa: S701 -- SQL templates, not HTML; autoescape N/A
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    output: dict[str, str] = {}

    for deployment_name in GENERATED_DEPLOYMENTS:
        file_map = _resolve_file_map(deployment_name)
        for base_name, out_name in file_map.items():
            template_path = _resolve_template_path(deployment_name, base_name, out_name)
            rendered = env.get_template(template_path).render()

            rel_path = f"deployments/{deployment_name}/postgres/init/{out_name}"
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
    for deployment_name in GENERATED_DEPLOYMENTS:
        init_dir = ROOT / "deployments" / deployment_name / "postgres" / "init"
        if not init_dir.exists():
            continue
        for sql_file in sorted(init_dir.glob("*.sql")):
            rel = f"deployments/{deployment_name}/postgres/init/{sql_file.name}"
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
