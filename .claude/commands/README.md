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
code-reviewer (CR), security-auditor (SA), performance-engineer (PE),
test-automator (TA), bigbrotr-expert (BB)
```
Best for: Fast feedback on critical issues.

### /audit-core (10 agents)
```
code-reviewer (CR), python-pro (PP), architect-reviewer (AR),
postgres-pro (PG), database-optimizer (DO), security-auditor (SA),
test-automator (TA), performance-engineer (PE),
bigbrotr-expert (BB), nostr-expert (NE)
```
Best for: Comprehensive check during active development.

### /audit-full (31 agents in 4 waves)
```
Wave 1: bigbrotr-expert (BB), nostr-expert (NE), python-pro (PP), code-reviewer (CR),
        architect-reviewer (AR), security-auditor (SA), postgres-pro (PG), performance-engineer (PE)

Wave 2: debugger (DB), error-detective (ED), database-optimizer (DO), database-administrator (DA),
        test-automator (TA), qa-expert (QA), backend-developer (BD), microservices-architect (MA)

Wave 3: devops-engineer (DE), deployment-engineer (DP), sre-engineer (SR), incident-responder (IR),
        chaos-engineer (CE), websocket-engineer (WS), api-designer (AD), cli-developer (CD)

Wave 4: refactoring-specialist (RS), dependency-manager (DM), documentation-engineer (DC),
        legacy-modernizer (LM), data-engineer (DT), sql-pro (SP), penetration-tester (PT)
```
Best for: Release preparation, security audit, major refactoring.

## How It Works

1. **Run command**: Type `/audit-quick`, `/audit-core`, or `/audit-full`
2. **Agents analyze**: Multiple agents run in parallel, each returning JSON-formatted findings
3. **Reports generated**:
   - `AUDIT_REPORT.md` - Human-readable report with collapsible code blocks
   - `AUDIT_REPORT.json` - Machine-readable JSON for automation
4. **You approve**: Choose which issues to fix (by severity, category, ID, etc.)
5. **Fixes applied**: All fixes from approved issues are applied automatically

## Output Format

Each agent returns findings as a JSON array. Each finding can have **multiple fixes** across different files or locations:

### Single-Location Issue
```json
{
  "id": "CR-001",
  "agent": "code-reviewer",
  "severity": "critical",
  "category": "code",
  "title": "Unhandled exception in WebSocket",
  "description": "Detailed explanation...",
  "impact": "Service crashes on disconnect",
  "effort": "small",
  "fixes": [
    {
      "file": "src/services/monitor.py",
      "line": 142,
      "line_end": 145,
      "current_code": "async with connect(url) as ws:\n    ...",
      "fixed_code": "try:\n    async with connect(url) as ws:\n        ...\nexcept ConnectionClosed:\n    ..."
    }
  ]
}
```

### Multi-Location Issue
```json
{
  "id": "SA-001",
  "agent": "security-auditor",
  "severity": "high",
  "category": "security",
  "title": "Missing input validation across handlers",
  "description": "User input not validated before database queries",
  "impact": "Potential SQL injection",
  "effort": "medium",
  "fixes": [
    {
      "file": "src/services/finder.py",
      "line": 89,
      "description": "Add URL validation",
      "current_code": "url = data.get('url')",
      "fixed_code": "url = data.get('url')\nif not self._validate_url(url): ..."
    },
    {
      "file": "src/services/finder.py",
      "line": 250,
      "description": "Add validation helper",
      "current_code": "class Finder(BaseService):",
      "fixed_code": "class Finder(BaseService):\n    def _validate_url(...):"
    },
    {
      "file": "src/services/monitor.py",
      "line": 156,
      "description": "Same pattern in Monitor",
      "current_code": "relay_url = event.tags.get('r')",
      "fixed_code": "relay_url = event.tags.get('r')\nif not relay_url: continue"
    }
  ]
}
```

### New File Creation
```json
{
  "id": "TA-001",
  "agent": "test-automator",
  "severity": "medium",
  "category": "testing",
  "title": "Missing tests for Finder service",
  "fixes": [
    {
      "file": "tests/unit/services/test_finder.py",
      "action": "create",
      "description": "Create new test file",
      "fixed_code": "\"\"\"Unit tests for Finder.\"\"\"\nimport pytest\n..."
    }
  ]
}
```

### Key Fields

#### Issue-Level
| Field | Description |
|-------|-------------|
| `id` | Unique ID: `{PREFIX}-{NUMBER}` (e.g., CR-001) |
| `severity` | `critical` (breaks), `high` (significant), `medium` (should fix), `low` (suggestion) |
| `fixes` | Array of fix objects (can have multiple!) |

#### Fix-Level
| Field | Description |
|-------|-------------|
| `file` | Path to file |
| `action` | `edit` (default) or `create` for new files |
| `line` | Line number (required for edits) |
| `description` | What this specific fix does |
| `current_code` | Code to find and replace (required for edits) |
| `fixed_code` | Replacement code or new file content |

## Approval Options

After audit completes, you can approve:

| Option | Example | Description |
|--------|---------|-------------|
| **All** | "all" | Fix everything found |
| **Severity** | "critical and high" | Fix by severity level |
| **Category** | "security and database" | Fix by category |
| **Agent** | "postgres-pro findings" | Fix from specific agent |
| **IDs** | "CR-001, SA-003, PG-002" | Fix specific issues |
| **Interactive** | "interactive" | Review each one |
| **Skip** | "skip" | Don't fix now |

For `/audit-full` only:
- **By wave**: "wave 1 only"
- **By consensus**: "issues found by 2+ agents"

## Example Session

```
You: /audit-core

Claude: Running Core Audit with 10 agents in parallel...

        ✓ code-reviewer: 5 issues (8 fixes)
        ✓ security-auditor: 3 issues (6 fixes)
        ✓ python-pro: 4 issues (4 fixes)
        ... [all 10 agents]

        Audit complete! Found 42 issues with 67 total fixes.

        | Severity | Issues | Fixes | Files |
        |----------|--------|-------|-------|
        | Critical | 2      | 3     | 2     |
        | High     | 8      | 15    | 6     |
        | Medium   | 20     | 35    | 12    |
        | Low      | 12     | 14    | 8     |

        Reports generated:
        - AUDIT_REPORT.md
        - AUDIT_REPORT.json

        Which fixes would you like me to apply?

You: critical and high

Claude: Applying 10 issues (18 fixes)...

        ✅ CR-001: Fixed WebSocket exception handling
           - src/services/monitor.py:142 ✓

        ✅ SA-001: Added input validation (3 fixes)
           - src/services/finder.py:89 ✓
           - src/services/finder.py:250 ✓
           - src/services/monitor.py:156 ✓

        ✅ PG-001: Added missing index
           - implementations/bigbrotr/postgres/init/08_indexes.sql:45 ✓
        ...

        ## Summary
        ✅ Applied: 18 fixes across 8 files
        ⚠️ Manual: 0 items
        ❌ Failed: 0 fixes

        ## Validation
        - Ruff: ✅ passed
        - Tests: ✅ 156 passed, 0 failed

        Remaining: 20 Medium, 12 Low issues
        Want to address these too?
```

## Report Structure

### AUDIT_REPORT.md

```markdown
# BigBrotr Core Audit Report

Generated: 2025-01-15 14:30:00
Agents: 10

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code     | 1        | 3    | 8      | 5   | 17    |
| Security | 1        | 2    | 4      | 2   | 9     |
| ...      | ...      | ...  | ...    | ... | ...   |

## Critical Issues

### CR-001: Unhandled exception in WebSocket connection
- **Agent:** code-reviewer
- **Impact:** Service crashes when relay disconnects
- **Effort:** small
- **Files:** 1 file, 1 fix

#### Fix 1: src/services/monitor.py:142-145

<details>
<summary>Current Code</summary>

```python
async with connect(url) as ws:
    await ws.send(msg)
```
</details>

<details>
<summary>Fixed Code</summary>

```python
try:
    async with connect(url) as ws:
        await ws.send(msg)
except ConnectionClosed:
    logger.warning('connection_closed', url=url)
```
</details>

---

### SA-001: Missing input validation across API handlers
- **Agent:** security-auditor
- **Impact:** Potential SQL injection
- **Effort:** medium
- **Files:** 2 files, 3 fixes

#### Fix 1: src/services/finder.py:89-92
Add URL validation before processing
[code blocks...]

#### Fix 2: src/services/finder.py:250
Add validation helper method
[code blocks...]

#### Fix 3: src/services/monitor.py:156-158
Same validation pattern in Monitor
[code blocks...]

---

[... more issues ...]

## Raw JSON Data
[... full JSON array ...]
```

### AUDIT_REPORT.json

Clean JSON array for automation:
```json
[
  {
    "id": "CR-001",
    "severity": "critical",
    "fixes": [{"file": "...", "line": 142, ...}]
  },
  {
    "id": "SA-001",
    "severity": "high",
    "fixes": [
      {"file": "src/services/finder.py", "line": 89, ...},
      {"file": "src/services/finder.py", "line": 250, ...},
      {"file": "src/services/monitor.py", "line": 156, ...}
    ]
  }
]
```

## Tips

1. **Start with `/audit-quick`** for rapid feedback during development
2. **Use `/audit-core`** before committing significant changes
3. **Run `/audit-full`** before releases or after major refactoring
4. **Fix by severity** to address critical issues first
5. **Multi-location issues** are fixed atomically - all fixes for an issue are applied together
6. **Consensus issues** (found by multiple agents) are highest confidence
7. **Check `AUDIT_REPORT.json`** for programmatic access to findings
