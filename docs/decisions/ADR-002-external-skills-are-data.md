# ADR-002: External Skills are data, not Git source

External Skill files are untrusted input. Sync, search, and inspect never execute them, and their cache/snapshots live outside this repository.

