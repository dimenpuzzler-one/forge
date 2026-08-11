# ADR-001: Local-first SQLite registry

## Decision

Forge stores its registry in SQLite under `FORGE_HOME` or `~/.forge`, not in the source repository.

## Consequences

The core works without a server and downloaded external data never pollutes Git history.

