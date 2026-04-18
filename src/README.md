# src

Tracked Python package source for BigBrotr.

## What Lives Here

- `bigbrotr/`: the actual shipped Python package.
- `bigbrotr.egg-info/`: generated packaging metadata that may appear locally but
  is not a design surface.

## Rules

- Code under `src/bigbrotr/` is both application runtime and Python library
  surface.
- Generated or cache folders are explicit exceptions and do not need their own
  README files.
