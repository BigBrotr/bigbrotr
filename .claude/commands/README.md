# BigBrotr Audit Commands

Three audit commands for analyzing the BigBrotr codebase with AI agents.

## Available Commands

| Command | Agents | Time | Use When |
|---------|--------|------|----------|
| `/audit-quick` | 5 | ~2-3 min | Quick health check |
| `/audit-core` | 10 | ~5-7 min | Regular development |
| `/audit-full` | 31 | ~15-20 min | Before release or major refactoring |

## Quick Reference

### /audit-quick (5 agents)
```
code-reviewer, security-auditor, performance-engineer,
test-automator, bigbrotr-expert
```
Best for: Fast feedback on critical issues.

### /audit-core (10 agents)
```
code-reviewer, python-pro, architect-reviewer,
postgres-pro, database-optimizer, security-auditor,
test-automator, performance-engineer,
bigbrotr-expert, nostr-expert
```
Best for: Comprehensive check during active development.

### /audit-full (31 agents in 4 waves)
```
Wave 1: bigbrotr-expert, nostr-expert, python-pro, code-reviewer,
        architect-reviewer, security-auditor, postgres-pro, performance-engineer

Wave 2: debugger, error-detective, database-optimizer, database-administrator,
        test-automator, qa-expert, backend-developer, microservices-architect

Wave 3: devops-engineer, deployment-engineer, sre-engineer, incident-responder,
        chaos-engineer, websocket-engineer, api-designer, cli-developer

Wave 4: refactoring-specialist, dependency-manager, documentation-engineer,
        legacy-modernizer, data-engineer, sql-pro, penetration-tester
```
Best for: Release preparation, security audit, major refactoring.

## How It Works

1. **Run command**: Type `/audit-quick`, `/audit-core`, or `/audit-full`
2. **Agents analyze**: Multiple agents run in parallel, each focusing on their specialty
3. **Report generated**: `AUDIT_REPORT.md` created with all findings
4. **You approve**: Choose which issues to fix
5. **Agents fix**: Approved issues are automatically fixed

## Approval Options

After audit completes, you can approve:
- **All** - Fix everything found
- **By severity** - "Critical and High only"
- **By category** - "Security issues only"
- **Specific items** - "Items 1, 5, 12"
- **Interactive** - Review one by one
- **Skip** - Don't fix now

## Example Session

```
You: /audit-core

Claude: Running Core Audit with 10 agents...
        [Progress updates]

        Audit complete! Generated AUDIT_REPORT.md

        Summary:
        - Critical: 3 issues
        - High: 8 issues
        - Medium: 15 issues
        - Low: 12 suggestions

        What would you like to approve?

You: Fix all Critical and High

Claude: Fixing 11 issues...
        [Agent work]

        Done! Fixed:
        - 3 Critical issues
        - 8 High priority issues

        Remaining: 15 Medium, 12 Low
        Want to address these too?
```

## Report Structure

Generated `AUDIT_REPORT.md` contains:

```markdown
# BigBrotr Audit Report

## Summary Table
| Category | Critical | High | Medium | Low |
|----------|----------|------|--------|-----|
| ...      | ...      | ...  | ...    | ... |

## Critical Issues
- [ ] 1. [security-auditor] SQL injection in...
- [ ] 2. [performance-engineer] Memory leak in...

## High Priority
- [ ] 3. [code-reviewer] Missing error handling...
...

## Medium Priority
...

## Low Priority / Suggestions
...
```

Each item includes:
- Agent that found it
- File and line number
- Description
- Suggested fix
- Effort estimate
