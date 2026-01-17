# AI Agents for BigBrotr

This folder contains **31 AI agents** (29 generic + 2 BigBrotr-specific) selected to support the development of BigBrotr - an enterprise-grade system for archiving and monitoring the Nostr ecosystem.

## BigBrotr Tech Stack

- **Python 3.11+** with asyncio, asyncpg, aiohttp, Pydantic
- **PostgreSQL 16+** with stored procedures, materialized views, indexes
- **Docker** with 7 containerized services
- **WebSocket** via nostr-sdk (Rust/PyO3)
- **Parallel/async tasks** with aiomultiprocess
- **Testing** with pytest, mypy, ruff, pre-commit hooks

---

## BigBrotr-Specific Agents (2 agents)

These agents contain detailed project documentation:

| Agent | Description | Contents |
|-------|-------------|----------|
| **bigbrotr-expert/** | BigBrotr codebase expert | Pool, Brotr, BaseService, Logger API + 6 reference files (architecture, core, services, models, database, testing) |
| **nostr-expert/** | Nostr protocol expert | nostr-sdk Python, Khatru Go, NIP specs + 5 reference files (nip-index, kind-index, tag-index, sdk-reference, khatru-reference) |

### Using Specific Agents

```bash
# bigbrotr-expert - for internal development
bigbrotr-expert/
├── AGENT.md                    # Main system prompt (~1000 lines)
├── architecture-index.md       # Component relationships
├── core-reference.md           # Pool, Brotr, BaseService, Logger
├── services-reference.md       # Seeder, Finder, Validator, Monitor, Synchronizer
├── models-reference.md         # Event, Relay, Metadata, Nip11, Nip66, RelayMetadata
├── database-reference.md       # Schema, procedures, views, indexes
└── testing-reference.md        # Test patterns, fixtures, examples

# nostr-expert - for Nostr protocol
nostr-expert/
├── AGENT.md                    # Main system prompt
├── nip-index.md               # 94 NIPs organized by category
├── kind-index.md              # All event kinds
├── tag-index.md               # Common tags and usage
├── nostr-sdk-python-reference.md  # Python SDK documentation
└── khatru-reference.md        # Go relay framework
```

---

## Generic Agents by Category

### Python & Language (3 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **python-pro.md** | Python 3.11+ expert with async, type hints, Pydantic | Core development, asyncio, type safety |
| **sql-pro.md** | Cross-platform SQL expert | Query optimization, stored procedures |
| **cli-developer.md** | CLI and tool developer | CLI entry point (`__main__.py`) |

### Database & PostgreSQL (3 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **postgres-pro.md** | Advanced PostgreSQL specialist | Replication, VACUUM, JSONB, indexes |
| **database-optimizer.md** | Query and performance optimization | Materialized views, query tuning |
| **database-administrator.md** | DBA for HA, backup, recovery | Connection pooling, DR planning |

### Architecture & Backend (4 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **backend-developer.md** | Backend engineer for API and microservices | Service layer development |
| **microservices-architect.md** | Distributed systems architect | 5 services (Seeder, Finder, Validator, Monitor, Synchronizer) |
| **api-designer.md** | REST/GraphQL API design | Future API service (planned) |
| **websocket-engineer.md** | Real-time WebSocket specialist | nostr-sdk WebSocket connections |

### Quality & Testing (6 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **code-reviewer.md** | Code review and best practices | Code quality, SOLID principles |
| **qa-expert.md** | QA and test strategy | Test planning, 24 test files |
| **test-automator.md** | CI/CD test automation | pytest, pytest-asyncio |
| **debugger.md** | Complex problem debugging | Multiprocessing, race conditions |
| **error-detective.md** | Error pattern analysis | Distributed error correlation |
| **performance-engineer.md** | Performance optimization | Async I/O, connection pooling |

### Security & Audit (3 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **security-auditor.md** | Complete security audit | SQL injection prevention, secrets |
| **penetration-tester.md** | Ethical hacking and vulnerability | WebSocket security, API security |
| **architect-reviewer.md** | System architecture review | 3-layer architecture validation |

### DevOps & Infrastructure (5 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **devops-engineer.md** | CI/CD, containers, automation | Docker, docker-compose |
| **deployment-engineer.md** | Deployment strategies | Zero-downtime deployments |
| **sre-engineer.md** | Site Reliability Engineering | SLOs, toil reduction, automation |
| **incident-responder.md** | Incident management | Service failure response |
| **chaos-engineer.md** | Resilience testing | Failure injection testing |

### Developer Experience (5 agents)

| Agent | Description | Use in BigBrotr |
|-------|-------------|-----------------|
| **refactoring-specialist.md** | Safe and incremental refactoring | Code smell removal, complexity reduction |
| **dependency-manager.md** | Dependency management and security | requirements.txt, CVE scanning |
| **documentation-engineer.md** | Technical documentation | docs/, README, API docs |
| **legacy-modernizer.md** | System modernization | Python version updates |
| **data-engineer.md** | Data pipelines and ETL | Event sync pipelines |

---

## How to Use These Agents

1. **Copy the content** of an agent into your system prompt
2. **Adapt the context** to the specific BigBrotr task
3. **Combine agents** for complex tasks (e.g., `postgres-pro` + `performance-engineer` for DB optimization)

### Suggested Combinations for BigBrotr

| Task | Agents to Combine |
|------|-------------------|
| SQL query optimization | `postgres-pro` + `database-optimizer` + `sql-pro` |
| New async service | `python-pro` + `backend-developer` + `microservices-architect` |
| Complex bug fix | `debugger` + `error-detective` + `python-pro` |
| Security review | `security-auditor` + `penetration-tester` + `code-reviewer` |
| New version deploy | `devops-engineer` + `deployment-engineer` + `sre-engineer` |
| Code refactoring | `refactoring-specialist` + `code-reviewer` + `architect-reviewer` |
| Test automation | `test-automator` + `qa-expert` + `python-pro` |
| WebSocket issues | `websocket-engineer` + `debugger` + `performance-engineer` |

---

## Critical BigBrotr Areas to Improve

Based on project analysis, these agents are particularly useful for:

1. **Multiprocessing Complexity** (`debugger`, `python-pro`)
   - Synchronizer uses aiomultiprocess with worker processes
   - Possible race conditions and memory issues

2. **Connection Pool Tuning** (`postgres-pro`, `database-optimizer`)
   - 10 worker processes with 20 max connections
   - Potential contention under load

3. **WebSocket Reliability** (`websocket-engineer`, `chaos-engineer`)
   - No circuit breaker pattern implemented
   - No adaptive timeout

4. **Integration Testing** (`test-automator`, `qa-expert`)
   - Unit tests present, minimal integration tests
   - No end-to-end pipeline tests

5. **Monitoring & Observability** (`sre-engineer`, `devops-engineer`)
   - No Prometheus metrics
   - No health check endpoints

---

## Folder Structure

```
.claude/agents/
├── README.md                    # This file
│
├── bigbrotr-expert/             # BIGBROTR-SPECIFIC AGENT
│   ├── AGENT.md                 # System prompt (~1000 lines)
│   ├── architecture-index.md
│   ├── core-reference.md
│   ├── services-reference.md
│   ├── models-reference.md
│   ├── database-reference.md
│   └── testing-reference.md
│
├── nostr-expert/                # NOSTR-SPECIFIC AGENT
│   ├── AGENT.md                 # System prompt
│   ├── nip-index.md
│   ├── kind-index.md
│   ├── tag-index.md
│   ├── nostr-sdk-python-reference.md
│   └── khatru-reference.md
│
├── python-pro.md                # Python development
├── sql-pro.md                   # SQL queries
├── postgres-pro.md              # PostgreSQL specialist
├── database-optimizer.md        # DB performance
├── database-administrator.md    # DBA operations
├── backend-developer.md         # Backend development
├── microservices-architect.md   # Distributed systems
├── api-designer.md              # API design
├── websocket-engineer.md        # WebSocket/real-time
├── code-reviewer.md             # Code review
├── qa-expert.md                 # Quality assurance
├── test-automator.md            # Test automation
├── debugger.md                  # Debugging
├── error-detective.md           # Error analysis
├── performance-engineer.md      # Performance
├── security-auditor.md          # Security audit
├── penetration-tester.md        # Penetration testing
├── architect-reviewer.md        # Architecture review
├── devops-engineer.md           # DevOps
├── deployment-engineer.md       # Deployments
├── sre-engineer.md              # Site reliability
├── incident-responder.md        # Incident response
├── chaos-engineer.md            # Chaos engineering
├── refactoring-specialist.md    # Refactoring
├── dependency-manager.md        # Dependencies
├── documentation-engineer.md    # Documentation
├── legacy-modernizer.md         # Modernization
├── cli-developer.md             # CLI tools
└── data-engineer.md             # Data pipelines
```

---

*Auto-generated by analyzing BigBrotr v2.0.0*
