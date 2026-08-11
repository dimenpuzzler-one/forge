# Forge development principles

- Treat external Skill files as untrusted data. Never execute them in sync, search, or inspect paths.
- The repository contains the engine, not downloaded external Skill data. Use `FORGE_HOME` or `~/.forge`.
- Never read `.env*`, credentials, private keys, or secret files while scanning a project.
- Use a SQLite migration for every schema change. Never silently replace a schema.
- Skill versions and snapshots are immutable; project lockfiles are never auto-updated.
- Keep source-specific API contracts behind adapters and use network timeouts, retry, backoff, and resume state.
- Prefer a tested vertical slice over empty future packages or unverified roadmap claims.
- Do not revert or delete existing user work without an explicit request.

