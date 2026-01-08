"""
Integration tests for NIP-66 operations.

Requires: Internet connection.
Run with: pytest tests/integration/test_nip66_integration.py -v -m integration
"""

import pytest
from nostr_sdk import EventBuilder, Filter, Keys

from models.nip66 import Nip66
from models.relay import Relay


class TestNip66Integration:
    """Integration tests for NIP-66 operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_rtt_integration(self) -> None:
        """
        Test the full RTT (open, read, write) cycle against a public relay.

        This test connects to a live relay (wss://relay.damus.io), sends an event,
        and reads it back to measure round-trip times. It implicitly tests the
        `models.client.Client` wrapper's ability to connect and handle
        communications.
        """
        relay = Relay("wss://relay.damus.io")
        keys = Keys.generate()
        event_builder = EventBuilder.text_note("test: BigBrotr NIP-66 integration test")
        # Use a unique filter to avoid getting other messages
        read_filter = Filter().author(keys.public_key()).limit(1)

        nip66_result = await Nip66.test(
            relay=relay,
            keys=keys,
            event_builder=event_builder,
            read_filter=read_filter,
            run_ssl=False,
            run_geo=False,
            run_dns=False,
            run_http=False,
        )

        assert nip66_result is not None
        assert nip66_result.rtt_metadata is not None

        rtt_data = nip66_result.rtt_metadata.data
        assert rtt_data.get("rtt_open") is not None and rtt_data.get("rtt_open") > 0
        # damus.io sometimes doesn't allow reads, so we don't assert read

        assert rtt_data.get("rtt_write") is not None and rtt_data.get("rtt_write") > 0
