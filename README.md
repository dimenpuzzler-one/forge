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

Next: deterministic project recommendations, pin/lockfiles, collections and composition manifests. Later phases add provenance enrichment, security/audit signals, agent session bundles, web exploration, Skill Graphs, and local Skill extraction. These are design boundaries, not currently implemented commands.

Current milestone: **Phase 0–3 is implemented and fixture-tested.** Live skills.sh sync/inspect needs a caller-provided OIDC token; the status ledger distinguishes that external limitation from local verification. See [implementation status](docs/roadmap/IMPLEMENTATION_STATUS.md) and the [development log](docs/development-log/2026-08-11.md).

See [MVP-0 architecture](docs/architecture/mvp-0.md) and [ADRs](docs/decisions/) for the decisions behind the local-first, immutable, deterministic core.

## License and provenance

Forge retains source/provenance fields and treats external Skill licenses as a separate future enrichment concern. Public availability does not grant Forge permission to redistribute cached Skill content. The local cache is for the user's inspection; a future public Explorer must apply license policy before exposing full contents.
