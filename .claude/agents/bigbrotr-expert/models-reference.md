# Models Reference

Complete documentation for BigBrotr's data models (Relay, Event, EventRelay, Metadata, RelayMetadata, Nip11, Nip66, NetworkType, MetadataType).

## Immutability Pattern

All models use frozen dataclasses with `__new__` and `object.__setattr__` to enforce true immutability:

```python
@dataclass(frozen=True)
class MyModel:
    field: str

    def __new__(cls, field: str):
        instance = object.__new__(cls)
        object.__setattr__(instance, "field", field)
        return instance

    def __init__(self, field: str):
        pass  # Required but empty
```

This pattern prevents accidental mutation after creation.

---

## Relay - Relay URL Model

**Location**: `src/models/relay.py`

Immutable representation of a Nostr relay with URL parsing and validation.

### Constructor

```python
Relay(raw: str, discovered_at: Optional[int] = None)
```

**Parameters**:
- `raw`: Raw WebSocket URL (e.g., `wss://relay.example.com/path`)
- `discovered_at`: Unix timestamp when relay was first discovered (defaults to `int(time())`)

**Validation**:
- URL must be valid WebSocket (`ws://` or `wss://`)
- Local addresses are rejected
- Unknown network types are rejected

### Attributes

```python
_url_without_scheme: str  # e.g., "relay.example.com/path"
network: str              # "clearnet", "tor", "i2p", "loki"
discovered_at: int        # Unix timestamp when first discovered
scheme: str               # "ws" or "wss"
host: str
port: Optional[int]
path: Optional[str]
```

### Properties

```python
@property
def url() -> str
```
Full URL with scheme: `f"{scheme}://{_url_without_scheme}"`

### Methods

```python
def to_db_params() -> tuple[str, str, int]
```
Returns `(url, network, discovered_at)` for database insertion.

### Network Detection

Automatic network detection from hostname:
- `.onion` → `"tor"`
- `.i2p` → `"i2p"`
- `.loki` → `"loki"`
- Local IPs (127.0.0.0/8, 10.0.0.0/8, etc.) → `"local"` (rejected)
- Public IPs/domains → `"clearnet"`

### Examples

```python
from models import Relay

# Create relay
relay = Relay("wss://relay.example.com")
print(relay.url)         # wss://relay.example.com
print(relay.network)     # clearnet
print(relay.host)        # relay.example.com
print(relay.port)        # None (default 443 for wss)

# Tor relay
tor_relay = Relay("wss://abcd1234.onion:9050/path")
print(tor_relay.network)  # tor
print(tor_relay.path)     # /path

# Database params
params = relay.to_db_params()
# ("relay.example.com", "clearnet", 1700000000)
```

---

## EventRelay - Event-Relay Junction

**Location**: `src/models/event_relay.py`

Immutable representation of an Event seen on a Relay.

### Constructor

```python
EventRelay(
    event: Union[Event, NostrEvent],
    relay: Relay,
    seen_at: Optional[int] = None
)
```

**Parameters**:
- `event`: nostr_sdk Event or models.Event
- `relay`: Relay instance
- `seen_at`: Unix timestamp (defaults to `int(time())`)

### Factory Method

```python
@classmethod
def from_nostr_event(
    cls,
    event: NostrEvent,
    relay: Relay,
    seen_at: Optional[int] = None
) -> EventRelay
```

### Attributes

```python
event: Union[Event, NostrEvent]
relay: Relay
seen_at: int
```

### Methods

```python
def to_db_params() -> tuple
```
Returns 11-tuple for `insert_event` procedure:
```
(event_id: bytes, pubkey: bytes, created_at: int, kind: int,
 tags: str (JSON), content: str, sig: bytes,
 relay_url: str, relay_network: str, relay_discovered_at: int,
 seen_at: int)
```

### Examples

```python
from models import EventRelay, Relay
from nostr_sdk import Event

# From nostr-sdk event
event = ... # nostr_sdk.Event from relay
relay = Relay("wss://relay.example.com")
event_relay = EventRelay.from_nostr_event(event, relay)

# Insert into database
inserted, skipped = await brotr.insert_events([event_relay])
```

---

## Metadata - Metadata Payload

**Location**: `src/models/metadata.py`

Immutable metadata payload for NIP-11 and NIP-66 data.

### Constructor

```python
Metadata(data: Optional[dict[str, Any]] = None)
```

### Attributes

```python
data: dict[str, Any]  # Raw metadata dictionary
```

### Type-Safe Helpers

```python
def _get(self, key: str, expected_type: Type[T], default: T) -> T
```
Get value with type checking. Returns default if wrong type.

```python
def _get_optional(self, key: str, expected_type: Type[T]) -> Optional[T]
```
Get optional value with type checking. Returns None if wrong type.

```python
def _get_nested(self, outer: str, key: str, expected_type: Type[T], default: T) -> T
```
Get nested value from dict within dict.

```python
def _get_nested_optional(self, outer: str, key: str, expected_type: Type[T]) -> Optional[T]
```
Get nested optional value.

### Properties

```python
@property
def data_jsonb() -> str
```
Sanitized JSON string for PostgreSQL JSONB storage.

### Examples

```python
from models import Metadata

# Create metadata
metadata = Metadata({
    "name": "Test Relay",
    "supported_nips": [1, 2, 9, 11],
    "limitation": {
        "max_message_length": 16384,
        "auth_required": False
    }
})

# Type-safe access
name = metadata._get("name", str, "Unknown")
nips = metadata._get("supported_nips", list, [])
auth = metadata._get_nested("limitation", "auth_required", bool, False)

# JSON for database
json_str = metadata.data_jsonb
```

---

## RelayMetadata - Metadata Junction

**Location**: `src/models/relay_metadata.py`

Immutable relay metadata junction record linking Relay to Metadata.

### Constructor

```python
RelayMetadata(
    relay: Relay,
    metadata: Metadata,
    metadata_type: MetadataType,
    snapshot_at: Optional[int] = None
)
```

**Metadata Types**:
```python
MetadataType = Literal[
    "nip11", "nip66_rtt", "nip66_probe", "nip66_ssl",
    "nip66_geo", "nip66_net", "nip66_dns", "nip66_http"
]
```

### Attributes

```python
relay: Relay
metadata: Metadata
metadata_type: MetadataType
snapshot_at: int
```

### Methods

```python
def to_db_params() -> tuple[str, str, int, int, str, str]
```
Returns 6-tuple for `insert_relay_metadata` procedure:
```
(relay_url, relay_network, relay_discovered_at,
 snapshot_at, metadata_type, metadata_data_jsonb)
```

### Examples

```python
from models import RelayMetadata, Relay, Metadata

relay = Relay("wss://relay.example.com")
metadata = Metadata({"name": "Test", "supported_nips": [1, 2]})

record = RelayMetadata(
    relay=relay,
    metadata=metadata,
    metadata_type="nip11",
    snapshot_at=1700000001
)

# Insert
await brotr.insert_relay_metadata([record])
```

---

## Nip11 - NIP-11 Relay Information

**Location**: `src/models/nip11.py`

Immutable NIP-11 relay information document with type-safe property access.

### Factory Method

```python
@classmethod
async def fetch(
    cls,
    relay: Relay,
    timeout: float = 30.0,
    proxy_url: Optional[str] = None
) -> Optional["Nip11"]
```

Fetches NIP-11 document from relay via HTTP.

**Parameters**:
- `relay`: Relay object
- `timeout`: Request timeout in seconds
- `proxy_url`: Optional SOCKS5 proxy URL for Tor/I2P

### Attributes

```python
relay: Relay
metadata: Metadata
snapshot_at: int
```

### Properties

**Base Fields**:
- `name`, `description`, `banner`, `icon`
- `pubkey`, `self_pubkey`, `contact`
- `software`, `version`
- `supported_nips: list[int]`
- `privacy_policy`, `terms_of_service`
- `tags: list[str]`, `language_tags: list[str]`

**Limitations** (from `limitation` object):
- `max_message_length`, `max_subscriptions`, `max_limit`
- `max_subid_length`, `max_event_tags`, `max_content_length`
- `min_pow_difficulty`
- `auth_required`, `payment_required`, `restricted_writes`
- `created_at_lower_limit`, `created_at_upper_limit`
- `default_limit`

**Retention**:
- `retention: list[dict]` - Retention policies

**Fees**:
- `payments_url`, `fees: dict`
- `admission_fees`, `subscription_fees`, `publication_fees`

### Methods

```python
def to_relay_metadata() -> RelayMetadata
```
Convert to RelayMetadata with `metadata_type="nip11"`.

### Examples

```python
from models import Nip11, Relay

relay = Relay("wss://relay.example.com")
nip11 = await Nip11.fetch(relay, timeout=30.0)

if nip11:
    print(nip11.name)
    print(nip11.supported_nips)
    print(nip11.auth_required)

    # Convert to database record
    metadata = nip11.to_relay_metadata()
    await brotr.insert_relay_metadata([metadata])
```

---

## Nip66 - NIP-66 Relay Monitoring

**Location**: `src/models/nip66.py`

Immutable NIP-66 relay monitoring data with connection tests and geolocation.

### Factory Method

```python
@classmethod
async def test(
    cls,
    relay: Relay,
    timeout: float = 30.0,
    keys: Optional[Keys] = None,
    city_db_path: Optional[str] = None,
    asn_db_path: Optional[str] = None
) -> "Nip66"
```

Test relay and collect monitoring data.

**Parameters**:
- `relay`: Relay to test
- `timeout`: Connection timeout
- `keys`: Optional Keys for write test
- `city_db_path`: Path to GeoLite2-City database
- `asn_db_path`: Optional path to GeoLite2-ASN database

### Attributes

```python
relay: Relay
rtt_metadata: Metadata       # RTT and network data (always present)
ssl_metadata: Optional[Metadata]  # SSL/TLS data (optional)
geo_metadata: Optional[Metadata]  # Geo data (optional)
snapshot_at: int
```

### Properties

**RTT (Round-Trip Time)**:
- `rtt_open: Optional[int]` - WebSocket connection RTT (ms)
- `rtt_read: Optional[int]` - REQ/EOSE subscription RTT (ms)
- `rtt_write: Optional[int]` - EVENT/OK publication RTT (ms)
- `rtt_dns: Optional[int]` - DNS resolution RTT (ms)

**Availability**:
- `is_openable: bool` - WebSocket connection succeeded
- `is_readable: bool` - Subscription succeeded
- `is_writable: bool` - Publication succeeded

**SSL/TLS** (clearnet only):
- `ssl_valid: Optional[bool]` - Certificate is valid
- `ssl_issuer: Optional[str]` - Certificate issuer
- `ssl_expires: Optional[int]` - Expiration timestamp
- `has_ssl: bool` - SSL metadata is present

**Geolocation** (clearnet only):
- `geohash: Optional[str]` - Geohash (precision 9)
- `geo_ip`, `geo_country`, `geo_region`, `geo_city`
- `geo_lat: Optional[float]`, `geo_lon: Optional[float]`
- `geo_tz`, `geo_asn`, `geo_asn_org`, `geo_isp`
- `has_geo: bool` - Geo metadata is present

**Classification**:
- `network: Optional[str]` - "clearnet", "tor", etc.

### Methods

```python
def to_relay_metadata() -> list[RelayMetadata]
```
Convert to list of RelayMetadata (up to 8 types):
1. `nip66_rtt` - RTT and basic connectivity data
2. `nip66_probe` - Detailed probe results
3. `nip66_ssl` - SSL/TLS certificate data (clearnet only)
4. `nip66_geo` - Geolocation data (clearnet only)
5. `nip66_net` - Network information
6. `nip66_dns` - DNS resolution data
7. `nip66_http` - HTTP header data

### Examples

```python
from nostr_sdk import Keys
from models import Nip66, Relay
from utils.keys import load_keys_from_env

relay = Relay("wss://relay.example.com")
keys = load_keys_from_env("PRIVATE_KEY")  # Optional, for write test

nip66 = await Nip66.test(
    relay,
    timeout=30.0,
    keys=keys,
    city_db_path="/usr/share/GeoIP/GeoLite2-City.mmdb"
)

print(f"Open: {nip66.is_openable}")
print(f"Read: {nip66.rtt_read}ms")
print(f"Write: {nip66.rtt_write}ms")
print(f"SSL: {nip66.ssl_valid}")
print(f"Location: {nip66.geo_city}, {nip66.geo_country}")
print(f"Geohash: {nip66.geohash}")

# Convert to database records
metadata_records = nip66.to_relay_metadata()
await brotr.insert_relay_metadata(metadata_records)
```

---

## Key Loading Utility

**Location**: `src/utils/keys.py`

Simple utility function for loading Nostr keys from environment variables.

### Function

```python
def load_keys_from_env(env_var: str) -> Keys | None
```

Load keys from environment variable.

**Parameters**:
- `env_var`: Environment variable name

**Returns**:
- nostr_sdk.Keys instance or None if not set

**Raises**:
- Exception: If key format is invalid

**Supported Formats**:
- Hex string (64 characters)
- nsec1... (Bech32)

### Examples

```python
from nostr_sdk import Keys
from utils.keys import load_keys_from_env

# Load from environment
keys = load_keys_from_env("PRIVATE_KEY")
keys = load_keys_from_env("CUSTOM_KEY")

if keys:
    pubkey = keys.public_key()
    print(pubkey.to_hex())
    print(pubkey.to_bech32())
else:
    print("No keys configured")

# Use nostr_sdk.Keys directly for other operations
keys = Keys.generate()  # Generate new keys
keys = Keys.parse("nsec1...")  # Parse from string
```

---

## Common Patterns

### Database Insertion

```python
from models import Relay, EventRelay, RelayMetadata, Nip11, Nip66

# Insert relays
relays = [Relay("wss://relay1.com"), Relay("wss://relay2.com")]
await brotr.insert_relays(relays)

# Insert events
event_relays = [EventRelay.from_nostr_event(evt, relay) for evt in events]
inserted, skipped = await brotr.insert_events(event_relays)

# Insert NIP-11 metadata
nip11 = await Nip11.fetch(relay)
if nip11:
    await brotr.insert_relay_metadata([nip11.to_relay_metadata()])

# Insert NIP-66 metadata
nip66 = await Nip66.test(relay)
await brotr.insert_relay_metadata(nip66.to_relay_metadata())
```

### Type-Safe Metadata Access

```python
# NIP-11
nip11 = await Nip11.fetch(relay)
name = nip11.name  # Optional[str]
nips = nip11.supported_nips  # list[int]
auth = nip11.auth_required  # Optional[bool]

# NIP-66
nip66 = await Nip66.test(relay)
if nip66.is_openable:
    print(f"RTT: {nip66.rtt_open}ms")
if nip66.has_geo:
    print(f"{nip66.geo_city}, {nip66.geo_country}")
```

### Immutability Enforcement

```python
relay = Relay("wss://relay.example.com")

# These all fail (frozen=True)
relay.network = "tor"  # AttributeError
relay.host = "other.com"  # AttributeError

# Create new instance instead
new_relay = Relay("wss://other.com")
```

### Error Handling

```python
# Invalid URLs raise ValueError
try:
    relay = Relay("http://not-a-websocket.com")
except ValueError as e:
    print(f"Invalid URL: {e}")

# Local addresses rejected
try:
    relay = Relay("wss://localhost")
except ValueError as e:
    print(f"Local address rejected: {e}")

# Invalid keys raise ValueError
try:
    keys = Keys.from_env()
except ValueError as e:
    print(f"Invalid key: {e}")
```
