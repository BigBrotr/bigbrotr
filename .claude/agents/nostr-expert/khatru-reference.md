# Khatru Framework Reference

Khatru is a Go framework for building custom Nostr relays. It provides a flexible, hook-based architecture that allows developers to implement custom event handling, storage, policies, and authentication.

**Source code:** `../../resources/khatru/`

## Quick Start

```go
package main

import (
    "net/http"
    "github.com/fiatjaf/khatru"
    "github.com/fiatjaf/eventstore/badger"
)

func main() {
    relay := khatru.NewRelay()

    // Configure NIP-11 info
    relay.Info.Name = "my relay"
    relay.Info.Description = "this is my custom relay"

    // Set up storage
    db := badger.BadgerBackend{Path: "/tmp/khatru-badger"}
    db.Init()

    relay.StoreEvent = append(relay.StoreEvent, db.SaveEvent)
    relay.QueryEvents = append(relay.QueryEvents, db.QueryEvents)
    relay.DeleteEvent = append(relay.DeleteEvent, db.DeleteEvent)
    relay.ReplaceEvent = append(relay.ReplaceEvent, db.ReplaceEvent)

    http.ListenAndServe(":3334", relay)
}
```

## Core Concepts

### The Relay Struct

The `Relay` struct is the heart of khatru. It implements `http.Handler` and manages WebSocket connections, event processing, and client subscriptions.

Key fields:
- `Info` - NIP-11 relay information document
- `ServiceURL` - Base URL of the relay
- `Negentropy` - Enable NIP-77 negentropy syncing
- `ManagementAPI` - NIP-86 management handlers

### Hook System

Khatru uses a hook-based architecture where you append functions to slices. Each hook is called in order, allowing multiple handlers for the same operation.

#### Event Lifecycle Hooks

| Hook | Signature | Purpose |
|------|-----------|---------|
| `RejectEvent` | `func(ctx, *Event) (bool, string)` | Validate/reject incoming events |
| `StoreEvent` | `func(ctx, *Event) error` | Persist regular events |
| `ReplaceEvent` | `func(ctx, *Event) error` | Handle replaceable events |
| `DeleteEvent` | `func(ctx, *Event) error` | Handle event deletions |
| `OnEventSaved` | `func(ctx, *Event)` | Post-save callback |
| `OnEphemeralEvent` | `func(ctx, *Event)` | Handle ephemeral events |
| `OverwriteDeletionOutcome` | `func(ctx, target, deletion) (bool, string)` | Custom deletion logic |

#### Query Hooks

| Hook | Signature | Purpose |
|------|-----------|---------|
| `RejectFilter` | `func(ctx, Filter) (bool, string)` | Validate/reject queries |
| `OverwriteFilter` | `func(ctx, *Filter)` | Modify incoming filters |
| `QueryEvents` | `func(ctx, Filter) (chan *Event, error)` | Execute queries |
| `CountEvents` | `func(ctx, Filter) (int64, error)` | NIP-45 count queries |
| `OverwriteResponseEvent` | `func(ctx, *Event)` | Modify events before sending |

#### Connection Hooks

| Hook | Signature | Purpose |
|------|-----------|---------|
| `RejectConnection` | `func(*http.Request) bool` | Reject WebSocket connections |
| `OnConnect` | `func(ctx)` | Client connected callback |
| `OnDisconnect` | `func(ctx)` | Client disconnected callback |

#### Broadcast Hooks

| Hook | Signature | Purpose |
|------|-----------|---------|
| `PreventBroadcast` | `func(*WebSocket, *Event) bool` | Prevent event broadcast to specific clients |

## NIP-42 Authentication

Khatru has built-in NIP-42 support:

```go
// Request auth on connect
relay.OnConnect = append(relay.OnConnect, func(ctx context.Context) {
    khatru.RequestAuth(ctx)
})

// Check auth status
relay.RejectFilter = append(relay.RejectFilter, func(ctx context.Context, filter nostr.Filter) (bool, string) {
    pubkey := khatru.GetAuthed(ctx)
    if pubkey == "" {
        return true, "auth-required: please authenticate"
    }
    return false, ""
})
```

The `auth-required:` prefix triggers automatic AUTH flow.

## Built-in Policies

Import `github.com/fiatjaf/khatru/policies` for common policies:

### Event Policies

- `PreventTooManyIndexableTags(max, ignoreKinds, onlyKinds)` - Limit indexable tags
- `PreventLargeTags(maxLen)` - Reject events with large tag values
- `RestrictToSpecifiedKinds(allowEphemeral, kinds...)` - Whitelist event kinds
- `PreventTimestampsInThePast(threshold)` - Reject old events
- `PreventTimestampsInTheFuture(threshold)` - Reject future events
- `RejectEventsWithBase64Media` - Block base64 embedded media
- `OnlyAllowNIP70ProtectedEvents` - Require NIP-70 protection

### Filter Policies

- `NoComplexFilters` - Reject complex queries
- `FilterIPRateLimiter(rate, window, max)` - Rate limit queries

### Rate Limiting

- `EventIPRateLimiter(rate, window, max)` - Rate limit event publishing
- `ConnectionRateLimiter(rate, window, max)` - Rate limit connections

### Sane Defaults

```go
policies.ApplySaneDefaults(relay)
```

Applies: `RejectEventsWithBase64Media`, event/filter/connection rate limiting, `NoComplexFilters`

## Event Storage with eventstore

The `eventstore` library provides database adapters:

```go
import "github.com/fiatjaf/eventstore/sqlite3"

db := sqlite3.SQLite3Backend{DatabaseURL: "/tmp/relay.db"}
db.Init()

relay.StoreEvent = append(relay.StoreEvent, db.SaveEvent)
relay.QueryEvents = append(relay.QueryEvents, db.QueryEvents)
relay.CountEvents = append(relay.CountEvents, db.CountEvents)
relay.DeleteEvent = append(relay.DeleteEvent, db.DeleteEvent)
relay.ReplaceEvent = append(relay.ReplaceEvent, db.ReplaceEvent)
```

Available backends:
- `sqlite3` - SQLite (local file)
- `badger` - Badger DB (embedded key-value)
- `lmdb` - LMDB (embedded)
- `postgresql` - PostgreSQL (remote)
- `mysql` - MySQL (remote)

## Blossom Media Storage

Khatru includes built-in Blossom (NIP-B7) support:

```go
import "github.com/fiatjaf/khatru/blossom"

bl := blossom.New(relay, "http://localhost:3334")

// Blob metadata store
blobdb := &badger.BadgerBackend{Path: "/tmp/blobstore"}
blobdb.Init()
bl.Store = blossom.EventStoreBlobIndexWrapper{Store: blobdb, ServiceURL: bl.ServiceURL}

// Storage implementation
bl.StoreBlob = append(bl.StoreBlob, func(ctx context.Context, sha256, ext string, body []byte) error {
    // Store blob
    return nil
})
bl.LoadBlob = append(bl.LoadBlob, func(ctx context.Context, sha256, ext string) (io.ReadSeeker, error) {
    // Load blob
    return nil, nil
})
bl.DeleteBlob = append(bl.DeleteBlob, func(ctx context.Context, sha256, ext string) error {
    // Delete blob
    return nil
})

// Upload restrictions
bl.RejectUpload = append(bl.RejectUpload, func(ctx context.Context, auth *nostr.Event, size int, ext string) (bool, string, int) {
    if size > 10*1024*1024 {
        return true, "file too large", 413
    }
    return false, "", 0
})
```

## NIP-86 Management API

```go
relay.ManagementAPI.RejectAPICall = append(relay.ManagementAPI.RejectAPICall,
    func(ctx context.Context, mp nip86.MethodParams) (bool, string) {
        if khatru.GetAuthed(ctx) != ownerPubkey {
            return true, "not authorized"
        }
        return false, ""
    },
)

relay.ManagementAPI.AllowPubKey = func(ctx context.Context, pubkey, reason string) error {
    // Add pubkey to allowlist
    return nil
}
relay.ManagementAPI.BanPubKey = func(ctx context.Context, pubkey, reason string) error {
    // Remove pubkey from allowlist
    return nil
}
```

## Request Routing

For complex relays that need different policies for different event types:

```go
router := khatru.NewRouter()

// Route group events to groups relay
router.Route().
    Req(func(filter nostr.Filter) bool {
        _, hasH := filter.Tags["h"]
        return hasH
    }).
    Event(func(event *nostr.Event) bool {
        return event.Tags.Find("h") != nil
    }).
    Relay(groupsRelay)

// Route everything else to public relay
router.Route().
    Req(func(filter nostr.Filter) bool { return true }).
    Event(func(event *nostr.Event) bool { return true }).
    Relay(publicRelay)

http.ListenAndServe(":3334", router)
```

## HTTP Routing

Add custom HTTP handlers alongside the relay:

```go
mux := relay.Router()

mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("content-type", "text/html")
    fmt.Fprintf(w, "<b>Welcome to my relay!</b>")
})

http.ListenAndServe(":3334", relay)
```

## Context Utilities

```go
// Get authenticated pubkey
pubkey := khatru.GetAuthed(ctx)

// Get WebSocket connection
ws := khatru.GetConnection(ctx)

// Request authentication
khatru.RequestAuth(ctx)

// Get client IP
ip := khatru.GetIPFromRequest(r)
```

## Supported NIPs

Khatru supports these NIPs out of the box:
- NIP-01: Basic protocol
- NIP-11: Relay information document
- NIP-40: Expiration timestamp
- NIP-42: Authentication
- NIP-45: Event counts
- NIP-70: Protected events
- NIP-77: Negentropy syncing (optional)
- NIP-86: Management API

## Examples

Full examples available at: `../../resources/khatru/examples/`

- `basic-badger` - Simple relay with Badger storage
- `basic-sqlite3` - Simple relay with SQLite storage
- `basic-lmdb` - Simple relay with LMDB storage
- `basic-postgres` - Relay with PostgreSQL
- `blossom` - Relay with Blossom media storage
- `exclusive` - Relay with exclusive access
- `routing` - Multi-relay routing
