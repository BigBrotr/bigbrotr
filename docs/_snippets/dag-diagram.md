```mermaid
graph TD
    S["<b>services</b><br/><small>Business logic</small>"]
    C["<b>core</b><br/><small>Pool, Brotr, BaseService</small>"]
    N["<b>nips</b><br/><small>NIP-11, NIP-66</small>"]
    U["<b>utils</b><br/><small>DNS, Keys, Transport</small>"]
    M["<b>models</b><br/><small>Pure dataclasses</small>"]

    S --> C
    S --> N
    S --> U
    N --> C
    N --> U
    C --> M
    N --> M
    U --> M
```
