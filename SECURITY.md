# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 2.0.x   | :white_check_mark: |
| 1.0.x   | :x:                |

Only the latest major version receives security updates.

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

### How to Report

1. **Email**: Send details to the project maintainers (check repository for contact info)
2. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

### What to Expect

- **Acknowledgment**: Within 48 hours
- **Initial Assessment**: Within 7 days
- **Resolution Timeline**: Depends on severity

### After Reporting

- We will investigate and validate the report
- We will work on a fix and coordinate disclosure
- You will be credited (unless you prefer anonymity)

---

## Security Best Practices

When deploying BigBrotr, follow these recommendations:

### Database Security

```bash
# Use strong passwords
openssl rand -base64 32

# Restrict network access (pg_hba.conf)
# Only allow connections from application hosts

# Enable SSL for database connections
ssl = on
ssl_cert_file = '/path/to/server.crt'
ssl_key_file = '/path/to/server.key'
```

### Environment Variables

```bash
# Protect .env files
chmod 600 .env

# Never commit .env files
# Use secrets management in production:
# - Docker secrets
# - HashiCorp Vault
# - AWS Secrets Manager
```

### Network Security

```bash
# Firewall: Only expose necessary ports
# PostgreSQL: Internal only (no public access)
# PGBouncer: Internal only
# Tor: Internal only

# Use internal Docker networks
networks:
  internal:
    internal: true
```

### Container Security

- Use non-root users in containers
- Keep base images updated
- Scan images for vulnerabilities
- Use read-only file systems where possible

---

## Known Security Considerations

### Data Storage

BigBrotr archives public Nostr events. Be aware that:

- All stored data was publicly available on relays
- Event content may include sensitive information
- Consider data retention policies

### Tor Integration

When using Tor for .onion relays:

- Traffic is routed through Tor network
- Ensure Tor proxy is properly configured
- Monitor for unusual traffic patterns

### Database Access

- Use PGBouncer for connection pooling
- Implement connection limits
- Monitor for SQL injection (stored procedures help mitigate)

---

## Security Updates

Security updates are released as patch versions (e.g., 2.0.1).

To stay informed:
- Watch the repository for releases
- Check CHANGELOG.md for security fixes
- Subscribe to GitHub security advisories

---

## Acknowledgments

We thank the security researchers who help keep BigBrotr secure.
