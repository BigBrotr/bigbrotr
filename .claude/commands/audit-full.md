# Full Audit Command

Run a complete audit of BigBrotr using ALL 31 agents organized in waves.

## Agents Used (31 total)

### Wave 1: Foundation (8 agents) - Run in parallel
1. **bigbrotr-expert** (BB) - BigBrotr-specific patterns
2. **nostr-expert** (NE) - Nostr protocol compliance
3. **python-pro** (PP) - Python best practices
4. **code-reviewer** (CR) - Code quality
5. **architect-reviewer** (AR) - Architecture patterns
6. **security-auditor** (SA) - Security vulnerabilities
7. **postgres-pro** (PG) - PostgreSQL optimization
8. **performance-engineer** (PE) - Performance bottlenecks

### Wave 2: Depth Analysis (8 agents) - Run in parallel
9. **debugger** (DB) - Potential bugs, race conditions
10. **error-detective** (ED) - Error handling patterns
11. **database-optimizer** (DO) - Query optimization
12. **database-administrator** (DA) - HA, backup, DR
13. **test-automator** (TA) - Test coverage
14. **qa-expert** (QA) - Quality assurance
15. **backend-developer** (BD) - Backend patterns
16. **microservices-architect** (MA) - Service design

### Wave 3: Operations (8 agents) - Run in parallel
17. **devops-engineer** (DE) - Docker, CI/CD
18. **deployment-engineer** (DP) - Deployment strategies
19. **sre-engineer** (SR) - Reliability, SLOs
20. **incident-responder** (IR) - Incident readiness
21. **chaos-engineer** (CE) - Resilience testing
22. **websocket-engineer** (WS) - WebSocket patterns
23. **api-designer** (AD) - API design
24. **cli-developer** (CD) - CLI patterns

### Wave 4: Maintenance (7 agents) - Run in parallel
25. **refactoring-specialist** (RS) - Refactoring opportunities
26. **dependency-manager** (DM) - Dependencies, CVEs
27. **documentation-engineer** (DC) - Documentation gaps
28. **legacy-modernizer** (LM) - Modernization opportunities
29. **data-engineer** (DT) - Data pipeline patterns
30. **sql-pro** (SP) - SQL best practices
31. **penetration-tester** (PT) - Security testing

## Instructions

You are running a FULL AUDIT of the BigBrotr codebase. Execute audits in 4 WAVES, with each wave running agents in parallel.

### Wave Execution Strategy

Execute waves sequentially, but agents within each wave run in parallel:
1. Launch all Wave 1 agents (8) in parallel
2. Wait for Wave 1 to complete
3. Launch all Wave 2 agents (8) in parallel
4. Wait for Wave 2 to complete
5. Launch all Wave 3 agents (8) in parallel
6. Wait for Wave 3 to complete
7. Launch all Wave 4 agents (7) in parallel
8. Wait for Wave 4 to complete

This prevents overwhelming the system while maximizing parallelism.

### CRITICAL: Output Format

Each agent MUST return findings as a **JSON array** wrapped in a code block. This is MANDATORY for proper aggregation.

#### Single-Location Issue
```json
{
  "id": "CR-001",
  "agent": "code-reviewer",
  "severity": "critical",
  "category": "code",
  "title": "Unhandled exception in WebSocket connection",
  "description": "The WebSocket connection can raise ConnectionClosed but it's not caught.",
  "impact": "Service crashes when relay disconnects unexpectedly",
  "effort": "small",
  "references": ["NIP-01"],
  "wave": 1,
  "fixes": [
    {
      "file": "src/services/monitor.py",
      "line": 142,
      "line_end": 145,
      "current_code": "async with connect(url) as ws:\n    await ws.send(msg)",
      "fixed_code": "try:\n    async with connect(url) as ws:\n        await ws.send(msg)\nexcept ConnectionClosed:\n    logger.warning('connection_closed', url=url)"
    }
  ]
}
```

#### Multi-Location Issue
```json
{
  "id": "SA-001",
  "agent": "security-auditor",
  "severity": "high",
  "category": "security",
  "title": "Missing input validation across API handlers",
  "description": "User input is not validated before being used in database queries.",
  "impact": "Potential SQL injection or data corruption",
  "effort": "medium",
  "references": ["OWASP Top 10"],
  "wave": 1,
  "fixes": [
    {
      "file": "src/services/finder.py",
      "line": 89,
      "line_end": 92,
      "description": "Add URL validation before processing",
      "current_code": "url = data.get('url')\nawait self.process_url(url)",
      "fixed_code": "url = data.get('url')\nif not self._validate_url(url):\n    raise ValueError(f'Invalid URL: {url}')\nawait self.process_url(url)"
    },
    {
      "file": "src/services/finder.py",
      "line": 250,
      "description": "Add validation helper method",
      "current_code": "class Finder(BaseService):",
      "fixed_code": "class Finder(BaseService):\n    def _validate_url(self, url: str) -> bool:\n        \"\"\"Validate relay URL format.\"\"\"\n        return url and url.startswith(('ws://', 'wss://'))"
    },
    {
      "file": "src/services/monitor.py",
      "line": 156,
      "line_end": 158,
      "description": "Same validation pattern in Monitor",
      "current_code": "relay_url = event.tags.get('r')\nawait self.check_relay(relay_url)",
      "fixed_code": "relay_url = event.tags.get('r')\nif not relay_url or not relay_url.startswith(('ws://', 'wss://')):\n    continue\nawait self.check_relay(relay_url)"
    }
  ]
}
```

#### New File Creation
```json
{
  "id": "TA-001",
  "agent": "test-automator",
  "severity": "medium",
  "category": "testing",
  "title": "Missing unit tests for Finder service",
  "description": "The Finder service has no dedicated unit tests.",
  "impact": "Regressions may go undetected",
  "effort": "large",
  "wave": 2,
  "fixes": [
    {
      "file": "tests/unit/services/test_finder.py",
      "action": "create",
      "description": "Create new test file for Finder service",
      "fixed_code": "\"\"\"Unit tests for Finder service.\"\"\"\nimport pytest\n..."
    }
  ]
}
```

### Field Definitions

#### Issue-Level Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique ID: `{AGENT_PREFIX}-{NUMBER}` (e.g., CR-001, PP-002) |
| `agent` | Yes | Agent name that found this issue |
| `severity` | Yes | `critical`, `high`, `medium`, `low` |
| `category` | Yes | `code`, `security`, `performance`, `testing`, `database`, `devops`, `protocol`, `operations`, `documentation` |
| `title` | Yes | Short description (max 80 chars) |
| `description` | Yes | Detailed explanation of the issue |
| `impact` | Yes | What happens if not fixed |
| `effort` | Yes | `small` (<30 min), `medium` (30min-2hr), `large` (>2hr) |
| `references` | No | Array of relevant docs, NIPs, URLs |
| `wave` | Yes | Which wave found this (1-4) |
| `fixes` | Yes | Array of fix objects (see below) |

#### Fix-Level Fields (inside `fixes` array)

| Field | Required | Description |
|-------|----------|-------------|
| `file` | Yes | Relative path from project root |
| `action` | No | `edit` (default) or `create` for new files |
| `line` | No* | Starting line number (required if action=edit) |
| `line_end` | No | Ending line number if spans multiple lines |
| `description` | No | What this specific fix does (useful for multi-fix issues) |
| `current_code` | No* | The problematic code snippet (required if action=edit) |
| `fixed_code` | Yes | The corrected code or new file content |

*Required when `action` is `edit` (the default)

### Agent Prefixes (All 31)

| Wave | Agent | Prefix | Focus |
|------|-------|--------|-------|
| 1 | bigbrotr-expert | BB | Service patterns, Brotr API |
| 1 | nostr-expert | NE | NIP compliance, nostr-sdk |
| 1 | python-pro | PP | Async, types, Pydantic |
| 1 | code-reviewer | CR | Quality, SOLID, smells |
| 1 | architect-reviewer | AR | Architecture, boundaries |
| 1 | security-auditor | SA | Injection, secrets, auth |
| 1 | postgres-pro | PG | Schema, pooling, indexes |
| 1 | performance-engineer | PE | I/O, memory, bottlenecks |
| 2 | debugger | DB | Bugs, race conditions |
| 2 | error-detective | ED | Error handling |
| 2 | database-optimizer | DO | Queries, views |
| 2 | database-administrator | DA | HA, backup, DR |
| 2 | test-automator | TA | Coverage, CI |
| 2 | qa-expert | QA | Quality assurance |
| 2 | backend-developer | BD | Backend patterns |
| 2 | microservices-architect | MA | Service design |
| 3 | devops-engineer | DE | Docker, CI/CD |
| 3 | deployment-engineer | DP | Deployment |
| 3 | sre-engineer | SR | SLOs, reliability |
| 3 | incident-responder | IR | Incident readiness |
| 3 | chaos-engineer | CE | Resilience |
| 3 | websocket-engineer | WS | WebSocket |
| 3 | api-designer | AD | API design |
| 3 | cli-developer | CD | CLI patterns |
| 4 | refactoring-specialist | RS | Refactoring |
| 4 | dependency-manager | DM | Dependencies, CVEs |
| 4 | documentation-engineer | DC | Docs gaps |
| 4 | legacy-modernizer | LM | Modernization |
| 4 | data-engineer | DT | Data pipelines |
| 4 | sql-pro | SP | SQL practices |
| 4 | penetration-tester | PT | Security testing |

### Agent Prompt Template

For EACH agent, spawn a Task with this prompt:

```
You are performing a specialized audit of the BigBrotr codebase as the {agent-name} agent.

First, read your agent instructions from `.claude/agents/{agent-name}.md` (or `.claude/agents/{agent-name}/AGENT.md` for folder-based agents).

Key areas to analyze:
- src/core/ - Pool, Brotr, BaseService, Logger
- src/services/ - Seeder, Finder, Validator, Monitor, Synchronizer
- src/models/ - Data models
- deployments/bigbrotr/postgres/init/ - SQL schema (10 files)
- tests/ - Test coverage (18 files)
- docker-compose.yaml, Dockerfile - Container config
- pyproject.toml - Dependencies

YOUR OUTPUT MUST BE A JSON ARRAY wrapped in a ```json code block.

Each finding follows this schema:
{
  "id": "{PREFIX}-{NUMBER}",
  "agent": "{agent-name}",
  "severity": "critical|high|medium|low",
  "category": "code|security|performance|testing|database|devops|protocol|operations|documentation",
  "title": "Short description (max 80 chars)",
  "description": "Detailed explanation",
  "impact": "What happens if not fixed",
  "effort": "small|medium|large",
  "references": ["optional"],
  "wave": {wave_number},
  "fixes": [
    {
      "file": "path/to/file.py",
      "line": 42,
      "line_end": 50,
      "description": "What this fix does",
      "current_code": "code to replace",
      "fixed_code": "replacement code"
    }
  ]
}

RULES:
1. Return ONLY the JSON array in a code block. No other text.
2. If no issues found, return: []
3. The `fixes` array can contain MULTIPLE entries for multi-file or multi-location issues
4. For new files, use `"action": "create"` and omit `line`/`current_code`
5. Each fix must have exact `current_code` that can be found in the file
6. Use your agent prefix: {PREFIX}
7. Set wave: {wave_number}
8. Be thorough - examine ALL relevant files in your domain
9. Be actionable - fixed_code must be directly applicable
10. Don't duplicate obvious issues - focus on YOUR expertise
```

### After All Waves Complete

1. **Collect JSON arrays** from all 31 agents (across 4 waves)

2. **Parse and validate** each JSON array:
   - Skip malformed JSON with warning
   - Validate required fields exist
   - Normalize severity/category values

3. **Merge into master array** preserving all findings

4. **Aggressive deduplication**:
   - Group fixes by `file` + overlapping line ranges
   - For duplicate fixes:
     - Keep highest severity version
     - Keep most complete `fixed_code`
     - Create `found_by: ["agent1", "agent2"]` array
     - Note consensus in description

5. **Sort** by:
   - Severity (critical → low)
   - Category
   - Primary file path
   - Line number

6. **Generate AUDIT_REPORT.md**:

```markdown
# BigBrotr Full Audit Report

Generated: {timestamp}
Agents: 31 (4 waves)
Duration: ~{X} minutes

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Quality | X | X | X | X | X |
| Database | X | X | X | X | X |
| Security | X | X | X | X | X |
| Testing | X | X | X | X | X |
| Performance | X | X | X | X | X |
| Protocol | X | X | X | X | X |
| Operations | X | X | X | X | X |
| Documentation | X | X | X | X | X |
| **TOTAL** | **X** | **X** | **X** | **X** | **X** |

### Top Issues by Consensus
Issues found by multiple agents (higher confidence):

1. **{title}** - Found by: {agent1}, {agent2}, {agent3} (3 fixes)
2. **{title}** - Found by: {agent1}, {agent2} (5 fixes across 3 files)
...

### Most Common Issue Types
1. {issue_type}: X occurrences
2. {issue_type}: X occurrences
3. {issue_type}: X occurrences

---

## Critical Issues

### CR-001: Unhandled exception in WebSocket connection
- **Category:** code
- **Found by:** code-reviewer, error-detective, websocket-engineer
- **Impact:** Service crashes when relay disconnects unexpectedly
- **Effort:** small
- **Wave:** 1
- **Files:** 1 file, 1 fix

#### Fix 1: src/services/monitor.py:142-145

<details>
<summary>Current Code</summary>

\`\`\`python
async with connect(url) as ws:
    await ws.send(msg)
\`\`\`
</details>

<details>
<summary>Fixed Code</summary>

\`\`\`python
try:
    async with connect(url) as ws:
        await ws.send(msg)
except ConnectionClosed:
    logger.warning('connection_closed', url=url)
\`\`\`
</details>

---

### SA-001: Missing input validation across API handlers
- **Category:** security
- **Found by:** security-auditor, penetration-tester
- **Impact:** Potential SQL injection or data corruption
- **Effort:** medium
- **Wave:** 1
- **Files:** 2 files, 3 fixes

#### Fix 1: src/services/finder.py:89-92
Add URL validation before processing
[Current/Fixed code blocks...]

#### Fix 2: src/services/finder.py:250
Add validation helper method
[Fixed code block...]

#### Fix 3: src/services/monitor.py:156-158
Same validation pattern in Monitor
[Current/Fixed code blocks...]

---

[... all critical issues ...]

## High Priority Issues
[... issues ...]

## Medium Priority Issues
[... issues ...]

## Low Priority / Suggestions
[... issues ...]

---

## Appendix

### Agent Contributions

| Agent | Wave | Critical | High | Medium | Low | Total | Fixes |
|-------|------|----------|------|--------|-----|-------|-------|
| bigbrotr-expert | 1 | X | X | X | X | X | Y |
| nostr-expert | 1 | X | X | X | X | X | Y |
| ... | ... | ... | ... | ... | ... | ... | ... |
| **TOTAL** | - | **X** | **X** | **X** | **X** | **X** | **Y** |

### Issues by File

| File | Issues | Fixes | Critical | High | Medium | Low |
|------|--------|-------|----------|------|--------|-----|
| src/services/monitor.py | X | Y | X | X | X | X |
| src/core/pool.py | X | Y | X | X | X | X |
| ... | ... | ... | ... | ... | ... | ... |

### Duplicates Merged

| Original Count | After Dedup | Duplicates Removed |
|----------------|-------------|-------------------|
| X | X | X |

## Raw JSON Data

\`\`\`json
[... full merged and deduplicated JSON array ...]
\`\`\`
```

7. **Write AUDIT_REPORT.json** with the clean JSON array

8. **Write AUDIT_REPORT_DETAILED.json** with per-agent breakdown:
```json
{
  "summary": { ... },
  "issues": [ ... ],
  "by_agent": {
    "code-reviewer": [ ... ],
    "python-pro": [ ... ]
  },
  "duplicates_removed": [ ... ]
}
```

9. **Present to user:**

```
Full audit complete! 31 agents analyzed the codebase in 4 waves.

## Summary
| Severity | Issues | Fixes | Files |
|----------|--------|-------|-------|
| Critical | X | Y | Z |
| High | X | Y | Z |
| Medium | X | Y | Z |
| Low | X | Y | Z |
| **Total** | **X** | **Y** | **Z** |

Top consensus issues (found by multiple agents):
1. {issue} - 3 agents agree (4 fixes)
2. {issue} - 2 agents agree (2 fixes)

Reports generated:
- AUDIT_REPORT.md (human-readable)
- AUDIT_REPORT.json (clean issue list)
- AUDIT_REPORT_DETAILED.json (full breakdown by agent)

Which fixes would you like me to apply?
1. All issues
2. By severity (e.g., "critical and high only")
3. By category (e.g., "security and database")
4. By agent (e.g., "bigbrotr-expert findings")
5. By wave (e.g., "wave 1 only")
6. By consensus (e.g., "issues found by 2+ agents")
7. Specific IDs (e.g., "CR-001, SA-005, PG-002")
8. Interactive (go through each category)
9. Skip
```

### Applying Fixes

When user approves fixes:

1. **Filter approved issues** from AUDIT_REPORT.json based on user selection

2. **Flatten all fixes** from approved issues into master fix list with issue ID references

3. **Validate fixes**:
   - Ensure all have `file` and either `action: create` or `line`/`current_code`
   - Separate issues needing manual action

4. **Group by file** to minimize I/O

5. **For each file** (alphabetical order):
   - Separate `create` actions from `edit` actions
   - For `create` actions:
     - Use Write tool to create the file with `fixed_code`
     - Log: "Created {file} for {issue_id}"
   - For `edit` actions:
     - Read the file content once
     - Sort fixes by line number DESCENDING (apply from bottom up)
     - For each fix:
       - Find `current_code` in the file around the specified line
       - Replace with `fixed_code` using Edit tool
       - Log success/failure with issue ID and fix description
     - Verify file is syntactically valid after all edits

6. **For issues without actionable `fixes`**:
   - Group by category
   - Present as "Manual Action Required" list
   - Provide guidance on what needs to be done

7. **Post-fix validation**:
   ```bash
   ruff check src/ tests/ --fix  # Auto-fix lint
   ruff format src/ tests/       # Format
   mypy src/                     # Type check
   pytest tests/ -x --tb=short  # Quick test
   ```

8. **Generate fix report**:
   ```
   ## Fix Summary

   ✅ Applied: X fixes across Y files
   - CR-001: Fixed WebSocket exception handling
     - src/services/monitor.py:142 ✓
   - SA-001: Added input validation (3 fixes)
     - src/services/finder.py:89 ✓
     - src/services/finder.py:250 ✓
     - src/services/monitor.py:156 ✓
   - TA-001: Created test file
     - tests/unit/services/test_finder.py (new) ✓
   - ...

   ⚠️ Manual Action Required: X items
   - DA-002: Configure PostgreSQL HA
     - Action: Update postgresql.conf with HA settings
   - DC-001: Update README
     - Action: Document new configuration options
   - ...

   ❌ Failed: X fixes
   - PP-005: Could not locate code block
     - File: src/core/pool.py:89
     - Reason: Code has changed since audit
   - ...

   ## Validation
   - Ruff: ✅ passed
   - Mypy: ✅ passed (or ⚠️ X warnings)
   - Tests: ✅ X passed, 0 failed
   ```

9. **Offer follow-up**:
   ```
   Would you like me to:
   1. Commit these changes
   2. Review the manual action items in detail
   3. Re-run failed fixes with fresh file reads
   4. Run full test suite with coverage
   5. Generate a summary for PR description
   ```
