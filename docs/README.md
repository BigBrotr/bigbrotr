# BigBrotr Documentation

Comprehensive documentation for the BigBrotr Nostr network intelligence platform.

---

## Quick Links

### Getting Started

- **[OVERVIEW.md](OVERVIEW.md)** - Marketing-focused project overview
  - What is BigBrotr?
  - Key features and use cases
  - Quick start guide
  - Deployment options
  - Perfect for: Users, stakeholders, decision-makers

- **[TECHNICAL.md](TECHNICAL.md)** - Deep technical architecture
  - System architecture (four-layer design)
  - Core components (Pool, Brotr, BaseService, Logger)
  - Service layer (Seeder, Finder, Validator, Monitor, Synchronizer)
  - Utils layer (network, parsing, transport, YAML, keys)
  - Data models and database schema
  - Design patterns and performance characteristics
  - Perfect for: Developers, architects, contributors

---

## Documentation Index

### For Users

| Document | Description |
|----------|-------------|
| [OVERVIEW.md](OVERVIEW.md) | High-level introduction, features, and getting started |
| [../README.md](../README.md) | Repository README with quick setup |
| [../CLAUDE.md](../CLAUDE.md) | Development guide for Claude Code users |

### For Developers

| Document | Description |
|----------|-------------|
| [TECHNICAL.md](TECHNICAL.md) | Complete technical architecture and implementation details |
| [../CLAUDE.md](../CLAUDE.md) | Service development patterns and architecture |
| Agent Docs | Specialized knowledge agents (see below) |

### For Contributors

| Document | Description |
|----------|-------------|
| [TECHNICAL.md](TECHNICAL.md) | Architecture, patterns, and design decisions |
| [../tests/](../tests/) | Test organization and examples |
| [../.claude/agents/bigbrotr-expert/](../.claude/agents/bigbrotr-expert/) | Comprehensive codebase reference |

---

## Agent Documentation

BigBrotr includes specialized knowledge agents for development:

### Nostr Expert Agent

**Location:** `.claude/agents/nostr-expert/`

Expert on Nostr protocol, NIPs, and implementation.

| File | Description |
|------|-------------|
| [AGENT.md](../.claude/agents/nostr-expert/AGENT.md) | Main agent documentation |
| [nip-index.md](../.claude/agents/nostr-expert/nip-index.md) | NIPs organized by category |
| [kind-index.md](../.claude/agents/nostr-expert/kind-index.md) | All 150+ event kinds |
| [tag-index.md](../.claude/agents/nostr-expert/tag-index.md) | Common tags and usage |
| [nostr-sdk-python-reference.md](../.claude/agents/nostr-expert/nostr-sdk-python-reference.md) | Python SDK docs |
| [khatru-reference.md](../.claude/agents/nostr-expert/khatru-reference.md) | Go relay framework docs |

### BigBrotr Expert Agent

**Location:** `.claude/agents/bigbrotr-expert/`

Expert on BigBrotr codebase, architecture, and patterns.

| File | Description |
|------|-------------|
| [AGENT.md](../.claude/agents/bigbrotr-expert/AGENT.md) | Main agent documentation |
| [architecture-index.md](../.claude/agents/bigbrotr-expert/architecture-index.md) | Component relationships and design patterns |
| [core-reference.md](../.claude/agents/bigbrotr-expert/core-reference.md) | Pool, Brotr, BaseService, Logger API |
| [services-reference.md](../.claude/agents/bigbrotr-expert/services-reference.md) | All services with configs and workflows |
| [models-reference.md](../.claude/agents/bigbrotr-expert/models-reference.md) | Data models and database mappings |
| [database-reference.md](../.claude/agents/bigbrotr-expert/database-reference.md) | Schema, procedures, views, queries |
| [testing-reference.md](../.claude/agents/bigbrotr-expert/testing-reference.md) | Testing patterns, fixtures, examples |

---

## Documentation by Audience

### I want to...

#### Understand what BigBrotr does
→ Read [OVERVIEW.md](OVERVIEW.md)

#### Get BigBrotr running quickly
→ Follow quick start in [OVERVIEW.md](OVERVIEW.md#getting-started)

#### Understand the technical architecture
→ Read [TECHNICAL.md](TECHNICAL.md)

#### Add a new service
→ See [TECHNICAL.md](TECHNICAL.md#service-layer) and [BigBrotr Expert Agent](../.claude/agents/bigbrotr-expert/services-reference.md)

#### Work with the database
→ See [TECHNICAL.md](TECHNICAL.md#database-schema) and [database-reference.md](../.claude/agents/bigbrotr-expert/database-reference.md)

#### Implement Nostr protocol features
→ Read [Nostr Expert Agent](../.claude/agents/nostr-expert/AGENT.md)

#### Write tests
→ See [testing-reference.md](../.claude/agents/bigbrotr-expert/testing-reference.md)

#### Deploy to production
→ See [TECHNICAL.md](TECHNICAL.md#deployment-architecture)

#### Understand design decisions
→ Read [TECHNICAL.md](TECHNICAL.md#design-patterns) and [architecture-index.md](../.claude/agents/bigbrotr-expert/architecture-index.md)

#### Troubleshoot issues
→ Check [BigBrotr Expert Agent](../.claude/agents/bigbrotr-expert/AGENT.md) troubleshooting section

---

## Documentation Status

| Document | Status | Last Updated | Audience |
|----------|--------|--------------|----------|
| OVERVIEW.md | ✅ Complete | 2025-12-28 | Users, stakeholders |
| TECHNICAL.md | ✅ Complete | 2025-12-28 | Developers, architects |
| Nostr Expert Agent | ✅ Complete | 2025-12-27 | Protocol developers |
| BigBrotr Expert Agent | ✅ Complete | 2025-12-28 | Codebase contributors |
| API Reference | 🚧 Planned | TBD | API consumers |
| User Guide | 🚧 Planned | TBD | End users |
| Operations Manual | 🚧 Planned | TBD | Operators, DevOps |

---

## Contributing to Documentation

Documentation contributions are welcome! Please:

1. Keep technical accuracy high
2. Include code examples where relevant
3. Update the index when adding new docs
4. Follow the existing style and structure
5. Test all code examples before submitting

---

## License

All documentation is licensed under MIT License - see [../LICENSE](../LICENSE) for details.

---

**Questions?** Open an issue or discussion on GitHub.
