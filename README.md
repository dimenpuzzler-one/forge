# Forge

Forge is a local-first Skill exploration and engineering toolkit. It indexes publicly available Agent Skills, lets you search and inspect the locally cached registry, and builds a safe, machine-readable context for the software project you are working on.

It is deliberately more than a skills.sh downloader: the long-term product connects versioned Skill knowledge with project context, explicit pins, composition experiments, audits, and agent adapters. MVP-0 implements the first usable vertical slice:

```text
forge scan
forge sync --source skills-sh --metadata-only
forge search "postgres production"
forge inspect <skill-id>
```

## Safety and storage boundaries

- Forge source code and external Skill data are separate. Registry data lives in `FORGE_HOME`, or `~/.forge` when it is unset.
- skills.sh auth is global: Forge uses `VERCEL_OIDC_TOKEN` from the process first, then `<FORGE_HOME>/credentials.env`, then the known Forge checkout `.env.local` for development compatibility. It never searches the current project or target project for `.env` files.
- External `SKILL.md` files and scripts are untrusted data. Forge does not execute them during sync, search, or inspect.
- Detail caching validates paths and size before writing an immutable snapshot. Script files are explicitly marked, never run.
- Project scanning excludes `.env*`, credentials, private keys, Git internals, dependency folders, build outputs, binary data, and large files.
- Metadata sync discovers updates; it never applies or pins a newer Skill to a project automatically.

## Install and run

Requires Python 3.12+.

```powershell
cd C:\dev\forge
python -m pip install --no-deps -e .
forge doctor
```

Use a throwaway data directory while evaluating Forge:

```powershell
$env:FORGE_HOME = "$PWD\.forge-data"
forge doctor
```

`FORGE_HOME` is global registry storage; it is not the `.forge` directory that `forge scan` creates inside a scanned project.

For persistent local skills.sh authentication, put only the required token in the global, Git-unrelated file:

```text
%USERPROFILE%\.forge\credentials.env
```

`forge doctor` reports only `skills.sh auth: available|missing` and `auth source: process-env|forge-local-env|none`; it never prints the token.

## Commands implemented in MVP-0

### Scan a project

```powershell
cd C:\dev\stockback
forge scan
```

The command writes `.forge\project.json` with a bounded, reproducible context: project root, detected languages and stack, domain/architecture hints, test-command hints, and the safe documents considered. It does not execute project code.

### Sync metadata

```powershell
forge sync --source skills-sh --metadata-only
```

The official skills.sh API currently requires a Vercel OIDC bearer token. Configure `VERCEL_OIDC_TOKEN` in your own environment before syncing; Forge never prints it. Metadata pages are committed individually and the next page is recorded in SQLite, so an interrupted sync resumes from the saved page. Full Skill files are not fetched here.

Use explicit freshness policy when you want to avoid a catalog recheck that is unlikely to add value:

```powershell
forge sync --source skills-sh --metadata-only --if-stale 6h
forge status
```

Normal `forge sync` always rechecks the full catalog for correctness. It requests the maximum supported `500` entries per page by default (override with `--per-page 1..500`), displays API-derived page/total progress, and reports discovered, inserted, updated, unchanged, pages, duration, and request count. Identical metadata is counted as `unchanged` without rewriting its `skills` row or FTS entry. Forge deliberately does **not** provide `--changed-only`: the listing API does not safely identify a complete changed subset. Detail/hash refresh remains an explicit `forge inspect <id> --refresh` operation.

### Search the local registry

```powershell
forge search "postgres production"
```

Search uses SQLite FTS5 over locally synced name, description, source, and owner fields. It does not make a network request.

### Inspect a Skill

```powershell
forge inspect vercel-labs/skills/find-skills
```

When metadata exists but detail is missing, inspect fetches it on demand, validates it, stores a new immutable version/snapshot, and prints the file tree and `SKILL.md`. Pass `--no-fetch` to see metadata without making that request.

### Diagnose the environment

```powershell
forge doctor --project C:\dev\stockback
```

This checks the data directory, SQLite schema/FTS5, Python, configured skills.sh authentication (without revealing the token), and an optional project path.

### Recommend Skills for a scanned project

```powershell
forge recommend C:\dev\stockback
```

Recommendations are deterministic and evidence-led: stack, language, and domain signals activate focused local-registry searches. Each result states the project evidence and any relevant caution (for example, when detail has not been inspected locally). Forge does not call an LLM or network service for this command.

### Pin an explicit, immutable version

```powershell
forge inspect acme/skills/example
forge pin acme/skills/example --project C:\dev\stockback --reason "production review"
```

`forge pin` requires a locally cached detail hash, then writes that exact hash to `<project>\.forge\skills.lock`. A newer upstream version never changes a pin automatically.

### Review cached version safety and updates

```powershell
forge inspect acme/skills/example --refresh
forge audit-skill acme/skills/example
forge diff acme/skills/example <old-hash> <new-hash>
forge outdated --project C:\dev\stockback
```

`inspect` stores a local static-audit signal and available license metadata with the immutable version. `audit-skill` explicitly imports available upstream audit partners; no automatic audit/network refresh happens during local search. `outdated` only reports a newer **cached** version and never changes `skills.lock`; promotion remains an explicit `inspect` and `pin` decision.

### Prepare a generic agent session bundle

```powershell
forge bundle "production-review" --project C:\dev\stockback
forge use acme/skills/example --project C:\dev\stockback --goal "Review this change"
```

Both commands create a new global `sessions/session-.../` directory containing `manifest.json`, `project-context.json`, and copies of explicitly selected cached Skill files. The generic filesystem adapter always records `executeScripts: false`; it prepares reference material and does not launch an agent or execute any Skill code.

### Collect and compose Skills

```powershell
forge collection create "production-saas"
forge collection add "production-saas" acme/skills/example
forge collection show "production-saas"

forge compose create "production-review" --goal "Production readiness review"
forge compose add "production-review" acme/skills/example --role database
forge compose show "production-review"
forge compose analyze "production-review"
```

Collections are local references. A composition stores an ordered manifest of Skill ID, source, immutable cached hash, and role; it never merges upstream files. `compose analyze` is deterministic and reports empty compositions, duplicate roles, script presence, and multi-source provenance cautions without executing anything.

## Development

The repository uses a small Python monorepo boundary:

- `apps/cli/` — CLI entry point
- `packages/core/` — paths, errors, shared models
- `packages/project/` — secret-safe Project Scanner
- `packages/registry/` — SQLite migrations, versions, snapshots
- `packages/sources/` — skills.sh adapter and sync resilience
- `packages/search/` — local search boundary

Run the current checks on Windows PowerShell:

```powershell
$env:PYTHONPATH = 'apps/cli;packages/core;packages/project;packages/registry;packages/sources;packages/search'
python -m compileall -q apps packages tests
python -m unittest discover -s tests -t . -v
```

## Roadmap

Next: project audit and local Skill extraction. Later phases add specialized agent adapters, web exploration, Skill Graphs, and research labs. These are design boundaries, not currently implemented commands.

Current milestone: **Phase 0–7 generic adapter baseline is implemented and fixture-tested.** Live skills.sh sync/inspect/audit needs a caller-provided OIDC token; the status ledger distinguishes that external limitation from local verification. See [implementation status](docs/roadmap/IMPLEMENTATION_STATUS.md) and the [development log](docs/development-log/2026-08-11.md).

See [MVP-0 architecture](docs/architecture/mvp-0.md) and [ADRs](docs/decisions/) for the decisions behind the local-first, immutable, deterministic core.

## License and provenance

Forge retains source/provenance fields and treats external Skill licenses as a separate future enrichment concern. Public availability does not grant Forge permission to redistribute cached Skill content. The local cache is for the user's inspection; a future public Explorer must apply license policy before exposing full contents.
