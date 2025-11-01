# Brotr - Extensible Nostr Relay Archiving Platform

**A modular, plugin-based system for archiving and monitoring the Nostr network with customizable storage strategies.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)

---

## 🎯 What is Brotr?

Brotr is an **extensible platform** for archiving and monitoring Nostr relays with **customizable storage strategies**. Through its plugin architecture, developers can create implementations tailored to their specific needs—from full archival to minimal indexing.

### Available Implementations

- **Bigbrotr**: Full event storage including tags and content (complete archival)
- **Lilbrotr**: Minimal event storage without tags/content (lightweight indexing)
- **YourBrotr**: Create your own! See [How to Create a Brotr Implementation](#-create-your-own-implementation)

---

## ✨ Key Features

### 🔌 Plugin Architecture
- **Create custom implementations** by just adding a folder
- **Automatic discovery** and registration
- **No core code changes** needed
- Choose the storage strategy that fits your needs

### 📊 Multiple Storage Strategies
- **Bigbrotr**: Complete archival (100% storage)
- **Lilbrotr**: Minimal indexing (10-20% storage)
- **Community**: Infinite possibilities

### 🚀 High Performance
- Asynchronous Python with `asyncio` and `asyncpg`
- Connection pooling with PgBouncer
- Efficient batch operations
- Optimized for millions of events

### 🛡️ Robust Design
- Microservices architecture
- Health monitoring and auto-restart
- Rate limiting and error handling
- Tor support for anonymity

### 📡 Comprehensive Monitoring
- NIP-11 relay information tracking
- NIP-66 connection testing
- Relay discovery and metadata

---

## 🏗️ Architecture

```
brotr/
├── brotr_core/                   # Core framework
│   ├── database/                 # Database abstractions
│   │   ├── brotr.py             # Unified Brotr class
│   │   ├── base_event_repository.py  # Abstract base
│   │   └── ...
│   ├── registry.py              # Plugin discovery system
│   └── services/                # Shared services
│
├── implementations/              # 🔌 Plugin directory
│   ├── bigbrotr/                # Full storage
│   ├── lilbrotr/                # Minimal storage
│   ├── _template/               # Quick-start template
│   └── yourbrotr/               # Add your own!
│
├── deployments/                 # Deployment configs
│   ├── bigbrotr/
│   └── lilbrotr/
│
└── shared/                      # Shared utilities
```

### Microservices

- **Synchronizer**: Fetches events from relays using adaptive binary search
- **Priority Synchronizer**: Dedicated service for high-priority relays
- **Monitor**: Collects relay metadata (NIP-11, NIP-66)
- **Finder**: Discovers new relays from Nostr events
- **Initializer**: Seeds database with relay lists
- **Database**: PostgreSQL with optimized schema
- **PgBouncer**: Connection pooling layer
- **PgAdmin**: Web-based database management
- **TorProxy**: Optional Tor routing for anonymity

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose
- 4GB+ RAM (8GB+ recommended for Bigbrotr)
- Python 3.9+ (for development)

### 1. Choose Your Implementation

**Bigbrotr** (Full Archival):
```bash
cd deployments/bigbrotr
```

**Lilbrotr** (Lightweight):
```bash
cd deployments/lilbrotr
```

### 2. Configure Environment

```bash
cp .env.example .env
nano .env
```

Key settings:
```bash
BROTR_MODE=bigbrotr  # or lilbrotr
POSTGRES_PASSWORD=your_secure_password
NOSTR_PRIVATE_KEY=your_nostr_private_key_hex
```

### 3. Launch

```bash
docker-compose up -d
```

### 4. Monitor

```bash
# View logs
docker-compose logs -f synchronizer

# Check status
docker-compose ps

# Access PgAdmin
open http://localhost:5050
```

---

## 🔌 Create Your Own Implementation

The power of Brotr is its **extensibility**. Create a custom implementation in just **3 steps**:

### Step 1: Create Directory

```bash
cd implementations/
cp -r _template yourbrotr
cd yourbrotr
```

### Step 2: Customize Schema

Edit `sql/init.sql`:
```sql
CREATE TABLE events (
    id          CHAR(64)    PRIMARY KEY,
    pubkey      CHAR(64)    NOT NULL,
    created_at  BIGINT      NOT NULL,
    kind        INTEGER     NOT NULL,
    -- ADD YOUR CUSTOM FIELDS HERE
    sig         CHAR(128)   NOT NULL
);
```

### Step 3: Implement Repository

Edit `repositories/event_repository.py`:
```python
class EventRepository(BaseEventRepository):
    async def insert_event(self, event, relay, seen_at=None):
        # Your custom storage logic
        pass
```

**That's it!** The system automatically discovers your implementation.

### Deploy Your Implementation

```bash
export BROTR_MODE=yourbrotr
docker-compose up -d
```

**Full guide**: [docs/HOW_TO_CREATE_BROTR.md](docs/HOW_TO_CREATE_BROTR.md)

---

## 📊 Implementation Comparison

| Feature | Bigbrotr | Lilbrotr | Custom |
|---------|----------|----------|--------|
| Event ID | ✅ | ✅ | ✅ |
| Pubkey | ✅ | ✅ | ✅ |
| Kind | ✅ | ✅ | ✅ |
| Tags | ✅ | ❌ | Your choice |
| Content | ✅ | ❌ | Your choice |
| Signature | ✅ | ✅ | ✅ |
| **Storage/Event** | ~500 bytes | ~100 bytes | **You decide!** |
| **Use Case** | Full archival | Network indexing | **Your needs!** |

**Detailed comparison**: [docs/architecture/COMPARISON.md](docs/architecture/COMPARISON.md)

---

## 📚 Documentation

### Getting Started
- [README.md](README.md) - This file
- [docs/PLUGIN_ARCHITECTURE_SUMMARY.md](docs/PLUGIN_ARCHITECTURE_SUMMARY.md) - Architecture overview
- [docs/HOW_TO_CREATE_BROTR.md](docs/HOW_TO_CREATE_BROTR.md) - Create your own implementation

### Architecture
- [docs/architecture/BROTR_ARCHITECTURE.md](docs/architecture/BROTR_ARCHITECTURE.md) - Technical design
- [docs/architecture/COMPARISON.md](docs/architecture/COMPARISON.md) - Implementation comparison
- [docs/PLUGIN_ARCHITECTURE_SUMMARY.md](docs/PLUGIN_ARCHITECTURE_SUMMARY.md) - Plugin system overview

### Migration & Deployment
- [docs/MIGRATION_GUIDE.md](docs/MIGRATION_GUIDE.md) - Upgrade from old architecture
- [deployments/bigbrotr/](deployments/bigbrotr/) - Bigbrotr deployment
- [deployments/lilbrotr/](deployments/lilbrotr/) - Lilbrotr deployment

### Development
- [CLAUDE.md](CLAUDE.md) - Development guide
- [implementations/_template/](implementations/_template/) - Implementation template
- [QUICK_REFERENCE.md](QUICK_REFERENCE.md) - Quick reference card

### Project History & Summaries
- [docs/summaries/](docs/summaries/) - Historical summaries and migration docs

---

## 🛠️ Development

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt
```

### Run Tests

```bash
# Test plugin discovery
python3 -c "from brotr_core.registry import list_implementations; print(list_implementations())"

# Expected output: ['bigbrotr', 'lilbrotr', ...]
```

### Create New Implementation

```bash
# Copy template
cp -r implementations/_template implementations/mediumbrotr

# Edit files
nano implementations/mediumbrotr/sql/init.sql
nano implementations/mediumbrotr/repositories/event_repository.py

# Test
export BROTR_MODE=mediumbrotr
python3 -c "from brotr_core.registry import get_implementation; print(get_implementation('mediumbrotr'))"
```

---

## 🎯 Use Cases

### Bigbrotr (Full Archival)
- 📚 **Complete Event Archive**: Store everything for historical analysis
- 🔍 **Content Search**: Full-text search across event content
- 🏷️ **Tag Analysis**: Complex queries on event tags
- 📊 **Data Research**: Comprehensive dataset for research

### Lilbrotr (Lightweight Indexing)
- 📱 **Low-Resource Devices**: Run on Raspberry Pi, VPS
- 🌐 **Network Topology**: Track relay distribution and event propagation
- ⚡ **High-Performance**: Index millions of events with minimal resources
- 📈 **Scaling**: Handle high throughput with limited storage

### Custom Implementations
- 🎯 **Filtered Storage**: Store only specific event kinds
- 🔒 **Compliance**: Exclude content for regulatory requirements
- 💾 **Compression**: Store compressed content to save space
- 🎨 **Domain-Specific**: Tailor storage to your application

---

## 🌟 Example Community Implementations

### MediumBrotr (Tags Only)
```
Stores: id, pubkey, kind, tags, sig
Use case: Tag queries without content
Storage: ~40% of Bigbrotr
```

### TinyBrotr (Existence Only)
```
Stores: id
Use case: Event existence verification
Storage: ~1% of Bigbrotr
```

### KindBrotr (Filtered by Kind)
```
Stores: Only specific event kinds
Use case: Domain-specific archival
Storage: Depends on filter
```

**Want to share your implementation?** Submit a PR!

---

## 📈 Performance

### Bigbrotr
- **Throughput**: ~500-1000 events/second
- **Storage**: ~500 bytes/event
- **RAM**: 4-8GB recommended
- **CPU**: 2-4 cores

### Lilbrotr
- **Throughput**: ~2000-5000 events/second
- **Storage**: ~100 bytes/event
- **RAM**: 2-4GB recommended
- **CPU**: 1-2 cores

*Performance varies based on hardware, network, and configuration.*

---

## 🔒 Security & Privacy

- **Tor Support**: Route traffic through Tor for anonymity
- **Connection Pooling**: Isolated database connections
- **Rate Limiting**: Prevent overwhelming relays
- **Error Isolation**: Failures don't propagate
- **Health Checks**: Automatic service restart

---

## 🤝 Contributing

We welcome contributions!

### Ways to Contribute
1. **Create implementations**: Share your custom storage strategies
2. **Improve core**: Enhance the plugin system
3. **Documentation**: Help others understand the system
4. **Bug reports**: File issues on GitHub
5. **Feature requests**: Suggest new capabilities

### Submission Process
1. Fork the repository
2. Create your feature branch
3. Make your changes
4. Test thoroughly
5. Submit a Pull Request

---

## 🗺️ Roadmap

### Completed ✅
- [x] Plugin architecture design
- [x] Auto-discovery system
- [x] Bigbrotr implementation
- [x] Lilbrotr implementation
- [x] Comprehensive documentation
- [x] Template for new implementations

### In Progress 🚧
- [ ] Community implementations
- [ ] Performance benchmarking
- [ ] Migration tools
- [ ] Web UI for implementation selection

### Future 🔮
- [ ] Implementation marketplace
- [ ] Automated testing framework
- [ ] Monitoring dashboard
- [ ] Multi-implementation support (run multiple simultaneously)

---

## 📞 Support

- **Documentation**: Check the `docs/` directory
- **Issues**: [GitHub Issues](https://github.com/yourusername/bigbrotr/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/bigbrotr/discussions)
- **Email**: support@brotr.dev (if applicable)

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## 🙏 Acknowledgments

- **Nostr Community**: For the decentralized protocol
- **Contributors**: Everyone who helps improve Brotr
- **OpenSats**: For grant support (if applicable)
- **You**: For using and contributing to Brotr!

---

## 🚀 Get Started Now!

```bash
# Clone and choose your implementation
git clone https://github.com/yourusername/bigbrotr.git
cd bigbrotr/deployments/bigbrotr  # or lilbrotr

# Configure
cp .env.example .env
nano .env

# Launch
docker-compose up -d

# Monitor
docker-compose logs -f
```

**Questions?** Check [docs/HOW_TO_CREATE_BROTR.md](docs/HOW_TO_CREATE_BROTR.md) or open an issue!

---

**Built with ❤️ for the Nostr ecosystem**

**Brotr**: Because your relay data deserves customizable storage! 🚀
