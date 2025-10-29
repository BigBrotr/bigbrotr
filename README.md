# Bigbrotr

<div align="center">

**Full-Network Archival System for the Nostr Protocol**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![PostgreSQL 15](https://img.shields.io/badge/PostgreSQL-15-blue.svg)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-required-blue.svg)](https://www.docker.com/)

[Features](#-features) • [Architecture](#-architecture) • [Quick Start](#-quick-start) • [Documentation](#-documentation) • [Contributing](#-contributing)

</div>

---

## 📖 What is Bigbrotr?

**Bigbrotr** is an advanced, open-source archival infrastructure built for the [Nostr](https://nostr.com) protocol. It continuously monitors, archives, and analyzes **all public events** across the entire network—including both clearnet and Tor relays—while providing deep insights into relay behavior, event redundancy, network topology, and relay health metrics.

Think of Bigbrotr as a "black box" recorder for Nostr: continuously collecting, mapping, and analyzing everything happening across relays in real time. Unlike solutions that focus on isolated protocol features, Bigbrotr functions as a **full-archive instance** of the entire network, offering structured metadata and powerful analytical tools tailored for developers, researchers, relay operators, and power users.

### Why It Matters

Nostr's decentralized nature eliminates central authority, granting unprecedented freedom but also creating challenges around network visibility, coordination, and data integrity. Bigbrotr addresses these challenges by serving as a comprehensive, transparent archive of the entire Nostr ecosystem, enabling:

- **Network Transparency**: Understand relay uptime, behavior, and real-world performance metrics
- **Decentralization Monitoring**: Detect and prevent centralization risks by discovering and mapping new relays
- **Research & Analysis**: Access structured data ideal for social graph analysis, spam detection, and protocol research
- **Historical Preservation**: Archive valuable network data before it disappears from ephemeral relays
- **Advanced Services**: Build Data Vending Machines (DVMs) and custom integrations on top of comprehensive data

Built by and for the FOSS community, Bigbrotr is MIT licensed and designed to foster a transparent, open, and truly decentralized Nostr ecosystem.

---

## ✨ Features

### Core Capabilities

- 🗂 **Full Event Archive** - Chronologically stores all events from every reachable relay
- 🌍 **Relay Discovery** - Detects and indexes new relays across the network
- 🛰 **Live Monitoring** - Measures relay health and connectivity (RTT, availability, NIP compliance)
- 🔍 **Redundancy Tracking** - Tracks which relays host each event, revealing true network distribution
- 🧅 **Tor-Enabled** - Built-in Tor support for full `.onion` relay access
- 📊 **Network Analytics** - Provides insights into relay performance, event propagation, and network topology
- 🧠 **Graph Analysis Ready** - Ideal for social graph research, spam detection, and protocol analysis

### Technical Highlights

- ⚡ **High-Performance Async Architecture** - Built with Python asyncio and asyncpg for maximum throughput
- 🔄 **Optimized Connection Pooling** - PgBouncer + per-thread pools reduce database connections by 80%
- 🐳 **Docker-Native Microservices** - Easy deployment with docker-compose
- 🗄️ **Normalized Database Schema** - Efficient storage with hash-based deduplication
- 🔐 **Security-First Design** - Non-root containers, input validation, configurable resource limits
- �� **Production-Ready** - Health checks, graceful shutdown, failure tracking, and monitoring endpoints

---

## 🏗️ Architecture

Bigbrotr uses a **microservices architecture** with Docker containers coordinating through a shared PostgreSQL database with PgBouncer connection pooling.

### Service Overview

```
┌─────────────────┐
│   Initializer   │  Seeds database with initial relay list
└────────┬────────┘
         │
    ┌────▼─────────────────────────────────────┐
    │         PostgreSQL + PgBouncer           │  Normalized schema with deduplication
    └────▲─────────────────────────────────────┘
         │
    ┌────┴────┬──────────┬────────────┬────────────┐
    │         │          │            │            │
┌───▼───┐ ┌──▼──┐  ┌────▼─────┐ ┌────▼──────────┐ │
│Monitor│ │Sync │  │Priority  │ │   TorProxy    │ │
│       │ │     │  │   Sync   │ │   (SOCKS5)    │ │
└───────┘ └─────┘  └──────────┘ └───────────────┘ │
                                                   │
                                            ┌──────▼─────┐
                                            │  pgAdmin   │
                                            └────────────┘
```

### Service Descriptions

| Service | Purpose | Health Check |
|---------|---------|--------------|
| **Initializer** | Seeds database with initial relay URLs from `seed_relays.txt` | One-time |
| **Monitor** | Tests relay health, fetches NIP-11/NIP-66 metadata, measures RTT | `localhost:8081/health` |
| **Synchronizer** | Archives events from all readable relays (excludes priority list) | `localhost:8082/health` |
| **Priority Synchronizer** | Archives events from high-priority relays with dedicated resources | `localhost:8083/health` |
| **PgBouncer** | Connection pooling layer (1000 max clients, 100 DB connections) | Transaction pooling |
| **TorProxy** | SOCKS5 proxy for accessing `.onion` relays | Built-in |
| **pgAdmin** | Web UI for database management | `localhost:8080` |

### Database Schema

**Normalized PostgreSQL 15 schema** with hash-based deduplication:

- **events** - All Nostr events (id, pubkey, created_at, kind, tags, content, sig)
- **relays** - Relay registry (url, network, inserted_at)
- **events_relays** - Junction table tracking event distribution across relays
- **nip11** - Deduplicated NIP-11 relay information (SHA-256 hash PK)
- **nip66** - Deduplicated NIP-66 connection test results (SHA-256 hash PK)
- **relay_metadata** - Time-series snapshots linking relays to metadata

**Stored Procedures**: Atomic operations for event insertion, relay management, and metadata deduplication

**Views**: `relay_metadata_latest`, `readable_relays` for optimized queries

---

## 🚀 Quick Start

### Prerequisites

- **Docker** and **Docker Compose** installed
- **8GB+ RAM** recommended for production use
- **100GB+ storage** for event archival (grows over time)

### Installation

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/bigbrotr.git
   cd bigbrotr
   ```

2. **Configure environment**
   ```bash
   cp env.example .env
   nano .env  # Edit configuration (set passwords, adjust cores, etc.)
   ```

3. **Generate Nostr keypair** (for relay authentication)
   ```bash
   # Use any Nostr key generator or:
   # npx nostr-keygen
   # Add keys to .env: SECRET_KEY and PUBLIC_KEY
   ```

4. **Start services**
   ```bash
   docker-compose up -d
   ```

5. **Monitor logs**
   ```bash
   docker-compose logs -f monitor synchronizer
   ```

6. **Access pgAdmin** (optional)
   - Navigate to `http://localhost:8080`
   - Login with credentials from `.env`

### Verify Deployment

Check service health:
```bash
curl http://localhost:8081/health  # Monitor
curl http://localhost:8082/health  # Synchronizer
curl http://localhost:8083/health  # Priority Synchronizer
```

Check database:
```bash
docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "SELECT COUNT(*) FROM events;"
```

---

## ⚙️ Configuration

All configuration is done via environment variables in `.env`. Key settings:

### Database & Infrastructure

```bash
POSTGRES_USER=admin
POSTGRES_PASSWORD=your_secure_password_here
POSTGRES_DB=bigbrotr
DB_PORT=5432
PGADMIN_PORT=8080
```

### Nostr Authentication

```bash
SECRET_KEY=your_64_hex_char_private_key
PUBLIC_KEY=your_64_hex_char_public_key
```

### Monitor Service

```bash
MONITOR_FREQUENCY_HOUR=8         # Run every 8 hours
MONITOR_NUM_CORES=8              # CPU cores to use
MONITOR_CHUNK_SIZE=50            # Relays per chunk
MONITOR_REQUESTS_PER_CORE=10     # Parallel requests per core
MONITOR_REQUEST_TIMEOUT=20       # Timeout in seconds
```

### Synchronizer Service

```bash
SYNCHRONIZER_NUM_CORES=8                    # CPU cores to use
SYNCHRONIZER_REQUESTS_PER_CORE=10           # Parallel requests per core
SYNCHRONIZER_BATCH_SIZE=500                 # Events per pagination request
SYNCHRONIZER_RELAY_METADATA_THRESHOLD_HOURS=12  # Only sync relays with fresh metadata
SYNCHRONIZER_START_TIMESTAMP=0              # Start time (0 = genesis, -1 = from last sync)
SYNCHRONIZER_STOP_TIMESTAMP=-1              # End time (-1 = now)
```

### Resource Limits

Services have Docker resource limits configured in `docker-compose.yml`:
- Database: 4 CPU / 4GB RAM
- Synchronizers: 6 CPU / 4GB RAM
- Monitor: 4 CPU / 2GB RAM

Adjust these based on your hardware.

---

## 📚 Documentation

### For Users

- **[Quick Start Guide](CLAUDE.md#development-commands)** - Get up and running in minutes
- **[Configuration Reference](CLAUDE.md#configuration)** - All environment variables explained
- **[Database Schema](CLAUDE.md#database-schema)** - Understanding the data model
- **[Health Checks](CLAUDE.md#health-checks)** - Monitoring service status

### For Developers

- **[Architecture Overview](CLAUDE.md#architecture)** - System design and service interactions
- **[Development Guide](CLAUDE.md#best-practices)** - Code patterns and best practices
- **[API Reference](CLAUDE.md#core-classes)** - Core classes and methods
- **[Improvements Roadmap](IMPROVEMENTS_ROADMAP.md)** - Planned enhancements (89 items)

### Dependencies

Built with modern Python async stack:

- **[nostr-tools](https://pypi.org/project/nostr-tools/)** v1.2.1 - Nostr protocol library
- **asyncpg** v0.29.0 - High-performance async PostgreSQL driver
- **aiohttp** v3.9.3 - Async HTTP client
- **aiohttp-socks** v0.8.4 - Tor proxy support
- **PostgreSQL** 15 (Alpine) - Relational database
- **PgBouncer** - Connection pooling

---

## 🛠️ Common Tasks

### View Service Status

```bash
docker-compose ps
```

### Check Database Connection Pool

```bash
docker exec -it bigbrotr_pgbouncer psql -p 6432 -U admin pgbouncer -c "SHOW POOLS;"
```

### Query Event Count by Relay

```bash
docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "
  SELECT relay_url, COUNT(*) as event_count
  FROM events_relays
  GROUP BY relay_url
  ORDER BY event_count DESC
  LIMIT 10;
"
```

### Manually Trigger Monitor

```bash
docker-compose restart monitor
```

### View Real-Time Logs

```bash
docker-compose logs -f --tail=100 synchronizer
```

### Backup Database

```bash
docker exec bigbrotr_database pg_dump -U admin bigbrotr | gzip > backup_$(date +%Y%m%d).sql.gz
```

### Restore Database

```bash
gunzip -c backup_20250129.sql.gz | docker exec -i bigbrotr_database psql -U admin bigbrotr
```

---

## 🔍 Use Cases

### 1. Relay Operators

- Monitor your relay's health and performance metrics
- Compare your relay's uptime against network averages
- Understand event propagation patterns to your relay

### 2. Researchers

- Analyze social graph structures and user interaction patterns
- Study event propagation and network topology
- Detect spam, abuse, and centralization risks
- Export data snapshots for external analysis

### 3. Developers

- Build DVMs (Data Vending Machines) on comprehensive event data
- Create analytics dashboards and visualization tools
- Develop relay discovery and recommendation systems
- Test NIP compliance and protocol behavior

### 4. Power Users

- Track event redundancy across relays
- Discover new relays and assess their reliability
- Archive personal data before relay shutdowns
- Access historical network data

---

## 🤝 Contributing

Bigbrotr is open-source and welcomes contributions! Here's how you can help:

### Ways to Contribute

- 🐛 **Report Bugs** - Open an issue with reproduction steps
- 💡 **Suggest Features** - Share ideas for improvements
- 📝 **Improve Documentation** - Fix typos, add examples, clarify concepts
- 🔧 **Submit Pull Requests** - Fix bugs or implement new features
- 🧪 **Test & Review** - Try new features and provide feedback

### Development Setup

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Test thoroughly (see [CLAUDE.md](CLAUDE.md) for development commands)
5. Commit with clear messages (`git commit -m 'Add amazing feature'`)
6. Push to your branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

### Code Standards

- Follow PEP 8 style guidelines
- Use type hints for all functions
- Add docstrings for public APIs
- Test async code with proper error handling
- Use async context managers for resource management

---

## 📊 Roadmap

### Near-Term (Q1 2025)

- [ ] Interactive dashboards for real-time network insights
- [ ] Public API for relay health monitoring
- [ ] Exportable metrics for relay operators
- [ ] Circuit breaker pattern for failed relays
- [ ] Comprehensive type hints across codebase

### Medium-Term (Q2 2025)

- [ ] Grafana integration with Prometheus endpoints
- [ ] Public explorer to browse relays and events
- [ ] Downloadable data snapshots for researchers
- [ ] Unit and integration test suite
- [ ] Advanced query optimization with prepared statements

### Long-Term (Q3+ 2025)

- [ ] Nostr bot for network statistics
- [ ] Data Vending Machines leveraging archived data
- [ ] Machine learning for spam detection
- [ ] Distributed archival across multiple instances
- [ ] GraphQL API for flexible querying

See [IMPROVEMENTS_ROADMAP.md](IMPROVEMENTS_ROADMAP.md) for detailed breakdown (89 planned improvements).

---

## 📜 License

Bigbrotr is released under the **MIT License**. See [LICENSE](LICENSE) for details.

```
Copyright (c) 2024 Bigbrotr Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

---

## 🙏 Acknowledgments

- **Nostr Protocol** - For creating a truly decentralized communication protocol
- **nostr-tools** - Python library that powers Bigbrotr's Nostr interactions
- **PostgreSQL & PgBouncer** - Robust database foundation
- **Docker** - Simplifying deployment and scaling
- **FOSS Community** - For inspiring open, transparent infrastructure

---

## 📞 Support & Community

- **Issues**: [GitHub Issues](https://github.com/yourusername/bigbrotr/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/bigbrotr/discussions)
- **Nostr**: Follow project updates on Nostr (coming soon)

---

<div align="center">

**Built with ⚡ for a decentralized future**

[⬆ Back to Top](#bigbrotr)

</div>
