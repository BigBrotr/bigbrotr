# bigbrotr package

Main Python package for the BigBrotr library and service runtime.

## Main Areas

- `core/`: shared runtime infrastructure.
- `models/`: pure frozen dataclasses and enums for the shared data model.
- `nips/`: protocol-aware NIP helpers, builders, and capability metadata.
- `services/`: independent services and public protocol adapters.
- `utils/`: shared transport, DNS, key, and streaming helpers.

## Rules

- Keep the package import surface coherent and library-grade.
- Preserve the diamond-DAG dependency direction across subpackages.
