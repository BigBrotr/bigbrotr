# Nostr Common Tags Reference

Tags are arrays in Nostr events that provide structured metadata. The first element is the tag name, followed by values.

## Core Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `e` | event id (hex) | relay URL, marker, pubkey (hex) | [01](../../resources/nips/01.md), [10](../../resources/nips/10.md) | Reference to another event |
| `p` | pubkey (hex) | relay URL, petname | [01](../../resources/nips/01.md), [02](../../resources/nips/02.md) | Reference to a user |
| `a` | coordinates | relay URL | [01](../../resources/nips/01.md) | Reference to addressable event |
| `d` | identifier | -- | [01](../../resources/nips/01.md) | Unique identifier for addressable events |
| `k` | kind | -- | [18](../../resources/nips/18.md), [25](../../resources/nips/25.md) | Event kind reference |

## Reply/Thread Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `e` | event id | "reply", "root", "mention" marker | [10](../../resources/nips/10.md) | Thread reference with marker |
| `E` | root event id | relay URL | [22](../../resources/nips/22.md) | Root event reference |
| `A` | root address | relay URL | [22](../../resources/nips/22.md) | Root addressable event |
| `P` | pubkey (hex) | -- | [22](../../resources/nips/22.md), [57](../../resources/nips/57.md) | Original author pubkey |
| `K` | root scope | -- | [22](../../resources/nips/22.md) | Root scope reference |
| `q` | event id (hex) | relay URL, pubkey (hex) | [18](../../resources/nips/18.md) | Quote repost reference |

## Content Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `t` | hashtag | -- | [24](../../resources/nips/24.md), [34](../../resources/nips/34.md) | Hashtag for categorization |
| `r` | reference (URL, etc) | -- | [24](../../resources/nips/24.md), [25](../../resources/nips/25.md) | External reference |
| `subject` | subject | -- | [14](../../resources/nips/14.md), [17](../../resources/nips/17.md) | Message subject line |
| `title` | title | -- | [23](../../resources/nips/23.md), [B0](../../resources/nips/B0.md) | Content title |
| `summary` | summary | -- | [23](../../resources/nips/23.md), [52](../../resources/nips/52.md) | Content summary |
| `alt` | summary | -- | [31](../../resources/nips/31.md) | Alt text for unknown events |
| `content-warning` | reason | -- | [36](../../resources/nips/36.md) | Content warning message |

## Media Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `image` | image URL | dimensions in pixels | [23](../../resources/nips/23.md), [52](../../resources/nips/52.md), [58](../../resources/nips/58.md) | Image attachment |
| `thumb` | badge thumbnail | dimensions in pixels | [58](../../resources/nips/58.md) | Thumbnail image |
| `m` | MIME type | -- | [94](../../resources/nips/94.md) | File MIME type |
| `imeta` | inline metadata | -- | [92](../../resources/nips/92.md) | Inline media metadata |

## Identity Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `i` | external identity | proof, url hint | [35](../../resources/nips/35.md), [39](../../resources/nips/39.md), [73](../../resources/nips/73.md) | External identity claim |
| `I` | root external identity | -- | [22](../../resources/nips/22.md) | Root identity reference |

## Relay Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `r` | relay url | marker (read/write) | [65](../../resources/nips/65.md) | Relay preference |
| `relay` | relay url | -- | [42](../../resources/nips/42.md), [17](../../resources/nips/17.md) | Relay URL |
| `relays` | relay list | -- | [57](../../resources/nips/57.md) | Multiple relays |

## Payment Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `amount` | millisatoshis (string) | -- | [57](../../resources/nips/57.md) | Payment amount |
| `bolt11` | bolt11 invoice | -- | [57](../../resources/nips/57.md) | Lightning invoice |
| `lnurl` | bech32 encoded lnurl | -- | [57](../../resources/nips/57.md) | LNURL for payment |
| `preimage` | hash of bolt11 | -- | [57](../../resources/nips/57.md) | Payment preimage |
| `zap` | pubkey, relay URL | weight | [57](../../resources/nips/57.md) | Zap split configuration |
| `goal` | event id (hex) | relay URL | [75](../../resources/nips/75.md) | Fundraising goal reference |
| `u` | url | -- | [61](../../resources/nips/61.md), [98](../../resources/nips/98.md) | URL reference |

## Marketplace Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `price` | price | currency, frequency | [99](../../resources/nips/99.md) | Item price |
| `location` | location string | -- | [52](../../resources/nips/52.md), [99](../../resources/nips/99.md) | Physical location |
| `f` | currency code | -- | [69](../../resources/nips/69.md) | Currency for trading |
| `s` | status | -- | [69](../../resources/nips/69.md) | Order status |
| `y` | platform | -- | [69](../../resources/nips/69.md) | Trading platform |
| `z` | order number | -- | [69](../../resources/nips/69.md) | Order identifier |

## Git Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `c` | commit id | -- | [34](../../resources/nips/34.md) | Git commit reference |
| `clone` | git clone URL | -- | [34](../../resources/nips/34.md) | Repository clone URL |
| `web` | webpage URL | -- | [34](../../resources/nips/34.md) | Web interface URL |
| `branch-name` | branch name | -- | [34](../../resources/nips/34.md) | Suggested branch name |
| `merge-base` | commit id | -- | [34](../../resources/nips/34.md) | Merge base commit |
| `HEAD` | ref: refs/heads/branch | -- | [34](../../resources/nips/34.md) | HEAD reference |

## Group Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `h` | group id | -- | [29](../../resources/nips/29.md) | Group identifier |
| `g` | geohash | -- | [52](../../resources/nips/52.md) | Geographic hash |

## Label Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `l` | label | label namespace, language | [32](../../resources/nips/32.md), [C0](../../resources/nips/C0.md) | Content label |
| `L` | label namespace | -- | [32](../../resources/nips/32.md) | Label namespace |

## Code Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `extension` | file extension | -- | [C0](../../resources/nips/C0.md) | Programming language extension |
| `license` | license | -- | [C0](../../resources/nips/C0.md) | Code license |
| `dep` | dependency | -- | [C0](../../resources/nips/C0.md) | Required dependency |
| `repo` | repository | -- | [C0](../../resources/nips/C0.md) | Source repository |
| `runtime` | runtime spec | -- | [C0](../../resources/nips/C0.md) | Runtime environment |

## Other Tags

| Tag | Value | Other Parameters | NIP | Description |
|-----|-------|------------------|-----|-------------|
| `name` | name | -- | [34](../../resources/nips/34.md), [58](../../resources/nips/58.md), [72](../../resources/nips/72.md) | Name/title |
| `description` | description | -- | [34](../../resources/nips/34.md), [57](../../resources/nips/57.md), [58](../../resources/nips/58.md) | Description text |
| `emoji` | shortcode, image URL | -- | [30](../../resources/nips/30.md) | Custom emoji definition |
| `sound` | shortcode, sound url, image url | -- | [51](../../resources/nips/51.md) | Custom sound |
| `nonce` | random | difficulty | [13](../../resources/nips/13.md) | Proof of work nonce |
| `expiration` | unix timestamp (string) | -- | [40](../../resources/nips/40.md) | Event expiration time |
| `delegation` | pubkey, conditions, token | -- | [26](../../resources/nips/26.md) | Delegation info |
| `challenge` | challenge string | -- | [42](../../resources/nips/42.md) | Auth challenge |
| `proxy` | external ID | protocol | [48](../../resources/nips/48.md) | Proxy/bridge reference |
| `client` | name, address | relay URL | [89](../../resources/nips/89.md) | Client application |
| `x` | hash | -- | [35](../../resources/nips/35.md), [56](../../resources/nips/56.md) | Content hash |
| `server` | file storage URL | -- | [96](../../resources/nips/96.md) | File server |
| `tracker` | torrent tracker URL | -- | [35](../../resources/nips/35.md) | BitTorrent tracker |
| `file` | full path | -- | [35](../../resources/nips/35.md) | File path in torrent |
| `published_at` | unix timestamp (string) | -- | [23](../../resources/nips/23.md), [B0](../../resources/nips/B0.md) | Publication timestamp |
| `encrypted` | -- | -- | [90](../../resources/nips/90.md) | Indicates encrypted content |
| `-` | -- | -- | [70](../../resources/nips/70.md) | Protected event marker |

## Tag Usage Patterns

### Thread References (NIP-10)

```json
["e", "<root-event-id>", "<relay>", "root"]
["e", "<reply-to-id>", "<relay>", "reply"]
["e", "<mentioned-id>", "<relay>", "mention"]
["p", "<author-pubkey>", "<relay>"]
```

### Addressable Event Reference

```json
["a", "<kind>:<pubkey>:<d-tag>", "<relay>"]
```

### Zap Split (NIP-57)

```json
["zap", "<pubkey1>", "<relay>", "1"]
["zap", "<pubkey2>", "<relay>", "1"]
```

### Relay List (NIP-65)

```json
["r", "wss://relay.example.com", "read"]
["r", "wss://relay2.example.com", "write"]
["r", "wss://relay3.example.com"]
```
