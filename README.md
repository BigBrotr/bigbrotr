## What is Bigbrotr?

**Bigbrotr** is an advanced, open-source, and modular infrastructure built for the [Nostr](https://nostr.com) protocol. It is designed to comprehensively archive *all public events* across the entire network—both clearnet and Tor relays—while providing deep insights into relay behavior, event redundancy, and user interaction patterns.

Think of Bigbrotr as a “black box” recorder for Nostr: continuously collecting, mapping, and analyzing everything happening across relays in real time. Unlike solutions that focus on isolated protocol features, Bigbrotr functions as a full-archive instance of the entire network, offering structured metadata and powerful analytical tools tailored for developers, researchers, relay operators, and users alike.

With a mission to improve transparency, enable open research, and foster true decentralization, Bigbrotr empowers the community by providing unparalleled visibility and archival capabilities within the Nostr ecosystem—serving as a foundational tool to strengthen and support the decentralized network.

---

## Core Features

- 🗂 **Full Event Archive**: Chronologically stores all events from every reachable relay.
- 🌍 **Relay Mapping**: Detects and indexes new relays using historical snapshots and live discovery (e.g. Nostr.Watch).
- 🛰 **Live Monitoring**: Measures relay health and connectivity daily (RTT, availability, NIP-11 support).
- 🔍 **Redundancy Tracking**: Tracks which relays host each event, revealing true network distribution.
- 🧅 **Tor-Enabled**: Built-in Tor support for full `.onion` relay access.
- 🧠 **Graph Analysis Ready**: Ideal for social graph and protocol research, spam detection, and more.
- 🧾 **DVM Integration Ready**: Easily integrates with Nostr-native Data Vending Machines to provide custom data services and insights.

---

## Get Involved

- **Getting Started**: Spin up your own Bigbrotr instance and start archiving the Nostr universe in minutes. [Follow the setup guide](https://bigbrotr.com/guides/getting-started/)
- **Read the Documentation**: Dive into the data model, synchronization logic, and modular architecture powering Bigbrotr. [Explore the docs](https://bigbrotr.com/api/bigbrotr/)
- **Explore the Architecture**: Learn how the Docker containers work together to find, monitor, and archive the Nostr network. [Architecture guide](https://bigbrotr.com/guides/system-architecture/)
- **Explore the Database Schema**: View how Bigbrotr organizes and stores Nostr events, relays, and metadata. [Database guide](https://bigbrotr.com/guides/database-schema/)

---

## Why It Matters

Nostr’s decentralized nature eliminates any central authority, granting unprecedented freedom but also creating challenges around network visibility, coordination, and data integrity. Bigbrotr addresses these challenges by serving as a comprehensive, transparent “black box” archive of the entire Nostr ecosystem.

By continuously monitoring and archiving every public event across clearnet and Tor relays, Bigbrotr provides critical insights into relay health, event redundancy, and network topology. This empowers developers, researchers, relay operators, and users to:

- Understand relay uptime, behavior, and real-world performance metrics  
- Detect and prevent centralization risks by discovering and mapping new relays  
- Access structured data and metadata ideal for social graph analysis, spam detection, and protocol research  
- Preserve valuable historical network data before it disappears  
- Facilitate custom integrations and advanced services like Data Vending Machines (DVMs) built on top of Bigbrotr’s data  

Built by and for the FOSS community, Bigbrotr is MIT licensed and designed to foster a transparent, open, and truly decentralized Nostr ecosystem.

---

## Next Steps

- 📊 Develop interactive dashboards for real-time visual insights into relay and network activity  
- 🧪 Provide a public API enabling real-time queries and detailed relay health monitoring  
- 🛠 Enable exportable metrics to help relay operators optimize performance and reliability  
- 💬 Build a Nostr bot that shares up-to-date relay statistics and network health information  
- 🧰 Integrate with Grafana and offer custom Prometheus endpoints for advanced metrics visualization  
- 🌐 Launch a public explorer to browse relay statuses and archived events effortlessly
- 📦 Offer downloadable data snapshots to support researchers and data scientists  
- 🏗️ Create Data Vending Machines leveraging Bigbrotr’s comprehensive data archive for tailored Nostr-native data services  

This roadmap aims to enhance transparency, empower the community, and extend Bigbrotr’s capabilities as a foundational tool for the evolving Nostr ecosystem.
