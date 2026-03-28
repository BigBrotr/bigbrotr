# nips — Protocol-Aware I/O

Implements Nostr Implementation Possibilities (NIPs) as "sensors" that probe relays and produce
typed `Metadata` records. Sits in the middle of the diamond DAG: depends on `models` and `utils`,
depended upon by `services`. Has real I/O (HTTP, WebSocket, DNS, SSL, GeoIP).

## Core Invariant

**Fetch methods never raise.** All transport errors are captured in `logs.success` / `logs.reason`.
Only `CancelledError`, `KeyboardInterrupt`, and `SystemExit` propagate.

## Shared Infrastructure

### `parsing.py` — Declarative Field Parsing

Defensively coerces untrusted external data (relay responses) without raising.

**`FieldSpec`** (frozen dataclass, slots): declares expected types per field name.

| Field | Parsed As |
|-------|-----------|
| `int_fields` | `int` (excludes `bool`) |
| `bool_fields` | `bool` |
| `str_fields` | `str` |
| `float_fields` | `float` (accepts `int`, converts) |
| `str_list_fields` | `list[str]` (filters invalid elements) |
| `int_list_fields` | `list[int]` (filters invalid elements) |

**`parse_fields(data, spec)`**: applies spec to raw dict, silently drops invalid values.

Internal: `_SKIP` sentinel, `_parse_int`/`_parse_bool`/`_parse_str`/`_parse_float`/`_parse_str_list`/`_parse_int_list`,
`_FIELD_PARSERS` tuple, `_build_dispatch` (LRU-cached, maxsize=8).

### `base.py` — Abstract Base Classes

All NIP models inherit from these bases (Pydantic frozen models unless noted).

| Class | Purpose |
|-------|---------|
| `BaseData` | Data model base. Has `_FIELD_SPEC: ClassVar[FieldSpec]`. Provides `parse()`, `from_dict()`, `to_dict()` |
| `BaseLogs` | Log base. `success: StrictBool`, `reason: str \| None`. Semantic validation: `success=False` requires reason, `success=True` requires `reason=None` |
| `BaseNipMetadata` | Container pairing `data` + `logs`. Provides `from_dict()`, `to_dict()` (delegates to nested objects) |
| `BaseNipSelection` | Boolean fields controlling which metadata types to retrieve (default `True`) |
| `BaseNipOptions` | Retrieval options. `allow_insecure: bool = False` (SSL fallback for clearnet) |
| `BaseNipDependencies` | External deps (keys, GeoIP readers). Uses `@dataclass(frozen=True, slots=True)` (holds arbitrary third-party objects that don't benefit from Pydantic validation) |
| `BaseNip` | Top-level NIP container. `relay: Relay`, `generated_at: StrictInt` (default `int(time())`). Abstract: `to_relay_metadata_tuple()`, `create(cls, relay, **kwargs)` |

### `event_builders.py` — Nostr Event Construction

Standalone functions for building Nostr events from typed NIP data (consumed by Monitor service).

**`AccessFlags`** (NamedTuple): `payment`, `auth`, `writes`, `read_auth` (all `bool`).

Constants: `_ISO_639_1_LENGTH=2`, `_NIP_CAP_SEARCH=50`, `_NIP_CAP_COMMUNITY=29`, `_NIP_CAP_BLOSSOM=95`.

| Function | Event Kind | Purpose |
|----------|-----------|---------|
| `build_profile_event()` | Kind 0 | Monitor profile per NIP-01 |
| `build_relay_list_event()` | Kind 10002 | Relay list per NIP-65 |
| `build_monitor_announcement()` | Kind 10166 | Announces enabled checks, networks, timeouts |
| `build_relay_discovery()` | Kind 30166 | Relay health tags (RTT, SSL, geo, net, DNS, HTTP, capabilities, attributes) |

**`build_relay_discovery(relay, nip11=None, nip66=None)`** accepts `Nip11` and `Nip66` container
objects, NOT individual data fields. DNS and HTTP data are extracted internally from `nip66.dns.data`
and `nip66.http.data` respectively. Signature:

```python
def build_relay_discovery(
    relay: Relay,
    nip11: Nip11 | None = None,
    nip66: Nip66 | None = None,
) -> EventBuilder:
```

**Tag builders** (called by `build_relay_discovery()` internally):

| Function | Tags emitted |
|----------|-------------|
| `add_rtt_tags(tags, rtt_data)` | `rtt-open`, `rtt-read`, `rtt-write` |
| `add_ssl_tags(tags, ssl_data)` | `ssl`, `ssl-expires`, `ssl-issuer` |
| `add_net_tags(tags, net_data)` | `net-ip`, `net-ipv6`, `net-asn`, `net-asn-org` + NIP-32 `l` labels (`IANA-asn`, `IANA-asnOrg`) |
| `add_geo_tags(tags, geo_data)` | `g`, `geo-country`, `geo-city`, `geo-lat`, `geo-lon`, `geo-tz` + NIP-32 `l` labels (`ISO-3166-1`, `nip66.label.city`, `IANA-tz`) |
| `add_dns_tags(tags, dns_data)` | `dns-ip` (first IPv4), `dns-ip6` (first IPv6), `dns-cname`, `dns-ttl` |
| `add_http_tags(tags, http_data)` | `http-server`, `http-powered-by` |
| `add_attributes_tags(tags, nip11_data)` | `W` tags from `attributes` field (PascalCase strings) |
| `add_language_tags(tags, nip11_data)` | ISO 639-1 `l` labels from `language_tags` |
| `add_requirement_and_type_tags(tags, nip11_data, rtt_logs)` | `R` tags (`auth`, `payment`, `writes`, `pow`) + delegates to `add_type_tags` |
| `add_type_tags(tags, supported_nips, access)` | `T` tags (`Search`, `Paid`, `PrivateStorage`, `PublicInbox`, `PublicOutbox`, `Community`, `Blob`, etc.) |
| `add_nip11_tags(tags, nip11_data, rtt_logs=None)` | Orchestrates `add_language_tags` + `add_requirement_and_type_tags` + `add_attributes_tags`, plus `N` and `t` (hashtag) tags |

## NIP-11 — Relay Information Document

Subpackage: `nip11/`. Produces `MetadataType.NIP11_INFO`.

### Data Models (`nip11/data.py`)

**`Nip11InfoData`** — complete relay info document with nested sub-objects:

| Nested Model | Purpose |
|-------------|---------|
| `Nip11InfoDataLimitation` | Server-imposed limits: `max_message_length`, `max_subscriptions`, `max_limit`, `max_subid_length`, `max_event_tags`, `max_content_length`, `min_pow_difficulty`, `auth_required`, `payment_required`, `restricted_writes`, `created_at_lower_limit`, `created_at_upper_limit`, `default_limit` (13 optional fields) |
| `Nip11InfoDataRetentionEntry` | Single retention policy (`kinds` as `list[int\|KindRange]\|None`, `time`, `count`). Overrides `parse()` for mixed int/tuple format |
| `Nip11InfoDataFeeEntry` | Single fee entry (`amount`, `unit`, `period`, `kinds`) |
| `Nip11InfoDataFees` | Fee schedule (`admission`, `subscription`, `publication` — lists of `FeeEntry`) |

`KindRange = tuple[StrictInt, StrictInt]`

Key fields on `Nip11InfoData`: `name`, `description`, `banner`, `icon`, `pubkey`, `self_pubkey` (alias=`"self"`),
`contact`, `software`, `version`, `privacy_policy`, `terms_of_service`, `posting_policy`, `payments_url`,
`supported_nips` (sorted/deduplicated), `limitation`, `retention`, `fees`, `relay_countries`,
`language_tags`, `tags`, `attributes` (`list[str] | None`, NIP-11 self-describing PascalCase attributes).
`ConfigDict: populate_by_name=True`. Property: `self` -> `self_pubkey`. `parse()` handles `supported_nips`
sort/dedup + `_parse_sub_objects()`.

### Log Models (`nip11/logs.py`)

**`Nip11InfoLogs`** — extends `BaseLogs`, no additional fields.

### Fetch Logic (`nip11/info.py`)

**`Nip11InfoMetadata`**: fetches NIP-11 document via HTTP GET.

- `_INFO_MAX_SIZE: ClassVar = 65_536` (64 KB).
- `_request` (static, async): single HTTP GET, validates status/content-type/size/json-dict.
- `_info` (static, async): wraps `_request` with session/proxy handling.
- `execute` (classmethod, async): converts ws->http URL, IPv6 brackets, SSL fallback for clearnet, always insecure for overlays.

### Top-Level (`nip11/nip11.py`)

**`Nip11Selection(BaseNipSelection)`**: `info: bool = True`.

**`Nip11Options(BaseNipOptions)`**: `max_size: int = _INFO_MAX_SIZE`.

**`Nip11Dependencies(@dataclass)`**: empty, for future extensibility.

**`RelayNip11MetadataTuple(NamedTuple)`**: `nip11_info: RelayMetadata | None`.

**`Nip11(BaseNip)`**: `info: Nip11InfoMetadata | None = None`. `create()` calls `execute()` if `selection.info=True`.
`to_relay_metadata_tuple()` returns `RelayNip11MetadataTuple(nip11_info=RelayMetadata | None)`.

## NIP-66 — Relay Health Testing

Subpackage: `nip66/`. Six parallel tests, each producing a distinct `MetadataType`.

### Data Models (`nip66/data.py`)

6 data models, all `BaseData` with `_FIELD_SPEC` ClassVars:

| Model | MetadataType | Key Fields |
|-------|-------------|------------|
| `Nip66RttData` | `NIP66_RTT` | `rtt_open`, `rtt_read`, `rtt_write` (ms). `None` = phase not reached |
| `Nip66SslData` | `NIP66_SSL` | `ssl_valid`, `ssl_subject_cn`, `ssl_issuer`, `ssl_issuer_cn`, `ssl_expires`, `ssl_not_before`, `ssl_san`, `ssl_serial`, `ssl_version`, `ssl_fingerprint`, `ssl_protocol`, `ssl_cipher`, `ssl_cipher_bits` (13 fields) |
| `Nip66GeoData` | `NIP66_GEO` | `geo_country`, `geo_country_name`, `geo_continent`, `geo_continent_name`, `geo_is_eu`, `geo_region`, `geo_city`, `geo_postal`, `geo_lat`, `geo_lon`, `geo_accuracy`, `geo_tz`, `geo_hash`, `geo_geoname_id` (14 fields) |
| `Nip66NetData` | `NIP66_NET` | `net_ip`, `net_ipv6`, `net_asn`, `net_asn_org`, `net_network`, `net_network_v6` (6 fields) |
| `Nip66DnsData` | `NIP66_DNS` | `dns_ips`, `dns_ips_v6`, `dns_cname`, `dns_reverse`, `dns_ns`, `dns_ttl` (6 fields) |
| `Nip66HttpData` | `NIP66_HTTP` | `http_server`, `http_powered_by` (2 fields) |

### Log Models (`nip66/logs.py`)

- **`Nip66RttMultiPhaseLogs`** (BaseModel, frozen) — custom multi-phase structure (NOT `BaseLogs`).
  6 fields: `open_success`, `open_reason`, `read_success`, `read_reason`, `write_success`, `write_reason`.
  Cascading validation: if open fails, read and write must also fail.
- **`Nip66BaseLogs`**, **`Nip66SslLogs`**, **`Nip66GeoLogs`**, **`Nip66NetLogs`**, **`Nip66DnsLogs`**, **`Nip66HttpLogs`** — all
  extend `BaseLogs` (single `success`/`reason` pair), no additional fields.

### Test Implementations

#### `rtt.py` — Round-Trip Time (clearnet + overlay with proxy)

**`Nip66RttDependencies(NamedTuple)`**: `keys`, `event_builder`, `read_filter`.

**`Nip66RttMetadata(BaseNipMetadata)`**: `data: Nip66RttData`, `logs: Nip66RttMultiPhaseLogs`.

Three sequential phases:
1. **Open** (`_test_open`) — WebSocket connection via `connect_relay()`, measure latency
2. **Read** (`_test_read`) — stream events matching filter, measure time to first match
3. **Write** (`_test_write`) — publish event, verify storage via re-fetch (`_verify_write`), cleanup (`_cleanup`)

`execute`: 3 sequential phases with cascading failure (open fail -> read/write skip).
Overlay without proxy -> immediate cascading failure.

#### `ssl.py` — SSL/TLS Certificate (clearnet only)

**`CertificateExtractor`**: `extract_fingerprint` (SHA-256), `extract_all_from_x509` (subject CN, issuer, expiry, SANs, serial, version).

**`Nip66SslMetadata(BaseNipMetadata)`**: two-connection methodology:
1. **Extract** (`_extract_certificate_data`) with `CERT_NONE` (reads cert regardless of chain validity)
2. **Validate** (`_validate_certificate`) with default SSL context (verifies chain against trust store)

Runs sync SSL ops in thread pool via `asyncio.to_thread()`.

#### `geo.py` — Geolocation (clearnet only)

**`GeoExtractor`**: `extract_country`, `extract_administrative`, `extract_location` (lat/lon/geohash precision 9), `extract_all`.

**`Nip66GeoMetadata(BaseNipMetadata)`**: resolves hostname -> IP (prefers IPv4), queries GeoIP City database.
Runs in thread pool. Accepts `timeout: float | None` (default `DEFAULT_TIMEOUT`), wraps
`resolve_host()` and `asyncio.to_thread()` in `asyncio.wait_for()`.

#### `net.py` — Network/ASN (clearnet only)

**`Nip66NetMetadata(BaseNipMetadata)`**: resolves IPv4 + IPv6, queries GeoIP ASN database. IPv4 ASN takes priority; IPv6 as fallback.
Runs in thread pool. Accepts `timeout: float | None` (default `DEFAULT_TIMEOUT`), wraps
`resolve_host()` and `asyncio.to_thread()` in `asyncio.wait_for()`.

#### `dns.py` — DNS Resolution (clearnet only)

**`Nip66DnsMetadata(BaseNipMetadata)`**: comprehensive queries: A, AAAA, CNAME, NS (via `tldextract` for registered domain), PTR (reverse).
Individual record failures don't prevent others. Runs in thread pool via `dnspython`.

#### `http.py` — HTTP Headers (clearnet + overlay)

**`Nip66HttpMetadata(BaseNipMetadata)`**: captures `Server` and `X-Powered-By` from WebSocket upgrade handshake via aiohttp trace hooks.
Only NIP-66 test supporting overlay networks (with proxy).

### Top-Level (`nip66/nip66.py`)

**`Nip66Selection(BaseNipSelection)`**: `rtt`, `ssl`, `geo`, `net`, `dns`, `http`: `bool = True` (all enabled by default).

**`Nip66Options(BaseNipOptions)`**: inherits `allow_insecure` only.

**`Nip66Dependencies(@dataclass)`**: `keys` (default_factory=`Keys.generate`), `event_builder`, `read_filter`, `city_reader`, `asn_reader`.
Tests silently skipped when deps are `None`.

**`RelayNip66MetadataTuple(NamedTuple)`**: `rtt`, `ssl`, `geo`, `net`, `dns`, `http` (all `RelayMetadata | None`).

**`Nip66(BaseNip)`**: `rtt`, `ssl`, `geo`, `net`, `dns`, `http` (all metadata `| None`). `create()` runs all enabled tests
concurrently via `asyncio.gather(return_exceptions=True)`. `to_relay_metadata_tuple()` returns
`RelayNip66MetadataTuple(rtt, ssl, geo, net, dns, http)`.

## Network Awareness

| Test | Clearnet | Overlay (with proxy) | Overlay (no proxy) |
|------|----------|---------------------|-------------------|
| NIP-11 Info | HTTPS (verified, insecure fallback) | HTTP via proxy | HTTP via proxy |
| RTT | WebSocket | WebSocket via proxy | Immediate failure |
| SSL | Two-connection extraction + validation | Rejected | Rejected |
| GEO | GeoIP lookup on resolved IP | Rejected | Rejected |
| NET | ASN lookup on resolved IPs | Rejected | Rejected |
| DNS | Full resolution (A/AAAA/CNAME/NS/PTR) | Rejected | Rejected |
| HTTP | WebSocket upgrade headers | Via proxy (insecure SSL) | Immediate failure |

## Internal Dependency Graph

```
parsing.py <- base.py, nip11/data.py, nip66/data.py
base.py <- all NIP models inherit from it
event_builders.py <- imports nip11/data, nip66/data, nip66/logs (consumed by Monitor)

nip11/data.py, nip11/logs.py, nip11/info.py <- nip11/nip11.py
nip66/data.py, nip66/logs.py, nip66/{rtt,ssl,geo,net,dns,http}.py <- nip66/nip66.py
```

Cross-package imports: `bigbrotr.models` (Relay, Metadata, MetadataType, RelayMetadata, NetworkType),
`bigbrotr.utils` (resolve_host, connect_relay, DEFAULT_TIMEOUT, InsecureWebSocketTransport).

## External Dependencies

| Package | Used By | Purpose |
|---------|---------|---------|
| `aiohttp` | nip11/info, nip66/http | HTTP client, WebSocket, trace hooks |
| `aiohttp_socks` | nip66/http, nip66/rtt | SOCKS5 proxy for overlay networks |
| `nostr_sdk` | nip66/rtt, event_builders | Nostr protocol types (Client, Filter, Keys, EventBuilder) |
| `pydantic` | all models | Validation and serialization |
| `cryptography` | nip66/ssl | X.509 certificate parsing |
| `geoip2` | nip66/geo, nip66/net | GeoIP City and ASN database readers |
| `geohash2` | nip66/geo | Geohash encoding (precision 9) |
| `dnspython` | nip66/dns | Comprehensive DNS resolution |
| `tldextract` | nip66/dns | Public suffix extraction for NS queries |
