---
description: Run a fast 5-skill parallel audit of BigBrotr
argument-hint: "[scope]"
---

# Quick Audit

**Arguments:** $ARGUMENTS

---

## Skills (5)

| Skill | Prefix | Focus |
|-------|--------|-------|
| bigbrotr-expert | BB | Service patterns, Brotr API, diamond DAG |
| code-reviewer | CR | Code quality, SOLID principles, code smells |
| security-reviewer | SR | SQL injection, secrets, auth, WebSocket security |
| python-pro | PP | Async patterns, type hints, Pydantic, mypy |
| test-master | TM | Test coverage, missing tests, CI workflow |

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

Spawn **5 Task agents in a single message** (parallel).

For EACH skill, use `subagent_type` matching the skill name and the prompt template from audit-schema.md, filling in:
- `{domain}` — the skill's Focus from the table above
- `{skill-name}` — the skill directory name
- `{PREFIX}` — the 2-letter prefix from the table above

If a scope filter was provided, add it to each prompt to narrow the analysis.

---

## Phase 2: Post-Execution

Follow the post-execution workflow from audit-schema.md:

1. **Collect** — Gather JSON arrays from all 5 skills
2. **Merge** — Combine into single array, skip malformed JSON with warning
3. **Deduplicate** — Group by file + overlapping lines, keep best fix
4. **Sort** — By severity (critical → low), then file path
5. **Report** — Generate `AUDIT_REPORT.md` and `AUDIT_REPORT.json`
6. **Present** — Show summary table and ask which fixes to apply
7. **Apply** — Group approved fixes by file, apply bottom-up, run validation

---

## Output Template

```
## Quick Audit Results

| Severity | Count |
|----------|-------|
| Critical | N     |
| High     | N     |
| Medium   | N     |
| Low      | N     |

**Total findings:** N | **Skills:** 5 | **Files analyzed:** N

Reports: AUDIT_REPORT.md, AUDIT_REPORT.json

Which fixes would you like to apply? (all / by severity / by category / specific IDs / skip)
```

---

## Constraints

**MUST:**
- Read audit-schema.md before spawning any agents
- Run all 5 agents in a single message (parallel)
- Deduplicate before presenting results

**MUST NOT:**
- Apply fixes without user approval
- Skip the deduplication step
