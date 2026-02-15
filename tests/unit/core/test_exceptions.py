"""Unit tests for the BigBrotr exception hierarchy.

Tests verify:
- issubclass relationships match the documented tree
- except clauses catch the expected subclasses
- all exceptions accept a message string
"""

import pytest

from bigbrotr.core.exceptions import (
    BigBrotrError,
    ConfigurationError,
    ConnectionPoolError,
    ConnectivityError,
    DatabaseError,
    ProtocolError,
    PublishingError,
    QueryError,
    RelaySSLError,
    RelayTimeoutError,
)


ALL_CONCRETE = (
    ConfigurationError,
    ConnectionPoolError,
    QueryError,
    RelayTimeoutError,
    RelaySSLError,
    ProtocolError,
    PublishingError,
)

ALL_CLASSES = (BigBrotrError, DatabaseError, ConnectivityError, *ALL_CONCRETE)


# =============================================================================
# Hierarchy Tests
# =============================================================================


class TestExceptionHierarchy:
    """Verify issubclass relationships match the documented tree."""

    @pytest.mark.parametrize("exc_cls", ALL_CONCRETE)
    def test_all_concrete_inherit_from_bigbrotr_error(self, exc_cls: type) -> None:
        assert issubclass(exc_cls, BigBrotrError)

    def test_connection_pool_error_is_database_error(self) -> None:
        assert issubclass(ConnectionPoolError, DatabaseError)

    def test_query_error_is_database_error(self) -> None:
        assert issubclass(QueryError, DatabaseError)

    def test_relay_timeout_error_is_connectivity_error(self) -> None:
        assert issubclass(RelayTimeoutError, ConnectivityError)

    def test_relay_ssl_error_is_connectivity_error(self) -> None:
        assert issubclass(RelaySSLError, ConnectivityError)

    def test_database_error_is_bigbrotr_error(self) -> None:
        assert issubclass(DatabaseError, BigBrotrError)

    def test_connectivity_error_is_bigbrotr_error(self) -> None:
        assert issubclass(ConnectivityError, BigBrotrError)


class TestExceptionSiblingIndependence:
    """Verify sibling branches are NOT related."""

    def test_database_not_connectivity(self) -> None:
        assert not issubclass(DatabaseError, ConnectivityError)
        assert not issubclass(ConnectivityError, DatabaseError)

    def test_pool_not_query(self) -> None:
        assert not issubclass(ConnectionPoolError, QueryError)
        assert not issubclass(QueryError, ConnectionPoolError)

    def test_timeout_not_ssl(self) -> None:
        assert not issubclass(RelayTimeoutError, RelaySSLError)
        assert not issubclass(RelaySSLError, RelayTimeoutError)

    def test_protocol_not_database(self) -> None:
        assert not issubclass(ProtocolError, DatabaseError)

    def test_publishing_not_connectivity(self) -> None:
        assert not issubclass(PublishingError, ConnectivityError)


# =============================================================================
# Catching Tests
# =============================================================================


class TestExceptionCatching:
    """Verify except clauses catch the expected subclasses."""

    @pytest.mark.parametrize("exc_cls", ALL_CONCRETE)
    def test_bigbrotr_error_catches_all_concrete(self, exc_cls: type) -> None:
        with pytest.raises(BigBrotrError):
            raise exc_cls("test")

    @pytest.mark.parametrize("exc_cls", [ConnectionPoolError, QueryError])
    def test_database_error_catches_subtypes(self, exc_cls: type) -> None:
        with pytest.raises(DatabaseError):
            raise exc_cls("test")

    @pytest.mark.parametrize("exc_cls", [RelayTimeoutError, RelaySSLError])
    def test_connectivity_error_catches_subtypes(self, exc_cls: type) -> None:
        with pytest.raises(ConnectivityError):
            raise exc_cls("test")

    def test_database_error_does_not_catch_connectivity(self) -> None:
        with pytest.raises(ConnectivityError):
            raise RelayTimeoutError("test")
        # Verify it does NOT match DatabaseError
        with pytest.raises(RelayTimeoutError):
            try:
                raise RelayTimeoutError("test")
            except DatabaseError:
                pytest.fail("DatabaseError should not catch RelayTimeoutError")


# =============================================================================
# Instantiation Tests
# =============================================================================


class TestExceptionInstantiation:
    """Verify all exceptions can be instantiated with a message."""

    @pytest.mark.parametrize("exc_cls", ALL_CLASSES)
    def test_accepts_message(self, exc_cls: type) -> None:
        exc = exc_cls("something went wrong")
        assert str(exc) == "something went wrong"
        assert isinstance(exc, Exception)

    @pytest.mark.parametrize("exc_cls", ALL_CLASSES)
    def test_accepts_empty_message(self, exc_cls: type) -> None:
        exc = exc_cls()
        assert isinstance(exc, BigBrotrError)
