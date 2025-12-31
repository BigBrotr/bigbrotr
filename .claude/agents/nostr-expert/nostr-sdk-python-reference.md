# Nostr SDK Python Reference

The `nostr-sdk` Python package provides high-level bindings to the rust-nostr library for building Nostr clients and bots.

**Installation:**
```bash
pip install nostr-sdk
```

**Requirements:** Python >= 3.9

**Status:** ALPHA - API may change in breaking ways

**Source code:** `../../resources/nostr/`

## Quick Start

```python
import asyncio
from nostr_sdk import Keys, Client, EventBuilder, Filter, Kind

async def main():
    # Generate new keys
    keys = Keys.generate()
    print(f"Public key: {keys.public_key().to_bech32()}")
    print(f"Secret key: {keys.secret_key().to_bech32()}")

    # Create client with signer
    client = Client(keys)

    # Add relays
    await client.add_relay("wss://relay.damus.io")
    await client.add_relay("wss://nos.lol")

    # Connect
    await client.connect()

    # Publish a text note
    builder = EventBuilder.text_note("Hello from Python!")
    output = await client.send_event_builder(builder)
    print(f"Published event: {output.id().to_bech32()}")

asyncio.run(main())
```

## Keys

### Generating Keys

```python
from nostr_sdk import Keys

# Generate random keys
keys = Keys.generate()

# Get public key
public_key = keys.public_key()
print(public_key.to_hex())      # Hex format
print(public_key.to_bech32())   # npub format

# Get secret key
secret_key = keys.secret_key()
print(secret_key.to_hex())      # Hex format
print(secret_key.to_bech32())   # nsec format
```

### Parsing Keys

```python
from nostr_sdk import Keys, PublicKey, SecretKey

# Parse from bech32 (nsec)
keys = Keys.parse("nsec1...")

# Parse from hex
keys = Keys.parse("hex-secret-key...")

# Parse public key only
pubkey = PublicKey.parse("npub1...")
pubkey = PublicKey.from_hex("hex-pubkey...")
pubkey = PublicKey.from_bech32("npub1...")

# Parse secret key only
secret = SecretKey.parse("nsec1...")
secret = SecretKey.from_hex("hex-secret...")
secret = SecretKey.from_bech32("nsec1...")
```

### Key Derivation from Mnemonic (NIP-06)

```python
from nostr_sdk import Keys

# Generate keys from mnemonic
mnemonic = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about"
keys = Keys.from_mnemonic(mnemonic)

# With passphrase
keys = Keys.from_mnemonic(mnemonic, passphrase="optional-passphrase")
```

## Client

### Creating a Client

```python
from nostr_sdk import Client, Keys, ClientOptions, Connection

# Simple client with keys
keys = Keys.generate()
client = Client(keys)

# Client without signer (read-only)
client = Client()

# Client with options
opts = ClientOptions()
client = Client.with_opts(keys, opts)

# Client with builder pattern
client = Client.builder().signer(keys).build()
```

### Managing Relays

```python
from nostr_sdk import Client, RelayOptions

# Add relay
await client.add_relay("wss://relay.damus.io")

# Add relay with options
opts = RelayOptions()
await client.add_relay_with_opts("wss://relay.example.com", opts)

# Add read-only relay
await client.add_read_relay("wss://relay.nostr.info")

# Add write-only relay
await client.add_write_relay("wss://relay.example.com")

# Connect to all relays
await client.connect()

# Disconnect
await client.disconnect()

# Get relay list
relays = await client.relays()

# Remove relay
await client.remove_relay("wss://relay.damus.io")
```

## Events

### EventBuilder

The `EventBuilder` class provides static methods to create various event types.

#### Text Notes (Kind 1)

```python
from nostr_sdk import EventBuilder, Tag

# Simple text note
builder = EventBuilder.text_note("Hello Nostr!")

# With hashtags
builder = EventBuilder.text_note("Hello #nostr #python").tag(
    Tag.hashtag("nostr")
).tag(
    Tag.hashtag("python")
)

# With mentions
builder = EventBuilder.text_note("Hello @npub1...").tag(
    Tag.public_key(pubkey)
)

# Reply to another event
builder = EventBuilder.text_note_reply(
    content="This is a reply",
    reply_to=parent_event,
    root=root_event,  # Optional
    relay_url=None    # Optional
)

# With Proof of Work
builder = EventBuilder.text_note("POW note").pow(20)
```

#### Profile Metadata (Kind 0)

```python
from nostr_sdk import EventBuilder, Metadata
from urllib.parse import urlparse

metadata = Metadata() \
    .set_name("username") \
    .set_display_name("Display Name") \
    .set_about("Bio description") \
    .set_picture("https://example.com/avatar.png") \
    .set_banner("https://example.com/banner.png") \
    .set_nip05("user@example.com") \
    .set_lud16("user@walletofsatoshi.com")

builder = EventBuilder.metadata(metadata)
```

#### Contact List (Kind 3)

```python
from nostr_sdk import EventBuilder, Contact, PublicKey

contacts = [
    Contact(
        public_key=PublicKey.parse("npub1..."),
        relay_url="wss://relay.damus.io",
        alias="alice"
    ),
    Contact(
        public_key=PublicKey.parse("npub2..."),
        relay_url=None,
        alias="bob"
    )
]

builder = EventBuilder.contact_list(contacts)
```

#### Reactions (Kind 7)

```python
from nostr_sdk import EventBuilder

# Like (upvote)
builder = EventBuilder.reaction(event, "+")

# Dislike (downvote)
builder = EventBuilder.reaction(event, "-")

# Custom emoji
builder = EventBuilder.reaction(event, "🚀")
```

#### Reposts (Kind 6, 16)

```python
from nostr_sdk import EventBuilder

# Repost text note (kind 6)
builder = EventBuilder.repost(event, relay_url=None)

# Generic repost (kind 16) - for non-text events
builder = EventBuilder.repost(non_text_event, relay_url=None)
```

#### Long-form Content (Kind 30023)

```python
from nostr_sdk import EventBuilder, Tag, TagStandard, Timestamp

builder = EventBuilder.long_form_text_note(
    "# My Article\n\nThis is the content..."
).tag(
    Tag.identifier("my-article-slug")
).tag(
    Tag.parse(["title", "My Article Title"])
).tag(
    Tag.parse(["summary", "A brief summary"])
).tag(
    Tag.parse(["published_at", str(Timestamp.now())])
)
```

#### Delete Events (Kind 5)

```python
from nostr_sdk import EventBuilder, EventId, EventDeletionRequest

# Delete by event IDs
request = EventDeletionRequest([event_id1, event_id2], reason="spam")
builder = EventBuilder.delete(request)
```

#### Channel Messages (Kind 40-44)

```python
from nostr_sdk import EventBuilder, Metadata

# Create channel (kind 40)
metadata = Metadata().set_name("My Channel").set_about("Description")
builder = EventBuilder.channel(metadata)

# Channel message (kind 42)
builder = EventBuilder.channel_msg(
    channel_id=channel_event_id,
    relay_url="wss://relay.damus.io",
    content="Hello channel!"
)
```

#### Relay List (Kind 10002)

```python
from nostr_sdk import EventBuilder, RelayMetadata

relays = [
    ("wss://relay.damus.io", RelayMetadata.READ),
    ("wss://nos.lol", RelayMetadata.WRITE),
    ("wss://relay.nostr.info", None),  # Both read/write
]

builder = EventBuilder.relay_list(relays)
```

### Signing and Publishing Events

```python
from nostr_sdk import Client, EventBuilder

# Method 1: Build and sign with client
builder = EventBuilder.text_note("Hello!")
output = await client.send_event_builder(builder)

print(f"Event ID: {output.id().to_bech32()}")
print(f"Sent to: {output.success}")
print(f"Failed: {output.failed}")

# Method 2: Send to specific relays
output = await client.send_event_builder_to(
    ["wss://relay.damus.io", "wss://nos.lol"],
    builder
)

# Method 3: Build unsigned, then sign manually
unsigned = builder.build(keys.public_key())
event = await unsigned.sign(keys)
output = await client.send_event(event)
```

## Filters and Subscriptions

### Creating Filters

```python
from nostr_sdk import Filter, Kind, PublicKey, Timestamp
from datetime import timedelta

# Filter by author
filter = Filter().author(public_key)

# Filter by multiple authors
filter = Filter().authors([pubkey1, pubkey2])

# Filter by kind
filter = Filter().kind(Kind(1))  # Text notes
filter = Filter().kinds([Kind(0), Kind(1), Kind(3)])

# Filter by event ID
filter = Filter().id(event_id)
filter = Filter().ids([id1, id2])

# Filter by tags
filter = Filter().pubkey(mentioned_pubkey)  # p tag
filter = Filter().event(referenced_event_id)  # e tag
filter = Filter().hashtag("nostr")  # t tag

# Time range
filter = Filter().since(Timestamp.now() - timedelta(hours=24))
filter = Filter().until(Timestamp.now())

# Limit results
filter = Filter().limit(100)

# Combine filters
filter = Filter() \
    .author(pubkey) \
    .kind(Kind(1)) \
    .since(Timestamp.now() - timedelta(days=7)) \
    .limit(50)

# Search (NIP-50)
filter = Filter().search("hello nostr")
```

### Fetching Events

```python
from nostr_sdk import Client, Filter, Kind
from datetime import timedelta

# Fetch events matching filter
filter = Filter().kind(Kind(1)).limit(10)
events = await client.fetch_events(filter, timeout=timedelta(seconds=10))

for event in events:
    print(f"ID: {event.id().to_bech32()}")
    print(f"Author: {event.pubkey().to_bech32()}")
    print(f"Content: {event.content()}")
    print(f"Created at: {event.created_at()}")

# Fetch from specific relays
events = await client.fetch_events_from(
    ["wss://relay.damus.io"],
    filter,
    timeout=timedelta(seconds=10)
)
```

### Subscriptions

```python
from nostr_sdk import Client, Filter, Kind, RelayPoolNotification

# Subscribe to events
filter = Filter().kind(Kind(1)).since(Timestamp.now())
sub_output = await client.subscribe(filter, opts=None)
sub_id = sub_output.val

# Handle notifications
async def handle_notification(notification):
    if isinstance(notification, RelayPoolNotification.Event):
        event = notification.event
        print(f"New event: {event.content()}")
        return False  # Return True to stop
    return False

await client.handle_notifications(handle_notification)

# Unsubscribe
await client.unsubscribe(sub_id)
```

### Streaming Events

```python
from nostr_sdk import Client, Filter, Kind

# Stream events as they arrive
filter = Filter().kind(Kind(1)).limit(0)  # limit=0 for new events only

async for event in client.stream_events(filter):
    print(f"New event: {event.content()}")
```

## Private Messages

### NIP-17 (Recommended)

```python
from nostr_sdk import Client, PublicKey

# Send private message (NIP-17 gift wrap)
receiver = PublicKey.parse("npub1...")
output = await client.send_private_msg(
    receiver=receiver,
    message="Hello, this is private!",
    reply_to=None  # Optional: event ID to reply to
)

# Receive private messages
filter = Filter() \
    .pubkey(keys.public_key()) \
    .kind(Kind(1059))  # Gift wrap

await client.subscribe(filter, None)

async def handle_dm(notification):
    if isinstance(notification, RelayPoolNotification.Event):
        event = notification.event
        if event.kind() == Kind(1059):
            # Unwrap gift wrap
            unwrapped = await client.unwrap_gift_wrap(event)
            print(f"From: {unwrapped.sender.to_bech32()}")
            print(f"Message: {unwrapped.rumor.content()}")
    return False

await client.handle_notifications(handle_dm)
```

### NIP-04 (Deprecated)

```python
from nostr_sdk import nip04, Keys

# Encrypt
encrypted = nip04.encrypt(
    sender_secret_key,
    receiver_public_key,
    "plaintext message"
)

# Decrypt
decrypted = nip04.decrypt(
    receiver_secret_key,
    sender_public_key,
    encrypted
)
```

## NIP-05 Verification

```python
from nostr_sdk import nip05

# Verify NIP-05 identifier
result = await nip05.verify(
    public_key=pubkey,
    nip05="user@example.com"
)

if result:
    print("NIP-05 verified!")
else:
    print("NIP-05 verification failed")

# Get profile from NIP-05
profile = await nip05.profile("user@example.com")
if profile:
    print(f"Public key: {profile.public_key().to_bech32()}")
    print(f"Relays: {profile.relays()}")
```

## Zaps (NIP-57)

```python
from nostr_sdk import Client, PublicKey, ZapEntity, ZapType

# Create zap request
receiver = PublicKey.parse("npub1...")
zap_entity = ZapEntity.public_key(receiver)

# Get zap invoice
details = await client.zap(
    zap_entity,
    msats=1000,  # 1 sat
    details=None
)

print(f"Invoice: {details.invoice}")
```

## Nostr Wallet Connect (NIP-47)

```python
from nostr_sdk import NostrWalletConnectUri, Nwc

# Parse NWC URI
uri = NostrWalletConnectUri.parse("nostr+walletconnect://...")

# Create NWC client
nwc = Nwc(uri)

# Get balance
balance = await nwc.get_balance()
print(f"Balance: {balance} msats")

# Pay invoice
result = await nwc.pay_invoice("lnbc...")
print(f"Payment preimage: {result.preimage}")

# Create invoice
invoice = await nwc.make_invoice(
    amount=1000,  # msats
    description="Test invoice"
)
print(f"Invoice: {invoice.invoice}")
```

## Nostr Connect (NIP-46)

```python
from nostr_sdk import Client, NostrConnect, NostrConnectUri, Keys
from datetime import timedelta

# App keys (your app's keypair)
app_keys = Keys.generate()

# Parse bunker URI from signer
uri = NostrConnectUri.parse("bunker://...")

# Create signer
signer = NostrConnect(
    uri=uri,
    app_keys=app_keys,
    timeout=timedelta(seconds=120),
    opts=None
)

# Use with client
client = Client(signer)
await client.add_relay("wss://relay.damus.io")
await client.connect()

# Now all signing happens via the remote signer
builder = EventBuilder.text_note("Signed remotely!")
await client.send_event_builder(builder)

# Get bunker URI for reconnection
bunker_uri = await signer.bunker_uri()
print(f"Save this: {bunker_uri}")
```

## Tags

### Creating Tags

```python
from nostr_sdk import Tag, PublicKey, EventId, Coordinate, Kind

# Public key tag
tag = Tag.public_key(pubkey)  # ["p", "<pubkey>"]

# Event reference
tag = Tag.event(event_id)  # ["e", "<event_id>"]

# Hashtag
tag = Tag.hashtag("nostr")  # ["t", "nostr"]

# Identifier (for addressable events)
tag = Tag.identifier("my-slug")  # ["d", "my-slug"]

# Relay
tag = Tag.relay("wss://relay.damus.io")  # ["r", "wss://..."]

# Custom tag
tag = Tag.parse(["custom", "value1", "value2"])

# Coordinate (addressable event reference)
coord = Coordinate(
    kind=Kind(30023),
    public_key=pubkey,
    identifier="my-article"
)
tag = Tag.coordinate(coord)
```

### Reading Tags from Events

```python
# Get all tags
tags = event.tags()

for tag in tags:
    tag_kind = tag.kind()
    values = tag.content()
    print(f"{tag_kind}: {values}")

# Find specific tag
p_tag = event.tags().find(TagKind.p())
if p_tag:
    pubkey_hex = p_tag.content()
```

## Timestamps

```python
from nostr_sdk import Timestamp
from datetime import datetime, timedelta

# Current timestamp
now = Timestamp.now()

# From Unix timestamp (seconds)
ts = Timestamp.from_secs(1234567890)

# Convert to datetime
dt = now.to_datetime()

# Arithmetic
one_day_ago = Timestamp.now() - timedelta(days=1)
one_week_later = Timestamp.now() + timedelta(weeks=1)
```

## Event IDs and Coordinates

```python
from nostr_sdk import EventId, Coordinate, Kind

# Parse event ID
event_id = EventId.parse("note1...")  # bech32
event_id = EventId.from_hex("...")    # hex

# Convert
print(event_id.to_bech32())  # note1...
print(event_id.to_hex())     # hex

# Coordinates (for addressable events)
coord = Coordinate(
    kind=Kind(30023),
    public_key=pubkey,
    identifier="article-slug",
    relays=["wss://relay.damus.io"]
)

# Parse coordinate
coord = Coordinate.parse("30023:pubkey:identifier")
print(coord.to_bech32())  # naddr1...
```

## Logging

```python
from nostr_sdk import init_logger, LogLevel

# Initialize logging
init_logger(LogLevel.DEBUG)

# Log levels: TRACE, DEBUG, INFO, WARN, ERROR
```

## Error Handling

```python
from nostr_sdk import NostrSdkError

try:
    keys = Keys.parse("invalid-key")
except Exception as e:
    print(f"Error: {e}")

try:
    await client.send_event_builder(builder)
except Exception as e:
    print(f"Failed to publish: {e}")
```

## Common Patterns

### Bot Example

```python
import asyncio
from nostr_sdk import Keys, Client, EventBuilder, Filter, Kind, RelayPoolNotification

async def bot():
    keys = Keys.parse("nsec1...")  # Your bot's secret key
    client = Client(keys)

    await client.add_relay("wss://relay.damus.io")
    await client.connect()

    # Set bot profile
    metadata = Metadata() \
        .set_name("MyBot") \
        .set_about("A helpful Nostr bot")
    await client.set_metadata(metadata)

    # Subscribe to mentions
    filter = Filter() \
        .pubkey(keys.public_key()) \
        .kind(Kind(1)) \
        .limit(0)

    await client.subscribe(filter, None)

    async def handle(notification):
        if isinstance(notification, RelayPoolNotification.Event):
            event = notification.event
            content = event.content()

            if "/help" in content:
                reply = EventBuilder.text_note_reply(
                    "Available commands: /help, /ping",
                    reply_to=event,
                    root=None,
                    relay_url=None
                )
                await client.send_event_builder(reply)

        return False

    await client.handle_notifications(handle)

asyncio.run(bot())
```

### Aggregating Events from Multiple Relays

```python
from nostr_sdk import Client, Filter, Kind
from datetime import timedelta

async def fetch_user_notes(pubkey):
    client = Client()

    # Add multiple relays
    relays = [
        "wss://relay.damus.io",
        "wss://nos.lol",
        "wss://relay.nostr.info",
        "wss://nostr.wine"
    ]

    for relay in relays:
        await client.add_relay(relay)

    await client.connect()

    # Fetch from all relays
    filter = Filter() \
        .author(pubkey) \
        .kind(Kind(1)) \
        .limit(100)

    events = await client.fetch_events(filter, timedelta(seconds=15))

    # Events are automatically deduplicated
    return events
```

### Whitelist/Blacklist Relays

```python
from nostr_sdk import Client, PublicKey, RelayFiltering, RelayFilteringMode

# Whitelist mode - only interact with specific pubkeys
filtering = RelayFiltering(RelayFilteringMode.WHITELIST)
filtering.add_public_key(allowed_pubkey1)
filtering.add_public_key(allowed_pubkey2)

client = Client.builder() \
    .signer(keys) \
    .filtering(filtering) \
    .build()

# Blacklist mode - ignore specific pubkeys
filtering = RelayFiltering(RelayFilteringMode.BLACKLIST)
filtering.add_public_key(blocked_pubkey)
```

## Supported NIPs

The Python SDK supports the same NIPs as rust-nostr:

| NIP | Feature | Description |
|-----|---------|-------------|
| 01 | Core | Basic protocol |
| 02 | Core | Follow List |
| 04 | Optional | Encrypted DMs (deprecated, use NIP-17) |
| 05 | Core | DNS identifiers |
| 06 | Optional | Key derivation from mnemonic |
| 09 | Core | Event deletion |
| 10 | Core | Reply conventions |
| 11 | Core | Relay info |
| 13 | Core | Proof of Work |
| 17 | Core | Private DMs (Gift Wrap) |
| 19 | Core | bech32 encoding |
| 21 | Core | URI scheme |
| 25 | Core | Reactions |
| 42 | Core | Auth |
| 44 | Optional | Encrypted payloads |
| 46 | Optional | Nostr Connect |
| 47 | Optional | Wallet Connect |
| 57 | Optional | Zaps |
| 59 | Optional | Gift Wrap |
| 65 | Core | Relay List |

Enable optional features by installing with extras or using specific modules.

## Resources

- **Documentation:** https://rust-nostr.org
- **PyPI:** https://pypi.org/project/nostr-sdk/
- **GitHub:** https://github.com/rust-nostr/nostr
- **Rust examples:** `../../resources/nostr/crates/nostr-sdk/examples/`
