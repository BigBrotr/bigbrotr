# Nostr Event Kinds Reference

Complete reference of all Nostr event kinds. Events are categorized by their behavior:

- **Regular Events (0-9999)**: Stored by relays, multiple events per pubkey
- **Replaceable Events (10000-19999)**: Only latest event per pubkey+kind is stored
- **Ephemeral Events (20000-29999)**: Not stored by relays
- **Addressable Events (30000-39999)**: Replaceable by pubkey+kind+d-tag

## Core Events (0-99)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 0 | User Metadata | [01](../../resources/nips/01.md) | Profile information (name, about, picture) |
| 1 | Short Text Note | [10](../../resources/nips/10.md) | Basic text post |
| 2 | Recommend Relay | 01 | Deprecated |
| 3 | Follows | [02](../../resources/nips/02.md) | Contact/follow list |
| 4 | Encrypted Direct Messages | [04](../../resources/nips/04.md) | Legacy DMs (deprecated, use kind 14) |
| 5 | Event Deletion Request | [09](../../resources/nips/09.md) | Request to delete events |
| 6 | Repost | [18](../../resources/nips/18.md) | Share another event |
| 7 | Reaction | [25](../../resources/nips/25.md) | Like/emoji reaction |
| 8 | Badge Award | [58](../../resources/nips/58.md) | Award a badge to someone |
| 9 | Chat Message | [C7](../../resources/nips/C7.md) | Chat room message |
| 10 | Group Chat Threaded Reply | 29 | Deprecated |
| 11 | Thread | [7D](../../resources/nips/7D.md) | Thread post |
| 12 | Group Thread Reply | 29 | Deprecated |
| 13 | Seal | [59](../../resources/nips/59.md) | Encrypted event wrapper |
| 14 | Direct Message | [17](../../resources/nips/17.md) | Private DM (recommended) |
| 15 | File Message | [17](../../resources/nips/17.md) | File in DM |
| 16 | Generic Repost | [18](../../resources/nips/18.md) | Repost any event kind |
| 17 | Reaction to a website | [25](../../resources/nips/25.md) | React to external URL |
| 20 | Picture | [68](../../resources/nips/68.md) | Image post |
| 21 | Video Event | [71](../../resources/nips/71.md) | Video post |
| 22 | Short-form Portrait Video | [71](../../resources/nips/71.md) | Vertical video (TikTok-style) |
| 40 | Channel Creation | [28](../../resources/nips/28.md) | Create public chat channel |
| 41 | Channel Metadata | [28](../../resources/nips/28.md) | Update channel info |
| 42 | Channel Message | [28](../../resources/nips/28.md) | Message in channel |
| 43 | Channel Hide Message | [28](../../resources/nips/28.md) | Hide a channel message |
| 44 | Channel Mute User | [28](../../resources/nips/28.md) | Mute user in channel |
| 62 | Request to Vanish | [62](../../resources/nips/62.md) | Request account deletion |
| 64 | Chess (PGN) | [64](../../resources/nips/64.md) | Chess game in PGN format |

## Application Events (1000-1999)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 1018 | Poll Response | [88](../../resources/nips/88.md) | Vote on a poll |
| 1021 | Bid | [15](../../resources/nips/15.md) | Marketplace bid |
| 1022 | Bid confirmation | [15](../../resources/nips/15.md) | Confirm a bid |
| 1040 | OpenTimestamps | [03](../../resources/nips/03.md) | Timestamp attestation |
| 1059 | Gift Wrap | [59](../../resources/nips/59.md) | Encrypted event container |
| 1063 | File Metadata | [94](../../resources/nips/94.md) | File information |
| 1068 | Poll | [88](../../resources/nips/88.md) | Create a poll |
| 1111 | Comment | [22](../../resources/nips/22.md) | Comment on any event |
| 1222 | Voice Message | [A0](../../resources/nips/A0.md) | Audio message |
| 1244 | Voice Message Comment | [A0](../../resources/nips/A0.md) | Comment on voice message |
| 1311 | Live Chat Message | [53](../../resources/nips/53.md) | Live stream chat |
| 1337 | Code Snippet | [C0](../../resources/nips/C0.md) | Shared code |
| 1617 | Patches | [34](../../resources/nips/34.md) | Git patches |
| 1618 | Pull Requests | [34](../../resources/nips/34.md) | Git PRs |
| 1619 | Pull Request Updates | [34](../../resources/nips/34.md) | PR update notifications |
| 1621 | Issues | [34](../../resources/nips/34.md) | Git issues |
| 1622 | Git Replies | [34](../../resources/nips/34.md) | Deprecated |
| 1630-1633 | Status | [34](../../resources/nips/34.md) | Git status updates |
| 1984 | Reporting | [56](../../resources/nips/56.md) | Report content/user |
| 1985 | Label | [32](../../resources/nips/32.md) | Content labeling |

## Application Events (2000-9999)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 2003 | Torrent | [35](../../resources/nips/35.md) | Torrent metadata |
| 2004 | Torrent Comment | [35](../../resources/nips/35.md) | Comment on torrent |
| 4550 | Community Post Approval | [72](../../resources/nips/72.md) | Approve community post |
| 5000-5999 | Job Request | [90](../../resources/nips/90.md) | DVM job requests |
| 6000-6999 | Job Result | [90](../../resources/nips/90.md) | DVM job results |
| 7000 | Job Feedback | [90](../../resources/nips/90.md) | DVM job feedback |
| 7374 | Reserved Cashu Wallet Tokens | [60](../../resources/nips/60.md) | Cashu reserved tokens |
| 7375 | Cashu Wallet Tokens | [60](../../resources/nips/60.md) | Cashu tokens |
| 7376 | Cashu Wallet History | [60](../../resources/nips/60.md) | Cashu transaction history |
| 8000 | Add User | [43](../../resources/nips/43.md) | Add user to relay |
| 8001 | Remove User | [43](../../resources/nips/43.md) | Remove user from relay |
| 9000-9030 | Group Control Events | [29](../../resources/nips/29.md) | Group management |
| 9041 | Zap Goal | [75](../../resources/nips/75.md) | Fundraising goal |
| 9321 | Nutzap | [61](../../resources/nips/61.md) | Cashu zap |
| 9734 | Zap Request | [57](../../resources/nips/57.md) | Lightning zap request |
| 9735 | Zap | [57](../../resources/nips/57.md) | Lightning zap receipt |
| 9802 | Highlights | [84](../../resources/nips/84.md) | Text highlight |

## Replaceable Events (10000-19999)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 10000 | Mute list | [51](../../resources/nips/51.md) | Muted users/events |
| 10001 | Pin list | [51](../../resources/nips/51.md) | Pinned notes |
| 10002 | Relay List Metadata | [65](../../resources/nips/65.md) | User's relay list |
| 10003 | Bookmark list | [51](../../resources/nips/51.md) | Bookmarked events |
| 10004 | Communities list | [51](../../resources/nips/51.md) | Joined communities |
| 10005 | Public chats list | [51](../../resources/nips/51.md) | Joined public chats |
| 10006 | Blocked relays list | [51](../../resources/nips/51.md) | Blocked relays |
| 10007 | Search relays list | [51](../../resources/nips/51.md) | Preferred search relays |
| 10009 | User groups | [51](../../resources/nips/51.md), [29](../../resources/nips/29.md) | Group memberships |
| 10012 | Favorite relays list | [51](../../resources/nips/51.md) | Favorite relays |
| 10013 | Private event relay list | [37](../../resources/nips/37.md) | Draft relay list |
| 10015 | Interests list | [51](../../resources/nips/51.md) | User interests |
| 10019 | Nutzap Mint Recommendation | [61](../../resources/nips/61.md) | Recommended mints |
| 10020 | Media follows | [51](../../resources/nips/51.md) | Followed media accounts |
| 10030 | User emoji list | [51](../../resources/nips/51.md) | Custom emoji |
| 10050 | Relay list to receive DMs | [51](../../resources/nips/51.md), [17](../../resources/nips/17.md) | DM relay preferences |
| 10063 | User server list | Blossom | File storage servers |
| 10166 | Relay Monitor Announcement | [66](../../resources/nips/66.md) | Monitor service announcement |
| 10312 | Room Presence | [53](../../resources/nips/53.md) | Live room presence |
| 13194 | Wallet Info | [47](../../resources/nips/47.md) | NWC wallet info |
| 13534 | Membership Lists | [43](../../resources/nips/43.md) | Access control lists |
| 17375 | Cashu Wallet Event | [60](../../resources/nips/60.md) | Wallet configuration |

## Ephemeral Events (20000-29999)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 21000 | Lightning Pub RPC | Lightning.Pub | RPC calls |
| 22242 | Client Authentication | [42](../../resources/nips/42.md) | Auth challenge response |
| 23194 | Wallet Request | [47](../../resources/nips/47.md) | NWC payment request |
| 23195 | Wallet Response | [47](../../resources/nips/47.md) | NWC payment response |
| 24133 | Nostr Connect | [46](../../resources/nips/46.md) | Remote signing |
| 24242 | Blobs stored on mediaservers | Blossom | File storage |
| 27235 | HTTP Auth | [98](../../resources/nips/98.md) | HTTP authentication |
| 28934 | Join Request | [43](../../resources/nips/43.md) | Request to join |
| 28935 | Invite Request | [43](../../resources/nips/43.md) | Invite to join |
| 28936 | Leave Request | [43](../../resources/nips/43.md) | Leave notification |

## Addressable Events (30000-39999)

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 30000 | Follow sets | [51](../../resources/nips/51.md) | Named follow lists |
| 30002 | Relay sets | [51](../../resources/nips/51.md) | Named relay lists |
| 30003 | Bookmark sets | [51](../../resources/nips/51.md) | Named bookmark collections |
| 30004 | Curation sets | [51](../../resources/nips/51.md) | Curated content lists |
| 30005 | Video sets | [51](../../resources/nips/51.md) | Video playlists |
| 30007 | Kind mute sets | [51](../../resources/nips/51.md) | Muted event kinds |
| 30008 | Profile Badges | [58](../../resources/nips/58.md) | Displayed badges |
| 30009 | Badge Definition | [58](../../resources/nips/58.md) | Define a badge |
| 30015 | Interest sets | [51](../../resources/nips/51.md) | Interest groups |
| 30017 | Create/update stall | [15](../../resources/nips/15.md) | Marketplace stall |
| 30018 | Create/update product | [15](../../resources/nips/15.md) | Marketplace product |
| 30019 | Marketplace UI/UX | [15](../../resources/nips/15.md) | Marketplace config |
| 30020 | Product auction | [15](../../resources/nips/15.md) | Auction listing |
| 30023 | Long-form Content | [23](../../resources/nips/23.md) | Blog post / article |
| 30024 | Draft Long-form Content | [23](../../resources/nips/23.md) | Draft article |
| 30030 | Emoji sets | [51](../../resources/nips/51.md) | Custom emoji packs |
| 30063 | Release artifact sets | [51](../../resources/nips/51.md) | Software releases |
| 30078 | Application-specific Data | [78](../../resources/nips/78.md) | App data storage |
| 30166 | Relay Discovery | [66](../../resources/nips/66.md) | Relay metadata |
| 30267 | App curation sets | [51](../../resources/nips/51.md) | Recommended apps |
| 30311 | Live Event | [53](../../resources/nips/53.md) | Live stream |
| 30312 | Interactive Room | [53](../../resources/nips/53.md) | Live room |
| 30313 | Conference Event | [53](../../resources/nips/53.md) | Conference |
| 30315 | User Statuses | [38](../../resources/nips/38.md) | Status updates |
| 30402 | Classified Listing | [99](../../resources/nips/99.md) | For sale listing |
| 30403 | Draft Classified Listing | [99](../../resources/nips/99.md) | Draft listing |
| 30617 | Repository announcements | [34](../../resources/nips/34.md) | Git repo |
| 30618 | Repository state | [34](../../resources/nips/34.md) | Repo state |
| 30818 | Wiki article | [54](../../resources/nips/54.md) | Wiki page |
| 30819 | Redirects | [54](../../resources/nips/54.md) | Wiki redirect |
| 31234 | Draft Event | [37](../../resources/nips/37.md) | Draft of any event |
| 31890 | Feed | Custom Feeds | Custom feed definition |
| 31922 | Date-Based Calendar Event | [52](../../resources/nips/52.md) | All-day event |
| 31923 | Time-Based Calendar Event | [52](../../resources/nips/52.md) | Scheduled event |
| 31924 | Calendar | [52](../../resources/nips/52.md) | Calendar definition |
| 31925 | Calendar Event RSVP | [52](../../resources/nips/52.md) | Event response |
| 31989 | Handler recommendation | [89](../../resources/nips/89.md) | App recommendations |
| 31990 | Handler information | [89](../../resources/nips/89.md) | App info |
| 34550 | Community Definition | [72](../../resources/nips/72.md) | Community settings |
| 38172 | Cashu Mint Announcement | [87](../../resources/nips/87.md) | Mint info |
| 38173 | Fedimint Announcement | [87](../../resources/nips/87.md) | Fedimint info |
| 37516 | Geocache listing | Geocaching | Geocache location |
| 38383 | Peer-to-peer Order events | [69](../../resources/nips/69.md) | P2P trading |
| 39000-9 | Group metadata events | [29](../../resources/nips/29.md) | Group info |
| 39089 | Starter packs | [51](../../resources/nips/51.md) | Onboarding packs |
| 39092 | Media starter packs | [51](../../resources/nips/51.md) | Media onboarding |
| 39701 | Web bookmarks | [B0](../../resources/nips/B0.md) | Browser bookmarks |

## Special Protocol Events

| Kind | Name | NIP | Description |
|------|------|-----|-------------|
| 443 | KeyPackage | Marmot | MLS key package |
| 444 | Welcome Message | Marmot | MLS welcome |
| 445 | Group Event | Marmot | MLS group event |
