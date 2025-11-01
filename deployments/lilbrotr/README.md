# Lilbrotr Deployment

Minimal event indexing implementation for low-resource environments.

## Overview

Lilbrotr stores minimal Nostr events including ONLY:
- Event metadata (id, pubkey, created_at, kind, sig)
- **NO tags** (saves ~40% storage)
- **NO content** (saves ~50% storage)

**Storage**: ~100 bytes/event (10-20% of Bigbrotr)  
**RAM**: 2-4GB recommended  
**CPU**: 1-2 cores recommended  
**Use Case**: Event indexing, relay distribution tracking, network analysis

## Quick Start

```bash
# 1. Copy environment file
cp env.example .env

# 2. Edit configuration
nano .env

# 3. Start services
docker-compose up -d

# 4. View logs
docker-compose logs -f

# 5. Check status
docker-compose ps
```

## Configuration

Edit `.env` file:

```bash
# Key settings
BROTR_MODE=lilbrotr
POSTGRES_PASSWORD=your_secure_password_here
NOSTR_PRIVATE_KEY=your_nostr_private_key_hex_here

# Database init path (DO NOT CHANGE)
POSTGRES_DB_INIT_PATH=../../implementations/lilbrotr/sql/init.sql
```

## Services

- **database**: PostgreSQL with minimal event schema
- **pgbouncer**: Connection pooling
- **pgadmin**: Database management UI (http://localhost:5050)
- **torproxy**: Optional Tor routing
- **initializer**: Seeds database with relay lists
- **monitor**: Collects relay metadata (NIP-11, NIP-66)
- **synchronizer**: Fetches events from relays
- **priority_synchronizer**: Dedicated service for priority relays

## Resource Requirements

### Minimum (Perfect for Raspberry Pi!)
- RAM: 2GB
- CPU: 1 core
- Disk: 20GB (for ~200M events)

### Recommended
- RAM: 4GB
- CPU: 2 cores
- Disk: 100GB (for 1B+ events)

## Storage Estimates

| Events | Storage | RAM |
|--------|---------|-----|
| 1M     | ~100MB  | 2GB |
| 10M    | ~1GB    | 2GB |
| 100M   | ~10GB   | 3GB |
| 1B     | ~100GB  | 4GB |

## Performance Benefits

Compared to Bigbrotr:
- **80-90% less storage** per event
- **50% less RAM** required
- **2-5x faster** inserts
- **Perfect for**:
  - Raspberry Pi / Low-end VPS
  - Network analysis
  - Event existence verification
  - Relay health monitoring

## Management

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# Restart service
docker-compose restart synchronizer

# View logs
docker-compose logs -f synchronizer

# Database backup
docker-compose exec database pg_dump -U postgres lilbrotr > backup.sql

# Database restore
docker-compose exec -T database psql -U postgres lilbrotr < backup.sql
```

## Monitoring

- **PgAdmin**: http://localhost:5050 (or configured port)
- **Health Checks**: http://localhost:8000/health
- **Logs**: `docker-compose logs -f`

## Troubleshooting

### Services not starting
```bash
docker-compose down
docker-compose up -d
docker-compose logs
```

### Database connection issues
```bash
docker-compose exec database pg_isready -U postgres
docker-compose restart pgbouncer
```

### Still too much resource usage?
- Reduce `SYNCHRONIZER_NUM_CORES` to 1
- Reduce `SYNCHRONIZER_REQUESTS_PER_CORE` to 2
- Reduce `MONITOR_NUM_CORES` to 1
- Reduce `MONITOR_CHUNK_SIZE` to 2
- Set `SYNCHRONIZER_BATCH_SIZE` to 250

## Use Cases

### ✅ Perfect For:
- Network topology analysis
- Event distribution tracking
- Relay health monitoring
- Low-resource devices (Raspberry Pi, low-end VPS)
- Event existence verification
- Timeline construction (without content display)

### ❌ Not Suitable For:
- Content search
- Tag-based filtering
- Full event display
- Content analysis

## Upgrading

```bash
# Stop services
docker-compose down

# Pull latest images
docker-compose pull

# Start services
docker-compose up -d
```

## Migrating to Bigbrotr

If you need full event storage later:

1. Stop Lilbrotr: `docker-compose down`
2. Switch to Bigbrotr deployment: `cd ../bigbrotr`
3. Copy configuration: `cp ../lilbrotr/.env .env`
4. Update `BROTR_MODE=bigbrotr` in `.env`
5. Update `POSTGRES_DB_INIT_PATH=../../implementations/bigbrotr/sql/init.sql`
6. Start Bigbrotr: `docker-compose up -d`

**Note**: Existing events will not have tags/content retroactively filled.

## Documentation

- Main documentation: `../../README.md`
- Architecture: `../../docs/architecture/BROTR_ARCHITECTURE.md`
- Comparison: `../../docs/architecture/COMPARISON.md`
- Creating custom implementations: `../../docs/HOW_TO_CREATE_BROTR.md`

## Support

- Issues: GitHub Issues
- Discussions: GitHub Discussions
- Documentation: `docs/` directory
