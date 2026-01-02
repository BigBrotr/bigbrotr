# Quick Audit Command

Run a fast audit of BigBrotr using 5 critical agents in parallel.

## Agents Used
1. **code-reviewer** - Code quality, SOLID principles, code smells
2. **security-auditor** - SQL injection, secrets, vulnerabilities
3. **performance-engineer** - Async I/O, connection pooling, bottlenecks
4. **test-automator** - Test coverage, missing tests, CI/CD
5. **bigbrotr-expert** - BigBrotr-specific patterns and issues

## Instructions

You are running a QUICK AUDIT of the BigBrotr codebase. Execute these 5 audits IN PARALLEL using the Task tool with subagent_type="general-purpose".

For EACH agent, spawn a Task that:
1. Reads the agent's system prompt from `.claude/agents/<agent>.md`
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

### After All Agents Complete

1. Consolidate all reports into a single `AUDIT_REPORT.md` in the project root
2. Organize by severity (Critical first, then High, Medium, Low)
3. Remove duplicates (same issue found by multiple agents)
4. Add a summary table at the top
5. Present the report to the user for approval

### Key Areas to Audit

- `src/core/` - Pool, Brotr, BaseService, Logger
- `src/services/` - Seeder, Finder, Validator, Monitor, Synchronizer
- `src/models/` - Data models
- `implementations/bigbrotr/postgres/init/` - SQL schema
- `tests/` - Test coverage
- `docker-compose.yaml` - Container configuration
- `requirements.txt` - Dependencies

### Run Command

After generating the report, ask the user:
"Review AUDIT_REPORT.md and tell me which items to approve for fixing. You can:
1. Approve all
2. Approve by category (e.g., 'all Critical and High')
3. Approve specific items by number
4. Skip the audit"
