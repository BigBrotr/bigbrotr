"""NIP-66 RTT metadata container with test capabilities."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from time import perf_counter
from typing import TYPE_CHECKING, Any, Self

from core.logger import Logger
from models.nips.base import DEFAULT_TIMEOUT, BaseMetadata
from models.relay import NetworkType, Relay

from .data import Nip66RttData
from .logs import Nip66RttLogs


if TYPE_CHECKING:
    from nostr_sdk import EventBuilder, Filter, Keys


logger = Logger("models.nip66")


class Nip66RttMetadata(BaseMetadata):
    """Container for RTT data and logs with test capabilities."""

    data: Nip66RttData
    logs: Nip66RttLogs

    # -------------------------------------------------------------------------
    # RTT Test
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
        from nostr_sdk import Filter, RelayUrl  # noqa: PLC0415

        from utils.transport import connect_relay  # noqa: PLC0415

        timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        logger.debug("rtt_started", relay=relay.url, timeout_s=timeout, proxy=proxy_url)

        # Overlay networks require proxy
        overlay_networks = (NetworkType.TOR, NetworkType.I2P, NetworkType.LOKI)
        if proxy_url is None and relay.network in overlay_networks:
            raise ValueError(f"overlay network {relay.network.value} requires proxy")

        # RTT data (timing)
        rtt_data: dict[str, Any] = {
            "rtt_open": None,
            "rtt_read": None,
            "rtt_write": None,
        }
        # Probe logs (success/failure reasons)
        logs: dict[str, Any] = {
            "open_success": None,
            "open_reason": None,
            "read_success": None,
            "read_reason": None,
            "write_success": None,
            "write_reason": None,
        }
        relay_url = RelayUrl.parse(relay.url)

        # Test open: measure connection time
        logger.debug("rtt_connecting", relay=relay.url)
        try:
            start = perf_counter()
            client = await connect_relay(relay, keys, proxy_url, timeout, allow_insecure)
            rtt_open = int((perf_counter() - start) * 1000)
            rtt_data["rtt_open"] = rtt_open
            logs["open_success"] = True
            logger.debug("rtt_open_ok", relay=relay.url, rtt_open_ms=rtt_open)
        except Exception as e:
            reason = str(e)
            logs["open_success"] = False
            logs["open_reason"] = reason
            # If open fails, read and write cannot succeed
            logs["read_success"] = False
            logs["read_reason"] = reason
            logs["write_success"] = False
            logs["write_reason"] = reason
            logger.debug("rtt_open_failed", relay=relay.url, reason=reason)
            return cls(
                data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
                logs=Nip66RttLogs.model_validate(logs),
            )

        try:
            # Test read: stream_events to measure time to first event
            try:
                logger.debug("rtt_reading", relay=relay.url)
                start = perf_counter()
                stream = await client.stream_events(read_filter, timeout=timedelta(seconds=timeout))
                first_event = await stream.next()
                if first_event is not None:
                    rtt_read = int((perf_counter() - start) * 1000)
                    rtt_data["rtt_read"] = rtt_read
                    logs["read_success"] = True
                    logger.debug("rtt_read_ok", relay=relay.url, rtt_read_ms=rtt_read)
                else:
                    logs["read_success"] = False
                    logs["read_reason"] = "no events returned"
                    logger.debug("rtt_read_no_events", relay=relay.url)
            except Exception as e:
                logs["read_success"] = False
                logs["read_reason"] = str(e)
                logger.debug("rtt_read_failed", relay=relay.url, reason=str(e))

            # Test write: send event and verify by reading it back
            try:
                logger.debug("rtt_writing", relay=relay.url)
                start = perf_counter()
                output = await asyncio.wait_for(
                    client.send_event_builder(event_builder), timeout=timeout
                )
                rtt_write = int((perf_counter() - start) * 1000)

                if output and relay_url in output.failed:
                    reason = output.failed.get(relay_url, "unknown")
                    logs["write_success"] = False
                    logs["write_reason"] = str(reason) if reason else "unknown"
                    logger.debug("rtt_write_rejected", relay=relay.url, reason=str(reason))
                elif output and relay_url in output.success:
                    logger.debug("rtt_write_accepted", relay=relay.url, rtt_write_ms=rtt_write)
                    event_id = output.id
                    verify_filter = Filter().id(event_id).limit(1)
                    logger.debug("rtt_write_verifying", relay=relay.url, event_id=str(event_id))
                    try:
                        stream = await client.stream_events(
                            verify_filter, timeout=timedelta(seconds=timeout)
                        )
                        verify_event = await stream.next()
                        if verify_event is not None:
                            rtt_data["rtt_write"] = rtt_write
                            logs["write_success"] = True
                            logger.debug("rtt_write_verified", relay=relay.url)
                        else:
                            logs["write_success"] = False
                            logs["write_reason"] = "unverified: accepted but not retrievable"
                            logger.debug(
                                "rtt_write_unverified",
                                relay=relay.url,
                                reason="event not retrievable",
                            )
                    except Exception as e:
                        logs["write_success"] = False
                        logs["write_reason"] = str(e)
                        logger.debug("rtt_write_unverified", relay=relay.url, reason=str(e))
                else:
                    logs["write_success"] = False
                    logs["write_reason"] = "no response from relay"
                    logger.debug("rtt_write_no_response", relay=relay.url)
            except Exception as e:
                logs["write_success"] = False
                logs["write_reason"] = str(e)
                logger.debug("rtt_write_failed", relay=relay.url, reason=str(e))

        finally:
            try:
                await client.disconnect()
            except Exception:
                pass

        logger.debug(
            "rtt_completed",
            relay=relay.url,
            rtt_data=rtt_data,
            open_success=logs.get("open_success"),
            read_success=logs.get("read_success"),
            write_success=logs.get("write_success"),
        )
        return cls(
            data=Nip66RttData.model_validate(Nip66RttData.parse(rtt_data)),
            logs=Nip66RttLogs.model_validate(logs),
        )
