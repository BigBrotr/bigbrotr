# Bigbrotr Deployment

Full event archival implementation with complete storage of event tags and content.

## Overview

Bigbrotr stores complete Nostr events including:
- Event metadata (id, pubkey, created_at, kind, sig)
- Event tags (JSONB array for flexible querying)
- Event content (full text content)

**Storage**: ~500 bytes/event  
**RAM**: 4-8GB recommended  
**CPU**: 2-4 cores recommended  
**Use Case**: Complete archival, content analysis, tag-based queries

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
BROTR_MODE=bigbrotr
POSTGRES_PASSWORD=your_secure_password_here
NOSTR_PRIVATE_KEY=your_nostr_private_key_hex_here

# Database init path (DO NOT CHANGE)
POSTGRES_DB_INIT_PATH=../../implementations/bigbrotr/sql/init.sql
```

## Services

- **database**: PostgreSQL with full event schema
- **pgbouncer**: Connection pooling
- **pgadmin**: Database management UI (http://localhost:5050)
- **torproxy**: Optional Tor routing
- **initializer**: Seeds database with relay lists
- **monitor**: Collects relay metadata (NIP-11, NIP-66)
- **synchronizer**: Fetches events from relays
- **priority_synchronizer**: Dedicated service for priority relays

## Resource Requirements

### Minimum
- RAM: 4GB
- CPU: 2 cores
- Disk: 100GB (for ~200M events)

### Recommended
- RAM: 8GB
- CPU: 4 cores
- Disk: 500GB+ (for 1B+ events)

## Storage Estimates

| Events | Storage | RAM |
|--------|---------|-----|
| 1M     | ~500MB  | 4GB |
| 10M    | ~5GB    | 4GB |
| 100M   | ~50GB   | 6GB |
| 1B     | ~500GB  | 8GB |

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

# Scale synchronizer (multiple instances)
docker-compose up -d --scale synchronizer=3

# Database backup
docker-compose exec database pg_dump -U postgres bigbrotr > backup.sql

# Database restore
docker-compose exec -T database psql -U postgres bigbrotr < backup.sql
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

### High memory usage
- Reduce `SYNCHRONIZER_NUM_CORES` and `SYNCHRONIZER_REQUESTS_PER_CORE`
- Reduce `MONITOR_NUM_CORES` and `MONITOR_CHUNK_SIZE`
- Adjust PostgreSQL `shared_buffers` in `postgresql.conf`

### Slow synchronization
- Increase `SYNCHRONIZER_NUM_CORES` (if resources available)
- Increase `SYNCHRONIZER_REQUESTS_PER_CORE`
- Adjust `SYNCHRONIZER_RATE_LIMIT`

## Upgrading

```bash
# Stop services
docker-compose down

# Pull latest images
docker-compose pull

# Start services
docker-compose up -d
```

## Documentation

- Main documentation: `../../README.md`
- Architecture: `../../docs/architecture/BROTR_ARCHITECTURE.md`
- Comparison: `../../docs/architecture/COMPARISON.md`
- Creating custom implementations: `../../docs/HOW_TO_CREATE_BROTR.md`

## Support

- Issues: GitHub Issues
- Discussions: GitHub Discussions
- Documentation: `docs/` directory

