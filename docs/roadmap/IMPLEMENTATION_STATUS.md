# Forge implementation status

Last updated: 2026-08-11

This is the implementation ledger for the phases in `FORGE_CODEX_IMPLEMENTATION_BRIEF.md`. “Complete” means implemented, tested, and smoke-tested locally unless a limitation is explicitly noted.

| Phase | Status | Implemented scope | Verification | Remaining / risk |
| --- | --- | --- | --- | --- |
| 0 — Bootstrap | Complete | Python 3.12 package layout, CLI entry point, ignore rules, ADRs, test layout | compileall; unittest; `forge doctor` | Initial Git remote/push pending first commit |
| 1 — Project Scanner v0 | Complete | Safe root detection; legacy README selection/stub rules; bounded document scan; `.forge/project.json` | Scanner unit/regression tests; `forge scan C:\dev\forge` | More project-specific signal extractors will follow recommender needs |
| 2 — Registry + metadata sync | Complete (fixture-tested) | Versioned SQLite schema/migration; metadata upsert; page resume cursor; retry/backoff/rate-limit handling; skills.sh adapter | Adapter contract tests and two-page integration flow | Live API requires `VERCEL_OIDC_TOKEN`; no token is available in this environment |
| 3 — Search + Inspect | Complete (fixture-tested) | SQLite FTS5 search; local result display; on-demand detail fetch; immutable snapshot cache; path/size safety checks | Registry and end-to-end cache integration tests; local search smoke test | Live inspect also requires skills.sh authentication |
| 4 — Recommend + pin/lock | Not started | — | — | Next vertical slice |
| 5 — Collections + composition | Not started | — | — | Follows project-use workflow |
| 6 — Evaluation + version lifecycle | Not started | — | — | Security, license, diff, update availability |
| 7 — Runtime + agent adapter | Not started | — | — | Generic filesystem bundle first |
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
```

The missing-ID `inspect` smoke test returned the intended action-oriented error. A live sync/inspect run is blocked only by absent `VERCEL_OIDC_TOKEN`, not by an implementation failure.

## Commit ledger

| Milestone | Commit | Push |
| --- | --- | --- |
| Phase 0–3 initial vertical slice | Pending first commit | Pending first push |

