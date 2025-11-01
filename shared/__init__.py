"""Shared utilities for Brotr implementations.

This package provides shared utilities used by both Bigbrotr and Lilbrotr:
    - utils: Common functions, logging, constants, health checks
    - config: Configuration loading and validation

Usage:
    from shared.utils import chunkify, RelayFailureTracker
    from shared.config import load_monitor_config
"""

__all__ = ['utils', 'config']

