# `tests/system/resilience/concurrency`

Repeated overlap drills for the higher-band composed stacks.

## What Lives Here

- concurrent `bigbrotr` / `lilbrotr` stack coexistence proof;
- repeated overlap rounds that exercise deterministic runtime addressing;
- and teardown checks that rule out hidden Docker resource drift after both
  profiles have been alive at the same time.
