# Full Audit Command

Run a complete audit of BigBrotr using ALL 31 agents organized in waves.

## Agents Used (31 total)

### Wave 1: Foundation (8 agents) - Run in parallel
1. **bigbrotr-expert** - BigBrotr-specific patterns
2. **nostr-expert** - Nostr protocol compliance
3. **python-pro** - Python best practices
4. **code-reviewer** - Code quality
5. **architect-reviewer** - Architecture patterns
6. **security-auditor** - Security vulnerabilities
7. **postgres-pro** - PostgreSQL optimization
8. **performance-engineer** - Performance bottlenecks

### Wave 2: Depth Analysis (8 agents) - Run in parallel
9. **debugger** - Potential bugs, race conditions
10. **error-detective** - Error handling patterns
11. **database-optimizer** - Query optimization
12. **database-administrator** - HA, backup, DR
13. **test-automator** - Test coverage
14. **qa-expert** - Quality assurance
15. **backend-developer** - Backend patterns
16. **microservices-architect** - Service design

### Wave 3: Operations (8 agents) - Run in parallel
17. **devops-engineer** - Docker, CI/CD
18. **deployment-engineer** - Deployment strategies
19. **sre-engineer** - Reliability, SLOs
20. **incident-responder** - Incident readiness
21. **chaos-engineer** - Resilience testing
22. **websocket-engineer** - WebSocket patterns
23. **api-designer** - API design
24. **cli-developer** - CLI patterns

### Wave 4: Maintenance (7 agents) - Run in parallel
25. **refactoring-specialist** - Refactoring opportunities
26. **dependency-manager** - Dependencies, CVEs
27. **documentation-engineer** - Documentation gaps
28. **legacy-modernizer** - Modernization opportunities
29. **data-engineer** - Data pipeline patterns
30. **sql-pro** - SQL best practices
31. **penetration-tester** - Security testing

## Instructions

You are running a FULL AUDIT of the BigBrotr codebase. Execute audits in 4 WAVES, with each wave running agents in parallel.

### Wave Execution

For EACH wave:
1. Spawn all agents in the wave IN PARALLEL using Task tool
2. Wait for all to complete
3. Proceed to next wave

This staged approach prevents overwhelming the system while maximizing parallelism.

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

### After All Waves Complete

1. Consolidate all 31 reports into `AUDIT_REPORT.md`
2. Deduplicate (many agents may find same issues)
3. Organize by:
   - Severity (Critical → Low)
   - Category (Code, Database, Security, Testing, DevOps, Documentation)
4. Create summary dashboard:

```markdown
# BigBrotr Full Audit Report

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Quality | X | X | X | X | X |
| Database | X | X | X | X | X |
| Security | X | X | X | X | X |
| Testing | X | X | X | X | X |
| Performance | X | X | X | X | X |
| DevOps | X | X | X | X | X |
| Documentation | X | X | X | X | X |
| **TOTAL** | **X** | **X** | **X** | **X** | **X** |

## Agents Contributing
- 31 agents analyzed the codebase
- X unique issues found (after deduplication)
- Most common issues: [list top 3]
```

5. Present to user for approval

### Key Files to Analyze

```
src/
├── core/
│   ├── pool.py          # Connection pooling
│   ├── brotr.py         # Database interface
│   ├── base_service.py  # Service base class
│   └── logger.py        # Logging
├── services/
│   ├── seeder.py        # Initial seeding
│   ├── finder.py        # Relay discovery
│   ├── validator.py     # Relay validation
│   ├── monitor.py       # Health monitoring
│   ├── synchronizer.py  # Event sync (multiprocess)
│   └── __main__.py      # CLI entry
└── models/              # Data models

implementations/bigbrotr/
├── postgres/init/       # SQL schema (10 files)
├── yaml/               # Service configs
├── docker-compose.yaml # Container setup
└── Dockerfile

tests/                  # 18 test files
docs/                   # Documentation
requirements.txt        # Dependencies
pyproject.toml         # Project config
```

### Run Command

After generating the report, ask the user:
"Review AUDIT_REPORT.md - this is a comprehensive analysis from 31 specialized agents.

You can approve fixes by:
1. **All** - Fix everything
2. **Severity** - e.g., 'Critical and High only'
3. **Category** - e.g., 'Security and Database only'
4. **Specific items** - e.g., 'items 1, 5, 12, 23'
5. **Interactive** - Go through each category one by one
6. **Skip** - Don't fix anything now

What would you like to do?"
