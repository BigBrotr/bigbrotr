# `tests/system/resilience/database`

Database and pool failure drills for the higher-band system suite.

## What Lives Here

- startup-failure proof when a service cannot reach the authored pool boundary;
- transient `postgres` plus `pgbouncer` outage drills against long-running services;
- rollback-honesty checks that no partial database side effects leak through a failed cycle;
- and recovery proof that the running service resumes without duplicate drift once the database path is healthy again.
