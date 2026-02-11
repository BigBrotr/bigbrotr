# Monitoring Setup

Configure Prometheus metrics collection, Grafana dashboards, and alerting for BigBrotr services.

---

## Overview

Every BigBrotr service exposes a `/metrics` endpoint in Prometheus exposition format. The Docker Compose stack includes Prometheus and Grafana pre-configured, but you can also connect to an external monitoring stack.

### Metrics Exposed

| Metric | Type | Description |
|--------|------|-------------|
| `service_info` | Info | Static service metadata (name, version) |
| `service_gauge` | Gauge | Point-in-time state (consecutive_failures, last_cycle_timestamp, progress) |
| `service_counter` | Counter | Cumulative totals (cycles_success, cycles_failed, errors by type) |
| `cycle_duration_seconds` | Histogram | Cycle latency with 10 buckets (1s to 1h) |

## 1. Start the Monitoring Stack

### Using Docker Compose (included)

The default `docker-compose.yaml` starts Prometheus and Grafana automatically:

```bash
cd deployments/bigbrotr
docker compose up -d prometheus grafana
```

Endpoints:

| Service | URL |
|---------|-----|
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3000` |

!!! note
    The default Grafana credentials are `admin` / `<GRAFANA_PASSWORD from .env>`.

### Using an external Prometheus

If you already run Prometheus, add scrape targets for each service:

```yaml
scrape_configs:
  - job_name: bigbrotr-finder
    static_configs:
      - targets: ["finder:8001"]
  - job_name: bigbrotr-validator
    static_configs:
      - targets: ["validator:8002"]
  - job_name: bigbrotr-monitor
    static_configs:
      - targets: ["monitor:8003"]
  - job_name: bigbrotr-synchronizer
    static_configs:
      - targets: ["synchronizer:8004"]
```

## 2. Enable Service Metrics

Each service must have metrics enabled in its YAML config. Set `metrics.enabled: true` and assign a unique port:

```yaml
# config/services/finder.yaml
metrics:
  enabled: true
  port: 8001
  host: "0.0.0.0"
  path: "/metrics"
```

Default metric ports by service:

| Service | Port |
|---------|------|
| Finder | 8001 |
| Validator | 8002 |
| Monitor | 8003 |
| Synchronizer | 8004 |

## 3. Configure Prometheus Targets

The included Prometheus configuration is at `monitoring/prometheus/prometheus.yml`. It scrapes all service endpoints every 30 seconds with 30-day data retention.

To verify targets are being scraped:

1. Open `http://localhost:9090/targets`
2. All endpoints should show state **UP**
3. If a target shows **DOWN**, check that the service is running and the port is correct

## 4. Import Grafana Dashboards

The BigBrotr deployment auto-provisions Grafana with:

- A Prometheus datasource pointing to `http://prometheus:9090`
- A dashboard directory at `monitoring/grafana/dashboards/`

To add a custom dashboard:

1. Open Grafana at `http://localhost:3000`
2. Navigate to **Dashboards** > **New** > **Import**
3. Paste the JSON or upload a file
4. Select the **Prometheus** datasource

!!! tip
    The auto-provisioned dashboard includes per-service panels for cycle time, cycle duration, error counts (24h), and consecutive failures. The Validator has additional candidate progress panels.

## 5. Set Up Alerting Rules

BigBrotr includes four alerting rules in `monitoring/prometheus/rules/alerts.yml`:

| Alert | Expression | Duration | Severity |
|-------|-----------|----------|----------|
| **ServiceDown** | `up == 0` | 5 minutes | critical |
| **HighFailureRate** | `rate(bigbrotr_errors_total[5m]) > 0.1` | 5 minutes | warning |
| **PoolExhausted** | `bigbrotr_pool_available_connections == 0` | 2 minutes | critical |
| **DatabaseSlow** | `histogram_quantile(0.99, rate(bigbrotr_query_duration_seconds_bucket[5m])) > 5` | 5 minutes | warning |

### Verify alerts are loaded

1. Open `http://localhost:9090/alerts`
2. All four rules should appear under the `bigbrotr` group
3. Rules in **inactive** state means no alerts are currently firing

### Configure alert notifications

To receive alerts via email, Slack, or PagerDuty, configure an Alertmanager and add it to your Prometheus config:

```yaml
# prometheus.yml
alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]
```

!!! warning
    The default Docker Compose stack does not include Alertmanager. You need to add it as a separate service or use Grafana alerting as an alternative.

## 6. Create Custom Dashboards

Useful PromQL queries for custom panels:

```promql
# Successful cycles per hour (by service)
increase(bigbrotr_service_counter{counter="cycles_success"}[1h])

# Average cycle duration (last 5 minutes)
rate(bigbrotr_cycle_duration_seconds_sum[5m])
  / rate(bigbrotr_cycle_duration_seconds_count[5m])

# Current consecutive failures
bigbrotr_service_gauge{gauge="consecutive_failures"}

# Error rate by type
rate(bigbrotr_service_counter{counter=~"errors_.*"}[5m])
```

!!! tip
    Use Grafana variables to create a single dashboard with a service selector dropdown. Set a `$service` variable from the `job` label values.

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- the monitoring stack is included
- [Manual Deployment](manual-deploy.md) -- add monitoring to a non-Docker deployment
- [Troubleshooting](troubleshooting.md) -- diagnose metrics and alerting issues
