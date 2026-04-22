# tests/system/pipelines/discovery

Runtime certification for the discovery-side service chain:

- `Seeder`
- `Finder`
- `Validator`
- `Monitor`

The tests here prove the handoff from static and HTTP relay discovery through
validation and metadata persistence against the composed stack and a real relay
boundary.
