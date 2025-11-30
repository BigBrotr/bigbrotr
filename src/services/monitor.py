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
from typing import TYPE_CHECKING, Any, Optional

from nostr_tools import Client, Relay, RelayMetadata
from nostr_tools.actions import fetch_relay_metadata
from nostr_tools.exceptions import RelayValidationError
from nostr_tools.utils import validate_keypair
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

from core.base_service import BaseService

if TYPE_CHECKING:
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


def _get_private_key_from_env() -> Optional[SecretStr]:
    """Load private key from MONITOR_PRIVATE_KEY environment variable."""
    key = os.getenv("MONITOR_PRIVATE_KEY")
    return SecretStr(key) if key else None


class KeysConfig(BaseModel):
    """Nostr keys for NIP-66 testing."""

    public_key: Optional[str] = Field(default=None, description="Public key (hex) for write tests")
    private_key: Optional[SecretStr] = Field(
        default_factory=_get_private_key_from_env,
        description="Private key (from MONITOR_PRIVATE_KEY env)",
    )

    @field_validator("private_key", mode="before")
    @classmethod
    def load_private_key_from_env(cls, v: Optional[str]) -> Optional[SecretStr]:
        """Load private key from environment if not provided."""
        if v is None or v == "":
            return _get_private_key_from_env()
        if isinstance(v, SecretStr):
            return v
        return SecretStr(v)

    @model_validator(mode="after")
    def validate_keypair_match(self) -> KeysConfig:
        """Validate that public and private keys match if both provided."""
        if self.public_key and self.private_key:
            if not validate_keypair(self.private_key.get_secret_value(), self.public_key):
                raise ValueError("MONITOR_PRIVATE_KEY and public_key do not match")
        return self


class TimeoutsConfig(BaseModel):
    """Timeout configuration for relay checks."""

    clearnet: float = Field(
        default=30.0, ge=5.0, le=120.0, description="Timeout for clearnet relay checks in seconds"
    )
    tor: float = Field(
        default=60.0, ge=10.0, le=180.0, description="Timeout for Tor relay checks in seconds"
    )


class ConcurrencyConfig(BaseModel):
    """Concurrency configuration for parallel relay checking."""

    max_parallel: int = Field(
        default=50, ge=1, le=500, description="Maximum concurrent relay checks"
    )
    batch_size: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Number of relays to process before pushing to database",
    )


class SelectionConfig(BaseModel):
    """Configuration for relay selection."""

    min_age_since_check: int = Field(
        default=3600,  # 1 hour
        ge=0,
        description="Minimum seconds since last check",
    )


class MonitorConfig(BaseModel):
    """Monitor configuration."""

    interval: float = Field(default=3600.0, ge=60.0, description="Seconds between monitor cycles")
    tor: TorConfig = Field(default_factory=TorConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    selection: SelectionConfig = Field(default_factory=SelectionConfig)


# =============================================================================
# Helpers
# =============================================================================


def metadata_to_db_record(metadata: RelayMetadata) -> dict[str, Any]:
    """
    Transform a RelayMetadata object into a dictionary for Brotr.insert_relay_metadata().

    The nostr_tools RelayMetadata.to_dict() returns:
        {
            "relay": {"url": str, "network": str},
            "generated_at": int,
            "nip11": {...} | None,
            "nip66": {...} | None
        }

    Brotr.insert_relay_metadata() expects:
        {
            "relay_url": str,
            "relay_network": str,
            "relay_inserted_at": int,
            "generated_at": int,
            "nip11": {...} | None,
            "nip66": {...} | None
        }

    Args:
        metadata: RelayMetadata object from nostr_tools

    Returns:
        Dictionary formatted for Brotr.insert_relay_metadata()
    """
    return {
        "relay_url": metadata.relay.url,
        "relay_network": metadata.relay.network,
        "relay_inserted_at": int(time.time()),
        "generated_at": metadata.generated_at,
        "nip11": metadata.nip11.to_dict() if metadata.nip11 else None,
        "nip66": metadata.nip66.to_dict() if metadata.nip66 else None,
    }


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

        # Metrics
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

        # 1. Fetch relays to check
        relays = await self._fetch_relays_to_check()
        if not relays:
            self._logger.info("no_relays_to_check")
            return

        self._logger.info("monitor_started", relay_count=len(relays))

        # 2. Prepare for parallel execution
        semaphore = asyncio.Semaphore(self._config.concurrency.max_parallel)
        metadata_batch: list[dict[str, Any]] = []

        # 3. Process relays
        # We create tasks for all relays but limit concurrency with semaphore
        tasks = [self._process_relay(relay, semaphore) for relay in relays]

        for future in asyncio.as_completed(tasks):
            try:
                result = await future
                if result:
                    metadata_batch.append(metadata_to_db_record(result))

                    # Insert batch if full
                    if len(metadata_batch) >= self._config.concurrency.batch_size:
                        await self._insert_metadata_batch(metadata_batch)
                        metadata_batch = []
            except Exception as e:
                self._logger.error("unexpected_error_in_loop", error=str(e))

        # 4. Insert remaining records
        if metadata_batch:
            await self._insert_metadata_batch(metadata_batch)

        # 5. Log stats
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
        """Fetch relays that need health checking from database."""
        relays: list[Relay] = []
        threshold = int(time.time()) - self._config.selection.min_age_since_check

        # Use the view to find relays with stale or missing metadata
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
                # Filter Tor relays if proxy disabled
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
    # Relay Processing
    # -------------------------------------------------------------------------

    async def _process_relay(
        self, relay: Relay, semaphore: asyncio.Semaphore
    ) -> Optional[RelayMetadata]:
        """
        Check a single relay with concurrency limit.

        Returns formatted dictionary for DB insertion or None on failure/no data.
        """
        async with semaphore:
            self._checked_relays += 1

            # Determine configuration for this check
            is_tor = relay.network == "tor"
            timeout = self._config.timeouts.tor if is_tor else self._config.timeouts.clearnet

            socks5_proxy = None
            if is_tor and self._config.tor.enabled:
                socks5_proxy = f"socks5://{self._config.tor.host}:{self._config.tor.port}"

            try:
                client = Client(
                    relay=relay,
                    timeout=int(timeout),
                    socks5_proxy_url=socks5_proxy,
                )

                # Use library action to fetch all metadata
                # This handles NIP-11 (HTTP) and NIP-66 (WebSocket) internally
                try:
                    metadata = await fetch_relay_metadata(
                        client=client,
                        sec=self._config.keys.private_key.get_secret_value(),
                        pub=self._config.keys.public_key,
                        event_creation_timeout=int(timeout),
                    )
                except Exception:
                    self._failed_checks += 1
                    self._logger.info("check_failed", relay=relay.url)
                    return None

                # Check if we got any meaningful data
                if metadata and (metadata.nip66 or metadata.nip11):
                    self._successful_checks += 1
                    self._logger.info("check_ok", relay=relay.url)
                    return metadata

                self._failed_checks += 1
                self._logger.info("check_failed", relay=relay.url)
                return None

            except Exception as e:
                self._failed_checks += 1
                self._logger.debug("relay_check_failed", relay=relay.url, error=str(e))
                return None

    async def _insert_metadata_batch(self, batch: list[dict[str, Any]]) -> None:
        """Insert a batch of metadata records into database."""
        if not batch:
            return

        try:
            count = await self._brotr.insert_relay_metadata(batch)
            self._logger.debug("metadata_batch_inserted", count=count)
        except Exception as e:
            self._logger.warning("metadata_batch_failed", count=len(batch), error=str(e))
