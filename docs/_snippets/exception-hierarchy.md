```
BigBrotrError (base)
├── ConfigurationError
├── DatabaseError
│   ├── ConnectionPoolError (transient, retry)
│   └── QueryError (permanent)
├── ConnectivityError
│   ├── RelayTimeoutError
│   └── RelaySSLError
├── ProtocolError
└── PublishingError
```
