# Forge implementation status

Last updated: 2026-08-11

This is the implementation ledger for the phases in `FORGE_CODEX_IMPLEMENTATION_BRIEF.md`. “Complete” means implemented, tested, and smoke-tested locally unless a limitation is explicitly noted.

| Phase | Status | Implemented scope | Verification | Remaining / risk |
| --- | --- | --- | --- | --- |
| 0 — Bootstrap | Complete | Python 3.12 package layout, CLI entry point, ignore rules, ADRs, test layout | compileall; unittest; editable install; `forge doctor` | First push pending origin setup |
| 1 — Project Scanner v0 | Complete | Safe root detection; legacy README selection/stub rules; bounded document scan; `.forge/project.json` | Scanner unit/regression tests; `forge scan C:\dev\forge` | More project-specific signal extractors will follow recommender needs |
| 2 — Registry + metadata sync | Complete (fixture-tested) | Versioned SQLite schema/migration; metadata upsert; page resume cursor; retry/backoff/rate-limit handling; skills.sh adapter | Adapter contract tests and two-page integration flow | Live API requires `VERCEL_OIDC_TOKEN`; no token is available in this environment |
| 3 — Search + Inspect | Complete (fixture-tested) | SQLite FTS5 search; local result display; on-demand detail fetch; immutable snapshot cache; path/size safety checks | Registry and end-to-end cache integration tests; local search smoke test | Live inspect also requires skills.sh authentication |
| 4 — Recommend + pin/lock | Complete | Explainable local project recommendations; explicit immutable hash pins in project-local `skills.lock` | 14 tests, including CLI recommend → inspect-cache → pin flow | Rules are intentionally small and deterministic; richer evidence comes later |
| 5 — Collections + composition | Complete | Local collections; provenance-preserving cached-hash composition manifests; deterministic analysis | 17 tests, including CLI collection and compose flow | No LLM ideation/play runtime yet by design |
| 6 — Evaluation + version lifecycle | Complete | Local static audit, license status, optional upstream audit import, version refresh/diff, cached update reporting | 20 tests, including CLI diff + outdated preserving a pin | Static signals are not a safety guarantee; live audit requires OIDC |
| 7 — Runtime + agent adapter | In progress | Generic filesystem session materialization and `forge bundle`/`use` | 21 tests, including isolated bundle with a script file | No specialized Agent adapter or project audit yet |
| 8+ — Explorer, graph, labs, learning | Not started | — | — | Build only as working local slices |

## Phase 0–3 details

### Major files

- `apps/cli/forge/cli.py` — `doctor`, `scan`, `sync`, `search`, `inspect`
- `packages/project/forge_project/scanner.py` — bounded secret-safe project context collector
- `packages/registry/forge_registry/database.py` — migration, FTS5, metadata, immutable versions/files
- `packages/sources/forge_sources/skills_sh.py` — API contract boundary and resumable sync
- `tests/` — unit, contract, and integration coverage with synthetic fixtures only

### Decisions

- Registry data is global (`FORGE_HOME` / `~/.forge`) rather than repository data.
- The existing `C:\dev\readmecollects` Collector is preserved. Its root README priority and stub behavior are covered by Scanner regression tests.
- External files are cached only after rejecting unsafe paths and oversized content; no code path executes them.
- Metadata is committed page by page before the resume state advances.

### Latest verification

```text
python -m compileall -q apps packages tests                 PASS
python -m unittest discover -s tests -t . -v                PASS (11 tests)
python -m forge --forge-home .test-forge-home doctor        PASS
python -m forge scan C:\dev\forge                           PASS
python -m forge --forge-home .test-forge-home search ...    PASS (expected empty local registry)
CLI recommend → pin with cached detail hash                    PASS (integration test)
CLI collection / compose create / show / analyze              PASS
CLI cached-version diff / outdated (no pin mutation)          PASS
Generic session bundle materialization (no script execution)  PASS
```

The missing-ID `inspect` smoke test returned the intended action-oriented error. A live sync/inspect run is blocked only by absent `VERCEL_OIDC_TOKEN`, not by an implementation failure.

## Live skills.sh validation and catalog-sync lifecycle

The user completed live validation against skills.sh on 2026-08-11:

```text
First metadata sync:  9,610 catalog entries stored successfully
Local search:         successful
Live inspect:         successful
Immutable hash/files: stored successfully
Upstream security audit: imported successfully
Forge static audit:   ran separately and successfully
Second metadata sync: 9,610 discovered / 0 inserted / 9,610 updated / 97 pages
```

The second result proved catalog correctness and exposed a write-amplification issue: before migration 3, unchanged metadata still issued an update and refreshed FTS. Migration 3 changes this to `unchanged` accounting with no `skills` or FTS write. It also records total/request statistics, emits progress from API pagination totals, exposes `forge status`/`doctor` freshness, and adds explicit `forge sync --if-stale 6h` skipping. `--changed-only` is intentionally deferred because listing-only incremental sync would sacrifice catalog correctness.

The subsequent live run after migration 3 confirmed the optimization: `9,610 discovered / 0 inserted / 0 updated / 9,610 unchanged / 97 pages / 97 requests`. This is the correct sequential 100/page baseline before the 500/page network tuning.

Implementation commit: `8743176` (`improve catalog sync freshness and observability`), pushed to `origin/main`.

Pagination performance commit: `cf7bf57` (`increase skills catalog sync page size`), pushed to `origin/main`.

### Pagination performance follow-up

The first measured full catalog recheck took `229.094s` for `9,610` Skills over `97` requests at 100 entries/page. The bottleneck is sequential network round-trips, not database upserts. The default page size is now 500, reducing the expected listing requests to `ceil(9610 / 500) = 20`; progress and totals use the response's `perPage` and `total` fields. Sequential 500/page remains the deliberate first tuning step. Bounded concurrent fetch (for example, 4 workers) remains a future option only if a new live measurement still warrants it; it must retain ordered transactional writes, retry/backoff, and resume correctness.

## Global skills.sh authentication

Forge resolves skills.sh authentication without depending on the current directory: process `VERCEL_OIDC_TOKEN` first, then the Forge-owned `<FORGE_HOME>/credentials.env`, then the known Forge checkout `.env.local` for development compatibility. It never searches a target project's `.env` file. The current token was migrated as a single `VERCEL_OIDC_TOKEN` entry into `C:\Users\beric\.forge\credentials.env` with current-user-only ACLs. `forge doctor` exposes only availability and source labels.

Live acceptance from `C:\dev\oracross`: `forge search`, `forge inspect --refresh`, and `forge audit-skill` all succeeded through global Forge authentication; live audit partners and Forge static audit returned results without exposing the token.

## Phase 4 details

- `forge recommend [path]` derives candidates only from explicit Scanner evidence (stack, languages, domains) and local FTS results. Each result shows the rule evidence and cached-detail caution.
- `forge pin <skill-id>` refuses metadata-only entries; it writes an exact locally cached content hash to `<project>/.forge/skills.lock` only after an explicit invocation.
- `packages/project/forge_project/recommend.py` and `lockfile.py` keep recommendation and lock serialization outside the CLI boundary.

## Phase 5 details

- Registry migration 2 adds collections and composition tables.
- `forge collection` stores local Skill references without copying source content.
- `forge compose` requires cached immutable versions and stores only ID/source/hash/role/position. Its deterministic analysis flags risk signals but does not execute scripts.

## Phase 6 details

- Detail cache writes a local static audit (`forge-static`) with script, suspicious download/payload, and credential-exfiltration signals, plus a license status when the detail provides one.
- `forge inspect --refresh` is an explicit version check; new content hashes retain prior cached files.
- `forge diff` compares two cached hashes; `forge outdated` reports newer cached versions without changing project locks; `forge audit-skill` imports upstream audits only on demand.

## Phase 7 baseline details

- `forge bundle` materializes a composition's selected cached hashes into a unique global session directory.
- `forge use` does the same for a single explicitly cached immutable Skill.
- The generic filesystem adapter creates an instruction string only; it neither starts an agent nor executes external scripts.

## Commit ledger

| Milestone | Commit | Push |
| --- | --- | --- |
| Phase 0–3 initial vertical slice | `914dc4b`, `3ef4ea8`, `12d75e3` | Pushed to `origin/main` |
| Phase 4 recommendation + lock | `fe57624` | Pushed to `origin/main` |
| Phase 5 collections + composition | `b358335` | Pushed to `origin/main` |
| Phase 6 version lifecycle + safety | `ec1be3d` | Pushed to `origin/main` |
| Phase 7 generic filesystem adapter baseline | `13ebe3b` | Pushed to `origin/main` |
