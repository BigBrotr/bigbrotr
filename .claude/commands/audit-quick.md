# Quick Audit Command

Run a fast audit of BigBrotr using 5 critical agents in parallel.

## Agents Used
1. **code-reviewer** - Code quality, SOLID principles, code smells
2. **security-auditor** - SQL injection, secrets, vulnerabilities
3. **performance-engineer** - Async I/O, connection pooling, bottlenecks
4. **test-automator** - Test coverage, missing tests, CI/CD
5. **bigbrotr-expert** - BigBrotr-specific patterns and issues

## Instructions

You are running a QUICK AUDIT of the BigBrotr codebase. Execute these 5 audits IN PARALLEL using the Task tool with subagent_type matching the agent name (e.g., "code-reviewer", "security-auditor", etc.).

### CRITICAL: Output Format

Each agent MUST return findings as a **JSON array** wrapped in a code block. This is MANDATORY for proper aggregation.

#### Single-Location Issue (simple case)
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

#### Multi-Location Issue (complex case)
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
      "line_end": 250,
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
      "fixed_code": "\"\"\"Unit tests for Finder service.\"\"\"\nimport pytest\nfrom src.services.finder import Finder\n\n\nclass TestFinder:\n    \"\"\"Test cases for Finder service.\"\"\"\n\n    def test_validate_url_valid(self):\n        \"\"\"Test URL validation with valid URLs.\"\"\"\n        assert Finder._validate_url(None, 'wss://relay.example.com')\n        assert Finder._validate_url(None, 'ws://localhost:8080')\n\n    def test_validate_url_invalid(self):\n        \"\"\"Test URL validation with invalid URLs.\"\"\"\n        assert not Finder._validate_url(None, 'http://example.com')\n        assert not Finder._validate_url(None, '')\n        assert not Finder._validate_url(None, None)\n"
    }
  ]
}
```

### Field Definitions

#### Issue-Level Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique ID: `{AGENT_PREFIX}-{NUMBER}` (e.g., CR-001, SA-002) |
| `agent` | Yes | Agent name that found this issue |
| `severity` | Yes | `critical` (breaks functionality), `high` (significant), `medium` (should fix), `low` (suggestion) |
| `category` | Yes | One of: `code`, `security`, `performance`, `testing`, `database`, `devops` |
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
| security-auditor | SA | SQL injection, secrets, auth, WebSocket security |
| performance-engineer | PE | Async I/O, connection pooling, memory |
| test-automator | TA | tests/, coverage gaps, CI workflow |
| bigbrotr-expert | BB | Service patterns, Brotr API usage |

### Agent Prompt Template

For EACH agent, spawn a Task with this prompt:

```
You are performing a security/code/performance audit of the BigBrotr codebase.

First, read your agent instructions from `.claude/agents/{agent-name}.md`.

Then analyze these key areas:
- src/core/ - Pool, Brotr, BaseService, Logger
- src/services/ - All services
- src/models/ - Data models
- deployments/bigbrotr/postgres/init/ - SQL schema
- tests/ - Test coverage

YOUR OUTPUT MUST BE A JSON ARRAY wrapped in a ```json code block.

Each finding follows this schema:
{
  "id": "{PREFIX}-{NUMBER}",
  "agent": "{agent-name}",
  "severity": "critical|high|medium|low",
  "category": "code|security|performance|testing|database|devops",
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
7. Be thorough - examine all relevant files
8. Be actionable - fixed_code must be directly applicable
```

### After All Agents Complete

1. **Collect all JSON arrays** from the 5 agents
2. **Merge into single array** preserving all findings
3. **Deduplicate** by checking for overlapping fixes (same file + overlapping lines)
4. **Sort** by severity (critical → low), then by primary file path
5. **Generate AUDIT_REPORT.md** with this structure:

```markdown
# BigBrotr Quick Audit Report

Generated: {timestamp}
Agents: 5

## Summary

| Severity | Count | Files Affected |
|----------|-------|----------------|
| Critical | X | Y |
| High | X | Y |
| Medium | X | Y |
| Low | X | Y |
| **Total** | **X** | **Y** |

## Critical Issues

### CR-001: Unhandled exception in WebSocket connection
- **Agent:** code-reviewer
- **Impact:** Service crashes when relay disconnects unexpectedly
- **Effort:** small
- **Files:** 1 file, 1 location

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
- **Impact:** Potential SQL injection or data corruption
- **Effort:** medium
- **Files:** 2 files, 3 locations

#### Fix 1: src/services/finder.py:89-92
Add URL validation before processing

<details>
<summary>Current Code</summary>

\`\`\`python
url = data.get('url')
await self.process_url(url)
\`\`\`
</details>

<details>
<summary>Fixed Code</summary>

\`\`\`python
url = data.get('url')
if not self._validate_url(url):
    raise ValueError(f'Invalid URL: {url}')
await self.process_url(url)
\`\`\`
</details>

#### Fix 2: src/services/finder.py:250
Add validation helper method

<details>
<summary>Fixed Code (insert after line 250)</summary>

\`\`\`python
    def _validate_url(self, url: str) -> bool:
        """Validate relay URL format."""
        return url and url.startswith(('ws://', 'wss://'))
\`\`\`
</details>

#### Fix 3: src/services/monitor.py:156-158
Same validation pattern in Monitor

<details>
<summary>Current/Fixed Code</summary>
[...]
</details>

---

[... more issues ...]

## Raw JSON Data

\`\`\`json
[... full merged JSON array ...]
\`\`\`
```

6. **Write AUDIT_REPORT.json** with just the merged JSON array (for programmatic access)

7. **Present to user:**

```
Audit complete! Found X issues affecting Y files:
- Critical: X (Y fixes)
- High: X (Y fixes)
- Medium: X (Y fixes)
- Low: X (Y fixes)

Reports generated:
- AUDIT_REPORT.md (human-readable)
- AUDIT_REPORT.json (machine-readable)

Which fixes would you like me to apply?
1. All issues
2. By severity (e.g., "critical and high")
3. By category (e.g., "security")
4. By agent (e.g., "code-reviewer findings")
5. Specific IDs (e.g., "CR-001, SA-003, PE-002")
6. Interactive (review each one)
7. Skip
```

### Applying Fixes

When user approves fixes:

1. **Load approved issues** from AUDIT_REPORT.json
2. **Flatten all fixes** from approved issues into a single list
3. **Group by file** to minimize file reads/writes
4. **For each file**:
   - Check if any fix has `action: create` - if so, create the file with `fixed_code`
   - For edit actions, read the file once
   - Sort fixes by line number DESCENDING (apply from bottom up to preserve line numbers)
   - For each fix:
     - Find `current_code` in the file around the specified line
     - Replace with `fixed_code` using the Edit tool
     - Log success/failure
   - Verify file is syntactically valid after all edits
5. **For issues with no `fixes`** or fixes without `fixed_code`:
   - List them separately as "Manual action required"
   - Explain what needs to be done
6. **After all edits**:
   - Run `ruff check src/ tests/ --fix` to auto-fix any lint issues
   - Run `ruff format src/ tests/` to format
7. **Report results**:
   - ✅ Applied: X fixes across Y files
   - ⚠️ Manual: X items need attention
   - ❌ Failed: X fixes couldn't be applied (with reasons)
