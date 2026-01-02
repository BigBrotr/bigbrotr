# Core Audit Command

Run a comprehensive audit of BigBrotr using 10 core agents in parallel.

## Agents Used

### Code Quality (3)
1. **code-reviewer** - Code quality, SOLID principles, code smells
2. **python-pro** - Python best practices, async patterns, type hints
3. **architect-reviewer** - Architecture patterns, design decisions

### Database (2)
4. **postgres-pro** - PostgreSQL optimization, schema design, indexes
5. **database-optimizer** - Query performance, materialized views

### Security & Testing (2)
6. **security-auditor** - SQL injection, secrets, vulnerabilities
7. **test-automator** - Test coverage, missing tests, CI/CD

### Performance (1)
8. **performance-engineer** - Async I/O, connection pooling, bottlenecks

### Domain Experts (2)
9. **bigbrotr-expert** - BigBrotr-specific patterns and issues
10. **nostr-expert** - Nostr protocol compliance, nostr-sdk usage

## Instructions

You are running a CORE AUDIT of the BigBrotr codebase. Execute these 10 audits IN PARALLEL using the Task tool with subagent_type="general-purpose".

For EACH agent, spawn a Task that:
1. Reads the agent's system prompt from `.claude/agents/<agent>.md` (or `.claude/agents/<agent>/AGENT.md` for folder agents)
2. Analyzes the relevant parts of the codebase
3. Returns a structured report with findings

### Report Format (each agent must return)

```markdown
## [Agent Name] Audit Report

### Critical Issues (must fix)
- [ ] **[FILE:LINE]** Description of issue
  - Impact: [description]
  - Fix: [suggested fix]
  - Effort: small/medium/large

### High Priority
- [ ] **[FILE:LINE]** Description...

### Medium Priority
- [ ] **[FILE:LINE]** Description...

### Low Priority / Suggestions
- [ ] Description...

### Summary
- Critical: N issues
- High: N issues
- Medium: N issues
- Low: N suggestions
```

### Agent-Specific Focus Areas

| Agent | Focus On |
|-------|----------|
| code-reviewer | src/core/, src/services/, src/models/ |
| python-pro | Async patterns, type hints, Pydantic usage |
| architect-reviewer | 3-layer architecture, service boundaries |
| postgres-pro | postgres/init/*.sql, connection pooling |
| database-optimizer | Queries, indexes, materialized views |
| security-auditor | SQL injection, secrets, auth, WebSocket security |
| test-automator | tests/, coverage gaps, CI workflow |
| performance-engineer | Async I/O, aiomultiprocess, memory |
| bigbrotr-expert | Service patterns, Brotr API usage |
| nostr-expert | nostr-sdk usage, NIP compliance |

### After All Agents Complete

1. Consolidate all reports into a single `AUDIT_REPORT.md` in the project root
2. Organize by severity (Critical first, then High, Medium, Low)
3. Group by category (Code, Database, Security, Testing, Performance, Domain)
4. Remove duplicates (same issue found by multiple agents)
5. Add a summary table at the top with counts per category
6. Present the report to the user for approval

### Run Command

After generating the report, ask the user:
"Review AUDIT_REPORT.md and tell me which items to approve for fixing. You can:
1. Approve all
2. Approve by severity (e.g., 'all Critical and High')
3. Approve by category (e.g., 'all Security issues')
4. Approve specific items by number
5. Skip the audit"
