# Brotr Migration Guide

## Overview

This guide helps you migrate your existing Bigbrotr deployment to the new Brotr architecture, or deploy Lilbrotr for the first time.

---

## Migration Scenarios

### Scenario 1: Existing Bigbrotr → New Bigbrotr Structure

**Use case**: You're running the old Bigbrotr and want to update to the new modular structure

**Steps**:

1. **Backup your data**
   ```bash
   # Backup database
   docker exec bigbrotr_database pg_dump -U admin bigbrotr | gzip > backup_$(date +%Y%m%d).sql.gz
   
   # Backup configuration
   cp .env .env.backup
   cp docker-compose.yml docker-compose.yml.backup
   ```

2. **Stop current services**
   ```bash
   docker-compose down
   ```

3. **Update repository**
   ```bash
   git pull origin main
   ```

4. **Migrate configuration**
   ```bash
   cd deployments/bigbrotr
   cp .env.example .env
   
   # Copy values from your old .env to new .env
   # The structure is the same, just in a new location
   ```

5. **Update database init path**
   ```bash
   # Edit .env
   POSTGRES_DB_INIT_PATH=../../bigbrotr/sql/init.sql
   ```

6. **Start new deployment**
   ```bash
   docker-compose up -d
   ```

7. **Verify migration**
   ```bash
   # Check services
   curl http://localhost:8081/health
   curl http://localhost:8082/health
   curl http://localhost:8083/health
   
   # Check data
   docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "SELECT COUNT(*) FROM events;"
   ```

**Data Migration**: Not required - database schema is backward compatible

---

### Scenario 2: Bigbrotr → Lilbrotr (Cost Reduction)

**Use case**: You want to reduce costs by switching to lightweight indexing

**Important**: This is a **destructive migration** - you will lose event tags and content

**Steps**:

1. **Backup current data**
   ```bash
   docker exec bigbrotr_database pg_dump -U admin bigbrotr | gzip > backup_full_$(date +%Y%m%d).sql.gz
   ```

2. **Export minimal event data**
   ```bash
   docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "
   COPY (
     SELECT id, pubkey, created_at, kind, sig
     FROM events
     ORDER BY created_at
   ) TO STDOUT CSV HEADER
   " > events_minimal.csv
   
   docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "
   COPY (
     SELECT event_id, relay_url, seen_at
     FROM events_relays
     ORDER BY seen_at
   ) TO STDOUT CSV HEADER
   " > events_relays.csv
   ```

3. **Export relay and metadata**
   ```bash
   docker exec bigbrotr_database pg_dump -U admin bigbrotr \
     -t relays -t nip11 -t nip66 -t relay_metadata \
     | gzip > relays_metadata.sql.gz
   ```

4. **Deploy Lilbrotr**
   ```bash
   cd deployments/lilbrotr
   cp .env.example .env
   # Configure .env with same credentials
   docker-compose up -d
   ```

5. **Import data to Lilbrotr**
   ```bash
   # Import relay and metadata
   gunzip -c relays_metadata.sql.gz | docker exec -i lilbrotr_database psql -U admin lilbrotr
   
   # Import minimal events
   cat events_minimal.csv | docker exec -i lilbrotr_database psql -U admin lilbrotr -c "
   COPY events(id, pubkey, created_at, kind, sig) FROM STDIN CSV HEADER
   "
   
   # Import events_relays
   cat events_relays.csv | docker exec -i lilbrotr_database psql -U admin lilbrotr -c "
   COPY events_relays(event_id, relay_url, seen_at) FROM STDIN CSV HEADER
   "
   ```

6. **Verify migration**
   ```bash
   # Check event count
   docker exec -it lilbrotr_database psql -U admin -d lilbrotr -c "
   SELECT 
     (SELECT COUNT(*) FROM events) as events,
     (SELECT COUNT(*) FROM relays) as relays,
     (SELECT COUNT(*) FROM events_relays) as event_relay_associations
   "
   ```

**Cost Savings**: ~80% reduction in monthly costs

---

### Scenario 3: Fresh Lilbrotr Deployment

**Use case**: You want to start with lightweight indexing from scratch

**Steps**:

1. **Clone repository**
   ```bash
   git clone https://github.com/yourusername/bigbrotr.git
   cd bigbrotr
   ```

2. **Choose deployment**
   ```bash
   cd deployments/lilbrotr
   ```

3. **Configure**
   ```bash
   cp .env.example .env
   nano .env
   ```

4. **Generate Nostr keypair**
   ```bash
   # Option 1: Using npx
   npx nostr-keygen
   
   # Option 2: Using Python nostr-tools
   python3 -c "from nostr_tools import generate_keypair; sk, pk = generate_keypair(); print(f'SECRET_KEY={sk}\\nPUBLIC_KEY={pk}')"
   
   # Add to .env
   ```

5. **Create relay lists**
   ```bash
   # Seed relays
   cat > ../../seed_relays.txt << EOF
   wss://relay.damus.io
   wss://nos.lol
   wss://relay.nostr.band
   wss://nostr.wine
   EOF
   
   # Priority relays
   cat > ../../priority_relays.txt << EOF
   wss://relay.damus.io
   EOF
   ```

6. **Deploy**
   ```bash
   docker-compose up -d
   ```

7. **Monitor progress**
   ```bash
   docker-compose logs -f synchronizer
   ```

---

### Scenario 4: Hybrid Deployment (Both Bigbrotr + Lilbrotr)

**Use case**: You want fast indexing (Lilbrotr) + selective full archival (Bigbrotr)

**Architecture**:
- Lilbrotr: Index all events (fast, minimal storage)
- Bigbrotr: Archive important events (selective, full storage)

**Steps**:

1. **Deploy Lilbrotr** (see Scenario 3)
   ```bash
   cd deployments/lilbrotr
   docker-compose up -d
   ```

2. **Deploy Bigbrotr with filters**
   ```bash
   cd ../bigbrotr
   cp .env.example .env
   
   # Configure selective archival in .env
   SYNCHRONIZER_EVENT_FILTER={"kinds": [0, 1, 3, 10000, 10001, 10002, 30023]}
   # This archives only: metadata, notes, contacts, mute lists, relay lists, bookmarks
   
   # Use different ports to avoid conflicts
   DB_PORT=5433
   PGADMIN_PORT=8081
   
   docker-compose up -d
   ```

3. **Benefits**:
   - Query Lilbrotr for event existence (fast)
   - Query Bigbrotr for full event content (when needed)
   - Cost-effective: full coverage + selective detail

---

## Configuration Comparison

### Old Structure (root level)
```bash
./
├── docker-compose.yml
├── .env
├── init.sql
└── src/
```

### New Structure (organized)
```bash
./
├── deployments/
│   ├── bigbrotr/
│   │   ├── docker-compose.yml
│   │   └── .env
│   └── lilbrotr/
│       ├── docker-compose.yml
│       └── .env
├── bigbrotr/sql/init.sql
├── lilbrotr/sql/init.sql
└── brotr_core/
```

### Configuration Mapping

| Old Location | New Location (Bigbrotr) | New Location (Lilbrotr) |
|--------------|-------------------------|-------------------------|
| `./docker-compose.yml` | `deployments/bigbrotr/docker-compose.yml` | `deployments/lilbrotr/docker-compose.yml` |
| `./.env` | `deployments/bigbrotr/.env` | `deployments/lilbrotr/.env` |
| `./init.sql` | `bigbrotr/sql/init.sql` | `lilbrotr/sql/init.sql` |

---

## Environment Variables

### New Variables in Brotr

| Variable | Purpose | Values |
|----------|---------|--------|
| `BROTR_MODE` | Select implementation | `bigbrotr` or `lilbrotr` |
| `POSTGRES_DB_INIT_PATH` | Path to init.sql | `../../bigbrotr/sql/init.sql` or `../../lilbrotr/sql/init.sql` |

### Resource Adjustments for Lilbrotr

| Variable | Bigbrotr | Lilbrotr |
|----------|----------|----------|
| `MONITOR_NUM_CORES` | 8 | 2 |
| `SYNCHRONIZER_NUM_CORES` | 8 | 2 |
| `SYNCHRONIZER_BATCH_SIZE` | 500 | 500 |
| Docker CPU Limit | 6.0 | 2.0 |
| Docker RAM Limit | 4G | 2G |

---

## Data Migration Scripts

### Export Minimal Events from Bigbrotr

```bash
#!/bin/bash
# export_minimal_events.sh

docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "
SELECT 
  id,
  pubkey,
  created_at,
  kind,
  sig
FROM events
ORDER BY created_at
" > events_minimal.csv
```

### Import Events to Lilbrotr

```bash
#!/bin/bash
# import_to_lilbrotr.sh

cat events_minimal.csv | docker exec -i lilbrotr_database psql -U admin -d lilbrotr -c "
COPY events(id, pubkey, created_at, kind, sig)
FROM STDIN CSV HEADER
"
```

---

## Rollback Procedures

### If Migration Fails

1. **Restore from backup**
   ```bash
   # Stop new deployment
   docker-compose down
   
   # Restore database
   gunzip -c backup_20251101.sql.gz | docker exec -i bigbrotr_database psql -U admin bigbrotr
   
   # Restore configuration
   cp .env.backup .env
   cp docker-compose.yml.backup docker-compose.yml
   
   # Restart old deployment
   docker-compose up -d
   ```

2. **Verify restoration**
   ```bash
   docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "SELECT COUNT(*) FROM events;"
   ```

---

## Testing Your Migration

### Health Checks

```bash
# Test all service endpoints
curl http://localhost:8081/health  # Monitor
curl http://localhost:8082/health  # Synchronizer
curl http://localhost:8083/health  # Priority Synchronizer

# Expected response: {"status": "ready"}
```

### Data Integrity

```bash
# Check event counts
docker exec -it bigbrotr_database psql -U admin -d bigbrotr -c "
SELECT 
  (SELECT COUNT(*) FROM events) as total_events,
  (SELECT COUNT(*) FROM relays) as total_relays,
  (SELECT COUNT(*) FROM events_relays) as total_associations
"

# Compare with old deployment
# Numbers should match (for Bigbrotr)
# or be close (for Lilbrotr if data was migrated)
```

### Performance Testing

```bash
# Monitor synchronization speed
docker-compose logs -f synchronizer | grep "events/hour"

# Expected:
# Bigbrotr: ~1M events/hour
# Lilbrotr: ~5-10M events/hour (faster due to minimal storage)
```

---

## Troubleshooting

### Issue: Services won't start

**Solution**:
```bash
# Check logs
docker-compose logs

# Common issues:
# 1. Port conflicts (change ports in .env)
# 2. Missing .env (copy from .env.example)
# 3. Invalid Nostr keys (regenerate keypair)
```

### Issue: Database connection failed

**Solution**:
```bash
# Check database is running
docker-compose ps database

# Check database logs
docker-compose logs database

# Verify credentials in .env
```

### Issue: High resource usage on Lilbrotr

**Solution**:
```bash
# Edit .env to reduce cores
MONITOR_NUM_CORES=1
SYNCHRONIZER_NUM_CORES=1
SYNCHRONIZER_REQUESTS_PER_CORE=5

# Restart services
docker-compose up -d
```

### Issue: Data migration incomplete

**Solution**:
```bash
# Check export files
ls -lh events_minimal.csv events_relays.csv

# Re-run import with error checking
cat events_minimal.csv | docker exec -i lilbrotr_database psql -U admin -d lilbrotr -c "
COPY events(id, pubkey, created_at, kind, sig) FROM STDIN CSV HEADER
" 2>&1 | tee import_errors.log
```

---

## Support

- **Documentation**: [docs/architecture/](docs/architecture/)
- **Issues**: [GitHub Issues](https://github.com/yourusername/bigbrotr/issues)
- **Comparison Guide**: [docs/architecture/COMPARISON.md](docs/architecture/COMPARISON.md)
- **Architecture**: [docs/architecture/BROTR_ARCHITECTURE.md](docs/architecture/BROTR_ARCHITECTURE.md)

---

## Migration Checklist

### Pre-Migration

- [ ] Backup current database
- [ ] Backup configuration files
- [ ] Document current resource usage
- [ ] Review new architecture documentation
- [ ] Choose target implementation (Bigbrotr or Lilbrotr)

### During Migration

- [ ] Stop old services
- [ ] Update repository
- [ ] Configure new deployment
- [ ] Migrate data (if needed)
- [ ] Start new services
- [ ] Verify health checks

### Post-Migration

- [ ] Compare event counts
- [ ] Monitor resource usage
- [ ] Test query performance
- [ ] Update documentation
- [ ] Clean up old backups (after 30 days)

---

**Migration complete! Welcome to the Brotr architecture. 🎉**

