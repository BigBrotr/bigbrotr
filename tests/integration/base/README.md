# integration/base

Canonical integration tests for the shared BigBrotr contract.

## What Lives Here

- shared-schema CRUD tests;
- derived-table and refresher tests;
- ranker and assertor pipeline tests;
- foreign-key, retention, and transactional behavior tests.

## Rules

- Base integration tests should describe behavior common to all supported
  storage profiles unless a profile-specific difference is intentional.
