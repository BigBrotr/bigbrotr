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
```
