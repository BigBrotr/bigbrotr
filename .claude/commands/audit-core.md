# Core Audit Command

Run a comprehensive audit of BigBrotr using 10 core agents in parallel.

## Agents Used

### Code Quality (3)
1. **code-reviewer** (CR) - Code quality, SOLID principles, code smells
2. **python-pro** (PP) - Python best practices, async patterns, type hints
3. **architect-reviewer** (AR) - Architecture patterns, design decisions

### Database (2)
4. **postgres-pro** (PG) - PostgreSQL optimization, schema design, indexes
5. **database-optimizer** (DO) - Query performance, materialized views

### Security & Testing (2)
6. **security-auditor** (SA) - SQL injection, secrets, vulnerabilities
7. **test-automator** (TA) - Test coverage, missing tests, CI/CD

### Performance (1)
8. **performance-engineer** (PE) - Async I/O, connection pooling, bottlenecks

### Domain Experts (2)
9. **bigbrotr-expert** (BB) - BigBrotr-specific patterns and issues
10. **nostr-expert** (NE) - Nostr protocol compliance, nostr-sdk usage

## Instructions

You are running a CORE AUDIT of the BigBrotr codebase. Execute these 10 audits IN PARALLEL using the Task tool with subagent_type matching the agent name.

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
| `severity` | Yes | `critical` (breaks functionality), `high` (significant), `medium` (should fix), `low` (suggestion) |
| `category` | Yes | One of: `code`, `security`, `performance`, `testing`, `database`, `devops`, `protocol` |
| `title` | Yes | Short description (max 80 chars) |
| `description` | Yes | Detailed explanation of the issue |
| `impact` | Yes | What happens if not fixed |
| `effort` | Yes | `small` (<30 min), `medium` (30min-2hr), `large` (>2hr) |
| `references` | No | Array of relevant docs, NIPs, URLs |
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

### Agent Prefixes

| Agent | Prefix | Focus Areas |
|-------|--------|-------------|
| code-reviewer | CR | src/core/, src/services/, src/models/ |
| python-pro | PP | Async patterns, type hints, Pydantic usage |
| architect-reviewer | AR | 3-layer architecture, service boundaries |
| postgres-pro | PG | postgres/init/*.sql, connection pooling |
| database-optimizer | DO | Queries, indexes, materialized views |
| security-auditor | SA | SQL injection, secrets, auth, WebSocket |
| test-automator | TA | tests/, coverage gaps, CI workflow |
| performance-engineer | PE | Async I/O, aiomultiprocess, memory |
| bigbrotr-expert | BB | Service patterns, Brotr API usage |
| nostr-expert | NE | nostr-sdk usage, NIP compliance |

### Agent Prompt Template

For EACH agent, spawn a Task with this prompt:

```
You are performing a {domain} audit of the BigBrotr codebase.

First, read your agent instructions from `.claude/agents/{agent-name}.md` (or `.claude/agents/{agent-name}/AGENT.md` for folder-based agents like bigbrotr-expert and nostr-expert).

Then analyze these key areas based on your expertise:
- src/core/ - Pool, Brotr, BaseService, Logger
- src/services/ - Seeder, Finder, Validator, Monitor, Synchronizer
- src/models/ - Data models
- implementations/bigbrotr/postgres/init/ - SQL schema
- tests/ - Test coverage

YOUR OUTPUT MUST BE A JSON ARRAY wrapped in a ```json code block.

Each finding follows this schema:
{
  "id": "{PREFIX}-{NUMBER}",
  "agent": "{agent-name}",
  "severity": "critical|high|medium|low",
  "category": "code|security|performance|testing|database|devops|protocol",
  "title": "Short description (max 80 chars)",
  "description": "Detailed explanation",
  "impact": "What happens if not fixed",
  "effort": "small|medium|large",
  "references": ["optional"],
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
7. Be thorough - examine ALL relevant files in your domain
8. Be actionable - fixed_code must be directly applicable
```

### After All Agents Complete

1. **Collect all JSON arrays** from the 10 agents
2. **Parse and merge** into single array preserving all findings
3. **Deduplicate** by checking for overlapping fixes:
   - Group by file + overlapping line ranges
   - If same fix found by multiple agents:
     - Keep the most complete `fixed_code`
     - Create `found_by: ["agent1", "agent2"]` array
4. **Sort** by:
   - Severity (critical → low)
   - Category
   - Primary file path
5. **Generate AUDIT_REPORT.md**:

```markdown
# BigBrotr Core Audit Report

Generated: {timestamp}
Agents: 10

## Executive Summary

| Category | Critical | High | Medium | Low | Total |
|----------|----------|------|--------|-----|-------|
| Code Quality | X | X | X | X | X |
| Database | X | X | X | X | X |
| Security | X | X | X | X | X |
| Testing | X | X | X | X | X |
| Performance | X | X | X | X | X |
| Protocol | X | X | X | X | X |
| **TOTAL** | **X** | **X** | **X** | **X** | **X** |

## Critical Issues

### CR-001: Unhandled exception in WebSocket connection
- **Agent:** code-reviewer
- **Category:** code
- **Impact:** Service crashes when relay disconnects unexpectedly
- **Effort:** small
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
- **Agent:** security-auditor
- **Category:** security
- **Impact:** Potential SQL injection or data corruption
- **Effort:** medium
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

[... continue for all issues ...]

## High Priority Issues
[... issues ...]

## Medium Priority Issues
[... issues ...]

## Low Priority / Suggestions
[... issues ...]

## Agent Contributions

| Agent | Critical | High | Medium | Low | Total |
|-------|----------|------|--------|-----|-------|
| code-reviewer | X | X | X | X | X |
| python-pro | X | X | X | X | X |
| ... | ... | ... | ... | ... | ... |

## Raw JSON Data

\`\`\`json
[... full merged JSON array ...]
\`\`\`
```

6. **Write AUDIT_REPORT.json** with the merged JSON array

7. **Present to user:**

```
Core audit complete! Found X issues (Y total fixes) across 10 agents:

| Severity | Issues | Fixes | Files |
|----------|--------|-------|-------|
| Critical | X | Y | Z |
| High | X | Y | Z |
| Medium | X | Y | Z |
| Low | X | Y | Z |

Reports generated:
- AUDIT_REPORT.md (human-readable with collapsible code)
- AUDIT_REPORT.json (machine-readable for automation)

Which fixes would you like me to apply?
1. All issues
2. By severity (e.g., "critical and high")
3. By category (e.g., "security and database")
4. By agent (e.g., "postgres-pro findings")
5. Specific IDs (e.g., "CR-001, PG-003, SA-002")
6. Interactive (review each category)
7. Skip
```

### Applying Fixes

When user approves fixes:

1. **Load approved issues** from AUDIT_REPORT.json
2. **Flatten all fixes** from approved issues into a single list with issue ID reference
3. **Group by file** to minimize file reads/writes
4. **For each file** (alphabetical order):
   - Separate `create` actions from `edit` actions
   - For `create` actions: use Write tool to create the file
   - For `edit` actions:
     - Read the file once
     - Sort fixes by line number DESCENDING (apply from bottom up)
     - For each fix:
       - Find `current_code` in the file around the specified line
       - Replace with `fixed_code` using the Edit tool
       - Log success/failure with issue ID
     - Verify file is syntactically valid
5. **For issues without actionable `fixes`**:
   - List them separately as "Manual action required"
   - Explain what needs to be done
6. **After all edits**:
   ```bash
   ruff check src/ tests/ --fix  # Auto-fix lint
   ruff format src/ tests/       # Format
   pytest tests/ -x --tb=short   # Quick test
   ```
7. **Report results**:
   ```
   ## Fix Summary

   ✅ Applied: X fixes across Y files
   - CR-001: Fixed WebSocket exception handling (1 fix)
   - SA-001: Added input validation (3 fixes across 2 files)
   - ...

   ⚠️ Manual Action Required: X items
   - DA-002: Configure PostgreSQL HA (see docs)
   - ...

   ❌ Failed: X fixes
   - PP-005: Could not locate code block (file may have changed)
   - ...

   ## Validation
   - Ruff: ✅ passed
   - Tests: ✅ X passed, 0 failed
   ```
