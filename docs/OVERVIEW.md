# BigBrotr: Nostr Network Intelligence Platform

**A powerful, modular system for archiving, monitoring, and analyzing the Nostr protocol ecosystem.**

---

## What is BigBrotr?

BigBrotr is a comprehensive data intelligence platform for the Nostr network. It automatically discovers relays, monitors their health and capabilities, and archives events across the decentralized social network—giving you complete visibility into the Nostr ecosystem.

Think of it as your personal observatory for the Nostr universe: discovering new relays as they come online, tracking their reliability and features, and building a complete archive of network activity.

---

## Why BigBrotr?

### The Problem

The Nostr network is inherently decentralized with thousands of relays scattered across the internet. This creates challenges:

- **Discovery**: How do you find all available relays?
- **Reliability**: Which relays are actually online and working?
- **Capabilities**: What features does each relay support?
- **Data Preservation**: How do you ensure important events aren't lost?
- **Analytics**: How do you understand network-wide patterns?

### The Solution

BigBrotr solves these challenges with an automated, always-on system that:

1. **Discovers** relays from multiple sources (APIs, network events, relay lists)
2. **Validates** each relay to ensure it's accessible and functional
3. **Monitors** relay health, performance, and supported features (NIP-11, NIP-66)
4. **Archives** events from across the network for analysis and preservation
5. **Tracks** changes over time with historical metadata

All running autonomously with minimal configuration.

---

## Key Features

### 🔍 Automatic Relay Discovery

- **API Integration**: Pulls relay lists from services like nostr.watch
- **Event Mining**: Extracts relay URLs from kind 2, 3, and 10002 events
- **Network Scanning**: Discovers relays mentioned in user profiles and relay lists
- **Continuous Operation**: Runs 24/7 finding new relays as they appear

### ✅ Intelligent Validation

- **Connection Testing**: Verifies each relay is actually reachable
- **WebSocket Validation**: Tests real Nostr protocol communication
- **Tor Support**: First-class support for .onion relays via SOCKS5
- **Retry Logic**: Smart retry with exponential backoff for flaky networks
- **NIP-42 Authentication**: Handles authenticated relay access

### 📊 Comprehensive Monitoring

**NIP-11 Compliance**: Fetches relay information documents
- Name, description, operator contact
- Supported NIPs (protocol features)
- Limitations (max event size, rate limits, etc.)
- Payment requirements and fees

**NIP-66 Monitoring**: Advanced health checks
- **Open/Read/Write Tests**: Measures actual relay functionality
- **Round-Trip Time (RTT)**: Performance metrics for each operation
- **SSL/TLS Validation**: Certificate checking and expiration tracking
- **DNS Resolution**: Monitors DNS lookup performance
- **Geolocation**: Maps relay physical locations (country, city, coordinates)
- **Event Publishing**: Publishes monitoring data as Nostr events (kind 30166)

### 💾 Event Archiving

- **Multiprocessing**: Uses all CPU cores for high-throughput collection
- **Filter Support**: Customize which event kinds to archive
- **Deduplication**: Prevents storing duplicate events
- **Junction Tracking**: Records which relays host which events
- **Timestamp Preservation**: Maintains original event metadata

### 🗄️ Flexible Storage

Two deployment modes to match your needs:

**BigBrotr (Full)**: Complete event storage
- All event fields: tags, content, signatures
- Full-text search and complex queries
- Maximum data retention (~100% storage)

**LilBrotr (Lightweight)**: Essential metadata only
- Event IDs, authors, kinds, timestamps
- 60% less disk space
- Fast queries for event discovery
- Perfect for relay monitoring focus

### 🌐 Privacy-First Design

- **Tor Integration**: Built-in SOCKS5 proxy support for .onion relays
- **Network Detection**: Automatically identifies Tor, I2P, Loki networks
- **Separate Timeouts**: Optimized settings for clearnet vs. Tor
- **No Leaks**: Local IP addresses rejected from database

---

## Use Cases

### 🔬 Researchers

- **Network Analysis**: Study relay distribution, growth patterns, and censorship resistance
- **Event Archaeology**: Analyze historical Nostr events and user behavior
- **Protocol Evolution**: Track NIP adoption across the network
- **Relay Economics**: Monitor payment requirements and fee structures

### 🏗️ Relay Operators

- **Competitive Intelligence**: See what features other relays offer
- **Performance Benchmarking**: Compare your relay's RTT against the network
- **Network Health**: Monitor the overall ecosystem you're part of
- **Discovery**: Get your relay indexed and monitored automatically

### 👨‍💻 Client Developers

- **Relay Selection**: Find the best relays for your users based on real metrics
- **Fallback Discovery**: Maintain lists of reliable backup relays
- **Feature Detection**: Query which relays support specific NIPs
- **Geographic Distribution**: Route users to nearby relays

### 📈 Network Observers

- **Real-Time Dashboard**: Track relay count, event volume, network growth
- **Outage Detection**: Identify when relays go offline
- **Geographic Mapping**: Visualize relay locations worldwide
- **Censorship Monitoring**: Detect relay blocking and network partitions

---

## How It Works

BigBrotr operates as a suite of autonomous services that work together:

```
┌─────────────────────────────────────────────────────────┐
│                    BigBrotr Pipeline                     │
└─────────────────────────────────────────────────────────┘

1. FINDER
   ↓ Discovers relay URLs from APIs and events
   ↓ Stores candidates for validation

2. VALIDATOR
   ↓ Tests WebSocket connections
   ↓ Validates relay functionality
   ↓ Inserts working relays to database

3. MONITOR
   ↓ Performs NIP-11/NIP-66 health checks
   ↓ Measures RTT, SSL, DNS, geolocation
   ↓ Publishes monitoring events

4. SYNCHRONIZER
   ↓ Connects to validated relays
   ↓ Archives events in parallel
   ↓ Tracks event-relay relationships
```

Each service runs independently and can be scaled separately based on your needs.

---

## Technical Highlights

### Modern Python Stack

- **Python 3.11+**: Async-first with `asyncio`
- **PostgreSQL**: Robust relational storage with JSONB
- **nostr-sdk**: Rust-powered protocol implementation via Python bindings
- **Docker**: One-command deployment with compose

### Production-Ready Design

- **Connection Pooling**: Efficient database access with PGBouncer
- **Retry Logic**: Exponential backoff for network failures
- **Graceful Shutdown**: Clean service lifecycle management
- **Structured Logging**: Key-value output for easy parsing
- **Health Checks**: Built-in monitoring for all components

### Scalable Architecture

- **Multiprocessing**: Synchronizer uses all CPU cores
- **Concurrent I/O**: Asyncio for high network throughput
- **Batched Operations**: Efficient bulk database inserts
- **Materialized Views**: Pre-computed queries for fast reads
- **Content-Addressed Storage**: Automatic metadata deduplication (~90% savings)

### Developer-Friendly

- **Modular Design**: Easy to add new services
- **Comprehensive Tests**: Unit tests with >80% coverage
- **Type Hints**: Full mypy type checking
- **Pre-commit Hooks**: Automatic code quality enforcement
- **Clear Documentation**: Architecture guides and API references

---

## Getting Started

### Quick Start (5 minutes)

```bash
# Clone repository
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr/implementations/bigbrotr

# Configure
cp .env.example .env
# Edit .env and set DB_PASSWORD

# Launch
docker-compose up -d

# Check status
docker-compose logs -f
```

That's it! BigBrotr will:
1. Initialize the database schema
2. Load seed relays
3. Start discovering new relays
4. Begin monitoring and archiving

### Customization

Create your own implementation by copying and modifying:

```bash
cp -r implementations/bigbrotr implementations/myproject
cd implementations/myproject

# Customize:
# - yaml/services/*.yaml (service configs)
# - postgres/init/02_tables.sql (schema)
# - docker-compose.yaml (ports, resources)
```

---

## Deployment Options

### Single Server

Perfect for personal projects or small networks:
- 4 CPU cores
- 8GB RAM
- 100GB+ SSD storage
- PostgreSQL + PGBouncer + Tor
- All services on one machine

### Distributed

For high-volume archiving or large networks:
- Separate database server (PostgreSQL cluster)
- Multiple synchronizer workers across machines
- Load-balanced monitor instances
- Centralized finder/validator
- Petabyte-scale storage potential

### Cloud-Native

Deploy on any platform:
- AWS (RDS + ECS/Fargate)
- Google Cloud (Cloud SQL + GKE)
- DigitalOcean (Managed Postgres + Droplets)
- Kubernetes manifests included

---

## Data Access

All data is stored in PostgreSQL and accessible via:

### SQL Queries

```sql
-- Find most popular relays by event count
SELECT relay_url, COUNT(*) as event_count
FROM events_relays
GROUP BY relay_url
ORDER BY event_count DESC
LIMIT 10;

-- Relays supporting NIP-42 authentication
SELECT url, data->'supported_nips' as nips
FROM relays r
JOIN relay_metadata_latest rml ON r.url = rml.relay_url
WHERE rml.type = 'nip11_fetch'
  AND data->'supported_nips' @> '42';

-- Events by kind distribution
SELECT kind, COUNT(*) as count
FROM events
GROUP BY kind
ORDER BY count DESC;
```

### REST API (Coming Soon)

Query relays, events, and monitoring data via HTTP API.

### GraphQL (Planned)

Flexible queries with real-time subscriptions.

### Data Export

- CSV/JSON dumps
- Nostr event streams
- PostgreSQL logical replication

---

## Monitoring Dashboard

BigBrotr publishes its monitoring data as Nostr events:

- **Kind 30166**: Per-relay monitoring data (NIP-66)
- **Kind 10166**: Monitor announcement and capabilities
- Published to monitored relays or custom relay list
- Compatible with existing NIP-66 tools

---

## Community & Support

### Open Source

BigBrotr is free and open-source software:
- MIT License
- Community contributions welcome
- Public roadmap and issue tracker

### Documentation

- Architecture guides
- API references
- Service development tutorials
- Database schema documentation
- Testing patterns

### Support Channels

- GitHub Issues: Bug reports and feature requests
- GitHub Discussions: Questions and community help
- Documentation: Comprehensive guides and examples

---

## Roadmap

### Short-term (Q1 2025)

- [ ] REST API for data access
- [ ] Real-time event streaming
- [ ] Web dashboard for monitoring
- [ ] Export tools (CSV, JSON, Parquet)

### Medium-term (Q2-Q3 2025)

- [ ] GraphQL API
- [ ] Advanced analytics (network graphs, event flows)
- [ ] Machine learning relay scoring
- [ ] Automated relay classification

### Long-term (Q4 2025+)

- [ ] Distributed archiving network
- [ ] IPFS/Torrent event distribution
- [ ] Historical event replay
- [ ] Network simulation tools

---

## Why "BigBrotr"?

The name is a playful twist on "Big Brother"—but with a key difference:

- **Transparent**: All code is open-source
- **Decentralized**: You run your own instance
- **Permissionless**: No central authority controls the data
- **Privacy-Respecting**: Tor support and local-only processing

BigBrotr watches the Nostr network, but it's *your* observer, under *your* control, serving *your* needs.

---

## License

MIT License - see [LICENSE](../LICENSE) for details.

---

## Get Involved

- ⭐ Star the repository
- 🐛 Report bugs and request features
- 💻 Contribute code and documentation
- 💬 Join discussions and help others
- 📢 Share your BigBrotr use case

---

**Built with ❤️ for the Nostr community**

*Decentralized social networking deserves decentralized infrastructure.*
