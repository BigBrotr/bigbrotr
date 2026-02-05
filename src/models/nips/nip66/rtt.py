"""NIP-66 RTT metadata container with test capabilities."""

from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any, Self

from nostr_sdk import Filter, RelayUrl

from logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import Relay
from utils.network import NetworkType

from .data import Nip66RttData
from .logs import Nip66RttLogs


if TYPE_CHECKING:
    from nostr_sdk import Client, EventBuilder, Keys


logger = Logger("models.nip66")


class Nip66RttMetadata(BaseMetadata):
    """Container for RTT data and logs with test capabilities."""

    data: Nip66RttData
    logs: Nip66RttLogs

    # -------------------------------------------------------------------------
    # RTT Test - Main Entry Point
    # -------------------------------------------------------------------------

    @classmethod
    async def rtt(
        cls,
        relay: Relay,
        keys: Keys,
        event_builder: EventBuilder,
        read_filter: Filter,
        timeout: float | None = None,
        proxy_url: str | None = None,
        allow_insecure: bool = True,
    ) -> Self:
        """Test relay RTT (round-trip times) with probe results in logs.

        Raises:
            ValueError: If overlay network without proxy.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("rtt_started", relay=relay.url, timeout_s=timeout, proxy=proxy_url)

        cls._validate_network(relay, proxy_url)

        rtt_data = cls._empty_rtt_data()
        logs = cls._empty_logs()
        relay_url = RelayUrl.parse(relay.url)

        # Phase 1: Test open connection
        client, open_rtt = await cls._test_open(
            relay, keys, proxy_url, timeout, allow_insecure, logs
        )
        if client is None:
            # Open failed - logs already set by _test_open
            return cls._build_result(rtt_data, logs)

        rtt_data["rtt_open"] = open_rtt
        logs["open_success"] = True

        try:
            # Phase 2: Test read capability
            read_result = await cls._test_read(client, read_filter, timeout, relay.url)
            rtt_data["rtt_read"] = read_result.get("rtt_read")
            logs["read_success"] = read_result["read_success"]
            logs["read_reason"] = read_result.get("read_reason")

            # Phase 3: Test write capability
            write_result = await cls._test_write(
                client, event_builder, relay_url, timeout, relay.url
            )
            rtt_data["rtt_write"] = write_result.get("rtt_write")
            logs["write_success"] = write_result["write_success"]
            logs["write_reason"] = write_result.get("write_reason")
        finally:
            await cls._cleanup(client)

        logger.debug(
            "rtt_completed",
            relay=relay.url,
            rtt_data=rtt_data,
            open_success=logs.get("open_success"),
            read_success=logs.get("read_success"),
            write_success=logs.get("write_success"),
        )
        return cls._build_result(rtt_data, logs)

    # -------------------------------------------------------------------------
    # Helper Methods
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_network(relay: Relay, proxy_url: str | None) -> None:
        """Validate that overlay networks have a proxy configured."""
        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            raise ValueError(f"overlay network {relay.network.value} requires proxy")

    @staticmethod
    def _empty_rtt_data() -> dict[str, Any]:
        """Return empty RTT data dictionary."""
        return {"rtt_open": None, "rtt_read": None, "rtt_write": None}

    @staticmethod
    def _empty_logs() -> dict[str, Any]:
        """Return empty logs dictionary."""
        return {
            "open_success": None,
            "open_reason": None,
            "read_success": None,
            "read_reason": None,
            "write_success": None,
            "write_reason": None,
        }

    @classmethod
    def _build_result(cls, rtt_data: dict[str, Any], logs: dict[str, Any]) -> Self:
        """Build the final Nip66RttMetadata result."""
        return cls(
            data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
            logs=Nip66RttLogs.model_validate(logs),
        )

    # -------------------------------------------------------------------------
    # Phase Methods
    # -------------------------------------------------------------------------

    @classmethod
    async def _test_open(
        cls,
        relay: Relay,
        keys: Keys,
        proxy_url: str | None,
        timeout: float,
        allow_insecure: bool,
        logs: dict[str, Any],
    ) -> tuple[Client | None, int | None]:
        """Test open connection, return (client, rtt_ms) or (None, None) on failure.

        On failure, sets open/read/write logs to indicate cascading failure.
        """
        from utils.transport import connect_relay  # noqa: PLC0415 - Avoid circular import

        logger.debug("rtt_connecting", relay=relay.url)
        try:
            start = perf_counter()
            client = await connect_relay(relay, keys, proxy_url, timeout, allow_insecure)
            rtt_open = int((perf_counter() - start) * 1000)
            logger.debug("rtt_open_ok", relay=relay.url, rtt_open_ms=rtt_open)
            return client, rtt_open
        except Exception as e:
            reason = str(e)
            logger.debug("rtt_open_failed", relay=relay.url, reason=reason)
            # Set cascading failure for all phases
            logs["open_success"] = False
            logs["open_reason"] = reason
            logs["read_success"] = False
            logs["read_reason"] = reason
            logs["write_success"] = False
            logs["write_reason"] = reason
            return None, None

    @staticmethod
    async def _test_read(
        client: Client,
        read_filter: Filter,
        timeout: float,
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Test read capability, return result dict with read_success and optional rtt_read."""
        result: dict[str, Any] = {"read_success": False, "read_reason": None, "rtt_read": None}

        try:
            logger.debug("rtt_reading", relay=relay_url_str)
            start = perf_counter()
            stream = await client.stream_events(read_filter, timeout=timedelta(seconds=timeout))
            first_event = await stream.next()

            if first_event is not None:
                rtt_read = int((perf_counter() - start) * 1000)
                result["rtt_read"] = rtt_read
                result["read_success"] = True
                logger.debug("rtt_read_ok", relay=relay_url_str, rtt_read_ms=rtt_read)
            else:
                result["read_reason"] = "no events returned"
                logger.debug("rtt_read_no_events", relay=relay_url_str)
        except Exception as e:
            result["read_reason"] = str(e)
            logger.debug("rtt_read_failed", relay=relay_url_str, reason=str(e))

        return result

    @staticmethod
    async def _test_write(
        client: Client,
        event_builder: EventBuilder,
        relay_url: RelayUrl,
        timeout: float,
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Test write capability, return result dict with write_success and optional rtt_write."""
        result: dict[str, Any] = {"write_success": False, "write_reason": None, "rtt_write": None}

        try:
            logger.debug("rtt_writing", relay=relay_url_str)
            start = perf_counter()
            output = await asyncio.wait_for(
                client.send_event_builder(event_builder), timeout=timeout
            )
            rtt_write = int((perf_counter() - start) * 1000)

            if output and relay_url in output.failed:
                reason = output.failed.get(relay_url, "unknown")
                result["write_reason"] = str(reason) if reason else "unknown"
                logger.debug("rtt_write_rejected", relay=relay_url_str, reason=str(reason))
            elif output and relay_url in output.success:
                logger.debug("rtt_write_accepted", relay=relay_url_str, rtt_write_ms=rtt_write)
                verify_result = await Nip66RttMetadata._verify_write(
                    client, output.id, timeout, relay_url_str
                )
                if verify_result["verified"]:
                    result["rtt_write"] = rtt_write
                    result["write_success"] = True
                else:
                    result["write_reason"] = verify_result["reason"]
            else:
                result["write_reason"] = "no response from relay"
                logger.debug("rtt_write_no_response", relay=relay_url_str)
        except Exception as e:
            result["write_reason"] = str(e)
            logger.debug("rtt_write_failed", relay=relay_url_str, reason=str(e))

        return result

    @staticmethod
    async def _verify_write(
        client: Client,
        event_id: Any,
        timeout: float,
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Verify written event can be retrieved."""
        logger.debug("rtt_write_verifying", relay=relay_url_str, event_id=str(event_id))
        try:
            verify_filter = Filter().id(event_id).limit(1)
            stream = await client.stream_events(verify_filter, timeout=timedelta(seconds=timeout))
            verify_event = await stream.next()

            if verify_event is not None:
                logger.debug("rtt_write_verified", relay=relay_url_str)
                return {"verified": True, "reason": None}
            else:
                logger.debug(
                    "rtt_write_unverified", relay=relay_url_str, reason="event not retrievable"
                )
                return {"verified": False, "reason": "unverified: accepted but not retrievable"}
        except Exception as e:
            logger.debug("rtt_write_unverified", relay=relay_url_str, reason=str(e))
            return {"verified": False, "reason": str(e)}

    @staticmethod
    async def _cleanup(client: Client) -> None:
        """Safely disconnect the client."""
        with contextlib.suppress(Exception):
            await client.disconnect()
