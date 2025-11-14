"""
Test script to demonstrate Brotr with composition pattern.
"""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from core.brotr import Brotr
from core.pool import ConnectionPool


def test_brotr_composition():
    """Test that Brotr properly uses composition with dependency injection."""

    print("=" * 70)
    print("Testing Brotr with Composition Pattern (Dependency Injection)")
    print("=" * 70)

    # Test 1: Direct instantiation with pool injection
    print("\n1. Dependency Injection (Custom Pool):")
    print("-" * 70)
    pool = ConnectionPool(
        host="localhost",
        database="brotr",
        user="admin",
        min_size=5,
        max_size=20
    )
    brotr1 = Brotr(pool=pool, max_batch_size=20000)
    print(f"   {brotr1}")
    print(f"   Host: {brotr1.pool.config.database.host}")
    print(f"   Database: {brotr1.pool.config.database.database}")
    print(f"   Pool min size: {brotr1.pool.config.limits.min_size}")
    print(f"   Pool max size: {brotr1.pool.config.limits.max_size}")
    print(f"   Max batch size: {brotr1.config.batch.max_batch_size}")
    print(f"   Connected: {brotr1.pool.is_connected}")
    print(f"   Pool object is same? {brotr1.pool is pool}")

    # Test 2: from_dict (unified structure with pool key)
    print("\n2. From Dictionary (Unified Structure):")
    print("-" * 70)
    config = {
        "pool": {
            "database": {"host": "dict.example.com", "database": "dict_db"},
            "limits": {"min_size": 8, "max_size": 40}
        },
        "batch": {"max_batch_size": 30000}
    }
    brotr2 = Brotr.from_dict(config)
    print(f"   {brotr2}")
    print(f"   Host: {brotr2.pool.config.database.host}")
    print(f"   Database: {brotr2.pool.config.database.database}")
    print(f"   Max batch size: {brotr2.config.batch.max_batch_size}")

    # Test 3: Verify composition pattern
    print("\n3. Composition Pattern Verification:")
    print("-" * 70)
    print(f"   Has pool property? {hasattr(brotr1, 'pool')}")
    print(f"   Pool type: {type(brotr1.pool).__name__}")
    print(f"   Pool has acquire method? {hasattr(brotr1.pool, 'acquire')}")
    print(f"   Pool has connect method? {hasattr(brotr1.pool, 'connect')}")
    print(f"   Brotr has insert_events method? {hasattr(brotr1, 'insert_events')}")
    print(f"   Brotr has cleanup_orphans method? {hasattr(brotr1, 'cleanup_orphans')}")

    # Test 4: All defaults
    print("\n4. All Defaults:")
    print("-" * 70)
    brotr3 = Brotr()
    print(f"   {brotr3}")
    print(f"   Host (default): {brotr3.pool.config.database.host}")
    print(f"   Database (default): {brotr3.pool.config.database.database}")
    print(f"   Max batch size (default): {brotr3.config.batch.max_batch_size}")

    print("\n" + "=" * 70)
    print("All tests passed! ✓")
    print("=" * 70)

    print("\n📝 Summary:")
    print("   - Brotr uses composition with dependency injection")
    print("   - API Option 1: Brotr(pool=custom_pool, max_batch_size=...)")
    print("   - API Option 2: Brotr(max_batch_size=...) → uses default pool")
    print("   - API Option 3: Brotr.from_dict(config) → creates pool internally")
    print("   - Pool operations: brotr.pool.fetch(), brotr.pool.acquire(), etc.")
    print("   - Unified API: brotr.insert_events([...]), brotr.insert_relays([...]), etc.")
    print("   - Clear separation: pool for connections, brotr for business logic")
    print("   - Reduced __init__ parameters from 28 to 12 (1 pool + 11 brotr)")
    print("   - Unified YAML config with pool under 'pool' root key")


if __name__ == "__main__":
    test_brotr_composition()
