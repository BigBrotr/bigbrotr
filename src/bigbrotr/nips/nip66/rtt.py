"""
NIP-66 RTT metadata container with relay probe capabilities.

Tests a relay's round-trip time by measuring connection open, event
read, and event write latencies. Results are stored as millisecond
integers alongside detailed logs for each phase.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any, NamedTuple, Self

from nostr_sdk import Filter, NostrSdkError, RelayUrl

from bigbrotr.models.constants import DEFAULT_TIMEOUT, NetworkType
from bigbrotr.models.relay import Relay  # noqa: TC001
from bigbrotr.nips.base import BaseMetadata

from .data import Nip66RttData
from .logs import Nip66RttMultiPhaseLogs


if TYPE_CHECKING:
    from nostr_sdk import Client, EventBuilder, Keys


logger = logging.getLogger("bigbrotr.nips.nip66")


class Nip66RttDependencies(NamedTuple):
    """Grouped dependencies for RTT probe tests.

    Bundles the signing keys, event builder, and read filter required
    by the RTT measurement phases (open, read, write).
    """

    keys: Keys
    event_builder: EventBuilder
    read_filter: Filter


class Nip66RttMetadata(BaseMetadata):
    """Container for RTT measurement data and multi-phase probe logs.

    Provides the ``execute()`` class method that connects to a relay and
    measures open, read, and write round-trip times.
    """

    data: Nip66RttData
    logs: Nip66RttMultiPhaseLogs

    # -------------------------------------------------------------------------
    # RTT Test - Main Entry Point
    # -------------------------------------------------------------------------

    @classmethod
    async def execute(
        cls,
        relay: Relay,
        deps: Nip66RttDependencies,
        timeout: float | None = None,  # noqa: ASYNC109
        proxy_url: str | None = None,
        *,
        allow_insecure: bool = True,
    ) -> Self:
        """Test a relay's round-trip times across three phases.

        Phases are executed sequentially: open -> read -> write.
        If the open phase fails, read and write are marked as failed
        with the same reason (cascading failure).

        Args:
            relay: Relay to test.
            deps: Grouped dependencies (keys, event_builder, read_filter).
            timeout: Connection timeout in seconds (default: 10.0).
            proxy_url: Optional SOCKS5 proxy URL for overlay networks.
            allow_insecure: Fall back to unverified SSL (default: True).

        Returns:
            An ``Nip66RttMetadata`` instance with measurement data and logs.

        Raises:
            ValueError: If an overlay network relay has no proxy configured.
        """
        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("rtt_started relay=%s timeout_s=%s proxy=%s", relay.url, timeout, proxy_url)

        cls._validate_network(relay, proxy_url)

        rtt_data = cls._empty_rtt_data()
        logs = cls._empty_logs()
        relay_url = RelayUrl.parse(relay.url)

        # Phase 1: Open connection
        client, open_rtt = await cls._test_open(
            relay, deps.keys, proxy_url, timeout, allow_insecure=allow_insecure, logs=logs
        )
        if client is None:
            return cls._build_result(rtt_data, logs)

        rtt_data["rtt_open"] = open_rtt
        logs["open_success"] = True

        try:
            # Phase 2: Read capability
            read_result = await cls._test_read(client, deps.read_filter, timeout, relay.url)
            rtt_data["rtt_read"] = read_result.get("rtt_read")
            logs["read_success"] = read_result["read_success"]
            logs["read_reason"] = read_result.get("read_reason")

            # Phase 3: Write capability
            write_result = await cls._test_write(
                client, deps.event_builder, relay_url, timeout, relay.url
            )
            rtt_data["rtt_write"] = write_result.get("rtt_write")
            logs["write_success"] = write_result["write_success"]
            logs["write_reason"] = write_result.get("write_reason")
        finally:
            await cls._cleanup(client)

        logger.debug(
            "rtt_completed relay=%s rtt_data=%s open_success=%s read_success=%s write_success=%s",
            relay.url,
            rtt_data,
            logs.get("open_success"),
            logs.get("read_success"),
            logs.get("write_success"),
        )
        return cls._build_result(rtt_data, logs)

    # -------------------------------------------------------------------------
    # Validation and Construction Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _validate_network(relay: Relay, proxy_url: str | None) -> None:
        """Ensure overlay network relays have a proxy configured.

        Raises:
            ValueError: If the relay is on an overlay network without a proxy.
        """
        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            raise ValueError(f"overlay network {relay.network.value} requires proxy")

    @staticmethod
    def _empty_rtt_data() -> dict[str, Any]:
        """Return an initialized RTT data dictionary with all fields set to None."""
        return {"rtt_open": None, "rtt_read": None, "rtt_write": None}

    @staticmethod
    def _empty_logs() -> dict[str, Any]:
        """Return an initialized logs dictionary with all fields set to None."""
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
        """Construct the final Nip66RttMetadata from raw data and logs dicts."""
        return cls(
            data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
            logs=Nip66RttMultiPhaseLogs.model_validate(logs),
        )

    # -------------------------------------------------------------------------
    # Phase Methods
    # -------------------------------------------------------------------------

    @classmethod
    async def _test_open(  # noqa: PLR0913
        cls,
        relay: Relay,
        keys: Keys,
        proxy_url: str | None,
        timeout: float,  # noqa: ASYNC109
        *,
        allow_insecure: bool,
        logs: dict[str, Any],
    ) -> tuple[Client | None, int | None]:
        """Test the WebSocket connection open phase.

        On success, returns the connected client and the RTT in milliseconds.
        On failure, sets cascading failure logs for all three phases and
        returns (None, None).
        """
        from bigbrotr.utils.transport import connect_relay  # noqa: PLC0415 - Avoid circular import

        logger.debug("rtt_connecting relay=%s", relay.url)
        try:
            start = perf_counter()
            client = await connect_relay(
                relay, keys, proxy_url, timeout, allow_insecure=allow_insecure
            )
            rtt_open = int((perf_counter() - start) * 1000)
            logger.debug("rtt_open_ok relay=%s rtt_open_ms=%s", relay.url, rtt_open)
            return client, rtt_open
        except (OSError, TimeoutError, NostrSdkError, ValueError) as e:
            reason = str(e)
            logger.debug("rtt_open_failed relay=%s reason=%s", relay.url, reason)
            # Cascading failure: mark all phases as failed
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
        timeout: float,  # noqa: ASYNC109
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Test the read capability by streaming events with the given filter.

        Returns a result dict with ``read_success``, ``read_reason``, and
        ``rtt_read`` (milliseconds, only set on success).
        """
        result: dict[str, Any] = {"read_success": False, "read_reason": None, "rtt_read": None}

        try:
            logger.debug("rtt_reading relay=%s", relay_url_str)
            start = perf_counter()
            stream = await client.stream_events(read_filter, timeout=timedelta(seconds=timeout))
            first_event = await stream.next()

            if first_event is not None:
                rtt_read = int((perf_counter() - start) * 1000)
                result["rtt_read"] = rtt_read
                result["read_success"] = True
                logger.debug("rtt_read_ok relay=%s rtt_read_ms=%s", relay_url_str, rtt_read)
            else:
                result["read_reason"] = "no events returned"
                logger.debug("rtt_read_no_events relay=%s", relay_url_str)
        except (OSError, TimeoutError, NostrSdkError) as e:
            result["read_reason"] = str(e)
            logger.debug("rtt_read_failed relay=%s reason=%s", relay_url_str, str(e))

        return result

    @staticmethod
    async def _test_write(
        client: Client,
        event_builder: EventBuilder,
        relay_url: RelayUrl,
        timeout: float,  # noqa: ASYNC109
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Test the write capability by publishing an event and verifying storage.

        Returns a result dict with ``write_success``, ``write_reason``, and
        ``rtt_write`` (milliseconds, only set on verified success).
        """
        result: dict[str, Any] = {"write_success": False, "write_reason": None, "rtt_write": None}

        try:
            logger.debug("rtt_writing relay=%s", relay_url_str)
            start = perf_counter()
            output = await asyncio.wait_for(
                client.send_event_builder(event_builder), timeout=timeout
            )
            rtt_write = int((perf_counter() - start) * 1000)

            if output and relay_url in output.failed:
                reason = output.failed.get(relay_url, "unknown")
                result["write_reason"] = str(reason) if reason else "unknown"
                logger.debug("rtt_write_rejected relay=%s reason=%s", relay_url_str, str(reason))
            elif output and relay_url in output.success:
                logger.debug(
                    "rtt_write_accepted relay=%s rtt_write_ms=%s", relay_url_str, rtt_write
                )
                # Verify the event can be retrieved back from the relay
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
                logger.debug("rtt_write_no_response relay=%s", relay_url_str)
        except (OSError, TimeoutError, NostrSdkError) as e:
            result["write_reason"] = str(e)
            logger.debug("rtt_write_failed relay=%s reason=%s", relay_url_str, str(e))

        return result

    @staticmethod
    async def _verify_write(
        client: Client,
        event_id: Any,
        timeout: float,  # noqa: ASYNC109
        relay_url_str: str,
    ) -> dict[str, Any]:
        """Verify that a previously written event can be retrieved.

        Returns a dict with ``verified`` (bool) and ``reason`` (str or None).
        """
        logger.debug("rtt_write_verifying relay=%s event_id=%s", relay_url_str, str(event_id))
        try:
            verify_filter = Filter().id(event_id).limit(1)
            stream = await client.stream_events(verify_filter, timeout=timedelta(seconds=timeout))
            verify_event = await stream.next()

            if verify_event is not None:
                logger.debug("rtt_write_verified relay=%s", relay_url_str)
                return {"verified": True, "reason": None}
            logger.debug(
                "rtt_write_unverified relay=%s reason=%s",
                relay_url_str,
                "event not retrievable",
            )
            return {"verified": False, "reason": "unverified: accepted but not retrievable"}
        except (OSError, TimeoutError, NostrSdkError) as e:
            logger.debug("rtt_write_unverified relay=%s reason=%s", relay_url_str, str(e))
            return {"verified": False, "reason": str(e)}

    @staticmethod
    async def _cleanup(client: Client) -> None:
        """Disconnect the client, suppressing any errors."""
        with contextlib.suppress(Exception):
            await client.disconnect()
