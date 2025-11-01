"""Database error handling utilities for network partition resilience.

This module provides utilities for handling database connection failures and network partitions
in a graceful manner with automatic retry logic.

Key Features:
    - Detects transient vs. permanent database errors
    - Implements exponential backoff for retries
    - Provides decorators for automatic retry logic
    - Logs error details for debugging

Network Partition Scenarios:
    - Database becomes unavailable after initial connection
    - Connection pool exhaustion
    - Network timeouts during operations
    - Connection termination mid-operation

Dependencies:
    - asyncpg: PostgreSQL async driver (for exception types)
    - asyncio: For async retry logic
"""
import asyncio
import logging
from functools import wraps
from typing import Callable, Any, TypeVar, Optional, cast

try:
    import asyncpg
    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    # Create placeholder exception classes for type checking
    class PostgresConnectionError(Exception):  # type: ignore
        pass
    class TooManyConnectionsError(Exception):  # type: ignore
        pass
    class QueryCanceledError(Exception):  # type: ignore
        pass

from constants import DEFAULT_DB_OPERATION_RETRIES, DEFAULT_DB_OPERATION_RETRY_DELAY

# Type variable for generic function return type
T = TypeVar('T')


def is_transient_db_error(error: Exception) -> bool:
    """Check if database error is transient and retryable.

    Args:
        error: Exception raised during database operation

    Returns:
        True if error is transient and operation should be retried
    """
    if not ASYNCPG_AVAILABLE:
        return False

    # Connection errors (network partition, database restart)
    if isinstance(error, (
        asyncpg.PostgresConnectionError,
        asyncpg.ConnectionDoesNotExistError,
        asyncpg.ConnectionFailureError,
        asyncpg.InterfaceError,
    )):
        return True

    # Connection pool exhaustion (temporary)
    if isinstance(error, asyncpg.TooManyConnectionsError):
        return True

    # Query timeouts (might succeed on retry)
    if isinstance(error, asyncpg.QueryCanceledError):
        return True

    # OSError and ConnectionError subclasses (network issues)
    if isinstance(error, (OSError, ConnectionError, TimeoutError)):
        return True

    return False


def is_permanent_db_error(error: Exception) -> bool:
    """Check if database error is permanent and not retryable.

    Args:
        error: Exception raised during database operation

    Returns:
        True if error is permanent and operation should not be retried
    """
    if not ASYNCPG_AVAILABLE:
        return True

    # Syntax errors (will never succeed)
    if isinstance(error, asyncpg.PostgresSyntaxError):
        return True

    # Data integrity errors (bad data, not network issue)
    if isinstance(error, (
        asyncpg.IntegrityConstraintViolationError,
        asyncpg.DataError,
        asyncpg.InvalidTextRepresentationError,
    )):
        return True

    # Authentication/authorization errors
    if isinstance(error, (
        asyncpg.InvalidPasswordError,
        asyncpg.InvalidAuthorizationSpecificationError,
    )):
        return True

    return False


async def retry_on_db_error(
    func: Callable[..., Any],
    *args: Any,
    max_retries: int = DEFAULT_DB_OPERATION_RETRIES,
    retry_delay: int = DEFAULT_DB_OPERATION_RETRY_DELAY,
    operation_name: str = "database operation",
    **kwargs: Any
) -> Any:
    """Execute database operation with automatic retry on transient errors.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        max_retries: Maximum number of retry attempts
        retry_delay: Base delay between retries (uses exponential backoff)
        operation_name: Name of operation for logging
        **kwargs: Keyword arguments for func

    Returns:
        Result of func(*args, **kwargs)

    Raises:
        Exception: If all retries fail or permanent error encountered
    """
    last_error: Exception = Exception("No error")

    for attempt in range(max_retries + 1):
        try:
            result = await func(*args, **kwargs)
            if attempt > 0:
                logging.info(
                    f"✅ {operation_name} succeeded after {attempt} retries"
                )
            return result

        except Exception as e:
            last_error = e

            # Check if error is permanent (don't retry)
            if is_permanent_db_error(e):
                logging.error(
                    f"❌ {operation_name} failed with permanent error: {e}",
                    extra={"operation": operation_name, "error_type": type(e).__name__}
                )
                raise

            # Check if error is transient (retry)
            if is_transient_db_error(e):
                if attempt < max_retries:
                    # Exponential backoff: delay * 2^attempt
                    backoff_delay = retry_delay * (2 ** attempt)
                    logging.warning(
                        f"⚠️ {operation_name} failed with transient error: {e}. "
                        f"Retrying in {backoff_delay}s (attempt {attempt + 1}/{max_retries})...",
                        extra={"operation": operation_name, "error_type": type(e).__name__}
                    )
                    await asyncio.sleep(backoff_delay)
                    continue
                else:
                    logging.error(
                        f"❌ {operation_name} failed after {max_retries} retries: {e}",
                        extra={"operation": operation_name, "error_type": type(e).__name__}
                    )
                    raise
            else:
                # Unknown error type - don't retry
                logging.error(
                    f"❌ {operation_name} failed with unknown error: {e}",
                    extra={"operation": operation_name, "error_type": type(e).__name__}
                )
                raise

    # Should never reach here, but raise last error if we do
    raise last_error


def with_db_retry(
    max_retries: int = DEFAULT_DB_OPERATION_RETRIES,
    retry_delay: int = DEFAULT_DB_OPERATION_RETRY_DELAY,
    operation_name: Optional[str] = None
):
    """Decorator to add automatic retry logic to async database operations.

    Args:
        max_retries: Maximum number of retry attempts
        retry_delay: Base delay between retries (uses exponential backoff)
        operation_name: Name of operation for logging (defaults to function name)

    Example:
        @with_db_retry(max_retries=3, retry_delay=5, operation_name="insert_events")
        async def insert_events_batch(bigbrotr, events):
            await brotr.insert_event_batch(events)
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            op_name = operation_name or func.__name__
            return await retry_on_db_error(
                func,
                *args,
                max_retries=max_retries,
                retry_delay=retry_delay,
                operation_name=op_name,
                **kwargs
            )
        return wrapper
    return decorator


async def check_db_connection(brotr: Any, logging_module: Any = None) -> bool:
    """Check if database connection is healthy.

    Args:
        brotr: Brotr instance to check
        logging_module: Logging module for output (optional)

    Returns:
        True if connection is healthy, False otherwise
    """
    try:
        # Simple query to check connection
        await brotr.fetch("SELECT 1")
        return True
    except Exception as e:
        if logging_module:
            logging_module.warning(
                f"⚠️ Database connection check failed: {e}",
                extra={"operation": "connection_check", "error_type": type(e).__name__}
            )
        return False
