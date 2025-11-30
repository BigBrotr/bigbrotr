"""
Monitor Service for BigBrotr.

Monitors relay health and metadata:
- Check relay connectivity (NIP-11 info document)
- Validate relay capabilities (NIP-66 monitoring)
- Track relay uptime and response times
- Update relay_metadata table with current status

Usage:
    from core import Brotr
    from services import Monitor

    brotr = Brotr.from_yaml("yaml/core/brotr.yaml")
    monitor = Monitor.from_yaml("yaml/services/monitor.yaml", brotr=brotr)

    async with brotr.pool:
        async with monitor:
            await monitor.run_forever(interval=3600)
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, Optional

from nostr_tools import Client, Relay, RelayValidationError, fetch_relay_metadata, validate_keypair
from pydantic import BaseModel, Field, field_validator, model_validator

from core.base_service import BaseService
from core.brotr import Brotr


SERVICE_NAME = "monitor"


# =============================================================================
# Configuration
# =============================================================================


class TorConfig(BaseModel):
    """Tor proxy configuration."""

    enabled: bool = Field(default=True, description="Enable Tor proxy for .onion relays")
    host: str = Field(default="127.0.0.1", description="Tor proxy host")
    port: int = Field(default=9050, ge=1, le=65535, description="Tor proxy port")


def _get_private_key_from_env() -> Optional[str]:
    """Load private key from MONITOR_PRIVATE_KEY environment variable."""
    return os.getenv("MONITOR_PRIVATE_KEY")


class KeysConfig(BaseModel):
    """Nostr keys for NIP-66 testing."""

    public_key: Optional[str] = Field(
        default=None,
        description="Public key (hex) for write tests"
    )
    private_key: Optional[str] = Field(
        default_factory=_get_private_key_from_env,
        description="Private key (from MONITOR_PRIVATE_KEY env)",
    )

    @field_validator("private_key", mode="before")
    @classmethod
    def load_private_key_from_env(cls, v: Optional[str]) -> Optional[str]:
        """Load private key from environment if not provided."""
        if not v:
            return _get_private_key_from_env()
        return v

    @model_validator(mode="after")
    def validate_keypair_match(self) -> "KeysConfig":
        """Validate that public and private keys match if both provided."""
        if self.public_key and self.private_key:
            if not validate_keypair(self.private_key, self.public_key):
                raise ValueError("MONITOR_PRIVATE_KEY and public_key do not match")
        return self


class TimeoutsConfig(BaseModel):
    """Timeout configuration for relay checks."""

    clearnet: float = Field(
        default=30.0,
        ge=5.0,
        le=120.0,
        description="Timeout for clearnet relay checks in seconds"
    )
    tor: float = Field(
        default=60.0,
        ge=10.0,
        le=180.0,
        description="Timeout for Tor relay checks in seconds"
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel relay checking."""

    max_parallel: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum concurrent relay checks"
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of relays to process before pushing to database"
    )


class SelectionConfig(BaseModel):
    """Configuration for relay selection."""

    min_age_since_check: int = Field(
        default=3600,  # 1 hour
        ge=0,
        description="Minimum seconds since last check"
    )


class MonitorConfig(BaseModel):
    """Monitor configuration."""

    interval: float = Field(
        default=3600.0, ge=60.0, description="Seconds between monitor cycles"
    )
    tor: TorConfig = Field(default_factory=TorConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)


# =============================================================================
# Service
# =============================================================================


class Monitor(BaseService):
    """
    Relay health monitoring service.

    Checks relay connectivity and capabilities:
    - NIP-11: Fetches relay info document
    - NIP-66: Tests read/write capabilities and measures RTT

    Results are stored in relay_metadata table.
    """

    SERVICE_NAME = SERVICE_NAME
    CONFIG_CLASS = MonitorConfig

    def __init__(
        self,
        brotr: Brotr,
        config: Optional[MonitorConfig] = None,
    ) -> None:
        """
        Initialize the service.

        Args:
            brotr: Brotr instance for database operations
            config: Service configuration (uses defaults if not provided)
        """
        super().__init__(brotr=brotr, config=config or MonitorConfig())
        self._config: MonitorConfig
        self._checked_relays: int = 0
        self._successful_checks: int = 0
        self._failed_checks: int = 0

    # -------------------------------------------------------------------------
    # BaseService Implementation
    # -------------------------------------------------------------------------

    async def run(self) -> None:
        """
        Run single monitoring cycle.

        Fetches relays needing checks and monitors each one concurrently,
        limited by max_concurrent. Results are batched for database insertion.
        Call via run_forever() for continuous operation.
        """
        cycle_start = time.time()
        self._checked_relays = 0
        self._successful_checks = 0
        self._failed_checks = 0

        # Fetch relays that need checking
        relays = await self._fetch_relays_to_check()
        if not relays:
            self._logger.info("no_relays_to_check")
            return

        self._logger.info("monitor_started", relay_count=len(relays))

        # Current timestamp for this batch
        generated_at = int(time.time())

        # Semaphore to limit concurrent checks
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)
        metadata_buffer: list[dict[str, Any]] = []

        async def check_with_limit(relay: Relay) -> Optional[dict[str, Any]]:
            async with semaphore:
                return await self._check_relay(relay, generated_at)

        # Process all relays concurrently (limited by semaphore)
        tasks = [check_with_limit(relay) for relay in relays]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect results and batch insert
        for result in results:
            if isinstance(result, dict):
                metadata_buffer.append(result)

                # Insert batch when threshold reached
                if len(metadata_buffer) >= self._config.concurrency.batch_size:
                    await self._insert_metadata_batch(metadata_buffer)
                    metadata_buffer = []

        # Insert remaining results
        if metadata_buffer:
            await self._insert_metadata_batch(metadata_buffer)

        elapsed = time.time() - cycle_start
        self._logger.info(
            "cycle_completed",
            checked=self._checked_relays,
            successful=self._successful_checks,
            failed=self._failed_checks,
            duration=round(elapsed, 2),
        )

    # -------------------------------------------------------------------------
    # Relay Selection
    # -------------------------------------------------------------------------

    async def _fetch_relays_to_check(self) -> list[Relay]:
        """Fetch relays that need health checking."""
        relays: list[Relay] = []
        threshold = int(time.time()) - self._config.selection.min_age_since_check

        # Query relays with stale or missing metadata using the view
        query = """
            SELECT relay_url
            FROM relay_metadata_latest
            WHERE generated_at IS NULL
               OR generated_at < $1
        """

        rows = await self._brotr.pool.fetch(query, threshold)

        skipped_tor = 0
        for row in rows:
            relay_url = row["relay_url"]
            try:
                relay = Relay(relay_url)
                # Skip .onion relays if Tor proxy is disabled
                if relay.network == "tor" and not self._config.tor.enabled:
                    skipped_tor += 1
                    continue
                relays.append(relay)
            except RelayValidationError:
                self._logger.debug("invalid_relay_url", url=relay_url)

        if skipped_tor > 0:
            self._logger.debug("skipped_tor_relays", count=skipped_tor)

        self._logger.debug("relays_to_check", count=len(relays))
        return relays

    # -------------------------------------------------------------------------
    # Relay Checking
    # -------------------------------------------------------------------------

    async def _check_relay(
        self, relay: Relay, generated_at: int
    ) -> Optional[dict[str, Any]]:
        """
        Check a single relay's health.

        Returns metadata dict or None on failure.
        """
        self._checked_relays += 1

        # Select timeout based on network type
        is_tor = relay.network == "tor"
        timeout = self._config.timeouts.tor if is_tor else self._config.timeouts.clearnet

        try:
            # Create client with optional SOCKS5 proxy for Tor
            socks5_proxy = None
            if is_tor and self._config.tor.enabled:
                socks5_proxy = f"socks5://{self._config.tor.host}:{self._config.tor.port}"

            client = Client(
                relay=relay,
                timeout=int(timeout),
                socks5_proxy_url=socks5_proxy,
            )

            # Fetch metadata using nostr_tools
            relay_metadata = await fetch_relay_metadata(
                client=client,
                sec=self._config.keys.private_key,
                pub=self._config.keys.public_key,
            )

            # Only return if we got useful data
            if relay_metadata and (relay_metadata.nip66 or relay_metadata.nip11):
                self._successful_checks += 1
                return self._metadata_to_dict(relay, relay_metadata, generated_at)

            self._failed_checks += 1
            return None

        except asyncio.TimeoutError:
            self._failed_checks += 1
            self._logger.debug("relay_timeout", relay=relay.url)
            return None
        except Exception as e:
            self._failed_checks += 1
            self._logger.debug("relay_check_failed", relay=relay.url, error=str(e))

    def _metadata_to_dict(
        self, relay: Relay, metadata: Any, generated_at: int
    ) -> dict[str, Any]:
        """Convert relay metadata to dict for database insertion."""
        result: dict[str, Any] = {
            "relay_url": relay.url,
            "relay_network": relay.network,
            "relay_inserted_at": int(time.time()),
            "generated_at": generated_at,
            "nip66": None,
            "nip11": None,
        }

        if metadata.nip66:
            result["nip66"] = {
                "openable": metadata.nip66.openable,
                "readable": metadata.nip66.readable,
                "writable": metadata.nip66.writable,
                "rtt_open": metadata.nip66.rtt_open,
                "rtt_read": metadata.nip66.rtt_read,
                "rtt_write": metadata.nip66.rtt_write,
            }

        if metadata.nip11:
            result["nip11"] = {
                "name": metadata.nip11.name,
                "description": metadata.nip11.description,
                "banner": metadata.nip11.banner,
                "icon": metadata.nip11.icon,
                "pubkey": metadata.nip11.pubkey,
                "contact": metadata.nip11.contact,
                "supported_nips": metadata.nip11.supported_nips,
                "software": metadata.nip11.software,
                "version": metadata.nip11.version,
                "privacy_policy": getattr(metadata.nip11, "privacy_policy", None),
                "terms_of_service": getattr(metadata.nip11, "terms_of_service", None),
                "limitation": getattr(metadata.nip11, "limitation", None),
                "extra_fields": getattr(metadata.nip11, "extra_fields", None),
            }

        return result

    async def _insert_metadata_batch(self, metadata_list: list[dict[str, Any]]) -> None:
        """Insert batch of relay metadata into database."""
        if not metadata_list:
            return

        success = await self._brotr.insert_relay_metadata(metadata_list)
        if success:
            self._logger.debug("metadata_batch_inserted", count=len(metadata_list))
        else:
            self._logger.warning("metadata_batch_failed", count=len(metadata_list))
