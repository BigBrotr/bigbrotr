---
description: Run a complete 22-skill audit of BigBrotr in 3 waves
argument-hint: "[scope]"
---

# Full Audit

**Arguments:** $ARGUMENTS

---

## Skills (22, 3 waves)

### Wave 1: Foundation (8)

| Skill | Prefix | Focus |
|-------|--------|-------|
| bigbrotr-expert | BB | Service patterns, Brotr API, diamond DAG |
| nostr-expert | NE | NIP compliance, nostr-sdk usage |
| python-pro | PP | Async patterns, type hints, Pydantic, mypy |
| code-reviewer | CR | Code quality, SOLID principles, code smells |
| architecture-designer | AD | Architecture patterns, service boundaries |
| security-reviewer | SR | SQL injection, secrets, auth, WebSocket security |
| postgres-pro | PG | PostgreSQL schema, indexes, stored procedures |
| test-master | TM | Test coverage, missing tests, CI workflow |

### Wave 2: Depth Analysis (8)

| Skill | Prefix | Focus |
|-------|--------|-------|
| database-optimizer | DO | Query performance, materialized views |
| debugging-wizard | DW | Potential bugs, race conditions, error handling |
| sql-pro | SP | SQL best practices, query optimization |
| secure-code-guardian | SG | OWASP Top 10, input validation, auth hardening |
| devops-engineer | DE | Docker, CI/CD pipelines, infrastructure |
| sre-engineer | SE | Reliability, SLOs, incident readiness |
| monitoring-expert | ME | Logging, metrics, observability gaps |
| websocket-engineer | WS | WebSocket patterns, connection lifecycle |

### Wave 3: Operations & Maintenance (6)

| Skill | Prefix | Focus |
|-------|--------|-------|
| chaos-engineer | CE | Resilience testing, failure scenarios |
| api-designer | AP | API design, interface consistency |
| cli-developer | CD | CLI patterns, argument parsing |
| legacy-modernizer | LM | Modernization opportunities, tech debt |
| code-documenter | DC | Documentation gaps, docstrings |
| the-fool | TF | Devil's advocate, pre-mortem, hidden assumptions |

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

## Phase 1: Execution (3 sequential waves)

Execute waves **sequentially**, agents within each wave **in parallel**.

For EACH skill, use `subagent_type` matching the skill name and the prompt template from audit-schema.md, filling in:
- `{domain}` — the skill's Focus from the tables above
- `{skill-name}` — the skill directory name
- `{PREFIX}` — the 2-letter prefix from the tables above
- `"wave": {wave_number}` — for wave tracking

**Wave 1:** Launch 8 agents in parallel → wait for all to complete
**Wave 2:** Launch 8 agents in parallel → wait for all to complete
**Wave 3:** Launch 6 agents in parallel → wait for all to complete

If a scope filter was provided, add it to each prompt to narrow the analysis.

---

## Phase 2: Post-Execution

Follow the post-execution workflow from audit-schema.md, with these additions:

1. **Collect** — Gather JSON arrays from all 22 skills across 3 waves
2. **Merge** — Combine into single array, validate required fields
3. **Deduplicate** — Group by file + overlapping lines, keep best fix, create `found_by` arrays for consensus
4. **Sort** — By severity (critical → low), then category, then file path
5. **Report** — Generate `AUDIT_REPORT.md` and `AUDIT_REPORT.json`
   - Include "Top Issues by Consensus" section (found by 2+ skills)
   - Include per-wave breakdown in agent contributions table
6. **Present** — Show summary with severity/category/wave breakdown
7. **Apply** — Group approved fixes by file, apply bottom-up, run validation

---

## Output Template

```
## Full Audit Results

| Severity | Count |
|----------|-------|
| Critical | N     |
| High     | N     |
| Medium   | N     |
| Low      | N     |

| Wave | Skills | Findings |
|------|--------|----------|
| 1    | 8      | N        |
| 2    | 8      | N        |
| 3    | 6      | N        |

**Consensus issues (2+ skills):** N
**Total findings:** N | **Skills:** 22 | **Files analyzed:** N

Reports: AUDIT_REPORT.md, AUDIT_REPORT.json

Which fixes would you like to apply?
(all / by severity / by category / by skill / by wave / by consensus / specific IDs / skip)
```

---

## Constraints

**MUST:**
- Read audit-schema.md before spawning any agents
- Execute waves sequentially (Wave 1 → 2 → 3)
- Run agents within each wave in parallel (single message)
- Track consensus across all waves
- Include wave number in each agent prompt

**MUST NOT:**
- Apply fixes without user approval
- Run all 22 agents simultaneously (waves must be sequential)
- Skip consensus tracking
