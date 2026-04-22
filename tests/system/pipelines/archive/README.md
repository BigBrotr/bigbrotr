# tests/system/pipelines/archive

Runtime certification for the archive-side service chain:

- `Validator`
- `Synchronizer`

The tests here prove that validated relays become real archive inputs and that
live event ingestion resumes honestly after restart without duplicate drift.
