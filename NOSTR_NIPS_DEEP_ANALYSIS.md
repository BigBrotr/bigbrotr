# Nostr NIPs Deep Analysis For BigBrotr

## Scope

This document consolidates a repository-wide reading of the official NIP
repository:

- source: <https://github.com/nostr-protocol/nips>
- snapshot commit: `0a25dd524389d642ec153d9009a16fb183eb23ce`

Its purpose is not to replace the NIP repository. Its purpose is to:

- anchor BigBrotr against the actual protocol texts;
- identify which NIPs are foundational, which are directly implemented, and
  which are only contextual;
- prevent protocol drift when redesigning services, schema, analytics, and
  public read surfaces;
- provide one place where the NIP landscape is interpreted through the lens of
  BigBrotr.

Role and precedence:

- this file is a **protocol-analysis reference**;
- it exists to keep BigBrotr aligned with the relevant NIPs and to support
  redesign decisions with protocol context;
- it is **not** the canonical redesign execution plan;
- final redesign decisions and execution sequencing belong to
  `planning/definitive-redesign/`.

## Important Note On Full NIP Text

I did **not** reproduce full NIP texts in this file.

The official NIP markdown files are copyrighted upstream documents and should
be read at the pinned source commit. For the most important NIPs this document
provides:

- exact file names;
- exact pinned GitHub URLs;
- detailed technical summaries;
- BigBrotr-specific consequences and implementation notes.

## Executive Summary

For BigBrotr, the NIP landscape is not flat.

There are four layers of protocol relevance:

1. **Foundational protocol**
   These define the event model, relay interaction model, tags, kinds, and
   filters that the whole project depends on:
   `01`, `02`, `11`, `19`, `21`, `42`, `65`.

2. **Analytics interpretation NIPs**
   These define how events should be interpreted when BigBrotr derives social
   or engagement facts:
   `10`, `18`, `22`, `23`, `24`, `25`, `31`, `32`, `56`, `57`, `70`, `73`.

3. **BigBrotr direct product NIPs**
   These are implemented or surfaced directly by the product:
   `11`, `65`, `66`, `85`, `89`, `90`.

4. **Adjacent or future-facing NIPs**
   These are not core to the current product, but matter for ecosystem
   awareness, future compatibility, or relay classification:
   `05`, `50`, `77`, `98`, plus most of the rest of the repository at low
   relevance.

The most important overall conclusion is this:

- BigBrotr is **not** a generic Nostr client and should not pretend all NIPs
  matter equally.
- But BigBrotr **must** remain precise on the few NIPs that define its event
  ingestion, relay monitoring, graph derivation, trusted assertion publishing,
  and DVM query surfaces.

## What BigBrotr Uses Most Strongly

### Directly implemented in code

These are strongly reflected in `src/bigbrotr/nips/`, service logic, event
builders, configs, and public surfaces:

- `NIP-11` Relay Information Document
- `NIP-65` Relay List Metadata
- `NIP-66` Relay Discovery and Liveness Monitoring
- `NIP-85` Trusted Assertions
- `NIP-89` Recommended Application Handlers
- `NIP-90` Data Vending Machines
- `NIP-42` Authentication of clients to relays

### Strong semantic dependencies

These are not always implemented as their own package, but they influence how
BigBrotr must interpret archived events and derived analytics:

- `NIP-01` basic event model, kinds, tags, filters, relay flow
- `NIP-02` follow lists
- `NIP-10` text notes and threads
- `NIP-18` reposts
- `NIP-22` comments
- `NIP-23` long-form content
- `NIP-24` extra metadata fields and common tags
- `NIP-25` reactions
- `NIP-31` dealing with unknown event kinds
- `NIP-32` labeling
- `NIP-56` reporting
- `NIP-57` zaps
- `NIP-70` protected events
- `NIP-73` external content IDs

### Useful adjacent context

- `NIP-05` DNS identifiers
- `NIP-19` bech32 entities
- `NIP-21` `nostr:` URIs
- `NIP-50` search capability
- `NIP-77` negentropy syncing
- `NIP-98` HTTP auth

## BigBrotr Module To NIP Map

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/nip11`

Implements:

- fetch of relay info documents;
- permissive parsing of untrusted NIP-11 JSON;
- normalization into typed models;
- conversion into content-addressed document rows.

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/nip66`

Implements:

- RTT open/read/write probing;
- SSL inspection;
- DNS, geo, net, HTTP checks;
- typed monitoring data and logs;
- inputs used to publish kinds `10166` and `30166`.

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/nip85`

Implements:

- typed provider declarations for kind `10040`;
- typed assertion subjects for kinds `30382`, `30383`, `30384`, `30385`;
- conversion from database rows into NIP-85 tag values.

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/event_builders.py`

Builds events for:

- kind `0`
- kind `10002`
- kind `10040`
- kind `10166`
- kind `30166`
- kinds `30382`-`30385`

This file is where many cross-NIP interactions become concrete:

- `NIP-01` kind `0`
- `NIP-24` extra profile fields and common tags
- `NIP-32` labels
- `NIP-50` relay capability classification
- `NIP-65` relay lists
- `NIP-66` monitor announcement and discovery events
- `NIP-85` provider declarations and trusted assertions

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/services/dvm`

Implements public query serving according to:

- `NIP-90` request/result/feedback flow
- `NIP-89` discoverability announcements

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/services/monitor`

Uses:

- `NIP-11` for relay info documents
- `NIP-66` for health checks and publication
- `NIP-65` for relay list publication
- `NIP-01` kind `0` for optional profile publication

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/services/assertor`

Uses:

- `NIP-85` for trusted assertion publication
- optionally kind `0` for provider profile discoverability

### `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/services/synchronizer`

Protocol-critical dependencies:

- `NIP-01` filter semantics
- `NIP-42` authenticated reads when required by relays
- future possible relevance of `NIP-77`

## Detailed Analysis Of The Most Important NIPs

## NIP-01 — Basic protocol flow description

- source: [01.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/01.md)
- role for BigBrotr: absolutely foundational

What it defines:

- canonical event wire format;
- canonical event id serialization and hashing rules;
- common `e`, `p`, `a` tags;
- kind categories: regular, replaceable, ephemeral, addressable;
- relay websocket protocol:
  - `EVENT`
  - `REQ`
  - `CLOSE`
  - `OK`
  - `EOSE`
  - `CLOSED`
  - `NOTICE`
- filter semantics:
  - `ids`
  - `authors`
  - `kinds`
  - `#x` single-letter tag filters
  - `since`
  - `until`
  - `limit`

Why it matters to BigBrotr:

- the archive schema stores the full NIP-01 event shape;
- the synchronizer must preserve event identity exactly;
- the meaning of `replaceable` and `addressable` drives current-state tables;
- the entire query layer depends on correct filter semantics;
- event interpretation for analytics starts from NIP-01 tags and kind classes.

Rules BigBrotr must not violate:

- event ids must come from the exact canonical serialization;
- only the first value of a single-letter tag is indexable for `#x` filter
  semantics;
- replaceable and addressable winner selection must follow timestamp ordering,
  with lexical-id tie-break;
- `since <= created_at <= until` semantics matter exactly;
- a `REQ` with multiple filters is logical OR across filters, but logical AND
  inside each filter.

BigBrotr implications:

- current tables for replaceable/addressable events should reflect NIP-01
  winner semantics directly;
- if schema is redesigned, winner-index tables should remain faithful to the
  NIP-01 rules even if they become much slimmer;
- public readable resources should never re-interpret replaceability in ways
  that diverge from this NIP.

## NIP-02 — Follow List

- source: [02.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/02.md)
- role for BigBrotr: core for graph derivation

What it defines:

- kind `3` follow list events;
- `p` tags as follows;
- whole-list overwrite semantics;
- optional relay hint and petname slots inside `p` tags.

Why it matters:

- `contact_lists_current` and `contact_list_edges_current` are derived from the
  latest kind `3` events;
- follower/following counts and the social graph that feeds the ranker all
  depend on correct overwrite semantics.

Rules BigBrotr must not violate:

- a new kind `3` replaces the previous list for that pubkey;
- empty latest lists are meaningful and should clear prior edges;
- graph derivation should use the latest list, not cumulative append logic.

Most important consequence:

- `contact_lists_current` and `contact_list_edges_current` are closer to
  canonical current facts than to convenience caches. They likely deserve to
  stay materialized even in a DB redesign.

## NIP-05 — Mapping keys to DNS identifiers

- source: [05.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/05.md)
- role for BigBrotr: contextual, low direct coupling today

Why it still matters:

- relay search and analytics ecosystems often expose NIP-05;
- `NIP-50` search extensions reference valid NIP-05 domains;
- future identity-oriented readable resources may need to respect these
  semantics.

Key protocol constraints:

- clients follow pubkeys, not NIP-05 strings;
- `.well-known/nostr.json` must not redirect;
- identifiers are identification-first, not universal verification.

## NIP-10 — Text Notes and Threads

- source: [10.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/10.md)
- role for BigBrotr: important for note/reply interpretation

Why it matters:

- BigBrotr counts posts and replies;
- some engagement semantics on kind `1` require understanding of reply and
  quote references;
- a wrong thread interpretation distorts NIP-85 facts.

Key implications:

- kind `1` replies should use `e` tags for thread stack;
- `q` tags are quotes;
- kind `1` must not be treated as the generic reply mechanism for every event
  kind, because `NIP-22` exists for cross-kind comments.

## NIP-11 — Relay Information Document

- source: [11.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/11.md)
- role for BigBrotr: first-class protocol dependency

What it defines:

- relay information document fetched over HTTP(S);
- metadata fields like name, software, version, pubkey, contact;
- supported NIPs;
- limitations, retention, fee schedules, language tags, tags, regions,
  posting policy, etc.

Why it matters:

- BigBrotr directly fetches, stores, normalizes, and republishes NIP-11 data;
- monitor classification derives relay capabilities from it;
- analytics like software counts and supported NIP counts depend on it.

BigBrotr-specific implementation note:

- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/nip11/info.py`
  is intentionally permissive with untrusted data and returns structured
  success/failure instead of throwing semantic exceptions to callers.

Critical interpretation rules:

- NIP-11 is self-report from the relay, not authoritative proof;
- capability derivation from `supported_nips` should remain clearly distinct
  from probe-verified facts;
- storage should keep the raw semantic content available even if current
  summary tables are slimmed down.

## NIP-18 — Reposts

- source: [18.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/18.md)
- role for BigBrotr: high for engagement analytics

Why it matters:

- repost counts are part of NIP-85 event and user facts;
- repost semantics should not be mixed with generic references.

## NIP-19 — bech32-encoded entities

- source: [19.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/19.md)
- role for BigBrotr: support-layer important

Why it matters:

- `NIP-89` handler URLs and many client-facing references use NIP-19 entities;
- read surfaces that reference events or profiles may need stable NIP-19
  encoding logic.

## NIP-21 — `nostr:` URI scheme

- source: [21.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/21.md)
- role for BigBrotr: support-layer important

Why it matters:

- quoted and referenced entities in text can use `nostr:` URIs;
- clients and DVM consumers may surface data through this representation.

## NIP-22 — Comment

- source: [22.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/22.md)
- role for BigBrotr: important for cross-kind engagement semantics

Why it matters:

- comments on non-kind-1 subjects should not be collapsed into ordinary
  NIP-10 replies;
- event and addressable comment counts in NIP-85 analytics depend on correct
  interpretation here.

## NIP-23 — Long-form Content

- source: [23.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/23.md)
- role for BigBrotr: important because kind `30023` is addressable content

Why it matters:

- addressable current-state derivation must correctly treat long-form content
  as addressable;
- engagement and addressable ranking facts may apply to this content class.

## NIP-24 — Extra metadata fields and tags

- source: [24.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/24.md)
- role for BigBrotr: important supporting NIP

What it contributes:

- extra kind `0` fields like `display_name`, `website`, `banner`, `bot`,
  `birthday`;
- common tags like:
  - `r`
  - `i`
  - `title`
  - `t`

Why it matters:

- BigBrotr's profile event builder already uses fields covered here;
- topic extraction depends on `t` tag semantics;
- `i` tags interact with `NIP-73`.

Design consequence:

- event and analytics interpretation should treat common tags from NIP-24 as
  protocol-level, not app-local accidents.

## NIP-25 — Reactions

- source: [25.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/25.md)
- role for BigBrotr: high for engagement counts

Why it matters:

- reaction counts are part of both user and event/addressable facts;
- target attribution rules matter when reconstructing counts from tags.

## NIP-31 — Dealing with unknown event kinds

- source: [31.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/31.md)
- role for BigBrotr: medium but important for product surface thinking

Why it matters:

- BigBrotr exposes and archives many events that downstream clients may not
  know how to render;
- `NIP-89` is explicitly mentioned as the way to make unknown kinds more
  usable;
- this strengthens the design decision that DVM/API/public readable resources
  should be product-shaped, not raw-table shaped.

## NIP-32 — Labeling

- source: [32.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/32.md)
- role for BigBrotr: directly relevant in monitor event building

Why it matters:

- BigBrotr emits `l` tags in monitor discovery events for ASN, ASN org,
  country, city, and timezone classification;
- this is a deliberate use of indexable labeling to make discovery events more
  filterable.

Important constraint:

- namespace discipline matters. Labels should not be emitted as ad hoc junk if
  they are meant to be queryable by others.

## NIP-42 — Authentication of clients to relays

- source: [42.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/42.md)
- role for BigBrotr: strong direct dependency

Why it matters:

- the synchronizer supports authenticated reads when relays require it;
- `NIP-70` protected events depend on the auth flow;
- monitor write tests and restricted relays interact with auth semantics.

Design consequence:

- service keys are not optional niceties; they are part of protocol
  correctness for some relays.

## NIP-50 — Search Capability

- source: [50.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/50.md)
- role for BigBrotr: adjacent but already referenced

Why it matters:

- `event_builders.py` classifies relays with a `T=Search` tag when NIP-50 is
  advertised in NIP-11 supported_nips;
- if future discovery or read surfaces include search-oriented models, this
  NIP becomes more directly important.

## NIP-56 — Reporting

- source: [56.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/56.md)
- role for BigBrotr: high for NIP-85 facts

Why it matters:

- report counts are part of per-user facts;
- misclassifying report targets or semantics would distort trusted assertions.

## NIP-57 — Lightning Zaps

- source: [57.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/57.md)
- role for BigBrotr: high for NIP-85 facts

Why it matters:

- zap counts and amounts are central in NIP-85 stats;
- validating zap amount semantics is necessary to avoid overstating
  engagement;
- the `LilBrotr` docs already acknowledge places where reduced storage weakens
  exact zap reconstruction.

Design consequence:

- if disk optimization removes necessary zap verification inputs, the system
  must degrade explicitly and not silently claim exactness.

## NIP-65 — Relay List Metadata

- source: [65.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/65.md)
- role for BigBrotr: direct protocol output and discovery input

Why it matters:

- the monitor publishes kind `10002`;
- relay list metadata is also an important discovery signal for the finder;
- `NIP-24` explicitly deprecates the old relay object embedded in kind `3`
  content in favor of this NIP.

Most important consequence:

- discovery logic should privilege true relay list metadata over historical
  hacks stored in kind `3` content.

## NIP-66 — Relay Discovery and Liveness Monitoring

- source: [66.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/66.md)
- role for BigBrotr: first-class protocol dependency

What it defines for BigBrotr:

- monitor announcement semantics for kind `10166`;
- relay discovery/liveness reporting semantics for kind `30166`;
- the conceptual space for RTT, SSL, DNS, Geo, Net, HTTP, NIP-11-derived
  access/capability tags.

Why it matters:

- BigBrotr is very explicitly a relay observatory; this NIP is aligned with
  the product itself, not just an output format.

Important implementation reality:

- BigBrotr uses probe results as stronger ground truth than relay self-report
  when classifying access restrictions.
- `/Users/vincenzo/Documents/GitHub/BigBrotr/bigbrotr/src/bigbrotr/nips/event_builders.py`
  already reflects this by combining NIP-11 data with actual RTT/write/auth
  outcomes.

Design consequence:

- NIP-66 data is a real product artifact and should not be treated as
  expendable “side metadata”.

## NIP-70 — Protected Events

- source: [70.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/70.md)
- role for BigBrotr: medium protocol guardrail

Why it matters:

- archiving and publishing systems should understand that protected events are
  meant to be author-published and require auth-aware relay behavior;
- analytics or republishing logic should not accidentally assume unrestricted
  relay propagation.

## NIP-73 — External Content IDs

- source: [73.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/73.md)
- role for BigBrotr: high because of kind `30385`

Why it matters:

- BigBrotr computes identifier-based NIP-85 facts and assertions;
- identifier syntax and attached `k` tags affect correctness of those outputs.

## NIP-77 — Negentropy Syncing

- source: [77.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/77.md)
- role for BigBrotr: future-facing but important

Why it matters:

- BigBrotr currently performs relay event ingestion through its own
  synchronizer logic;
- if the project later wants more protocol-native reconciliation for large
  event sets, this is the NIP to revisit.

## NIP-85 — Trusted Assertions

- source: [85.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/85.md)
- role for BigBrotr: first-class protocol dependency

What it defines:

- provider declaration list kind `10040`;
- user assertion kind `30382`;
- event assertion kind `30383`;
- addressable assertion kind `30384`;
- identifier assertion kind `30385`;
- tag names and value shapes for ranks and metrics.

Why it matters:

- BigBrotr's refresher, ranker, and assertor pipeline exists largely to
  produce these outputs;
- database facts and rank tables are organized around this protocol.

Critical implementation detail:

- BigBrotr already keeps a private compute store in DuckDB and exports final
  snapshots to PostgreSQL before publication. This matches the idea that NIP-85
  outputs are protocol artifacts derived from internal analytics, not the same
  thing as the analytics engine itself.

Design consequence:

- the canonical DB should keep the facts needed for NIP-85;
- the rank algorithm and its working state can remain private and
  replaceable.

## NIP-89 — Recommended Application Handlers

- source: [89.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/89.md)
- role for BigBrotr: direct dependency for DVM discoverability

Why it matters:

- the DVM announces itself through a handler-style discovery surface;
- handler metadata is what lets clients find a DVM for specific job kinds or
  surfaces.

Important product consequence:

- BigBrotr's public query surfaces should remain intentional enough that a
  handler announcement is meaningful to outside clients.

## NIP-90 — Data Vending Machines

- source: [90.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/90.md)
- role for BigBrotr: direct dependency for one public surface

What it defines:

- request kinds `5000-5999`;
- result kinds `6000-6999`;
- feedback kind `7000`;
- request, result, and feedback tag conventions;
- loose protocol flow for service providers.

Why it matters:

- BigBrotr's DVM is not just a relay query façade; it is a protocol product
  surface;
- feedback statuses like `payment-required`, `processing`, `error`, `success`,
  `partial` should remain modeled honestly even if BigBrotr keeps a simple
  free/public policy.

Design consequence:

- the readable-resource surface exposed through the DVM should be stable and
  product-oriented, not a shadow of internal table names.

## NIP-98 — HTTP Auth

- source: [98.md](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/98.md)
- role for BigBrotr: low direct relevance today

Why it still matters:

- if BigBrotr later adds authenticated HTTP endpoints or upstream HTTP service
  integrations for Nostr-native users, this is the right protocol anchor;
- worth keeping in context so future API features do not invent incompatible
  auth schemes unnecessarily.

## Protocol Rules BigBrotr Must Keep In Mind

These are the most important cross-NIP rules to keep present during redesign:

- `NIP-01` kinds divide into regular, replaceable, ephemeral, addressable.
- `NIP-02` follow lists overwrite wholesale.
- `NIP-24` makes `t` and `i` tags common semantic building blocks.
- `NIP-42` matters for authenticated relay interaction.
- `NIP-57` zap exactness depends on more than just counting events.
- `NIP-65` supersedes old relay-list hacks embedded in kind `3`.
- `NIP-70` means some events are intentionally not for unrestricted
  republishing.
- `NIP-73` identifier semantics matter if kind `30385` is a product output.
- `NIP-89` and `NIP-90` make discoverability and DVM behavior part of the
  public product contract, not internal details.

## BigBrotr-Specific Redesign Guidance Derived From The NIPs

### What should stay protocol-faithful and hard to change later

- event identity and tag interpretation;
- replaceable/addressable current-state semantics;
- follow graph current-state semantics;
- NIP-11 normalized storage and capability extraction;
- NIP-66 publication semantics;
- NIP-85 facts and assertion value shapes;
- NIP-89 and NIP-90 public contract surface.

### What can be redesigned aggressively without violating NIPs

- internal DB table names;
- how current winners are stored physically;
- whether current-state tables are wide or pointer-based;
- whether readable resources are catalog-backed or handler-backed;
- the internal compute engine behind NIP-85 ranks;
- service names and package boundaries.

### Where the NIPs push toward a cleaner architecture

- `Synchronizer` should stay about canonical relay/event ingestion, not
  ranking.
- `Refresher` should own canonical derived facts.
- `Ranker` should own private algorithmic compute.
- API and DVM should expose stable readable resources, not raw storage
  internals.
- deployment differences should mostly be about surface and storage profile,
  not protocol drift.

## Repository-Wide NIP Inventory

Relevance scale used below:

- `critical`: directly constrains core product behavior
- `high`: strongly affects analytics, publication, or public surfaces
- `medium`: meaningful context or future likely relevance
- `low`: ecosystem context only for the current product
- `none`: effectively irrelevant to the current project shape

| NIP | Title | Upstream note | Relevance | BigBrotr note |
| --- | ----- | ------------- | --------- | ------------- |
| 01 | Basic protocol flow description |  | critical | Canonical event, tag, kind, filter, relay flow model |
| 02 | Follow List |  | critical | Source of contact graph current state |
| 03 | OpenTimestamps Attestations for Events |  | low | Not core today |
| 04 | Encrypted Direct Message | deprecated in favor of 17 | none | Not a current product surface |
| 05 | Mapping Nostr keys to DNS-based internet identifiers |  | medium | Identity/search context |
| 06 | Basic key derivation from mnemonic seed phrase |  | low | Operational wallet/key context only |
| 07 | `window.nostr` capability for web browsers |  | none | Browser wallet context, not core backend |
| 08 | Handling Mentions | deprecated in favor of 27 | none | Superseded |
| 09 | Event Deletion Request |  | medium | Archive and current-state semantics may need it |
| 10 | Text Notes and Threads |  | high | Reply and quote interpretation |
| 11 | Relay Information Document |  | critical | Directly implemented and stored |
| 13 | Proof of Work |  | low | Not central today |
| 14 | Subject tag in text events |  | low | Weak current relevance |
| 15 | Nostr Marketplace |  | none | Not product-related |
| 17 | Private Direct Messages |  | none | Not a current product concern |
| 18 | Reposts |  | high | Needed for engagement counts |
| 19 | bech32-encoded entities |  | medium | Needed for client-facing entity references |
| 21 | `nostr:` URI scheme |  | medium | Relevant for references and client UX |
| 22 | Comment |  | high | Important for non-note comment semantics |
| 23 | Long-form Content |  | high | Addressable content semantics |
| 24 | Extra metadata fields and tags |  | high | Common tags and profile fields |
| 25 | Reactions |  | high | Important for NIP-85 facts |
| 26 | Delegated Event Signing | adds unnecessary burden for little gain | none | No current use |
| 27 | Text Note References |  | medium | Useful reference syntax context |
| 28 | Public Chat |  | low | Not a product focus |
| 29 | Relay-based Groups |  | low | Only indirect capability context |
| 30 | Custom Emoji |  | none | Not relevant |
| 31 | Dealing with Unknown Events |  | high | Reinforces alt-tag and handler strategy |
| 32 | Labeling |  | high | Directly used in monitor discovery tags |
| 34 | `git` stuff |  | none | Out of scope |
| 35 | Torrents |  | none | Out of scope |
| 36 | Sensitive Content |  | low | Possible moderation context only |
| 37 | Draft Events |  | low | Out of current scope |
| 38 | User Statuses |  | none | Out of scope |
| 39 | External Identities in Profiles |  | low | Profile enrichment only |
| 40 | Expiration Timestamp |  | low | Possible archive behavior nuance |
| 42 | Authentication of clients to relays |  | critical | Used by synchronizer/auth-aware relay interactions |
| 43 | Relay Access Metadata and Requests |  | low | Not a current focus |
| 44 | Encrypted Payloads (Versioned) |  | low | Only indirectly mentioned by NIP-85 private provider lists |
| 45 | Counting results |  | low | Search/counting context, not product core |
| 46 | Nostr Remote Signing |  | low | Signing infrastructure context only |
| 47 | Nostr Wallet Connect |  | none | Not product-related |
| 48 | Proxy Tags |  | none | Not used |
| 49 | Private Key Encryption |  | low | Key storage context only |
| 50 | Search Capability |  | medium | Already reflected in relay capability classification |
| 51 | Lists |  | low | Only partial ecosystem relevance |
| 52 | Calendar Events |  | none | Not product-related |
| 53 | Live Activities |  | none | Not product-related |
| 54 | Wiki |  | none | Not product-related |
| 55 | Android Signer Application |  | none | Not product-related |
| 56 | Reporting |  | high | Needed for report counts |
| 57 | Lightning Zaps |  | high | Needed for zap counts and amount semantics |
| 58 | Badges |  | none | Not product-related |
| 59 | Gift Wrap |  | none | Not product-related |
| 5A | Pubkey Static Websites |  | low | Ecosystem context only |
| 60 | Cashu Wallet |  | none | Not product-related |
| 61 | Nutzaps |  | low | Possible adjacent payment context |
| 62 | Request to Vanish |  | low | Archive policy nuance only |
| 64 | Chess (PGN) |  | none | Not product-related |
| 65 | Relay List Metadata |  | critical | Published by monitor and used in discovery |
| 66 | Relay Discovery and Liveness Monitoring |  | critical | Core product protocol |
| 68 | Picture-first feeds |  | none | Not product-related |
| 69 | Peer-to-peer Order events |  | none | Not product-related |
| 70 | Protected Events |  | medium | Auth and republishing semantics |
| 71 | Video Events |  | none | Not product-related |
| 72 | Moderated Communities |  | none | Not product-related |
| 73 | External Content IDs |  | high | Needed for identifier assertions |
| 75 | Zap Goals |  | none | Not product-related |
| 77 | Negentropy Syncing |  | medium | Strong future interest for sync strategy |
| 78 | Application-specific data |  | low | Not current core |
| 7D | Threads |  | low | Threading context, not core today |
| 84 | Highlights |  | none | Not product-related |
| 85 | Trusted Assertions |  | critical | Core ranking and assertion output |
| 86 | Relay Management API |  | low | Relay admin context, not product core |
| 87 | Ecash Mint Discoverability |  | none | Not product-related |
| 88 | Polls |  | none | Not product-related |
| 89 | Recommended Application Handlers |  | critical | DVM discoverability surface |
| 90 | Data Vending Machines |  | critical | DVM request/result contract |
| 92 | Media Attachments |  | low | Could affect event/media interpretation later |
| 94 | File Metadata |  | low | Media/file context only |
| 96 | HTTP File Storage Integration | replaced by blossom APIs | none | Not current product path |
| 98 | HTTP Auth |  | medium | Future HTTP auth relevance |
| 99 | Classified Listings |  | none | Not product-related |
| A0 | Voice Messages |  | none | Not product-related |
| A4 | Public Messages |  | none | Not product-related |
| B0 | Web Bookmarks |  | none | Not product-related |
| B7 | Blossom |  | low | Capability classification context |
| BE | Nostr BLE Communications Protocol |  | none | Not product-related |
| C0 | Code Snippets |  | none | Not product-related |
| C7 | Chats |  | none | Not product-related |
| EE | E2EE Messaging using MLS Protocol | superseded by Marmot | none | Not product-related |

## Exact Source Map For The Most Relevant NIPs

- [NIP-01](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/01.md)
- [NIP-02](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/02.md)
- [NIP-05](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/05.md)
- [NIP-10](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/10.md)
- [NIP-11](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/11.md)
- [NIP-18](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/18.md)
- [NIP-19](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/19.md)
- [NIP-21](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/21.md)
- [NIP-22](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/22.md)
- [NIP-23](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/23.md)
- [NIP-24](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/24.md)
- [NIP-25](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/25.md)
- [NIP-31](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/31.md)
- [NIP-32](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/32.md)
- [NIP-42](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/42.md)
- [NIP-50](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/50.md)
- [NIP-56](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/56.md)
- [NIP-57](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/57.md)
- [NIP-65](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/65.md)
- [NIP-66](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/66.md)
- [NIP-70](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/70.md)
- [NIP-73](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/73.md)
- [NIP-77](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/77.md)
- [NIP-85](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/85.md)
- [NIP-89](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/89.md)
- [NIP-90](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/90.md)
- [NIP-98](https://github.com/nostr-protocol/nips/blob/0a25dd524389d642ec153d9009a16fb183eb23ce/98.md)

## Final Takeaway

The protocol picture supports the same architectural direction that emerged
from the codebase reading:

- keep canonical archive semantics strict;
- keep current-state semantics faithful to NIP rules;
- keep monitoring outputs protocol-shaped;
- keep ranking as private compute over canonical facts;
- keep public read surfaces product-shaped and discoverable;
- do not let storage convenience distort protocol semantics.
