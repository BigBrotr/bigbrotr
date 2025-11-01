"""Rate limiting for relay connections using token bucket algorithm.

This module provides rate limiting to prevent services from being blocked by relay operators
due to excessive requests. Uses the token bucket algorithm for smooth rate limiting with
bursting capability.

Key Features:
    - Token bucket algorithm: allows controlled bursting
    - Per-relay rate limiting: each relay has independent rate limit
    - Async-aware: uses asyncio for time-based operations
    - Configurable: burst size and refill rate are adjustable
    - Thread-safe: uses asyncio locks for concurrent access

Algorithm:
    - Each relay gets a bucket with a maximum number of tokens (burst size)
    - Tokens are refilled at a constant rate (requests per second)
    - Each request consumes one token
    - If no tokens available, request must wait for refill

Dependencies:
    - asyncio: For async sleep and time operations
    - typing: For type hints
"""
import asyncio
import time
from typing import Dict, Optional
from dataclasses import dataclass

__all__ = [
    'TokenBucket',
    'RelayRateLimiter',
    'get_default_rate_limiter',
    'rate_limited_operation'
]


@dataclass
class TokenBucket:
    """Token bucket for rate limiting.

    Attributes:
        capacity: Maximum number of tokens (burst size)
        tokens: Current number of tokens available
        refill_rate: Tokens added per second
        last_refill: Timestamp of last refill
        lock: Asyncio lock for thread-safe access
    """
    capacity: float
    tokens: float
    refill_rate: float  # tokens per second
    last_refill: float
    lock: asyncio.Lock

    def __init__(self, capacity: float, refill_rate: float):
        """Initialize token bucket.

        Args:
            capacity: Maximum tokens (burst size)
            refill_rate: Tokens to add per second
        """
        self.capacity = capacity
        self.tokens = capacity  # Start with full bucket
        self.refill_rate = refill_rate
        self.last_refill = time.time()
        self.lock = asyncio.Lock()

    async def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.time()
        elapsed = now - self.last_refill

        # Add tokens based on elapsed time
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

    async def acquire(self, tokens: float = 1.0) -> None:
        """Acquire tokens from bucket, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire (default: 1.0)
        """
        async with self.lock:
            while True:
                await self._refill()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return

                # Calculate wait time for next token
                tokens_needed = tokens - self.tokens
                wait_time = tokens_needed / self.refill_rate

                # Release lock during wait to allow other operations
                await asyncio.sleep(wait_time)

    async def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire (default: 1.0)

        Returns:
            True if tokens acquired, False if insufficient tokens
        """
        async with self.lock:
            await self._refill()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True

            return False


class RelayRateLimiter:
    """Rate limiter for relay connections.

    Manages per-relay rate limits using token bucket algorithm.
    Each relay gets independent rate limiting to prevent overwhelming
    relay operators with requests.
    """

    def __init__(
        self,
        requests_per_second: float = 1.0,
        burst_size: Optional[int] = None
    ):
        """Initialize rate limiter.

        Args:
            requests_per_second: Maximum requests per second per relay
            burst_size: Maximum burst size (default: 2x requests_per_second)
        """
        self.requests_per_second = requests_per_second
        self.burst_size = burst_size or int(requests_per_second * 2)
        self.buckets: Dict[str, TokenBucket] = {}
        self.lock = asyncio.Lock()

    async def _get_bucket(self, relay_url: str) -> TokenBucket:
        """Get or create token bucket for relay.

        Args:
            relay_url: Relay URL to get bucket for

        Returns:
            TokenBucket for the relay
        """
        if relay_url not in self.buckets:
            async with self.lock:
                # Double-check after acquiring lock
                if relay_url not in self.buckets:
                    self.buckets[relay_url] = TokenBucket(
                        capacity=self.burst_size,
                        refill_rate=self.requests_per_second
                    )

        return self.buckets[relay_url]

    async def acquire(self, relay_url: str, tokens: float = 1.0) -> None:
        """Acquire permission to make request to relay.

        Blocks until rate limit allows the request.

        Args:
            relay_url: URL of relay to rate limit
            tokens: Number of tokens to acquire (default: 1.0)
        """
        bucket = await self._get_bucket(relay_url)
        await bucket.acquire(tokens)

    async def try_acquire(self, relay_url: str, tokens: float = 1.0) -> bool:
        """Try to acquire permission without waiting.

        Args:
            relay_url: URL of relay to rate limit
            tokens: Number of tokens to acquire (default: 1.0)

        Returns:
            True if permission granted, False if rate limited
        """
        bucket = await self._get_bucket(relay_url)
        return await bucket.try_acquire(tokens)

    def clear_bucket(self, relay_url: str) -> None:
        """Clear rate limit bucket for relay.

        Useful for testing or after extended downtime.

        Args:
            relay_url: Relay URL to clear bucket for
        """
        if relay_url in self.buckets:
            del self.buckets[relay_url]

    def get_bucket_status(self, relay_url: str) -> Optional[Dict[str, float]]:
        """Get current status of rate limit bucket.

        Args:
            relay_url: Relay URL to check

        Returns:
            Dict with tokens, capacity, refill_rate or None if no bucket
        """
        if relay_url not in self.buckets:
            return None

        bucket = self.buckets[relay_url]
        return {
            'tokens': bucket.tokens,
            'capacity': bucket.capacity,
            'refill_rate': bucket.refill_rate,
            'utilization': 1.0 - (bucket.tokens / bucket.capacity)
        }


# Global rate limiter instances (can be configured per service)
_default_rate_limiter: Optional[RelayRateLimiter] = None


def get_default_rate_limiter(
    requests_per_second: float = 1.0,
    burst_size: Optional[int] = None
) -> RelayRateLimiter:
    """Get or create default rate limiter instance.

    Args:
        requests_per_second: Maximum requests per second per relay
        burst_size: Maximum burst size

    Returns:
        Global RelayRateLimiter instance
    """
    global _default_rate_limiter

    if _default_rate_limiter is None:
        _default_rate_limiter = RelayRateLimiter(
            requests_per_second=requests_per_second,
            burst_size=burst_size
        )

    return _default_rate_limiter


async def rate_limited_operation(
    relay_url: str,
    operation,
    *args,
    rate_limiter: Optional[RelayRateLimiter] = None,
    **kwargs
):
    """Execute operation with rate limiting.

    Decorator-style function to wrap any relay operation with rate limiting.

    Args:
        relay_url: URL of relay being accessed
        operation: Async function to execute
        *args: Positional arguments for operation
        rate_limiter: Rate limiter to use (default: global instance)
        **kwargs: Keyword arguments for operation

    Returns:
        Result of operation

    Example:
        result = await rate_limited_operation(
            relay.url,
            client.fetch_events,
            event_filter,
            rate_limiter=limiter
        )
    """
    if rate_limiter is None:
        rate_limiter = get_default_rate_limiter()

    # Acquire rate limit token before operation
    await rate_limiter.acquire(relay_url)

    # Execute operation
    return await operation(*args, **kwargs)
