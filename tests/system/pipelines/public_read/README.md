# tests/system/pipelines/public_read

Runtime certification for the public-read service surfaces:

- `API`
- `DVM`

The tests here prove that the same shared read state is exposed coherently
through the HTTP API and the NIP-90 relay boundary, including live updates
after the underlying database state changes.
