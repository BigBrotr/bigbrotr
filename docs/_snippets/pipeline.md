```mermaid
flowchart TD
    DB[("PostgreSQL")]

    SE["Seeder<br/><small>Bootstrap</small>"]
    FI["Finder<br/><small>Discovery</small>"]
    VA["Validator<br/><small>Verification</small>"]
    MO["Monitor<br/><small>Health checks</small>"]
    SY["Synchronizer<br/><small>Event collection</small>"]
    RE["Refresher<br/><small>View refresh</small>"]
    AP["Api<br/><small>REST API</small>"]
    DV["Dvm<br/><small>Data Vending Machine</small>"]

    SE --> DB
    FI --> DB
    VA --> DB
    MO --> DB
    SY --> DB
    RE --> DB
    AP --> DB
    DV --> DB

    style SE fill:#7B1FA2,color:#fff,stroke:#4A148C
    style FI fill:#7B1FA2,color:#fff,stroke:#4A148C
    style VA fill:#7B1FA2,color:#fff,stroke:#4A148C
    style MO fill:#7B1FA2,color:#fff,stroke:#4A148C
    style SY fill:#7B1FA2,color:#fff,stroke:#4A148C
    style RE fill:#7B1FA2,color:#fff,stroke:#4A148C
    style AP fill:#7B1FA2,color:#fff,stroke:#4A148C
    style DV fill:#7B1FA2,color:#fff,stroke:#4A148C
    style DB fill:#311B92,color:#fff,stroke:#1A237E
```
