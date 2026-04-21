# System Test And Observability Deployment Inventory

## Purpose

This file freezes the live deployment and monitoring inventory that the broader
system-test and observability certification program must certify.

It is not a wish list.
It is the current concrete deployment surface that exists in the repository
today.

This inventory is derived from:

- [deployments/bigbrotr/docker-compose.yaml](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/deployments/bigbrotr/docker-compose.yaml)
- [deployments/lilbrotr/docker-compose.yaml](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/deployments/lilbrotr/docker-compose.yaml)
- [deployments/bigbrotr/README.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/deployments/bigbrotr/README.md)
- [deployments/lilbrotr/README.md](/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/deployments/lilbrotr/README.md)
- the tracked monitoring trees under `deployments/{bigbrotr,lilbrotr}/monitoring/`

---

## Frozen Context

- Frozen date:
  `2026-04-21`
- Frozen branch:
  `refactor/definitive-redesign-execution`
- Baseline commit entering this slice:
  `228e3670`
- Profiles in scope:
  `bigbrotr`, `lilbrotr`

---

## Compose Topology

Both built-in deployments currently ship the same container topology:

### Shared infrastructure containers

- `postgres`
- `pgbouncer`
- `tor`

### Product service containers

- `seeder`
- `finder`
- `validator`
- `monitor`
- `synchronizer`
- `refresher`
- `ranker`
- `api`
- `dvm`
- `assertor`

### Monitoring containers

- `postgres-exporter`
- `prometheus`
- `alertmanager`
- `grafana`

That gives each built-in deployment:

- `17` compose services total;
- `10` product service containers;
- `3` shared data/network infrastructure containers;
- `4` monitoring/observability containers.

### Named volumes and networks

Each profile also defines:

- `3` named volumes:
  `prometheus-data`, `alertmanager-data`, `grafana-data`
- `2` named networks:
  `<profile>-data-network`, `<profile>-monitoring-network`

The two built-in compose files are therefore structurally isomorphic at the top
level.

---

## Host Port Inventory

## `bigbrotr`

| Surface | Host Port(s) | Notes |
|---------|--------------|-------|
| PostgreSQL | `5432` | Full-archive reference profile DB |
| PgBouncer | `6432` | Shared DB pooler |
| Tor SOCKS5 | `9050` | Overlay/proxy support |
| Service metrics | `8001` through `8009` | Finder, Validator, Monitor, Synchronizer, Refresher, API, DVM, Assertor, Ranker |
| Prometheus | `9090` | Monitoring UI/API |
| Alertmanager | `9093` | Alert routing API/UI |
| Grafana | `3000` | Dashboard UI/API |

## `lilbrotr`

| Surface | Host Port(s) | Notes |
|---------|--------------|-------|
| PostgreSQL | `5433` | Lightweight-archive reference profile DB |
| PgBouncer | `6433` | Shared DB pooler |
| Tor SOCKS5 | `9051` | Overlay/proxy support |
| Service metrics | `9001` through `9009` | Finder, Validator, Monitor, Synchronizer, Refresher, API, DVM, Assertor, Ranker |
| Prometheus | `9091` | Monitoring UI/API |
| Alertmanager | `9094` | Alert routing API/UI |
| Grafana | `3001` | Dashboard UI/API |

## Important live-port observations

- `bigbrotr` and `lilbrotr` intentionally separate their host-facing DB,
  service-metrics, and monitoring ports.
- `postgres-exporter` exposes metrics only inside the compose networks; it is
  health-checked on container-local `9187`, but is not mapped to a host port in
  either built-in deployment.
- `seeder` remains a one-shot service and does not participate in the
  continuous `/metrics` port range.

---

## Metrics And Monitoring Surface Inventory

Each built-in profile currently ships the same monitoring subtree shape:

```text
monitoring/
  README.md
  alertmanager/
    README.md
    alertmanager.yml
  grafana/
    README.md
    provisioning/
      README.md
      dashboards/
        README.md
        dashboards.yaml
        <service dashboards>.json
        <profile root dashboard>.json
      datasources/
        README.md
        prometheus.yaml
  postgres-exporter/
    README.md
    queries.yaml
  prometheus/
    README.md
    prometheus.yaml
    rules/
      README.md
      alerts.yml
```

### File counts

| Profile | Monitoring file count | Notes |
|---------|-----------------------|-------|
| `bigbrotr` | `25` | Includes one profile root dashboard: `bigbrotr.json` |
| `lilbrotr` | `25` | Includes one profile root dashboard: `lilbrotr.json` |

### Shared dashboard set

Both profiles currently ship dashboards for:

- `api`
- `assertor`
- `dvm`
- `finder`
- `monitor`
- `ranker`
- `refresher`
- `synchronizer`
- `validator`

### Profile-specific root dashboard

The only profile-root dashboard filename difference in the tracked tree is:

- `deployments/bigbrotr/monitoring/grafana/provisioning/dashboards/bigbrotr.json`
- `deployments/lilbrotr/monitoring/grafana/provisioning/dashboards/lilbrotr.json`

### Datasource shape

Both profiles currently provision a single default Prometheus datasource via:

- `monitoring/grafana/provisioning/datasources/prometheus.yaml`

### Prometheus rule shape

Both profiles currently ship one tracked alert rules file via:

- `monitoring/prometheus/rules/alerts.yml`

### Exporter shape

Both profiles currently ship one tracked postgres-exporter query definition via:

- `monitoring/postgres-exporter/queries.yaml`

---

## Current Runtime Contract Observations

### 1. The monitoring stack is part of the shipped deployment contract

Prometheus, Alertmanager, Grafana, and postgres-exporter are not external
operator suggestions in the built-in deployments.

They are compose-managed runtime surfaces already present in the repository’s
reference deployments.

### 2. The profiles are topology-equal but not port-equal

`bigbrotr` and `lilbrotr` currently preserve:

- the same compose service set;
- the same monitoring subtree shape;
- and the same high-level observability architecture;

while intentionally differing in:

- DB ports;
- PgBouncer ports;
- Tor ports;
- service metrics host-port ranges;
- monitoring UI/API host ports;
- and the profile-root Grafana dashboard filename.

### 3. The certification program must treat profile parity carefully

Because the profiles are structurally similar, the higher-band tests should
look for:

- accidental drift where parity was intended;
- and accidental coupling where divergence was intended.

### 4. The current deployment inventory does not yet imply certified behavior

This inventory proves only that the repository ships these deployment surfaces.

It does **not** prove yet that:

- the compose stack starts cleanly under test control;
- the monitoring stack is functionally correct;
- the dashboards query valid live metrics;
- the alert rules still match the emitted metric surface;
- or the profile differences are all intentional and well-tested.

Those are later work packages.
