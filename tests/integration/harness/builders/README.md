# integration/harness/builders

Canonical domain builders for integration tests.

## What Lives Here

- relay, event, document, and junction builders;
- service-state builders for restart/checkpoint seams;
- shared identifier helpers such as canonical event-address construction.

## Rules

- keep builder names aligned with domain nouns;
- centralize reused record construction here instead of duplicating helpers in
  unrelated integration files;
- do not hide assertions or side effects inside builders.
