# Self-Hosting BigBrotr — Production Deployment Guide

A comprehensive, step-by-step guide for deploying BigBrotr on a self-hosted Proxmox server with dedicated ZFS storage, Cloudflare Tunnel for secure API exposure, and production-grade PostgreSQL tuning.

## Table of Contents

- [Target Hardware](#target-hardware)
- [Architecture Overview](#architecture-overview)
- [Phase 0 — Proxmox Post-Installation](#phase-0--proxmox-post-installation)
- [Phase 1 — Create ZFS Storage Pools](#phase-1--create-zfs-storage-pools)
- [Phase 2 — Create the Virtual Machine](#phase-2--create-the-virtual-machine)
- [Phase 3 — Install Debian](#phase-3--install-debian)
- [Phase 4 — Install Docker](#phase-4--install-docker)
- [Phase 5 — Deploy BigBrotr](#phase-5--deploy-bigbrotr)
- [Phase 6 — Cloudflare Tunnel Setup](#phase-6--cloudflare-tunnel-setup)
- [Phase 7 — Security Hardening](#phase-7--security-hardening)
- [Phase 8 — Database Backup](#phase-8--database-backup)
- [Phase 9 — Post-Deployment](#phase-9--post-deployment)
- [Troubleshooting](#troubleshooting)
- [Appendix A — Connecting for Research](#appendix-a--connecting-for-research)
- [Appendix B — Expanding Storage](#appendix-b--expanding-storage)
- [Appendix C — Running Multiple Deployments](#appendix-c--running-multiple-deployments)
- [Appendix D — Updating BigBrotr](#appendix-d--updating-bigbrotr)

---

## Target Hardware

This guide assumes a dedicated server with the following (adjust resource allocations to match your hardware):

| Component | Recommended Minimum | Example Used in This Guide |
|-----------|-------------------|---------------------------|
| CPU | 8 cores / 16 threads | 16 cores / 32 threads |
| RAM | 32 GB | 96 GB |
| Boot / OS | 2x NVMe/SSD in ZFS mirror | 2x NVMe 1TB — ZFS mirror (`rpool`) |
| Database storage | 2+ SSDs in ZFS mirror or RAID10 | 4x 4TB SATA SSD — ZFS RAID10 (`datapool`) |
| Work storage (optional) | Any disk(s) for backups | 2x 4TB SATA SSD — ZFS stripe (`workpool`) |

> **Storage sizing**: BigBrotr's database grows primarily through event archiving (Synchronizer service). With full event storage (tags, content, signatures), expect ~1-5 GB/day depending on how many relays are monitored. Plan for at least 1 TB for the first year.

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    PROXMOX HOST (NVMe ZFS mirror)                    │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │              VM "bigbrotr" (Debian 13 trixie)                  │  │
│  │              vCPUs · RAM · OS on NVMe                          │  │
│  │                                                                │  │
│  │  /mnt/pgdata  ← virtio disk from datapool (SSD RAID10)        │  │
│  │     ├── bigbrotr-production/  (PostgreSQL data)                │  │
│  │     ├── lilbrotr-production/  (future)                         │  │
│  │     └── bigbrotr-test/        (future)                         │  │
│  │                                                                │  │
│  │  /mnt/work    ← virtio disk from workpool (optional)           │  │
│  │     ├── bigbrotr-production/{dumps,exports,analysis}           │  │
│  │     └── lilbrotr-production/  (future)                         │  │
│  │                                                                │  │
│  │  Docker Compose → 15 containers (8 services + 7 infra)        │  │
│  │  cloudflared  → Cloudflare Tunnel (zero open ports)            │  │
│  │                                                                │  │
│  │  PostgreSQL accessible on internal network for research        │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  Internet → Cloudflare → Tunnel → localhost:8080 (API only)         │
│  No inbound ports open on the server                                │
└──────────────────────────────────────────────────────────────────────┘
```

### Storage Strategy

| Pool | Purpose | Topology | Why |
|------|---------|----------|-----|
| `rpool` | Proxmox OS + VM boot disk | ZFS mirror | Fast NVMe for OS, Docker images, container layers |
| `datapool` | PostgreSQL data exclusively | ZFS RAID10 or mirror | High IOPS for DB, redundancy against disk failure |
| `workpool` | DB dumps, exports, analysis | ZFS stripe or single disk | Large sequential files, data is reproducible, redundancy optional |

### Network & Security Strategy

- **Cloudflare Tunnel**: API exposed via outbound-only tunnel. Zero inbound ports opened. Cloudflare handles TLS, DDoS protection, and WAF.
- **PostgreSQL**: Available on the internal bridge network for research VMs. Blocked from the internet by firewall.
- **SSH**: Key-only authentication on a non-standard port with fail2ban.

---

## Phase 0 — Proxmox Post-Installation

A fresh Proxmox install requires baseline configuration.

### 0.1 — Access the Shell

Connect via SSH or use the **Shell** button in the Proxmox web GUI (`https://<SERVER_IP>:8006`).

### 0.2 — Disable Enterprise Repositories

Proxmox ships with enterprise repositories requiring a paid subscription. Disable them and enable the free community repository:

```bash
# Check repository format (Proxmox 9.x uses .sources files)
ls /etc/apt/sources.list.d/

# For .sources files (Proxmox 9.x) — add Enabled: no if the field doesn't exist
echo "Enabled: no" >> /etc/apt/sources.list.d/pve-enterprise.sources
echo "Enabled: no" >> /etc/apt/sources.list.d/ceph.sources

# For .list files (older Proxmox) — comment out the line
# sed -i 's/^deb/#deb/' /etc/apt/sources.list.d/pve-enterprise.list

# Add community repository
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" > /etc/apt/sources.list.d/pve-no-subscription.list

# Verify — should complete with no 401 errors
apt update
```

### 0.3 — Remove Subscription Popup (Optional)

```bash
sed -Ei.bak "s/NotFound/Active/g" /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
systemctl restart pveproxy
```

> This is overwritten by Proxmox upgrades — re-run after `apt full-upgrade` if the popup returns.

### 0.4 — Update and Install Tools

```bash
apt full-upgrade -y
# Reboot if kernel was updated: reboot

apt install -y htop iotop tmux tree
```

### 0.5 — Verify Boot Pool Health

```bash
zpool status rpool
```

Expected: `state: ONLINE`, zero errors on all disks.

---

## Phase 1 — Create ZFS Storage Pools

### 1.1 — Identify All Disks

Always use stable `/dev/disk/by-id/` identifiers — never bare `sda`/`sdb` names (they can change between reboots):

```bash
lsblk -d -o NAME,SIZE,MODEL,SERIAL
ls -la /dev/disk/by-id/ | grep -v part
```

**If mixing used and new disks in a RAID10**: Check SMART data to pair each used disk with a new one in the same mirror. This maximizes redundancy — if a used disk fails, the new disk has the complete copy.

```bash
smartctl -a /dev/sdX | grep -E "Device Model|Serial|Power_On_Hours|Total_LBAs_Written|Wear_Leveling"
```

### 1.2 — Create datapool (Database Storage)

Example: RAID10 with 4 disks (2 mirrored pairs striped):

```bash
zpool create -f \
  -o ashift=12 \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  -O recordsize=8K \
  -O primarycache=metadata \
  -O logbias=throughput \
  datapool \
  mirror \
    /dev/disk/by-id/DISK_A1 \
    /dev/disk/by-id/DISK_A2 \
  mirror \
    /dev/disk/by-id/DISK_B1 \
    /dev/disk/by-id/DISK_B2
```

For a 2-disk setup, use a simple mirror instead of RAID10:

```bash
zpool create -f \
  -o ashift=12 \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  -O recordsize=8K \
  -O primarycache=metadata \
  -O logbias=throughput \
  datapool \
  mirror \
    /dev/disk/by-id/DISK_1 \
    /dev/disk/by-id/DISK_2
```

**Option rationale**:

| Option | Value | Rationale |
|--------|-------|-----------|
| `ashift=12` | 4K sectors | Correct alignment for all modern SSDs/HDDs. Cannot be changed after creation. |
| `compression=lz4` | Fast compression | PostgreSQL data compresses ~1.5-2x. Negligible CPU overhead. |
| `atime=off` | No access timestamps | Eliminates unnecessary write I/O on every read. Critical for databases. |
| `recordsize=8K` | 8KB blocks | Matches PostgreSQL's page size exactly. Other values cause write amplification. |
| `primarycache=metadata` | Metadata caching only | PostgreSQL has its own buffer cache (`shared_buffers`). Duplicating in ZFS ARC wastes RAM. |
| `logbias=throughput` | Throughput-optimized | Reduces ZIL writes. Optimal with `synchronous_commit=off`. |

**Register in Proxmox**:

```bash
pvesm add zfspool datapool \
  --pool datapool \
  --content images \
  --sparse 0 \
  --blocksize 8k \
  --nodes $(hostname)
```

### 1.3 — Create workpool (Optional — Backup/Work Storage)

For dump files and large exports, use larger blocks and no redundancy (data is reproducible):

```bash
zpool create -f \
  -o ashift=12 \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  -O recordsize=1M \
  workpool \
  /dev/disk/by-id/DISK_W1 \
  /dev/disk/by-id/DISK_W2
```

| Option | datapool | workpool | Why |
|--------|----------|----------|-----|
| `recordsize` | 8K | 1M | DB pages vs. large sequential files |
| `primarycache` | metadata | all (default) | No app cache for workpool |
| `logbias` | throughput | latency (default) | Integrity over speed for backups |

```bash
pvesm add zfspool workpool \
  --pool workpool \
  --content images \
  --sparse 0 \
  --blocksize 128k \
  --nodes $(hostname)
```

### 1.4 — Verify

```bash
zpool list
zpool status
pvesm status
```

---

## Phase 2 — Create the Virtual Machine

### 2.1 — Download Debian ISO

From the Proxmox web GUI: **local** → **ISO Images** → **Download from URL**

Use the latest Debian stable netinst ISO from `https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/`

### 2.2 — Create the VM

Click **Create VM** in the Proxmox web GUI:

**General**: Name `bigbrotr`, note the VM ID.

**OS**: Select the Debian ISO, Type: Linux.

**System**:
- BIOS: **OVMF (UEFI)**
- Machine: **q35**
- EFI Storage: NVMe pool
- SCSI Controller: **VirtIO SCSI single**
- Qemu Agent: **Yes**

**Disks**:

| Disk | Storage | Size | Purpose |
|------|---------|------|---------|
| OS | NVMe pool | 50 GiB | Debian, Docker, images |
| DB data | datapool | ~90% of pool | PostgreSQL exclusively |
| Work | workpool | ~90% of pool | Dumps, exports (optional) |

For all disks: **Discard: Yes**, **IO Thread: Yes**, **Cache: No cache**.

> Leave ~10% free on each ZFS pool for metadata, copy-on-write, and snapshots. ZFS degrades above ~90% capacity.

**CPU**:
- Cores: allocate ~40-60% of available threads
- Type: **host** (native instruction passthrough)

**Memory**:
- Allocate 60-70% of total RAM
- **Disable ballooning** (in Advanced settings)

> PostgreSQL's `shared_buffers` must remain resident in RAM. Ballooning can cause catastrophic swapping.

**Network**: Bridge **vmbr0**, Model **VirtIO**, Firewall **Yes**.

**Do not start the VM yet.** Add additional disks via Hardware → Add → Hard Disk if you only created one during the wizard.

### 2.3 — Enable NUMA (Optional — Multi-CCD CPUs)

If using a multi-CCD CPU (AMD Ryzen 9, EPYC, Threadripper, or similar), enable NUMA awareness to distribute the workload across chiplets. Without this, the hypervisor may schedule all vCPUs on one chiplet, causing thermal imbalance.

```bash
# From the Proxmox host
qm set <VM_ID> --numa 1
```

> On an AMD Ryzen 9 with 12 vCPUs under sustained load, enabling NUMA reduced the hot CCD from 93°C to 60°C.

---

## Phase 3 — Install Debian

Start the VM and open the Console.

### 3.1 — Installer Settings

- Language: English, Country/Keyboard: your choice
- Hostname: **bigbrotr**, Domain: empty
- Root password: strong password (temporary — replaced with SSH keys later)
- Create a regular user (e.g., `bigbrotr`)
- Timezone: your timezone

### 3.2 — Disk Partitioning (CRITICAL)

Select **Manual**. Identify the OS disk by its size (~50 GiB). **Only partition the OS disk**:

| Partition | Size | Type | Mount |
|-----------|------|------|-------|
| 1 | 512 MB | EFI System Partition | /boot/efi |
| 2 | ~48 GiB | ext4 | / |
| 3 | remainder | swap | swap |

**Do NOT partition the data disks** — we format them after installation.

### 3.3 — Software Selection

Select **only**: SSH server + Standard system utilities. No desktop environment.

### 3.4 — First Boot

Login as root. Enable SSH root access (temporary):

```bash
echo "PermitRootLogin yes" > /etc/ssh/sshd_config.d/root.conf
systemctl restart sshd
```

SSH in from your workstation for easier copy-paste:

```bash
ssh root@<VM_IP>
```

Fix locale and install packages:

```bash
sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen

apt update && apt upgrade -y
apt install -y \
  qemu-guest-agent curl wget htop iotop tmux unzip \
  sudo ufw fail2ban parted xfsprogs

systemctl enable --now qemu-guest-agent
```

### 3.5 — Format and Mount Data Disks

Identify disks by size:

```bash
lsblk -d -o NAME,SIZE,MODEL
```

**PostgreSQL data disk — XFS** (superior for sustained write-heavy workloads):

```bash
parted /dev/<PGDATA_DISK> mklabel gpt
parted /dev/<PGDATA_DISK> mkpart primary 0% 100%

mkfs.xfs -f -L pgdata /dev/<PGDATA_DISK>1

mkdir -p /mnt/pgdata
echo 'LABEL=pgdata /mnt/pgdata xfs defaults,noatime,nodiratime,logbufs=8,logbsize=256k,inode64 0 2' >> /etc/fstab
mount /mnt/pgdata
```

XFS mount options:
- `noatime,nodiratime`: No access timestamp updates (eliminates write I/O on reads)
- `logbufs=8,logbsize=256k`: Larger journal buffers (better write throughput)
- `inode64`: Required for filesystems larger than 2 TB

**Work disk** (if applicable):

```bash
parted /dev/<WORK_DISK> mklabel gpt
parted /dev/<WORK_DISK> mkpart primary 0% 100%

mkfs.xfs -f -L workdata /dev/<WORK_DISK>1

mkdir -p /mnt/work
echo 'LABEL=workdata /mnt/work xfs defaults,noatime,nodiratime,inode64 0 2' >> /etc/fstab
mount /mnt/work

# Per-deployment subdirectories (add more as needed)
mkdir -p /mnt/work/bigbrotr-production/{dumps,exports,analysis}
```

### 3.6 — Configure Static IP

```bash
ip route | grep default
# Note the interface name (e.g., ens18) and gateway

cat > /etc/network/interfaces << 'EOF'
auto lo
iface lo inet loopback

auto ens18
iface ens18 inet static
    address <YOUR_VM_IP>/24
    gateway <YOUR_GATEWAY>
    dns-nameservers 1.1.1.1 8.8.8.8
EOF

systemctl restart networking
```

> **CRITICAL: Configure DNS resolver explicitly.** With a static IP, DHCP no longer manages `/etc/resolv.conf`. After a reboot, it will be empty — breaking `cloudflared`, `apt`, and any service that needs DNS. Write nameservers manually and lock the file:
>
> ```bash
> cat > /etc/resolv.conf << 'EOF'
> nameserver 1.1.1.1
> nameserver 8.8.8.8
> EOF
>
> # Make immutable to prevent overwriting on reboot
> chattr +i /etc/resolv.conf
> ```
>
> To edit the file later, first remove the immutable flag: `chattr -i /etc/resolv.conf`

### 3.7 — Kernel Parameters for PostgreSQL

Adjust `kernel.shmmax` based on your `shared_buffers` setting (should be >= shared_buffers in bytes):

```bash
cat > /etc/sysctl.d/99-postgresql.conf << 'EOF'
# Shared memory — adjust to match shared_buffers
kernel.shmmax = 17179869184
kernel.shmall = 4194304

# Virtual memory
vm.overcommit_memory = 2
vm.overcommit_ratio = 95
vm.swappiness = 1
vm.dirty_background_ratio = 3
vm.dirty_ratio = 10

# Network
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.core.netdev_max_backlog = 65535

# File descriptors
fs.file-max = 2097152
EOF

sysctl --system
```

| Parameter | Rationale |
|-----------|-----------|
| `vm.overcommit_memory=2` | Strict accounting — prevents OOM killer from targeting PostgreSQL |
| `vm.swappiness=1` | Almost never swap — swapping shared_buffers is catastrophic |
| `vm.dirty_*_ratio` | Flush dirty pages early — prevents I/O stalls from large write bursts |
| `fs.file-max` | Docker + PostgreSQL + 8 services need many open file descriptors |

### 3.8 — System Limits

```bash
cat > /etc/security/limits.d/99-bigbrotr.conf << 'EOF'
*    soft    nofile    1048576
*    hard    nofile    1048576
*    soft    nproc     65535
*    hard    nproc     65535
EOF
```

---

## Phase 4 — Install Docker

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 4.1 — Production Configuration

```bash
cat > /etc/docker/daemon.json << 'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "50m",
    "max-file": "5"
  },
  "storage-driver": "overlay2",
  "live-restore": true,
  "default-ulimits": {
    "nofile": {
      "Name": "nofile",
      "Hard": 1048576,
      "Soft": 1048576
    }
  }
}
EOF

systemctl restart docker
```

| Setting | Rationale |
|---------|-----------|
| `log-opts` | Log rotation prevents disk exhaustion |
| `live-restore` | Containers survive Docker daemon restarts |
| `default-ulimits` | Sufficient file descriptors for all containers |

---

## Phase 5 — Deploy BigBrotr

### 5.1 — Download the Deployment Folder

You only need the deployment folder — not the full repository. Download the latest release and extract the deployment template for your variant (`bigbrotr` for full event storage, `lilbrotr` for lightweight):

```bash
cd /opt
VARIANT=bigbrotr  # or lilbrotr
RELEASE=$(curl -s https://api.github.com/repos/BigBrotr/bigbrotr/releases/latest | grep tarball_url | cut -d '"' -f 4)
curl -sL "$RELEASE" | tar xz
mv BigBrotr-bigbrotr-*/deployments/$VARIANT "${VARIANT}-production"
rm -rf BigBrotr-bigbrotr-*
```

This gives you a standalone production folder at `/opt/bigbrotr-production/` with all configs, monitoring, SQL init scripts, PGBouncer settings, and backup script. No git required on the server.

Next, edit `docker-compose.yaml` to use pre-built Docker Hub images instead of building locally. Replace every `build:` block in the 8 service definitions with an `image:` line:

```yaml
# Replace this (in seeder, finder, validator, monitor, synchronizer, refresher, api, dvm):
    build:
      context: ../../
      dockerfile: deployments/Dockerfile
      args:
        DEPLOYMENT: bigbrotr

# With this:
    image: vincenzoimp/bigbrotr:6    # or vincenzoimp/lilbrotr:6
```

The `:6` tag always points to the latest 6.x.x release. Updates are a single command: `docker compose pull && docker compose up -d`.

### 5.2 — Link PostgreSQL Data to Dedicated Disk

Each deployment gets its own subdirectory on the datapool, enabling multiple deployments (bigbrotr-production, lilbrotr-production, bigbrotr-test) on the same hardware with isolated databases:

```bash
mkdir -p /mnt/pgdata/bigbrotr-production
mkdir -p /opt/bigbrotr-production/data
ln -s /mnt/pgdata/bigbrotr-production /opt/bigbrotr-production/data/postgres

# PostgreSQL in postgres:alpine runs as uid 999
chown -R 999:999 /mnt/pgdata/bigbrotr-production
```

### 5.3 — Generate Credentials

```bash
cd /opt/bigbrotr-production

DB_ADMIN_PW=$(openssl rand -base64 32)
DB_WRITER_PW=$(openssl rand -base64 32)
DB_READER_PW=$(openssl rand -base64 32)
DB_REFRESHER_PW=$(openssl rand -base64 32)
GRAFANA_PW=$(openssl rand -base64 24)
NOSTR_KEY=$(openssl rand -hex 32)

cat > .env << EOF
DB_ADMIN_PASSWORD=${DB_ADMIN_PW}
DB_WRITER_PASSWORD=${DB_WRITER_PW}
DB_READER_PASSWORD=${DB_READER_PW}
DB_REFRESHER_PASSWORD=${DB_REFRESHER_PW}
NOSTR_PRIVATE_KEY=${NOSTR_KEY}
GRAFANA_PASSWORD=${GRAFANA_PW}
EOF

chmod 600 .env
```

> **CRITICAL**: Save `.env` contents in a password manager immediately. These credentials cannot be recovered.

### 5.4 — PostgreSQL Production Tuning

The shipped `postgresql.conf` is tuned for 4 GB RAM. Create a production configuration scaled to your hardware.

```bash
cp postgres/postgresql.conf postgres/postgresql.conf.original
```

Write a new `postgres/postgresql.conf` with these key settings (scale values to your RAM):

```ini
# --- Connection ---
listen_addresses = '*'
port = 5432
max_connections = 200
password_encryption = 'scram-sha-256'

# --- Memory (adjust to your RAM) ---
# Rule of thumb: shared_buffers = 25% RAM, effective_cache_size = 75% RAM
shared_buffers = 16GB              # 25% of 64GB
effective_cache_size = 48GB        # 75% of 64GB
work_mem = 64MB                    # Per-sort/hash operation
maintenance_work_mem = 2GB         # VACUUM, CREATE INDEX
huge_pages = try                   # Reduces TLB misses

# --- WAL ---
wal_buffers = 64MB
min_wal_size = 2GB
max_wal_size = 8GB
checkpoint_completion_target = 0.9
checkpoint_timeout = 15min

# --- Write Performance ---
synchronous_commit = off           # ~10ms data risk, acceptable for Nostr data
commit_delay = 100
commit_siblings = 5
wal_writer_delay = 200ms

# --- Query Optimization (SSD) ---
random_page_cost = 1.1             # SSDs: random ≈ sequential
effective_io_concurrency = 200
default_statistics_target = 200

# --- Parallel Execution (adjust to your CPU cores) ---
max_worker_processes = 12
max_parallel_workers = 8
max_parallel_workers_per_gather = 4
max_parallel_maintenance_workers = 4

# --- Autovacuum (write-heavy tuning) ---
autovacuum_max_workers = 4
autovacuum_naptime = 30s
autovacuum_vacuum_threshold = 50
autovacuum_analyze_threshold = 50
autovacuum_vacuum_scale_factor = 0.05
autovacuum_analyze_scale_factor = 0.025
autovacuum_vacuum_cost_delay = 2ms
autovacuum_vacuum_cost_limit = 2000

# --- Background Writer ---
bgwriter_delay = 20ms
bgwriter_lru_maxpages = 400
bgwriter_lru_multiplier = 4.0

# --- Timeouts ---
idle_in_transaction_session_timeout = 60000
statement_timeout = 300000

# --- Logging ---
log_destination = 'stderr'
logging_collector = off
log_min_messages = warning
log_statement = 'none'
log_lock_waits = on
log_temp_files = 0

# --- Statistics ---
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all

timezone = 'UTC'
```

**Scaling guide**:

| RAM | shared_buffers | effective_cache_size | work_mem | maintenance_work_mem |
|-----|---------------|---------------------|----------|---------------------|
| 32 GB | 8 GB | 24 GB | 32 MB | 1 GB |
| 64 GB | 16 GB | 48 GB | 64 MB | 2 GB |
| 96 GB | 24 GB | 72 GB | 128 MB | 4 GB |
| 128 GB | 32 GB | 96 GB | 128 MB | 4 GB |

### 5.5 — Expose Services on Internal Network (Optional)

To access PostgreSQL, Grafana, and Prometheus from your local network:

```bash
cd /opt/bigbrotr-production

# PostgreSQL — for research queries from other VMs
sed -i 's/127.0.0.1:5432:5432/5432:5432/' docker-compose.yaml

# Grafana — for monitoring dashboards
sed -i 's/127.0.0.1:3000:3000/3000:3000/' docker-compose.yaml

# Prometheus — for metrics
sed -i 's/127.0.0.1:9090:9090/9090:9090/' docker-compose.yaml
```

Security is provided by UFW firewall (Phase 7) restricting access to the local subnet.

### 5.6 — Docker Shared Memory for PostgreSQL

Docker containers default to 64 MB of `/dev/shm`. PostgreSQL with large `shared_buffers` needs much more — parallel workers allocate shared memory segments for sort and hash operations. Without this, materialized view refreshes fail with `could not resize shared memory segment: No space left on device`.

```bash
# Match shm_size to your shared_buffers value
sed -i '/container_name: bigbrotr-postgres/a\    shm_size: 16g' docker-compose.yaml
```

| shared_buffers | shm_size |
|---------------|----------|
| 8 GB | `8g` |
| 16 GB | `16g` |
| 24 GB | `24g` |
| 32 GB | `32g` |

### 5.7 — Fix Permissions for GeoLite2 Databases

The Monitor service downloads MaxMind GeoLite2 databases on first run for IP geolocation. The container runs as uid 1000 (non-root) and needs write access to the `static/` directory:

```bash
chown -R 1000:1000 /opt/bigbrotr-production/static/
```

### 5.8 — Pull Images and Start

```bash
cd /opt/bigbrotr-production

# Pull pre-built images from Docker Hub
docker compose pull

# Start infrastructure gradually
docker compose up -d postgres
# Wait ~15 seconds, verify healthy:
docker compose ps postgres

docker compose up -d pgbouncer tor
# Wait ~30 seconds (Tor is slow to bootstrap):
docker compose ps

# Start all services
docker compose up -d

# Verify — all 14 containers should be "healthy"
docker compose ps
```

### 5.9 — Verify

```bash
# API health
curl -s http://localhost:8080/health
# Expected: {"status":"ok"}

# Seeder results
docker compose logs seeder --tail=5
# Expected: "candidates_inserted total=XXXX"

# Candidates in database
docker compose exec postgres psql -U admin -d bigbrotr \
  -c "SELECT count(*) FROM service_state;"

# Tables (6 expected)
docker compose exec postgres psql -U admin -d bigbrotr -c "\dt"

# Materialized views (11 expected)
docker compose exec postgres psql -U admin -d bigbrotr -c "\dm"
```

> The Seeder inserts relay URLs as candidates. The Validator checks each via WebSocket and promotes valid ones to the `relay` table. Expect relays to appear within 10-30 minutes.

---

## Phase 6 — Cloudflare Tunnel Setup

Cloudflare Tunnel exposes the API with zero inbound ports. The `cloudflared` daemon creates an outbound-only HTTPS connection to Cloudflare's edge.

### 6.1 — Create Cloudflare Account and Add Domain

1. Sign up at **cloudflare.com** (free tier)
2. **Add a site** → enter your domain
3. Select **Import DNS records automatically**
4. Choose the **Free** plan
5. Review imported DNS records (verify existing services like Vercel are correct)

### 6.2 — Change Nameservers

Cloudflare provides two nameservers. Update them at your domain registrar:

1. Go to your registrar's domain management
2. Change nameservers to the two provided by Cloudflare
3. Save and wait for propagation (15 minutes to 48 hours)

Cloudflare sends an email when the domain is active.

### 6.3 — Create and Install the Tunnel

**In the Cloudflare dashboard**:
1. Go to **Zero Trust** → **Networks** → **Tunnels** (or "Connectors")
2. **Add a tunnel** → Type: **Cloudflared** → Name: `bigbrotr-prod`
3. Select **64-bit** architecture
4. Copy the installation token

**In the VM**:

```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared.deb
rm cloudflared.deb

# Install as service with the token from Cloudflare
cloudflared service install <YOUR_TOKEN>

# Verify — should show 4 registered connections
systemctl status cloudflared
```

### 6.4 — Configure the Route

In the Cloudflare tunnel configuration, add a **Public Hostname**:

- **Subdomain**: `api`
- **Domain**: your domain
- **Type**: `HTTP`
- **URL**: `localhost:8080`

> **Why HTTP, not HTTPS?** The last hop (cloudflared → API) is localhost — no network traversal. Cloudflare handles TLS for the public side, and the tunnel is encrypted end-to-end.

### 6.5 — Cloudflare Security

In the main Cloudflare dashboard for your domain:

- **SSL/TLS**: Set to **Full (strict)**
- DDoS protection is enabled automatically on the free tier

### 6.6 — Verify

```bash
curl https://api.<YOUR_DOMAIN>/health
# Expected: {"status":"ok"}
```

If DNS hasn't propagated, test via Cloudflare's nameservers directly:

```bash
curl -s --resolve api.<YOUR_DOMAIN>:443:$(dig +short api.<YOUR_DOMAIN> @<CLOUDFLARE_NS>) https://api.<YOUR_DOMAIN>/health
```

---

## Phase 7 — Security Hardening

### 7.1 — VM Firewall (UFW)

```bash
ufw default deny incoming
ufw default allow outgoing

# SSH
ufw allow 22/tcp comment 'SSH'

# Internal network only (adjust subnet to match yours)
ufw allow from 192.168.0.0/16 to any port 5432 proto tcp comment 'PostgreSQL internal'
ufw allow from 192.168.0.0/16 to any port 3000 proto tcp comment 'Grafana internal'
ufw allow from 192.168.0.0/16 to any port 9090 proto tcp comment 'Prometheus internal'

ufw enable
```

> Cloudflare Tunnel requires **no inbound rules** — it uses outbound connections only.

### 7.2 — SSH Key Authentication

**On your local machine**:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/bigbrotr
ssh-copy-id -i ~/.ssh/bigbrotr.pub root@<VM_IP>

# Test — should not ask for password
ssh -i ~/.ssh/bigbrotr root@<VM_IP>
```

### 7.3 — SSH Hardening

**On the VM**:

```bash
cat > /etc/ssh/sshd_config.d/hardening.conf << 'EOF'
Port 2222
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
MaxSessions 5
ClientAliveInterval 300
ClientAliveCountMax 2
X11Forwarding no
AllowAgentForwarding no
EOF

# Update firewall BEFORE restarting SSH
ufw allow 2222/tcp comment 'SSH custom port'
ufw delete allow 22/tcp

systemctl restart sshd
```

> **CRITICAL**: Test from a **separate terminal** before closing the current session:
> ```bash
> ssh -i ~/.ssh/bigbrotr -p 2222 root@<VM_IP>
> ```

### 7.4 — Fail2ban

```bash
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 3
backend = systemd

[sshd]
enabled = true
port = 2222
maxretry = 3
bantime = 86400
EOF

systemctl restart fail2ban
fail2ban-client status sshd
```

### 7.5 — Automatic Security Updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
# Select "Yes"
```

---

## Phase 8 — Database Backup

A `backup.sh` script is included in the deployment folder. It dumps the database to the `dumps/` directory (already included in the deployment folder), compressed with gzip, and keeps only the 7 most recent dumps.

```bash
/opt/bigbrotr-production/backup.sh
```

If you have a dedicated backup disk, symlink the dumps directory to the per-deployment workpool folder:

```bash
mkdir -p /mnt/work/bigbrotr-production/dumps
rm -rf /opt/bigbrotr-production/dumps
ln -s /mnt/work/bigbrotr-production/dumps /opt/bigbrotr-production/dumps
```

**Optional** — schedule automatic daily backups:

```bash
echo '0 4 * * * root /opt/bigbrotr-production/backup.sh >> /var/log/bigbrotr-backup.log 2>&1' > /etc/cron.d/bigbrotr-backup
```

---

## Phase 9 — Post-Deployment

### Checklist

```bash
cd /opt/bigbrotr-production

# All 14 containers healthy
docker compose ps

# Service logs clean
docker compose logs --tail=20 finder
docker compose logs --tail=20 monitor
docker compose logs --tail=20 synchronizer

# API responding
curl -s http://localhost:8080/health

# API responding via Cloudflare
curl https://api.<YOUR_DOMAIN>/health

# Disk usage
df -h /mnt/pgdata /mnt/work
```

### Accessing Services

| Service | URL | Access |
|---------|-----|--------|
| API (public) | `https://api.<YOUR_DOMAIN>` | Internet via Cloudflare Tunnel |
| API (local) | `http://<VM_IP>:8080` | Local network |
| Grafana | `http://<VM_IP>:3000` | Local network |
| Prometheus | `http://<VM_IP>:9090` | Local network |
| PostgreSQL | `<VM_IP>:5432` | Local network |

### SSH Access

```bash
ssh -i ~/.ssh/bigbrotr -p 2222 root@<VM_IP>
```

### Key File Locations

| Path | Purpose |
|------|---------|
| `/opt/bigbrotr-production/` | Production deployment (standalone) |
| `/opt/bigbrotr-production/.env` | Credentials |
| `/opt/bigbrotr-production/docker-compose.yaml` | Docker Compose configuration |
| `/opt/bigbrotr-production/postgres/postgresql.conf` | PostgreSQL tuning |
| `/opt/bigbrotr-production/backup.sh` | Backup script |
| `/opt/bigbrotr-production/data/` | PostgreSQL data (symlink to dedicated disk if available) |
| `/opt/bigbrotr-production/dumps/` | Database backups (symlink to dedicated disk if available) |

---

## Troubleshooting

### cloudflared crashes after reboot

**Symptom**: `ERR Couldn't resolve SRV record ... connection refused` in `journalctl -u cloudflared`. Cloudflared enters a restart loop.

**Cause**: `/etc/resolv.conf` is empty. With a static IP, DHCP no longer populates DNS resolver configuration.

**Fix**: Write nameservers manually and make the file immutable (see Phase 3.6):

```bash
cat > /etc/resolv.conf << 'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF
chattr +i /etc/resolv.conf
systemctl restart cloudflared
```

### Materialized view refresh fails with "No space left on device"

**Symptom**: Refresher logs show `could not resize shared memory segment "/PostgreSQL.XXXX" to 16777216 bytes: No space left on device`. Disk usage shows plenty of free space.

**Cause**: Docker's default `/dev/shm` is 64 MB. PostgreSQL parallel workers need shared memory proportional to `shared_buffers`. The "no space" refers to `/dev/shm`, not disk.

**Fix**: Add `shm_size` to the postgres service in `docker-compose.yaml`, matching your `shared_buffers`:

```bash
sed -i '/container_name: bigbrotr-postgres/a\    shm_size: 16g' docker-compose.yaml
docker compose down postgres && docker compose up -d postgres
```

### Monitor fails with "Permission denied: GeoLite2-City.mmdb"

**Symptom**: Monitor crashes with consecutive failures. Logs show `[Errno 13] Permission denied: 'static/GeoLite2-City.mmdb'` followed by `[Errno 2] No such file or directory`.

**Cause**: The `static/` directory is bind-mounted from the host (owned by root) but the container runs as uid 1000 (non-root).

**Fix**:

```bash
chown -R 1000:1000 /opt/bigbrotr-production/static/
docker compose restart monitor
```

---

## Appendix A — Connecting for Research

From any machine on the same network:

```bash
psql -h <VM_IP> -p 5432 -U reader -d bigbrotr
```

Use `DB_READER_PASSWORD` from `.env`. The `reader` role has SELECT-only access.

For long-running analytical queries, connect directly to PostgreSQL (port 5432), **not** through PGBouncer (port 6432). PGBouncer's transaction pooling mode does not support cursors, multi-statement transactions, or long-running queries.

---

## Appendix B — Expanding Storage

ZFS RAID10 pools can be expanded by adding mirror pairs without downtime:

```bash
# From the Proxmox host
zpool add datapool mirror /dev/disk/by-id/NEW_DISK_1 /dev/disk/by-id/NEW_DISK_2
```

Then increase the VM disk in Proxmox (VM → Hardware → disk → Resize) and grow the filesystem:

```bash
# Inside the VM
xfs_growfs /mnt/pgdata
```

---

## Appendix C — Running Multiple Deployments

The same hardware can host multiple BigBrotr/LilBrotr instances, each fully isolated with its own database, configs, and Docker networks. Repeat Phase 5 with a different variant and name:

```bash
# Download lilbrotr deployment
cd /opt
curl -sL "$RELEASE" | tar xz
mv BigBrotr-bigbrotr-*/deployments/lilbrotr lilbrotr-production
rm -rf BigBrotr-bigbrotr-*

# Edit docker-compose.yaml: replace build: with image: vincenzoimp/lilbrotr:6
# Generate separate .env credentials
# Link to isolated database storage
mkdir -p /mnt/pgdata/lilbrotr-production
mkdir -p /opt/lilbrotr-production/data
ln -s /mnt/pgdata/lilbrotr-production /opt/lilbrotr-production/data/postgres
chown -R 999:999 /mnt/pgdata/lilbrotr-production

# Link to isolated workpool storage
mkdir -p /mnt/work/lilbrotr-production/dumps
ln -s /mnt/work/lilbrotr-production/dumps /opt/lilbrotr-production/dumps
```

Each deployment uses separate Docker networks and container names (prefixed `bigbrotr-` or `lilbrotr-`), so they coexist without conflicts. Adjust port mappings in `docker-compose.yaml` to avoid collisions (LilBrotr defaults use different ports — see the shipped compose file).

### Storage layout with multiple deployments

```
/opt/
├── bigbrotr-production/     # Full event storage
└── lilbrotr-production/     # Lightweight (no tags/content/sig)

/mnt/pgdata/
├── bigbrotr-production/     # Isolated PostgreSQL data
└── lilbrotr-production/     # Isolated PostgreSQL data

/mnt/work/
├── bigbrotr-production/     # Dumps, exports, analysis
│   ├── dumps/
│   ├── exports/
│   └── analysis/
└── lilbrotr-production/
    ├── dumps/
    ├── exports/
    └── analysis/
```

---

## Appendix D — Updating BigBrotr

```bash
cd /opt/bigbrotr-production
docker compose pull
docker compose up -d
```

This pulls the latest images from Docker Hub and restarts only the containers that changed. Your local configuration (`.env`, `postgresql.conf`, `docker-compose.yaml`) is never affected.

> **Schema changes**: If a release includes database schema changes (new materialized views, stored procedures, or indexes), the release notes will include migration instructions. In most cases this means re-initializing the database: `docker compose down && rm -rf data/postgres && docker compose up -d`.
