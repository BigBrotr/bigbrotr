# `bigbrotr/dumps`

Operator-managed output directory for backup artifacts in the `bigbrotr`
deployment.

## What Lives Here

- Compressed PostgreSQL dumps written by `backup.sh`.
- Optional backup logs or rotated artifacts kept local to the deployment.
- `.gitkeep`: keeps the empty directory tracked until the first local dump is
  created.

## Rules

- Treat backup outputs here as local operational artifacts, not repository
  inputs.
- Rotate, offload, or symlink this directory according to the backup guidance
  in `docs/how-to/backup-restore.md` and `docs/guides/self-hosting.md`.
