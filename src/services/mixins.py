"""Mixins per eliminare duplicazione tra services.

Provides reusable functionality that is common across multiple services:
- NetworkSemaphoreMixin: Per-network concurrency limiting with asyncio semaphores
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from utils.network import NetworkType


if TYPE_CHECKING:
    from utils.network import NetworkConfig


class NetworkSemaphoreMixin:
    """Mixin for services that use per-network concurrency semaphores.

    Provides methods to initialize and access asyncio semaphores that limit
    concurrent operations per network type (clearnet, tor, i2p, loki).

    Used by Validator and Monitor to prevent overwhelming network resources,
    especially important for Tor where too many simultaneous connections
    can degrade performance.

    The _semaphores dict is created by _init_semaphores() and should be called
    at the start of each run cycle to pick up configuration changes.
    """

    _semaphores: dict[NetworkType, asyncio.Semaphore]

    def _init_semaphores(self, networks: NetworkConfig) -> None:
        """Initialize per-network concurrency semaphores.

        Creates an asyncio.Semaphore for each network type with max_tasks
        from the network configuration. Should be called at the start of
        each run cycle to pick up configuration changes.

        Args:
            networks: Network configuration with max_tasks per network type.
        """
        self._semaphores = {
            network: asyncio.Semaphore(networks.get(network).max_tasks)
            for network in NetworkType
        }

    def _get_semaphore(self, network: NetworkType) -> asyncio.Semaphore | None:
        """Get the semaphore for a specific network type.

        Args:
            network: The network type to get the semaphore for.

        Returns:
            The semaphore for the network, or None if not found.
        """
        return self._semaphores.get(network)
