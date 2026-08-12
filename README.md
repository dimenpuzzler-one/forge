# Forge

Forge is a local-first Skill exploration and engineering toolkit. It indexes publicly available Agent Skills, lets you search and inspect the locally cached registry, and builds a safe, machine-readable context for the software project you are working on.

It is deliberately more than a skills.sh downloader: the long-term product connects versioned Skill knowledge with project context, explicit pins, composition experiments, audits, and agent adapters.

```text
forge scan
forge sync --source skills-sh --metadata-only
forge search "postgres production"
forge inspect <skill-id>
forge plan "landing page conversion redesign"
forge benchmark
```

**Core thesis.** A language model judges what a goal means. Forge enforces what is true: which
Skills exist, at which immutable hash, from which source, having passed which audit, and at
what risk level. A model's selection is a proposal; admission is a separate deterministic
decision that the model cannot influence.

**Current honest status.** The safety boundary is demonstrated by tests — six adversarial
probes covering every ADR-006 invariant pass. The planning *quality* is measured and currently
modest: the benchmark's ranking gap is 0.00, meaning reranking recovers nothing that retrieval
had not already surfaced, and three defects are open. Forge is a policy-bounded planner
foundation, not a system that has been shown to pick better Skills than a good prompt.

## Safety and storage boundaries

- Forge source code and external Skill data are separate. Registry data lives in `FORGE_HOME`, or `~/.forge` when it is unset.
- skills.sh auth is global: Forge uses `VERCEL_OIDC_TOKEN` from the process first, then `<FORGE_HOME>/credentials.env`, then the known Forge checkout `.env.local` for development compatibility. It never searches the current project or target project for `.env` files.
- A planning provider is a proposer, never an authority. It receives only Skill metadata — id, name, source, truncated description — never Skill file contents, and it cannot admit a Skill, choose a version hash, or lower a task's risk level. See [ADR-006](docs/decisions/ADR-006-llm-planner-cannot-override-the-policy-gate.md).
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

### Plan a goal (Vol.2 V2.1)

```powershell
forge plan "landing page conversion redesign" --project C:\dev\oracross
forge plan "landing page conversion redesign" --provider openai --model gpt-5.6-luna
forge plan "landing page conversion redesign" --provider anthropic
```

`forge plan` turns a goal into a Skill selection in two stages with opposite trust properties.

**Forge retrieves.** Stop words are dropped, project stack/domain/language terms are added,
and SQLite FTS returns a bounded candidate list. No network, no model.

**A provider proposes.** It receives the goal, a trimmed project context, and that candidate
list — id, name, source, truncated description only. Skill file contents are never sent. It
returns task roles, a selection with reasons, exclusions, a risk level, and a verification plan.
Everything it returns is untrusted.

**Forge admits.** Each nomination must clear four deterministic checks: it was in the retrieved
candidate set, it exists in the local registry, its detail is cached at an immutable hash, and
its static audit is not a hard block. Anything else is rejected with a recorded reason, and
invented Skill ids are counted and reported. Forge may raise the risk level from the goal text
(auth, payment, credential, secret, migration, billing, production) but never lowers what the
provider reported. See [ADR-006](docs/decisions/ADR-006-llm-planner-cannot-override-the-policy-gate.md).

#### Providers

| Provider | Network | Key | Notes |
| --- | --- | --- | --- |
| `stub` (default) | no | none | Lexical overlap only. Exists to make the pipeline testable, not to produce good plans. It says so in every artifact it writes. |
| `anthropic` | yes | `ANTHROPIC_API_KEY` | Messages API. Default model `claude-sonnet-5`. |
| `openai` | yes | `OPENAI_API_KEY` | Chat Completions. Default model `gpt-5.6-luna`. |

Both network providers use only the standard library, so Forge still declares no runtime
dependencies. Skill file contents are never sent to any provider — only id, name, source, and
a truncated description.

```powershell
# Current session only
$env:OPENAI_API_KEY = "sk-..."

# Persist for your user account (open a new terminal afterwards)
[Environment]::SetEnvironmentVariable("OPENAI_API_KEY", "sk-...", "User")

# Confirm it exists without printing it
[bool]$env:OPENAI_API_KEY
```

The OpenAI provider also reads `OPENAI_MODEL` and `OPENAI_BASE_URL`. Point `OPENAI_BASE_URL`
at any OpenAI-compatible gateway to use one; the request shape is plain Chat Completions.

A model name is not a provider name. Use `--provider openai --model gpt-5.6-luna`; passing a
model to `--provider` fails with a message that says so.

Both write `<FORGE_HOME>\plans\<plan-id>\plan.json` and `plan.md`. `plan.json` is normalized data
for later stages; `plan.md` is the human review surface and separates observed local facts from
inferred model judgment. A plan can legitimately admit zero Skills; that is reported as a blocker
rather than filled in with a weaker selection.

`forge plan` does not compose, bundle, or run anything. It produces a reviewable proposal.

### Measure the planner

```powershell
forge benchmark
forge benchmark --external-provider openai --model gpt-5.6-luna
```

`forge benchmark` runs three variants over the same fixture scenarios, through the same
retrieval and the same policy gate, so any difference is attributable to ranking alone.

| Variant | Ranking | Isolates |
| --- | --- | --- |
| A — retrieval-only | none; raw FTS order | the no-model floor |
| B — stub lexical | goal-term overlap | what a trivial reranker adds |
| C — LLM provider | semantic | what a real reranker adds |

It writes `artifacts/planner-benchmark/benchmark-summary.json` and `benchmark-report.md`, and
exits non-zero if any ADR-006 policy probe regresses, so it can be wired into CI directly. It
builds an isolated throwaway registry and never reads or writes your real one — an integration
test asserts this. If a network provider fails partway, that variant is dropped whole and the
reason is recorded; the offline results survive.

#### What the benchmark proves today

A provider cannot get past the policy gate. Six adversarial probes cover the ADR-006
invariants and all six pass:

| Probe | Invariant |
| --- | --- |
| P1 | An invented Skill id cannot enter a plan |
| P2 | A Skill with no immutable cached hash cannot enter a plan |
| P3 | A hard audit block cannot be argued past |
| P4 | A provider cannot lower risk — Forge raised "low" to "high" on a payment goal |
| P5 | Duplicate nominations collapse to one admission |
| P6 | Registry existence is not enough; the candidate-set check is independent |

Both deterministic variants reproduce exactly across consecutive runs, and explanation
coverage is 1.00 — every admitted, excluded, and rejected Skill carries a reason.

#### What it does not prove

Measured on the current fixture, the **ranking gap is 0.00**: role recall exactly equals the
retrieval ceiling, meaning reranking recovered nothing that retrieval had not already
surfaced. Retrieval, not ranking, is the binding constraint. The LLM variant has not been run.

Also unmeasured: whether a Forge plan produces better code than a plain prompt (needs agent
execution, which V2.1 does not perform), and whether historical evidence or adaptive
exploration help (V2.2 owns both).

Forge is a **policy-bounded planner foundation**. The safety boundary is demonstrated by
tests. The selection quality is measured and currently modest, with three open defects
recorded in [the benchmark findings](docs/roadmap/PLANNER_BENCHMARK.md) — an unreachable audit
block, no retrieval stemming, and silent role substitution — alongside a FIX-V2.1-FIRST
recommendation.

## Development

The repository uses a small Python monorepo boundary:

- `apps/cli/` — CLI entry point
- `packages/benchmark/` — planner measurement harness, fixtures, adversarial policy probes
- `packages/core/` — paths, errors, shared models
- `packages/planner/` — provider abstraction, deterministic policy gate, plan artifacts
- `packages/project/` — secret-safe Project Scanner
- `packages/registry/` — SQLite migrations, versions, snapshots
- `packages/sources/` — skills.sh adapter and sync resilience
- `packages/search/` — local search boundary

Run the current checks on Windows PowerShell:

```powershell
$env:PYTHONPATH = 'apps/cli;packages/benchmark;packages/compose;packages/core;packages/planner;packages/project;packages/registry;packages/runtime;packages/sources;packages/search'
python -m compileall -q apps packages tests
python -m unittest discover -s tests -t . -v
forge benchmark          # exits non-zero if an ADR-006 policy probe regresses
```

Tests never make a network call. The two network providers expose a `_post` seam that the
tests replace, so request shape, error translation, and response parsing are verified without
a key. What that cannot prove is that a live endpoint accepts the request — running
`forge benchmark --external-provider openai` with a real key is still outstanding.

## Roadmap

Current milestone: **Vol.2 V2.1 planner foundation plus its benchmark.** Phases 0–7 are
implemented and fixture-tested; `forge plan` and `forge benchmark` are the newest slices.

The benchmark recommendation is **FIX V2.1 FIRST**, not GO V2.2, and the evidence is a ranking
gap of 0.00 — V2.2's historical evidence and adaptive exploration both operate on the
reranking stage, which currently has nothing to recover. The suggested order before V2.2:

1. Make the audit hard block reachable (it is currently dead code — see finding F1).
2. Improve retrieval: stemming and a relevance floor. `search("redesign")` returns 0 results
   while `search("design")` returns 5, and no reranker can repair that.
3. Mark role coverage explicitly in the plan artifact instead of substituting silently.
4. Run benchmark variant C with a real key; until then LLM reranking is unmeasured.

Later phases add historical evidence, exploration budgets, composition DAGs, automatic
finalization, curated knowledge publishing, and specialized agent adapters. Those are design
boundaries in `forge-development-plan-vol2.md`, not implemented commands.

Live skills.sh sync/inspect/audit needs a caller-provided OIDC token; the status ledger
distinguishes that external limitation from local verification. See
[implementation status](docs/roadmap/IMPLEMENTATION_STATUS.md),
[benchmark findings](docs/roadmap/PLANNER_BENCHMARK.md), and the
[development log](docs/development-log/2026-08-11.md).

See [MVP-0 architecture](docs/architecture/mvp-0.md) and [ADRs](docs/decisions/) for the decisions behind the local-first, immutable, deterministic core.

## License and provenance

Forge retains source/provenance fields and treats external Skill licenses as a separate future enrichment concern. Public availability does not grant Forge permission to redistribute cached Skill content. The local cache is for the user's inspection; a future public Explorer must apply license policy before exposing full contents.
