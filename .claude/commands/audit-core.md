---
description: Run a comprehensive 11-skill parallel audit of BigBrotr
argument-hint: "[scope]"
---

# Core Audit

**Arguments:** $ARGUMENTS

---

## Skills (11)

### Code Quality (4)

| Skill | Prefix | Focus |
|-------|--------|-------|
| bigbrotr-expert | BB | Service patterns, Brotr API, diamond DAG |
| code-reviewer | CR | Code quality, SOLID principles, code smells |
| python-pro | PP | Async patterns, type hints, Pydantic, mypy |
| architecture-designer | AD | Architecture patterns, service boundaries |

### Database (2)

| Skill | Prefix | Focus |
|-------|--------|-------|
| postgres-pro | PG | PostgreSQL schema, indexes, stored procedures |
| database-optimizer | DO | Query performance, materialized views |

### Security & Testing (2)

| Skill | Prefix | Focus |
|-------|--------|-------|
| security-reviewer | SR | SQL injection, secrets, auth, WebSocket security |
| test-master | TM | Test coverage, missing tests, CI workflow |

### Operations & Protocol (3)

| Skill | Prefix | Focus |
|-------|--------|-------|
| nostr-expert | NE | NIP compliance, nostr-sdk usage |
| debugging-wizard | DW | Potential bugs, race conditions, error handling |
| monitoring-expert | ME | Logging, metrics, observability gaps |

---

## Phase 0: Setup

1. Read the shared audit schema from `.claude/skills/bigbrotr-expert/references/audit-schema.md`
2. Parse `$ARGUMENTS` for optional scope filter:
   - `(none)` — audit entire codebase
   - `services` — focus on `src/bigbrotr/services/`
   - `models` — focus on `src/bigbrotr/models/`
   - `core` — focus on `src/bigbrotr/core/`
   - `sql` — focus on `deployments/*/postgres/init/`

---

## Phase 1: Execution

Spawn **11 Task agents in a single message** (parallel).

For EACH skill, use `subagent_type` matching the skill name and the prompt template from audit-schema.md, filling in:
- `{domain}` — the skill's Focus from the tables above
- `{skill-name}` — the skill directory name
- `{PREFIX}` — the 2-letter prefix from the tables above

If a scope filter was provided, add it to each prompt to narrow the analysis.

---

## Phase 2: Post-Execution

Follow the post-execution workflow from audit-schema.md:

1. **Collect** — Gather JSON arrays from all 11 skills
2. **Merge** — Combine into single array, skip malformed JSON with warning
3. **Deduplicate** — Group by file + overlapping lines, keep best fix, track consensus
4. **Sort** — By severity (critical → low), then category, then file path
5. **Report** — Generate `AUDIT_REPORT.md` and `AUDIT_REPORT.json`
6. **Present** — Show summary with severity/category breakdown and ask which fixes to apply
7. **Apply** — Group approved fixes by file, apply bottom-up, run validation

---

## Output Template

```
## Core Audit Results

| Severity | Count |
|----------|-------|
| Critical | N     |
| High     | N     |
| Medium   | N     |
| Low      | N     |

| Category | Count |
|----------|-------|
| code     | N     |
| security | N     |
| database | N     |
| ...      | N     |

**Total findings:** N | **Skills:** 11 | **Files analyzed:** N

Reports: AUDIT_REPORT.md, AUDIT_REPORT.json

Which fixes would you like to apply? (all / by severity / by category / by skill / specific IDs / skip)
```

---

## Constraints

**MUST:**
- Read audit-schema.md before spawning any agents
- Run all 11 agents in a single message (parallel)
- Track consensus (findings reported by multiple skills)
- Deduplicate before presenting results

**MUST NOT:**
- Apply fixes without user approval
- Skip the deduplication step
