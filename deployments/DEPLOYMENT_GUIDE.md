# BigBrotr Production Deployment Guide

A comprehensive, step-by-step guide for deploying BigBrotr on a self-hosted Proxmox server with dedicated storage, Cloudflare Tunnel for secure API exposure, and production-grade PostgreSQL tuning.

## Target Hardware

| Component | Specification |
|-----------|--------------|
| CPU | 16 cores / 32 threads |
| RAM | 96 GB |
| Boot / OS | 2x NVMe SSD 1TB — ZFS mirror (`rpool`, Proxmox OS) |
| Database storage | 4x Samsung 870 EVO 4TB SATA SSD — ZFS RAID10 (`datapool`, ~7.2TB usable) |
| Work storage | 2x WD Blue SA510 4TB SATA SSD — ZFS stripe (`workpool`, ~7.2TB usable, no redundancy) |

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    PROXMOX HOST (rpool — NVMe ZFS mirror)           │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                 VM 100 "bigbrotr" (Debian 13 trixie)            │  │
│  │                 12 vCPU · 64GB RAM · OS on NVMe                │  │
│  │                                                                │  │
│  │  /mnt/pgdata  ← virtio disk from datapool (Samsung RAID10)    │  │
│  │     └── PostgreSQL data directory (EXCLUSIVELY)                │  │
│  │                                                                │  │
│  │  /mnt/work    ← virtio disk from workpool (WD stripe)         │  │
│  │     └── pg_dump, exports, analysis results, downloadable files │  │
│  │                                                                │  │
│  │  Docker Compose → 15 containers (8 services + 7 infra)        │  │
│  │  cloudflared  → Cloudflare Tunnel (zero open ports)            │  │
│  │                                                                │  │
│  │  PostgreSQL accessible on Proxmox internal network (vmbr0)     │  │
│  │  for research queries from other VMs/LXC containers            │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  Internet → Cloudflare → Tunnel → localhost:8080 (API only)         │
│  No inbound ports open on the server                                │
└──────────────────────────────────────────────────────────────────────┘
```

### Storage Strategy

| Pool | Disks | Topology | Use | Why |
|------|-------|----------|-----|-----|
| `rpool` | 2x NVMe 1TB | ZFS mirror | Proxmox OS + VM boot disk | Fast NVMe for OS operations, Docker images, container layers |
| `datapool` | 4x Samsung 870 EVO 4TB | ZFS RAID10 (2 mirrors striped) | PostgreSQL data exclusively | High IOPS for DB, redundancy (survives 1 disk failure per mirror), ~7.2TB usable |
| `workpool` | 2x WD Blue SA510 4TB | ZFS stripe (no redundancy) | DB dumps, exports, analysis results | Large sequential files, data is reproducible, no need for redundancy |

### Network & Security Strategy

- **Cloudflare Tunnel**: The API is exposed via an outbound-only tunnel. No inbound ports are opened on the server or the VM. Cloudflare handles TLS termination, DDoS protection, WAF, and rate limiting.
- **PostgreSQL access**: Available on the Proxmox internal bridge network (`vmbr0`) for research VMs/LXC containers. Blocked from the internet by UFW firewall rules.
- **SSH**: Key-only authentication on a non-standard port with fail2ban.

---

## Phase 0 — Proxmox Post-Installation

A fresh Proxmox install requires some baseline configuration before it is ready for production use.

### 0.1 — Access the Shell

Access the Proxmox shell via one of:
- **Physical access**: Keyboard and monitor connected to the server, login as `root`
- **Web GUI**: Browse to `https://<SERVER_IP>:8006` → login → select node `pve` → **Shell** (top right)

To find the server IP (if unknown), from the physical console:

```bash
ip addr show vmbr0
```

Look for the `inet` line — that is the server's IP (e.g., `192.168.1.100/24`).

### 0.2 — Disable Enterprise Repositories

Proxmox ships with enterprise repositories that require a paid subscription. Without a license, `apt update` will fail with `401 Unauthorized`. We disable them and enable the free community repository instead.

**Check what repository files exist** (Proxmox 9.x uses the `.sources` format, older versions use `.list`):

```bash
ls /etc/apt/sources.list.d/
```

**For Proxmox 9.x** (`.sources` files — e.g., `pve-enterprise.sources`, `ceph.sources`):

Check if the files contain an `Enabled:` field:

```bash
cat /etc/apt/sources.list.d/pve-enterprise.sources
cat /etc/apt/sources.list.d/ceph.sources
```

If there is **no** `Enabled:` field (common in Proxmox 9.1+), add it:

```bash
echo "Enabled: no" >> /etc/apt/sources.list.d/pve-enterprise.sources
echo "Enabled: no" >> /etc/apt/sources.list.d/ceph.sources
```

If there **is** an `Enabled: yes` field, change it:

```bash
sed -i 's/^Enabled: yes/Enabled: no/' /etc/apt/sources.list.d/pve-enterprise.sources
sed -i 's/^Enabled: yes/Enabled: no/' /etc/apt/sources.list.d/ceph.sources
```

**For older Proxmox** (`.list` files — e.g., `pve-enterprise.list`):

```bash
sed -i 's/^deb/#deb/' /etc/apt/sources.list.d/pve-enterprise.list
```

**Add the free community repository**:

```bash
echo "deb http://download.proxmox.com/debian/pve bookworm pve-no-subscription" > /etc/apt/sources.list.d/pve-no-subscription.list
```

**Verify** — this should complete with no errors:

```bash
apt update
```

### 0.3 — Remove Subscription Nag Popup (Optional)

Every login to the Proxmox web GUI shows a "No valid subscription" popup. This is cosmetic only but can be removed:

```bash
sed -Ei.bak "s/NotFound/Active/g" /usr/share/javascript/proxmox-widget-toolkit/proxmoxlib.js
systemctl restart pveproxy
```

> **Note**: This change is overwritten by Proxmox upgrades. Re-run after `apt full-upgrade` if the popup returns.

### 0.4 — Update the System

```bash
apt full-upgrade -y
```

If a kernel update is installed, reboot:

```bash
reboot
```

After reboot, verify:

```bash
pveversion
uname -r
```

### 0.5 — Install Useful Tools

```bash
apt install -y htop iotop tmux tree
```

### 0.6 — Verify rpool Health

```bash
zpool status rpool
zpool list rpool
```

Expected: `state: ONLINE`, no errors. Both NVMe disks in the mirror should show `ONLINE`.

---

## Phase 1 — Create ZFS Storage Pools

### 1.1 — Identify All Disks

Before creating any pools, positively identify every disk in the system using stable identifiers (never use `sda`/`sdb` names — they can change between reboots):

```bash
lsblk -d -o NAME,SIZE,MODEL,SERIAL
```

Then get the stable `/dev/disk/by-id/` names:

```bash
# Samsung disks (for datapool)
ls -la /dev/disk/by-id/ | grep -i samsung | grep -v part

# WD disks (for workpool)
ls -la /dev/disk/by-id/ | grep -iE "wd|western" | grep -v part
```

Record the full `ata-Samsung_SSD_870_EVO_4TB_XXXX` and `ata-WD_Blue_SA510_XXXX` identifiers. You need exactly 4 Samsung and 2 WD.

**Check SMART data to identify used vs. new disks** (critical for optimal mirror pairing):

```bash
smartctl -a /dev/sdX | grep -E "Device Model|Serial|Power_On_Hours|Total_LBAs_Written|Wear_Leveling"
```

Run this for each Samsung disk. Pair each used disk with a new disk in the same mirror, so that if a used disk fails, the new disk in that mirror has the complete copy. Never pair two used disks together.

### 1.2 — Destroy Existing datapool (If Previously Created)

If a `datapool` already exists and you want to start fresh:

```bash
# Check current state
zpool list datapool
zfs list -r datapool

# Destroy (WARNING: this deletes all data on the pool)
zpool destroy datapool

# Also remove the Proxmox storage definition if it exists
pvesm remove datapool 2>/dev/null

# Verify it is gone
zpool list
```

### 1.3 — Create datapool (Samsung RAID10)

This creates a RAID10 pool: two mirrored pairs striped together, giving ~7.2TB usable with single-disk-failure tolerance per mirror pair.

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
    /dev/disk/by-id/ata-Samsung_SSD_870_EVO_4TB_USED1 \
    /dev/disk/by-id/ata-Samsung_SSD_870_EVO_4TB_NEW1 \
  mirror \
    /dev/disk/by-id/ata-Samsung_SSD_870_EVO_4TB_USED2 \
    /dev/disk/by-id/ata-Samsung_SSD_870_EVO_4TB_NEW2
```

> **Replace** placeholders with actual serial-based disk IDs from step 1.1. Each mirror must pair one used disk with one new disk (based on SMART data from step 1.1).

**Option rationale**:

| Option | Value | Rationale |
|--------|-------|-----------|
| `ashift=12` | 4K sectors | Correct alignment for all modern SSDs/HDDs. Setting this wrong permanently degrades performance and cannot be changed after pool creation |
| `compression=lz4` | Fast compression | PostgreSQL data compresses ~1.5-2x. LZ4 has negligible CPU overhead |
| `atime=off` | No access timestamps | Eliminates unnecessary write I/O on every read. Critical for databases |
| `recordsize=8K` | 8KB blocks | Matches PostgreSQL's page size (8192 bytes) exactly. Any other value causes write amplification — ZFS would need to read-modify-write partial blocks |
| `primarycache=metadata` | Cache metadata only | PostgreSQL manages its own data cache via `shared_buffers`. Caching data again in ZFS's ARC wastes RAM. Metadata caching remains useful for filesystem navigation |
| `logbias=throughput` | Throughput-optimized | Reduces writes to the ZFS Intent Log (ZIL). Optimal for database workloads using `synchronous_commit=off` where PostgreSQL already accepts the small data-loss risk window |

**Register datapool in Proxmox**:

```bash
pvesm add zfspool datapool \
  --pool datapool \
  --content images \
  --sparse 0 \
  --blocksize 8k \
  --nodes pve
```

`sparse 0` means thick provisioning — the full zvol size is reserved immediately. This prevents fragmentation and guarantees space availability, both important for database workloads.

**Verify**:

```bash
zpool status datapool
zpool list datapool
zfs get all datapool | grep -E "(compress|atime|record|primary|logbias)"
```

### 1.4 — Create workpool (WD Stripe)

This creates a striped pool from two WD disks. No redundancy — if either disk fails, all data is lost. This is acceptable because the pool stores only reproducible data (database dumps, exports, analysis results).

```bash
zpool create -f \
  -o ashift=12 \
  -O compression=lz4 \
  -O atime=off \
  -O xattr=sa \
  -O recordsize=1M \
  workpool \
  /dev/disk/by-id/ata-WD_Blue_SA510_2.5_4TB_XXXXX \
  /dev/disk/by-id/ata-WD_Blue_SA510_2.5_4TB_YYYYY
```

> **Replace** the `XXXXX`, `YYYYY` placeholders with actual disk IDs from step 1.1.

**Key differences from datapool**:

| Option | datapool | workpool | Rationale |
|--------|----------|----------|-----------|
| `recordsize` | 8K | 1M | datapool: PostgreSQL 8KB pages. workpool: large sequential files (SQL dumps, CSV exports) benefit from large blocks |
| `primarycache` | metadata | all (default) | workpool: no application-level cache, ZFS ARC is beneficial |
| `logbias` | throughput | latency (default) | workpool: data integrity matters more than write speed for backups |
| Topology | mirror x2 (RAID10) | stripe | workpool: data is reproducible (re-dumpable), redundancy not needed |

**Register workpool in Proxmox**:

```bash
pvesm add zfspool workpool \
  --pool workpool \
  --content images \
  --sparse 0 \
  --blocksize 128k \
  --nodes pve
```

**Verify all storage**:

```bash
zpool list
zpool status
pvesm status
cat /etc/pve/storage.cfg
```

---

## Phase 2 — Create the Virtual Machine

### 2.1 — Download Debian 13 (trixie) ISO

From the Proxmox web GUI:
1. Navigate to **local (pve)** → **ISO Images** → **Download from URL**
2. URL: `https://cdimage.debian.org/debian-cd/current/amd64/iso-cd/` (pick the latest `debian-13.x.x-amd64-netinst.iso`)
3. Click **Query URL** then **Download**

> **Why Debian 13 (trixie)?** Proxmox 9.1 is based on Debian trixie. Using the same Debian release as the host ensures kernel and library compatibility.

### 2.2 — Create the VM

From the Proxmox web GUI, click **Create VM** and configure:

**General**:
- VM ID: `100`
- Name: `bigbrotr`

**OS**:
- ISO: Select the downloaded Debian 13 ISO
- Type: Linux
- Version: 6.x - 2.6 Kernel

**System**:
- BIOS: **OVMF (UEFI)**
- Machine: **q35**
- EFI Storage: **local-zfs** (NVMe)
- Add TPM: No
- SCSI Controller: **VirtIO SCSI single**
- Qemu Agent: **Yes** (enables host↔VM communication for IP reporting, graceful shutdown, etc.)

**Disks** — three disks are needed:

| Disk | Storage | Size | Purpose |
|------|---------|------|---------|
| scsi0 (OS) | **local-zfs** (NVMe) | **50 GiB** | Debian OS, Docker, container images |
| scsi1 (DB data) | **datapool** | **7000 GiB** (~6.8 TiB) | PostgreSQL data directory exclusively |
| scsi2 (Work) | **workpool** | **7000 GiB** (~6.8 TiB) | Dumps, exports, analysis results |

For all three disks:
- Discard: **Yes** (enables TRIM/UNMAP for ZFS)
- IO Thread: **Yes** (dedicated I/O thread per disk for better performance)
- Cache: **No cache** (ZFS and PostgreSQL handle their own caching)

> **Why 7000 GiB and not the full pool?** Leaving ~250 GiB free (~3.5%) gives ZFS headroom for metadata, copy-on-write operations, and occasional snapshots. ZFS performance degrades significantly above ~95% capacity. The datapool can be expanded later by adding another mirror pair (`zpool add datapool mirror /dev/disk/by-id/NEW_DISK_1 /dev/disk/by-id/NEW_DISK_2`).

**CPU**:
- Sockets: **1**
- Cores: **12**
- Type: **host** (passes through the host CPU's native instruction set for maximum performance — AES-NI, AVX2, etc.)

> **Why 12 of 32 threads?** Leaves 20 threads for the Proxmox host (minimal needs), future research VMs/LXC containers, and ZFS background operations (scrub, resilver).

**Memory**:
- Memory: **65536 MiB** (64 GiB)
- Ballooning: **No** (in Advanced settings)

> **Why disable ballooning?** Memory ballooning allows Proxmox to dynamically reclaim RAM from the VM. For database workloads this is dangerous — PostgreSQL's `shared_buffers` (16GB) must remain resident in RAM at all times. Ballooning could cause the OS to swap out shared_buffers, causing catastrophic performance degradation.

**Network**:
- Bridge: **vmbr0**
- Model: **VirtIO (paravirtualized)** (best network performance for Linux guests)
- Firewall: **Yes**

**Do not start the VM yet.**

### 2.3 — Verify VM Configuration

From the Proxmox shell:

```bash
qm config 100
```

Verify three disks are listed (`scsi0`, `scsi1`, `scsi2`) on the correct storage pools.

### 2.4 — Enable NUMA for Multi-CCD CPUs

The Ryzen 9 9955HX has two CCDs. Without NUMA awareness, Proxmox scheduled all 12 vCPUs on CCD1, which hit 93°C while CCD2 sat at 52°C. Enabling NUMA distributes the workload across both chiplets:

```bash
qm set 100 --numa 1
```

After enabling, CCD1 dropped to ~60°C and CCD2 came up to ~47°C. Requires a VM reboot to take effect.

---

## Phase 3 — Install Debian 13 (trixie)

Start the VM from the Proxmox GUI and open the **Console** (noVNC or xterm.js).

### 3.1 — Debian Installer

Select **Install** (text mode is fine):

- Language: **English**
- Country: **Your country** (e.g., Italy)
- Keyboard: **Your layout** (e.g., Italian)
- Hostname: **bigbrotr**
- Domain: leave empty
- Root password: **Choose a strong password** (will be replaced with SSH key auth later)
- Create user: full name **BigBrotr**, username **bigbrotr**
- Timezone: **Your timezone** (e.g., Europe/Rome)

**Partitioning — CRITICAL STEP**:

Select **Manual**. You will see three disks. The order may differ from what you expect — identify them by **size**, not by letter:

| Disk in installer | Size | Identity |
|-------------------|------|----------|
| ~50 GB | OS disk (NVMe via local-zfs) |
| ~7.5 TB | datapool (Samsung RAID10) |
| ~7.5 TB | workpool (WD stripe) |

> **IMPORTANT**: The disk letters (sda, sdb, sdc) assigned by the installer may not match the order you added them in Proxmox. Always identify the OS disk by its ~50 GB size.

**Only partition the ~50 GB OS disk**:

1. Select the ~50 GB disk → Create new partition table → **GPT**
2. Create partitions:

| Partition | Size | Type | Mount |
|-----------|------|------|-------|
| 1 | 512 MB | EFI System Partition | /boot/efi |
| 2 | ~48 GiB | ext4 | / |
| 3 | ~1.5 GiB (remainder) | swap | swap |

**Do NOT partition the two ~7.5 TB disks** — we will format them from the shell after installation for precise control over filesystem options.

**Software selection**:
- Deselect everything **except**:
  - **SSH server**
  - **Standard system utilities**
- Do **NOT** install a desktop environment (unnecessary overhead on a server)

**Bootloader**: Install GRUB on `sda`.

Complete installation and reboot.

### 3.2 — Enable Root SSH Access

Debian 13 disables root SSH login with password by default. To enable it temporarily (for convenient remote access during setup):

```bash
echo "PermitRootLogin yes" > /etc/ssh/sshd_config.d/root.conf
systemctl restart sshd
```

You can now SSH into the VM from your workstation: `ssh root@<VM_IP>`. This is much more convenient than the Proxmox console (supports copy-paste). This will be replaced with key-only authentication in Phase 7.

### 3.3 — First Boot Setup

Login as `root` via SSH.

**Fix locale warnings** (common on fresh Debian installs):

```bash
sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen && locale-gen
```

**Install essential packages**:

```bash
apt update && apt upgrade -y
apt install -y \
  qemu-guest-agent \
  curl \
  wget \
  git \
  htop \
  iotop \
  tmux \
  unzip \
  sudo \
  ufw \
  fail2ban \
  parted \
  xfsprogs
```

**Enable the QEMU guest agent** (allows Proxmox to see the VM's IP, issue graceful shutdowns, etc.):

```bash
systemctl enable --now qemu-guest-agent
```

### 3.4 — Format and Mount Data Disks

Identify the disks by size (letters may vary):

```bash
lsblk -d -o NAME,SIZE,MODEL
```

Map the disks by size:
- **~50G** → OS disk (already partitioned)
- **~6.8T** (two of these) → data disks (need formatting)

> **IMPORTANT**: Verify which 6.8T disk is on datapool vs workpool. If you added them in order (datapool first, workpool second), the first 6.8T disk is datapool. When in doubt, check `qm config 100` from the Proxmox host to see which SCSI ID maps to which pool.

In the example below, `sda` is the datapool disk and `sdc` is the workpool disk. **Adjust the device names to match your system.**

**PostgreSQL data disk — XFS**:

XFS is chosen over ext4 for the database disk because of superior performance with large files, better write-ahead log handling, and excellent behavior under sustained write-heavy workloads.

```bash
# Create a single GPT partition spanning the full disk
parted /dev/sda mklabel gpt
parted /dev/sda mkpart primary 0% 100%

# Format with XFS, optimized for database workloads
mkfs.xfs -f -L pgdata /dev/sda1

# Create mount point
mkdir -p /mnt/pgdata

# Add persistent mount to fstab
echo 'LABEL=pgdata /mnt/pgdata xfs defaults,noatime,nodiratime,logbufs=8,logbsize=256k,inode64 0 2' >> /etc/fstab

# Mount and verify
mount /mnt/pgdata
df -h /mnt/pgdata
```

XFS mount options explained:
- `noatime,nodiratime`: Do not update access timestamps on reads. Eliminates unnecessary write I/O.
- `logbufs=8,logbsize=256k`: Larger XFS journal buffers. Improves write throughput for database workloads.
- `inode64`: Allow inodes to be allocated across the entire filesystem. Required for filesystems larger than 2TB.

**Work disk (`sdc`) — XFS**:

```bash
parted /dev/sdc mklabel gpt
parted /dev/sdc mkpart primary 0% 100%

mkfs.xfs -f -L workdata /dev/sdc1

mkdir -p /mnt/work

echo 'LABEL=workdata /mnt/work xfs defaults,noatime,nodiratime,inode64 0 2' >> /etc/fstab

mount /mnt/work
df -h /mnt/work
```

**Create work directory structure**:

```bash
mkdir -p /mnt/work/{dumps,exports,analysis}
```

### 3.5 — Configure Static IP

A server must have a static IP to ensure consistent network access.

```bash
# Find current interface name and IP
ip addr show
# Typically ens18 or eth0 on Proxmox VMs
```

Edit `/etc/network/interfaces`:

```bash
nano /etc/network/interfaces
```

Replace the DHCP configuration for the main interface with a static one:

```
auto ens18
iface ens18 inet static
    address 192.168.1.XXX/24
    gateway 192.168.1.1
    dns-nameservers 1.1.1.1 8.8.8.8
```

> **Replace** `192.168.1.XXX` with the VM's current IP (or a new one in your subnet) and `192.168.1.1` with your router's IP.

Apply:

```bash
systemctl restart networking
```

**CRITICAL: Fix DNS resolver.** With a static IP, DHCP no longer manages `/etc/resolv.conf`. After a reboot, the file will be empty — `cloudflared` crashes (can't resolve SRV records), `apt` can't reach repositories, and services fail to reach external APIs.

```bash
cat > /etc/resolv.conf << 'EOF'
nameserver 1.1.1.1
nameserver 8.8.8.8
EOF

# Make immutable — prevents dhcpcd or other services from overwriting on reboot
chattr +i /etc/resolv.conf
```

> To edit the file later, remove the immutable flag first: `chattr -i /etc/resolv.conf`

### 3.6 — Kernel Parameters for PostgreSQL

These sysctl settings optimize the Linux kernel for running a large PostgreSQL instance:

```bash
cat >> /etc/sysctl.d/99-postgresql.conf << 'EOF'
# Shared memory — sized for PostgreSQL shared_buffers = 16GB
kernel.shmmax = 17179869184
kernel.shmall = 4194304

# Virtual memory
vm.overcommit_memory = 2
vm.overcommit_ratio = 95
vm.swappiness = 1
vm.dirty_background_ratio = 3
vm.dirty_ratio = 10

# Network — supports high connection count from services + WebSocket connections
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 65535
net.ipv4.ip_local_port_range = 1024 65535
net.ipv4.tcp_tw_reuse = 1
net.core.netdev_max_backlog = 65535

# File descriptors — Docker + PostgreSQL + services need many open files
fs.file-max = 2097152
EOF

sysctl --system
```

Parameter rationale:
- `kernel.shmmax/shmall`: Sized to accommodate PostgreSQL's 16GB `shared_buffers`.
- `vm.overcommit_memory=2`: Strict overcommit accounting. Prevents the OOM killer from killing PostgreSQL.
- `vm.swappiness=1`: Almost never swap. PostgreSQL manages its own memory; swapping shared_buffers is catastrophic.
- `vm.dirty_background_ratio=3` / `vm.dirty_ratio=10`: Start flushing dirty pages early and cap them. Prevents large write storms that cause I/O stalls.
- `net.core.somaxconn=65535`: Large listen backlog for PostgreSQL and the API service.
- `fs.file-max=2097152`: Docker containers, PostgreSQL, and the 8 BigBrotr services collectively open many file descriptors.

### 3.7 — System Limits

```bash
cat >> /etc/security/limits.d/99-bigbrotr.conf << 'EOF'
*    soft    nofile    1048576
*    hard    nofile    1048576
*    soft    nproc     65535
*    hard    nproc     65535
EOF
```

---

## Phase 4 — Install Docker

Docker is the container runtime for all BigBrotr services.

```bash
# Remove any old/conflicting packages
apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null

# Add Docker's official GPG key and repository
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group (optional, allows running docker without sudo)
usermod -aG docker vincenzo

# Verify installation
docker --version
docker compose version
```

### 4.1 — Docker Production Configuration

```bash
mkdir -p /etc/docker
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

Configuration rationale:
- `log-driver` / `log-opts`: JSON file logging with rotation. Prevents container logs from filling the disk.
- `storage-driver: overlay2`: The standard and most performant storage driver for modern Linux.
- `live-restore: true`: Keeps containers running during Docker daemon restarts (e.g., during Docker upgrades).
- `default-ulimits`: Ensures all containers can open enough file descriptors.

---

## Phase 5 — Deploy BigBrotr

### 5.1 — Download the Deployment Folder

You only need the deployment folder — not the full repository. Download the latest release and extract the deployment template:

```bash
cd /opt
RELEASE=$(curl -s https://api.github.com/repos/BigBrotr/bigbrotr/releases/latest | grep tarball_url | cut -d '"' -f 4)
curl -sL "$RELEASE" | tar xz --strip-components=2 --include="*/deployments/bigbrotr"
mv bigbrotr bigbrotr-production
```

### 5.2 — Configure Docker Hub Images

Edit `docker-compose.yaml` to use pre-built images from Docker Hub instead of building locally. Replace every `build:` block in the 8 service definitions with an `image:` line:

```yaml
# Replace this (in seeder, finder, validator, monitor, synchronizer, refresher, api, dvm):
    build:
      context: ../../
      dockerfile: deployments/Dockerfile
      args:
        DEPLOYMENT: bigbrotr

# With this:
    image: vincenzoimp/bigbrotr:6
```

The `:6` tag always points to the latest 6.x.x release.

All subsequent commands operate from the production folder:

```bash
cd /opt/bigbrotr-production
```

**Update procedure** (for future releases):

```bash
cd /opt/bigbrotr-production
docker compose pull                 # pulls latest images from Docker Hub
docker compose up -d                # restarts only changed containers
```

### 5.3 — Link PostgreSQL Data to Dedicated Disk

The `docker-compose.yaml` mounts `./data/postgres` as a bind mount for PostgreSQL data. We symlink this to the dedicated RAID10 disk:

```bash
# Create the PostgreSQL data directory on the RAID10 disk
mkdir -p /mnt/pgdata/postgres

# Create the data directory in the deployment and symlink
mkdir -p /opt/bigbrotr-production/data
ln -s /mnt/pgdata/postgres /opt/bigbrotr-production/data/postgres

# Set ownership for PostgreSQL container (runs as uid 999 in postgres:alpine)
chown -R 999:999 /mnt/pgdata/postgres
```

### 5.3.1 — Fix Permissions for Monitor GeoLite2 Downloads

The Monitor service downloads MaxMind GeoLite2 databases on first run. The container runs as uid 1000 (non-root) and needs write access to the `static/` directory:

```bash
chown -R 1000:1000 /opt/bigbrotr-production/static/
```

Without this, Monitor fails with `Permission denied: 'static/GeoLite2-City.mmdb'` and crashes after 5 consecutive failures.

### 5.4 — Generate Credentials

Generate strong random passwords for all database roles and services:

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

> **CRITICAL**: Save the contents of `.env` in a password manager (Bitwarden, 1Password, KeePass). Losing these credentials means losing access to the database.

### 5.5 — PostgreSQL Production Configuration

The shipped `postgresql.conf` is tuned for a 4GB RAM environment. For 64GB RAM, create an optimized production configuration. See the section below for the full file and rationale for each setting.

Back up the original and overwrite:

```bash
cp postgres/postgresql.conf postgres/postgresql.conf.original
# Write production config to postgres/postgresql.conf (see full config below)
```

**Production PostgreSQL Configuration (64GB RAM, 12 vCPU, SSD RAID10)**:

```ini
# --- Connection ---
listen_addresses = '*'
port = 5432
max_connections = 200
superuser_reserved_connections = 3
password_encryption = 'scram-sha-256'

# --- Memory (64GB RAM) ---
shared_buffers = 16GB              # 25% of RAM — PostgreSQL's main data cache
effective_cache_size = 48GB        # 75% of RAM — hint for query planner (includes OS page cache)
work_mem = 64MB                    # Per-sort/hash operation — generous for complex analytical queries
maintenance_work_mem = 2GB         # VACUUM, CREATE INDEX — large for fast maintenance on big tables
huge_pages = try                   # Use huge pages if available — reduces TLB misses for large shared_buffers

# --- WAL ---
wal_buffers = 64MB                 # WAL write buffer — auto-tuned default is often too small at this scale
min_wal_size = 2GB                 # Minimum WAL retained — reduces checkpoint frequency
max_wal_size = 8GB                 # Maximum WAL before forced checkpoint
checkpoint_completion_target = 0.9 # Spread checkpoint writes over 90% of the interval
checkpoint_timeout = 15min         # Time between automatic checkpoints

# --- Write Performance ---
synchronous_commit = off           # Async commits — ~10ms data loss risk, acceptable for re-fetchable Nostr data
commit_delay = 100                 # Microseconds to wait for group commit
commit_siblings = 5                # Minimum concurrent transactions to trigger commit_delay
wal_writer_delay = 200ms           # WAL writer sleep time

# --- Query Optimization (SSD) ---
random_page_cost = 1.1             # SSD-optimized — random reads nearly as fast as sequential
effective_io_concurrency = 200     # Concurrent I/O requests — high value for SSDs
default_statistics_target = 200    # More detailed statistics for better query plans

# --- Parallel Execution ---
max_worker_processes = 12          # Total background workers available
max_parallel_workers = 8           # Workers available for parallel queries
max_parallel_workers_per_gather = 4  # Max workers per single parallel query
max_parallel_maintenance_workers = 4 # Workers for parallel VACUUM, CREATE INDEX

# --- Autovacuum (write-heavy) ---
autovacuum_max_workers = 4         # Concurrent autovacuum workers
autovacuum_naptime = 30s           # Check for vacuum-needing tables every 30s
autovacuum_vacuum_threshold = 50   # Minimum dead tuples before vacuum
autovacuum_analyze_threshold = 50  # Minimum changed tuples before analyze
autovacuum_vacuum_scale_factor = 0.05  # Vacuum after 5% of rows are dead
autovacuum_analyze_scale_factor = 0.025  # Analyze after 2.5% of rows change
autovacuum_vacuum_cost_delay = 2ms # Minimal delay between vacuum I/O operations
autovacuum_vacuum_cost_limit = 2000  # High cost limit — let autovacuum work aggressively

# --- Background Writer ---
bgwriter_delay = 20ms              # Frequent background writing
bgwriter_lru_maxpages = 400        # More pages per round
bgwriter_lru_multiplier = 4.0      # Aggressive pre-cleaning of shared buffers

# --- Timeouts ---
idle_in_transaction_session_timeout = 60000   # Kill idle-in-transaction after 60s
statement_timeout = 300000                     # Kill queries running longer than 5 minutes

# --- Logging (minimal for production) ---
log_destination = 'stderr'
logging_collector = off            # Docker handles log collection
log_min_messages = warning
log_min_error_statement = error
log_statement = 'none'
log_lock_waits = on                # Log waits longer than deadlock_timeout
log_temp_files = 0                 # Log all temp file usage (indicates work_mem too small)

# --- Statistics ---
shared_preload_libraries = 'pg_stat_statements'
pg_stat_statements.track = all

# --- Misc ---
timezone = 'UTC'
```

### 5.5.1 — Docker Shared Memory for PostgreSQL

With `shared_buffers = 16GB`, Docker's default 64MB `/dev/shm` is insufficient. Materialized view refreshes that use parallel workers will fail with `could not resize shared memory segment: No space left on device`.

Add `shm_size` matching `shared_buffers` to the postgres service:

```bash
sed -i '/container_name: bigbrotr-postgres/a\    shm_size: 16g' docker-compose.yaml
```

Verify it was inserted correctly:

```bash
grep -A2 "bigbrotr-postgres" docker-compose.yaml | head -3
# Expected:
#     container_name: bigbrotr-postgres
#     shm_size: 16g
#     restart: unless-stopped
```

### 5.6 — Expose Services on Internal Network

By default, all service ports are bound to `127.0.0.1` (localhost only). For production use on a local network, we expose certain services so they are reachable from other devices on the Proxmox bridge network.

Edit `docker-compose.yaml` to change these port bindings:

```bash
cd /opt/bigbrotr-production

# PostgreSQL — accessible from research VMs/LXC on the local network
sed -i 's/127.0.0.1:5432:5432/5432:5432/' docker-compose.yaml

# Grafana — accessible from any device on the local network for monitoring
sed -i 's/127.0.0.1:3000:3000/3000:3000/' docker-compose.yaml

# Prometheus — accessible from the local network for monitoring
sed -i 's/127.0.0.1:9090:9090/9090:9090/' docker-compose.yaml
```

Security for exposed ports:
1. **VM firewall (UFW)**: Only allows connections from the Proxmox internal subnet
2. **Proxmox firewall**: No port forwarding to the internet
3. **PostgreSQL authentication**: SCRAM-SHA-256 with strong passwords
4. **Database roles**: Research queries use the `reader` role (SELECT-only)
5. **Grafana authentication**: Password-protected admin login

All other services (PGBouncer, Tor, Alertmanager, service metrics) remain on `127.0.0.1`.

### 5.7 — Pre-Flight Verification

Before starting services, verify all configuration is correct:

```bash
# Symlink points to RAID10 disk
ls -la /opt/bigbrotr-production/data/

# PostgreSQL config is production-tuned (should show 16GB, not 1GB)
grep "shared_buffers" /opt/bigbrotr-production/postgres/postgresql.conf

# Ports are exposed correctly
grep -E "5432|3000|9090" /opt/bigbrotr-production/docker-compose.yaml

# .env exists with restricted permissions
ls -la /opt/bigbrotr-production/.env

# PostgreSQL data directory has correct ownership
ls -la /mnt/pgdata/

# Production folder exists
ls /opt/bigbrotr-production/docker-compose.yaml
```

### 5.8 — Pull Images and Start

```bash
cd /opt/bigbrotr-production

# Pull pre-built images from Docker Hub
docker compose pull

# Start infrastructure gradually, waiting for health checks between each step
docker compose up -d postgres
# Wait ~15 seconds, then verify:
docker compose ps postgres
# Must show "healthy" before proceeding

docker compose up -d pgbouncer tor
# Wait ~30 seconds (Tor is slow to bootstrap), then verify:
docker compose ps

# Start all remaining services
docker compose up -d

# Verify everything is running
docker compose ps

# Check logs for errors
docker compose logs --tail=50 postgres
docker compose logs --tail=50 seeder
docker compose logs --tail=50 finder
```

### 5.9 — Verify Deployment

```bash
# API responding
curl -s http://localhost:8080/health
# Expected: {"status":"ok"}

# Seeder completed (should show candidates inserted)
docker compose logs seeder --tail=5

# Candidates in the database (populated by seeder, processed by validator)
docker compose exec postgres psql -U admin -d bigbrotr \
  -c "SELECT count(*) FROM service_state;"
# Expected: ~7000-8000 candidates

# Validator is processing
docker compose logs validator --tail=5

# Database tables (6 expected)
docker compose exec postgres psql -U admin -d bigbrotr -c "\dt"

# Materialized views (11 expected)
docker compose exec postgres psql -U admin -d bigbrotr -c "\dm"
```

> **Note**: The Seeder inserts relay URLs as **candidates** in `service_state`. The Validator then checks each candidate via WebSocket and promotes valid ones to the `relay` table. This process takes time — the first full validation pass runs on a 5-minute cycle, processing candidates in chunks. Expect relays to start appearing in the `relay` table within 10-30 minutes.

---

## Phase 6 — Cloudflare Tunnel Setup

Cloudflare Tunnel provides secure, zero-trust access to the API without opening any inbound ports on the server. The tunnel daemon (`cloudflared`) runs inside the VM and creates an outbound-only HTTPS connection to Cloudflare's edge network. Cloudflare then routes incoming requests for `api.bigbrotr.com` through this tunnel to your API.

### 6.1 — Create Cloudflare Account and Add Domain

1. Go to **cloudflare.com** → **Sign Up** (free tier is sufficient)
2. From the dashboard, click **Add a site**
3. Enter **bigbrotr.com**
4. Select **Import DNS records automatically** (recommended)
5. Under **Block AI training bots**, select **Block on all pages**
6. Click **Continue**
7. Select the **Free** plan → **Continue**
8. Cloudflare will scan existing DNS records and show them for review

### 6.2 — Review DNS Records

Cloudflare imports existing DNS records from your current nameservers. Review them carefully:

- If you have a website on Vercel (or any other service), verify those records are present
- Remove any records you don't recognize
- You can add missing records later from the Cloudflare DNS dashboard

Click **Continue** to proceed to the nameserver change instructions.

### 6.3 — Change Nameservers on Namecheap

Cloudflare provides two nameservers (e.g., `ada.ns.cloudflare.com`, `lee.ns.cloudflare.com`).

On Namecheap:
1. Go to **Dashboard** → **Domain List** → **bigbrotr.com** → **Manage**
2. In the **Nameservers** section, select **Custom DNS**
3. Enter the two Cloudflare nameservers (exactly as shown in the Cloudflare dashboard)
4. Click the green checkmark to save

Propagation typically takes 15-30 minutes (up to 48 hours in rare cases). Cloudflare will send an email when the domain is active.

> **Note**: During propagation, your existing website (e.g., Vercel) may experience brief downtime. This is normal and resolves once DNS propagates.

### 6.4 — Verify Existing DNS Records

Once the domain is active on Cloudflare, go to the **DNS** section in the Cloudflare dashboard. Verify that records for any existing services (e.g., Vercel site) are present and correct. Add or fix any missing records.

### 6.5 — Create and Install Cloudflare Tunnel

**In the Cloudflare dashboard**:
1. Go to **Zero Trust** (left sidebar)
2. Navigate to **Networks** → **Tunnels** (listed as "Connectors" in newer UI)
3. Click **Add a tunnel**
4. Select **Cloudflared** as the connector type → **Next**
5. Name: **bigbrotr-prod** → **Save tunnel**
6. Select architecture: **64-bit** (for Debian amd64)
7. Cloudflare will show installation commands and a token

**In the BigBrotr VM**:

```bash
# Install cloudflared
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared.deb
rm cloudflared.deb

# Install as a system service with the token from the Cloudflare dashboard
# Copy the FULL token from the "Install and run a connector" section
# It starts with eyJ... and is very long
cloudflared service install <TOKEN_FROM_DASHBOARD>

# Verify — should show "active (running)" with 4 registered connections
systemctl status cloudflared
```

Expected output should show `Registered tunnel connection` lines to multiple Cloudflare edge locations (e.g., `zrh02`, `ams01`).

### 6.6 — Configure Tunnel Route

After installation, the Cloudflare dashboard should show the tunnel as **Connected**. Configure the public hostname:

1. In the tunnel configuration page, find the **Public Hostnames** section
2. Add a hostname:
   - **Subdomain**: `api`
   - **Domain**: `bigbrotr.com`
   - **Type**: `HTTP`
   - **URL**: `localhost:8080`
3. Save

> **Why HTTP and not HTTPS?** The traffic path is: User → HTTPS → Cloudflare → encrypted tunnel → cloudflared in VM → HTTP → localhost:8080. The last hop is entirely internal to the VM (localhost), so TLS is unnecessary. Cloudflare handles the SSL certificate for the public-facing side, and the tunnel itself is encrypted.

### 6.7 — Cloudflare Security Settings

In the main Cloudflare dashboard for **bigbrotr.com** (not Zero Trust):

**SSL/TLS** (left sidebar): Set encryption mode to **Full (strict)**

> **Note**: WAF managed rules and advanced rate limiting require paid Cloudflare plans. The free tier includes basic DDoS protection and the tunnel's zero-trust architecture already provides strong security (no open ports).

### 6.8 — Verify

DNS propagation from Namecheap to Cloudflare can take 15-30 minutes (up to 48 hours). Once propagated:

```bash
curl https://api.bigbrotr.com/health
# Expected: {"status":"ok"}
```

If DNS hasn't propagated yet, you can test directly through Cloudflare's nameservers:

```bash
curl -s --resolve api.bigbrotr.com:443:$(dig +short api.bigbrotr.com @samara.ns.cloudflare.com) https://api.bigbrotr.com/health
```

Cloudflare will send an email notification once the domain is fully active.

---

## Phase 7 — Security Hardening

### 7.1 — VM Firewall (UFW)

```bash
# Default policy: deny all inbound, allow all outbound
ufw default deny incoming
ufw default allow outgoing

# SSH (will be changed to custom port in step 7.3)
ufw allow 22/tcp comment 'SSH'

# PostgreSQL — ONLY from Proxmox internal subnet (for research access)
ufw allow from 192.168.1.0/24 to any port 5432 proto tcp comment 'PostgreSQL internal'

# Grafana — ONLY from internal subnet
ufw allow from 192.168.1.0/24 to any port 3000 proto tcp comment 'Grafana internal'

# Prometheus — ONLY from internal subnet
ufw allow from 192.168.1.0/24 to any port 9090 proto tcp comment 'Prometheus internal'

# Enable firewall
ufw enable
ufw status verbose
```

> **Note**: Cloudflare Tunnel does NOT require any inbound port rules. It uses outbound HTTPS connections only. The tunnel daemon creates outbound connections to Cloudflare's edge network.

### 7.2 — SSH Key Authentication

**On your local computer** (Mac/Linux/Windows terminal):

```bash
# Generate an Ed25519 key pair
ssh-keygen -t ed25519 -C "vincenzo@bigbrotr" -f ~/.ssh/bigbrotr

# Copy the public key to the VM
ssh-copy-id -i ~/.ssh/bigbrotr.pub root@<VM_IP>

# Test key-based login (should not ask for password)
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

# Restart SSH
systemctl restart sshd
```

> **CRITICAL**: Test the new SSH configuration from a **separate terminal window** before closing your current session:
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

Expected output should show the `sshd` jail active with 0 currently banned.

### 7.5 — Automatic Security Updates

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
# Select "Yes"
```

---

## Phase 8 — Database Backup Script

Create a manual backup script that dumps the database to the work disk (`/mnt/work/dumps/`). Run it whenever you want a snapshot of the database.

```bash
cat > /opt/bigbrotr-production/backup.sh << 'BACKUP'
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/mnt/work/dumps"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DUMP_FILE="${BACKUP_DIR}/bigbrotr_${TIMESTAMP}.sql.gz"

# Load credentials
source /opt/bigbrotr-production/.env

# Compressed dump via pg_dump inside the container
PGPASSWORD="${DB_ADMIN_PASSWORD}" docker exec bigbrotr-postgres \
  pg_dump -U admin -d bigbrotr \
    --no-owner --no-privileges \
    -Z 6 \
  > "${DUMP_FILE}"

# Retain only the 7 most recent dumps
ls -t "${BACKUP_DIR}"/bigbrotr_*.sql.gz | tail -n +8 | xargs -r rm

echo "[$(date)] Backup completed: ${DUMP_FILE} ($(du -h "${DUMP_FILE}" | cut -f1))"
BACKUP

chmod +x /opt/bigbrotr-production/backup.sh
```

**Usage**: Run `/opt/bigbrotr-production/backup.sh` whenever you want to create a database dump. Dumps are stored on the work disk (WD stripe) at `/mnt/work/dumps/`, compressed with gzip level 6. The script automatically keeps only the 7 most recent dumps.

To schedule automatic daily backups (optional), add a cron job:

```bash
echo '0 4 * * * root /opt/bigbrotr-production/backup.sh >> /var/log/bigbrotr-backup.log 2>&1' > /etc/cron.d/bigbrotr-backup
```

---

## Phase 9 — Accessing Monitoring

Grafana and Prometheus are exposed on the local network (configured in Phase 5.6) but **not** on the internet. Access them from any device on the same network:

- **Grafana**: `http://192.168.1.234:3000` (user: `admin`, password: `GRAFANA_PASSWORD` from `.env`)
- **Prometheus**: `http://192.168.1.234:9090`

UFW firewall rules (configured in Phase 7) ensure these ports are only accessible from the Proxmox internal subnet (`192.168.1.0/24`), not from the internet.

If you prefer stricter access (SSH tunnel only), revert the port bindings in `docker-compose.yaml` to `127.0.0.1:3000:3000` and `127.0.0.1:9090:9090`, then access via:

```bash
# From your local computer
ssh -i ~/.ssh/bigbrotr -p 2222 \
  -L 3000:localhost:3000 \
  -L 9090:localhost:9090 \
  root@192.168.1.234
```

---

## Phase 10 — Post-Deployment Checklist

Run these checks from the VM (`ssh -i ~/.ssh/bigbrotr -p 2222 root@192.168.1.234`):

```bash
# All containers healthy (14 expected)
cd /opt/bigbrotr-production
docker compose ps

# No errors in service logs
docker compose logs --tail=20 finder
docker compose logs --tail=20 monitor
docker compose logs --tail=20 synchronizer

# Candidates populated by seeder
docker compose exec postgres psql -U admin -d bigbrotr \
  -c "SELECT count(*) FROM service_state;"

# Relays validated (appears after validator processes candidates, ~10-30 minutes)
docker compose exec postgres psql -U admin -d bigbrotr \
  -c "SELECT count(*) AS relays FROM relay;"

# API reachable locally
curl -s http://localhost:8080/health

# API reachable via Cloudflare (from any internet-connected device)
curl https://api.bigbrotr.com/health

# Disk usage
df -h /mnt/pgdata /mnt/work

# ZFS pool health (from the Proxmox host, not the VM)
# ssh root@<PROXMOX_HOST_IP>
# zpool status
```

---

## Resource Allocation Summary

| Resource | Allocated | Total | Destination |
|----------|-----------|-------|-------------|
| vCPU | 12 | 32 threads | BigBrotr VM |
| RAM | 64 GiB | 96 GiB | BigBrotr VM (no ballooning) |
| NVMe (rpool) | 50 GiB | 928 GiB | VM OS + Docker images |
| Samsung RAID10 (datapool) | 7000 GiB | ~7.25 TiB | PostgreSQL data exclusively |
| WD stripe (workpool) | 7000 GiB | ~7.25 TiB | Dumps, exports, analysis |

---

## Quick Reference

### SSH Access

```bash
ssh -i ~/.ssh/bigbrotr -p 2222 root@192.168.1.234
```

### Service Management

```bash
cd /opt/bigbrotr-production

# View status
docker compose ps

# View logs
docker compose logs -f <service>        # e.g., finder, monitor, api

# Restart a service
docker compose restart <service>

# Restart everything
docker compose down && docker compose up -d

# Stop everything
docker compose down
```

### Updating BigBrotr

```bash
cd /opt/bigbrotr-production
docker compose pull
docker compose up -d
```

### Manual Database Backup

```bash
/opt/bigbrotr-production/backup.sh
# Dumps saved to /mnt/work/dumps/
```

### Accessing Services

| Service | URL | Access |
|---------|-----|--------|
| API (public) | `https://api.bigbrotr.com` | Internet (via Cloudflare Tunnel) |
| API (local) | `http://192.168.1.234:8080` | Local network |
| Grafana | `http://192.168.1.234:3000` | Local network (admin / GRAFANA_PASSWORD) |
| Prometheus | `http://192.168.1.234:9090` | Local network |
| PostgreSQL | `192.168.1.234:5432` | Local network (reader / DB_READER_PASSWORD) |

### Key File Locations

| Path | Purpose |
|------|---------|
| `/opt/bigbrotr-production/` | Production deployment (standalone) |
| `/opt/bigbrotr-production/.env` | Credentials (chmod 600) |
| `/opt/bigbrotr-production/docker-compose.yaml` | Service orchestration |
| `/opt/bigbrotr-production/postgres/postgresql.conf` | PostgreSQL tuning (64GB RAM) |
| `/opt/bigbrotr-production/backup.sh` | Database backup script |
| `/mnt/pgdata/` | PostgreSQL data (Samsung RAID10) |
| `/mnt/work/` | Dumps, exports, analysis (WD stripe) |
| `/mnt/work/dumps/` | Database backup files |
| `/mnt/work/exports/` | Data exports |
| `/mnt/work/analysis/` | Research analysis results |

---

## Appendix A — Connecting for Research

From a research VM or LXC container on the same Proxmox bridge network:

```bash
psql -h 192.168.1.234 -p 5432 -U reader -d bigbrotr
```

Use the `DB_READER_PASSWORD` from the `.env` file. The `reader` role has SELECT-only access to all tables and materialized views.

For long-running analytical queries, connect directly to PostgreSQL (port 5432), not through PGBouncer (port 6432). PGBouncer's transaction pooling mode does not support cursors, multi-statement transactions, or long-running queries.

---

## Appendix B — Expanding Storage

When the datapool (Samsung RAID10) fills up, add a new mirror pair without downtime:

```bash
# From the Proxmox host
zpool add datapool mirror /dev/disk/by-id/ata-NEW_DISK_1 /dev/disk/by-id/ata-NEW_DISK_2
```

The pool expands immediately. Then increase the VM disk size in Proxmox GUI (VM → Hardware → scsi1 → Resize) and extend the XFS filesystem inside the VM:

```bash
# Inside the VM
xfs_growfs /mnt/pgdata
```
