"""BigBrotr exception hierarchy.

Provides typed exceptions for all error categories, replacing bare
``except Exception`` with specific catches that distinguish transient
from fatal errors and allow ``CancelledError`` to propagate untouched.

Hierarchy::

    BigBrotrError (base — never raised directly)
    ├── ConfigurationError      — config validation, missing keys, bad YAML
    ├── DatabaseError            — pool/brotr/query failures
    │   ├── ConnectionPoolError  — transient: pool exhausted, network blip
    │   └── QueryError           — permanent: bad SQL, constraint violation
    ├── ConnectivityError        — relay unreachable, network failures
    │   ├── RelayTimeoutError    — connection or response timed out
    │   └── RelaySSLError        — certificate issues
    ├── ProtocolError            — NIP parsing/validation failures
    └── PublishingError          — Nostr event broadcast failures
"""

from __future__ import annotations


class BigBrotrError(Exception):
    """Base exception for all BigBrotr errors.

    Never raised directly — always use a specific subclass.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(BigBrotrError):
    """Invalid or missing configuration (YAML, env vars, CLI flags)."""


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class DatabaseError(BigBrotrError):
    """Base for all database-related errors."""


class ConnectionPoolError(DatabaseError):
    """Transient database error: pool exhausted, connection refused, network blip.

    Callers may retry after a backoff.
    """


class QueryError(DatabaseError):
    """Permanent database error: bad SQL, constraint violation, data integrity.

    Callers should NOT retry — the query itself is wrong.
    """


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


class ConnectivityError(BigBrotrError):
    """Base for all relay/network connectivity errors."""


class RelayTimeoutError(ConnectivityError):
    """Connection or response timed out."""


class RelaySSLError(ConnectivityError):
    """TLS/SSL certificate or handshake failure."""


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ProtocolError(BigBrotrError):
    """NIP parsing, validation, or compliance failure."""


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


class PublishingError(BigBrotrError):
    """Failed to broadcast a Nostr event to relays."""
