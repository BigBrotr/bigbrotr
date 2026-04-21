# how-to

Step-by-step operational and extension procedures shipped in the public docs.

## What Lives Here

- `index.md`: landing page for procedural operator material.
- `docker-deploy.md` and `manual-deploy.md`: primary deployment procedures.
- `custom-deployment.md`: built-in deployment cloning and adaptation flow.
- `monitoring-setup.md`: Prometheus, Grafana, and alert routing setup.
- `backup-restore.md`: backup and restore procedures.
- `tor-relays.md`: Tor and overlay-network guidance.
- `new-service.md`: adding a new service without breaking architecture rules.
- `troubleshooting.md`: common recovery and debugging paths.

## Rules

- Keep each page action-oriented and scoped to one operator task.
- Move broader narrative guidance to `docs/guides/` instead of overloading
  the procedural section.
