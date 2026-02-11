"""BigBrotr exception hierarchy.

Provides typed exceptions for all error categories, replacing bare
``except Exception`` with specific catches that distinguish transient
from fatal errors and allow ``CancelledError`` to propagate untouched.

Exception hierarchy:

```text
BigBrotrError (base -- never raised directly)
├── ConfigurationError      -- config validation, missing keys, bad YAML
├── DatabaseError            -- pool/brotr/query failures
│   ├── ConnectionPoolError  -- transient: pool exhausted, network blip
│   └── QueryError           -- permanent: bad SQL, constraint violation
├── ConnectivityError        -- relay unreachable, network failures
│   ├── RelayTimeoutError    -- connection or response timed out
│   └── RelaySSLError        -- certificate issues
├── ProtocolError            -- NIP parsing/validation failures
└── PublishingError          -- Nostr event broadcast failures
```

See Also:
    [Pool][bigbrotr.core.pool.Pool]: Raises
        [ConnectionPoolError][bigbrotr.core.exceptions.ConnectionPoolError]
        on transient connection failures.
    [Brotr][bigbrotr.core.brotr.Brotr]: Raises
        [QueryError][bigbrotr.core.exceptions.QueryError] on permanent
        database errors.
    [BaseService][bigbrotr.core.base_service.BaseService]: Catches all
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError] subclasses
        in the
        [run_forever()][bigbrotr.core.base_service.BaseService.run_forever]
        loop.
"""

from __future__ import annotations


class BigBrotrError(Exception):
    """Base exception for all BigBrotr errors.

    Never raised directly -- always use a specific subclass.

    See Also:
        [ConfigurationError][bigbrotr.core.exceptions.ConfigurationError]:
            Invalid or missing configuration.
        [DatabaseError][bigbrotr.core.exceptions.DatabaseError]: Database
            operation failures.
        [ConnectivityError][bigbrotr.core.exceptions.ConnectivityError]:
            Relay/network connectivity failures.
        [ProtocolError][bigbrotr.core.exceptions.ProtocolError]: NIP
            parsing/validation failures.
        [PublishingError][bigbrotr.core.exceptions.PublishingError]: Nostr
            event broadcast failures.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class ConfigurationError(BigBrotrError):
    """Invalid or missing configuration (YAML, env vars, CLI flags).

    See Also:
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError]: Parent
            exception class.
        [load_yaml()][bigbrotr.core.yaml.load_yaml]: YAML loading function
            that may trigger configuration errors.
    """


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------


class DatabaseError(BigBrotrError):
    """Base for all database-related errors.

    See Also:
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError]: Parent
            exception class.
        [ConnectionPoolError][bigbrotr.core.exceptions.ConnectionPoolError]:
            Transient connection-level failures (retryable).
        [QueryError][bigbrotr.core.exceptions.QueryError]: Permanent
            query-level failures (not retryable).
    """


class ConnectionPoolError(DatabaseError):
    """Transient database error: pool exhausted, connection refused, network blip.

    Callers may retry after a backoff.

    See Also:
        [DatabaseError][bigbrotr.core.exceptions.DatabaseError]: Parent
            exception class.
        [QueryError][bigbrotr.core.exceptions.QueryError]: Sibling for
            permanent query-level errors.
        [Pool][bigbrotr.core.pool.Pool]: Connection pool that raises
            this exception on transient failures.
    """


class QueryError(DatabaseError):
    """Permanent database error: bad SQL, constraint violation, data integrity.

    Callers should NOT retry -- the query itself is wrong.

    See Also:
        [DatabaseError][bigbrotr.core.exceptions.DatabaseError]: Parent
            exception class.
        [ConnectionPoolError][bigbrotr.core.exceptions.ConnectionPoolError]:
            Sibling for transient connection-level errors.
        [Brotr][bigbrotr.core.brotr.Brotr]: Database interface where query
            errors typically surface.
    """


# ---------------------------------------------------------------------------
# Connectivity
# ---------------------------------------------------------------------------


class ConnectivityError(BigBrotrError):
    """Base for all relay/network connectivity errors.

    See Also:
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError]: Parent
            exception class.
        [RelayTimeoutError][bigbrotr.core.exceptions.RelayTimeoutError]:
            Connection or response timed out.
        [RelaySSLError][bigbrotr.core.exceptions.RelaySSLError]: TLS/SSL
            certificate or handshake failure.
    """


class RelayTimeoutError(ConnectivityError):
    """Connection or response timed out.

    See Also:
        [ConnectivityError][bigbrotr.core.exceptions.ConnectivityError]:
            Parent exception class.
        [RelaySSLError][bigbrotr.core.exceptions.RelaySSLError]: Sibling
            for TLS/SSL failures.
    """


class RelaySSLError(ConnectivityError):
    """TLS/SSL certificate or handshake failure.

    See Also:
        [ConnectivityError][bigbrotr.core.exceptions.ConnectivityError]:
            Parent exception class.
        [RelayTimeoutError][bigbrotr.core.exceptions.RelayTimeoutError]:
            Sibling for timeout failures.
    """


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


class ProtocolError(BigBrotrError):
    """NIP parsing, validation, or compliance failure.

    See Also:
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError]: Parent
            exception class.
        [bigbrotr.nips][bigbrotr.nips]: NIP implementation modules where
            protocol errors typically originate.
    """


# ---------------------------------------------------------------------------
# Publishing
# ---------------------------------------------------------------------------


class PublishingError(BigBrotrError):
    """Failed to broadcast a Nostr event to relays.

    See Also:
        [BigBrotrError][bigbrotr.core.exceptions.BigBrotrError]: Parent
            exception class.
        [ConnectivityError][bigbrotr.core.exceptions.ConnectivityError]:
            Lower-level connectivity errors that may cause publishing
            failures.
    """
