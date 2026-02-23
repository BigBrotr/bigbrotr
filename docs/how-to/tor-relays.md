# Connecting to Tor and Overlay Network Relays

Configure BigBrotr to discover and monitor relays on Tor (.onion), I2P (.i2p), and Lokinet (.loki) overlay networks.

---

## Overview

BigBrotr supports four network types. Clearnet is enabled by default. Overlay networks require a SOCKS5 proxy and are disabled by default.

| Network | Relay suffix | Default proxy | Default port |
|---------|-------------|---------------|-------------|
| Clearnet | `.com`, `.io`, etc. | None (direct) | -- |
| Tor | `.onion` | `socks5://tor:9050` | 9050 |
| I2P | `.i2p` | `socks5://i2p:4447` | 4447 |
| Lokinet | `.loki` | `socks5://lokinet:1080` | 1080 |

## Tor Setup

### Option A: Docker (recommended)

The default Docker Compose stack includes a Tor container. No additional setup is required -- just enable Tor in your service configs.

### Option B: System Tor

1. Install Tor:

    ```bash
    sudo apt install tor
    sudo systemctl start tor && sudo systemctl enable tor
    ```

2. Verify the SOCKS5 proxy is listening:

    ```bash
    ss -tlnp | grep 9050
    ```

3. Update `proxy_url` in your service configs to point to `localhost` instead of the Docker service name:

    ```yaml
    networks:
      tor:
        enabled: true
        proxy_url: "socks5://127.0.0.1:9050"
    ```

## Enable Tor in Service Configs

Edit each service config that connects to relays (`validator.yaml`, `monitor.yaml`, `synchronizer.yaml`):

```yaml
networks:
  clearnet:
    enabled: true
    max_tasks: 50
    timeout: 10.0
  tor:
    enabled: true
    proxy_url: "socks5://tor:9050"
    max_tasks: 10
    timeout: 30.0
```

!!! note "Per-network concurrency"
    Tor connections are slower than clearnet. The defaults use lower `max_tasks` (10 vs 50) and higher `timeout` (30s vs 10s) to account for Tor circuit latency.

### Concurrency Guidelines

| Network | Recommended `max_tasks` | Recommended `timeout` |
|---------|------------------------|----------------------|
| Clearnet | 50 | 10s |
| Tor | 5--15 | 30--60s |
| I2P | 3--10 | 45--60s |
| Lokinet | 3--10 | 30--45s |

!!! tip
    Start with low concurrency and increase gradually. Too many concurrent Tor connections can overwhelm your local Tor process and cause timeouts.

## Test Tor Connectivity

### From Docker

```bash
# Check the Tor container is healthy
docker compose ps tor

# Test SOCKS5 connectivity from a service container
docker compose exec finder python -c "
import socket
s = socket.create_connection(('tor', 9050), timeout=5)
print('Tor proxy reachable')
s.close()
"
```

### From the host

```bash
# Test with curl through Tor SOCKS5
curl --socks5-hostname 127.0.0.1:9050 https://check.torproject.org/api/ip
```

### Run a single validation cycle with debug logging

```bash
python -m bigbrotr validator --once --log-level DEBUG
```

Look for log lines containing `network=tor` to confirm Tor relays are being processed.

## I2P Setup

1. Install and start an I2P router (e.g., [i2pd](https://i2pd.readthedocs.io/)):

    ```bash
    sudo apt install i2pd
    sudo systemctl start i2pd && sudo systemctl enable i2pd
    ```

2. Enable I2P in service configs:

    ```yaml
    networks:
      i2p:
        enabled: true
        proxy_url: "socks5://127.0.0.1:4447"
        max_tasks: 5
        timeout: 45.0
    ```

!!! warning
    I2P connections are significantly slower than Tor. Allow at least 45 seconds for timeouts and keep concurrency low.

## Lokinet Setup

1. Install Lokinet (Linux only, see [lokinet.org](https://lokinet.org)):

    ```bash
    sudo apt install lokinet
    sudo systemctl start lokinet && sudo systemctl enable lokinet
    ```

2. Enable Lokinet in service configs:

    ```yaml
    networks:
      loki:
        enabled: true
        proxy_url: "socks5://127.0.0.1:1080"
        max_tasks: 5
        timeout: 30.0
    ```

## Security Considerations

!!! danger "Proxy isolation"
    Each overlay network should use its own dedicated proxy. Do not route Tor traffic through an I2P proxy or vice versa.

- **DNS leaks**: BigBrotr routes DNS resolution through the SOCKS5 proxy for overlay networks. No clearnet DNS queries are made for `.onion`, `.i2p`, or `.loki` addresses.
- **Mixed deployments**: Clearnet and overlay services run in the same process. The network type is determined by the relay URL suffix, and the correct proxy is selected automatically.
- **Docker networking**: In Docker, the Tor container is on the `data-network` only. It is not exposed on the monitoring network or to the host.

---

## Related Documentation

- [Docker Compose Deployment](docker-deploy.md) -- the default stack includes a Tor container
- [Monitoring Setup](monitoring-setup.md) -- monitor overlay network health checks
- [Troubleshooting](troubleshooting.md) -- diagnose Tor connection issues
