"""Generate API reference pages automatically from source code.

This script is executed by mkdocs-gen-files at build time. It walks the
``src/bigbrotr/`` package tree and creates one ``::: module`` page per
Python module, plus a SUMMARY.md for mkdocs-literate-nav navigation.

No manually maintained .md files are needed in ``docs/reference/``.
"""

from pathlib import Path

import mkdocs_gen_files


SRC = Path("src")
PACKAGE = "bigbrotr"
REF_DIR = "reference"

nav = mkdocs_gen_files.Nav()

for path in sorted(SRC.rglob("*.py")):
    # Only process files inside the bigbrotr package
    if PACKAGE not in path.parts:
        continue

    module_path = path.relative_to(SRC).with_suffix("")
    doc_path = path.relative_to(SRC / PACKAGE).with_suffix(".md")
    full_doc_path = Path(REF_DIR) / doc_path

    parts = tuple(module_path.parts)

    # Skip __main__ (CLI entry point, not API)
    if parts[-1] == "__main__":
        continue

    # For __init__.py, the page represents the package itself
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
        doc_path = doc_path.with_name("index.md")
        full_doc_path = full_doc_path.with_name("index.md")

    # Build navigation entry
    nav_parts = parts[1:]  # strip "bigbrotr" prefix for nav display
    if not nav_parts:
        # Top-level package -> section index
        nav_parts = (PACKAGE,)
        doc_path = Path("index.md")
    nav[nav_parts] = doc_path.as_posix()

    # Write the ::: directive page
    python_module = ".".join(parts)
    with mkdocs_gen_files.open(full_doc_path, "w") as fd:
        fd.write(f"::: {python_module}\n")
        if is_package:
            # Package index: show only docstring, members are on their own pages
            fd.write("    options:\n")
            fd.write("      members: false\n")

    # Set the edit path to the actual source file
    mkdocs_gen_files.set_edit_path(full_doc_path, path.relative_to(SRC))

# Write the navigation summary for literate-nav
with mkdocs_gen_files.open(f"{REF_DIR}/SUMMARY.md", "w") as nav_file:
    nav_file.writelines(nav.build_literate_nav())
