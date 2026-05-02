"""Root fixture entrypoint for the integration harness."""

from tests.integration.harness.fixtures import pg_container, pg_dsn


__all__ = ["pg_container", "pg_dsn"]
