# tests/system/services/api

Real runtime certification for the HTTP `API` service.

## What Lives Here

- composed-stack execution of the shipped `api` container for `bigbrotr` and `lilbrotr`;
- live PostgreSQL seeding of relay, event, and derived read-surface data consumed by the adapter;
- host-side HTTP assertions against health, discovery, list, and detail routes on the real bound port;
- restart proof for the uvicorn-backed runtime task and request logging boundary;
- and profile proof that shipped exposure-policy differences stay observable at the real HTTP surface.

## Rules

- hit the real HTTP port exposed by the composed stack, never a direct in-process FastAPI app;
- seed only authored tables and refresh procedures that the read surface actually depends on;
- keep assertions focused on transport contract, payload semantics, and profile-owned exposure policy;
- and capture HTTP/container/database artifacts for every certified run.
