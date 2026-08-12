# Forge implementation status

Last updated: 2026-08-12

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
| V2.1 — Planner foundation | Partial | `forge_planner` provider abstraction, offline stub provider, Anthropic provider, deterministic FTS retrieval, policy gate, `forge plan` with `plan.json`/`plan.md` artifacts | 41 tests (20 new), plus a lying-provider demo showing 3 nominations reduced to 1 admission | No historical evidence lookup, no exploration slot, no DAG metadata; the Anthropic path is unverified against the live API |
| V2.1b — Planner benchmark | Complete (fixture-tested) | `forge_benchmark` harness, 26-Skill fixture catalog, 12 graded scenarios, 3 variants, 6 adversarial policy probes, retrieval-ceiling metric, `forge benchmark` with committed artifacts | 60 tests; 6/6 probes pass; both deterministic variants reproduce exactly; verified on Python 3.12.10 with identical numbers | Measured ranking gap is 0.00; three open defects recorded (F1 unreachable audit block, F2 no retrieval stemming, F3 silent role substitution); variant C never ran |
| V2.1d — Real-catalog hardening | **Complete (live-verified)** | F7 evidence-weighted project signals (schema 2), F6 `--fetch-missing` lazy detail fetch with structured rejection codes, F1 external-audit escalation onto `skill_versions`, F2 affix stripping and relevance floor, F3 coverage marker | 100 tests (24 new); live `--fetch-missing` took a real plan from 1 admission to 6; variant C reached 12/12 with 0.000 irrelevant; 6/6 policy probes hold | Offline variants pay ~2 points of precision; duplicate role assignment, absent aggregate license warning, and unstable role decomposition remain open for V2.2 |
| V2.1c — OpenAI provider + provider tests | Complete (live-verified) | `OpenAIProvider` on Chat Completions with `OPENAI_BASE_URL`/`OPENAI_MODEL` overrides, shared `post_json` helper with a `_post` seam, benchmark survives a mid-run provider failure, auth test environment isolation | 76 tests (16 new); benchmark variant C ran end to end against `gpt-5.6-luna`, confirming `max_completion_tokens` and `response_format` are accepted | The Anthropic path is still unverified against a live endpoint; variant C has one run on one model with no variance measurement |

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

Implementation commit: `bde9c7d` (`make skills auth independent of project cwd`), pushed to `origin/main`.

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

## Vol.2 Milestone V2.1 details (planner foundation)

`forge-development-plan-vol2.md` §37 defines V2.1 as the planner foundation. This slice
implements the retrieval → judgment → admission path and stops there deliberately.

### What is implemented

- `packages/planner/forge_planner/provider.py` — a `PlanProvider` protocol, a `PlanRequest`
  carrying goal + trimmed context + candidate metadata, and tolerant parsing of untrusted
  provider JSON. `StubProvider` is offline and deterministic; `AnthropicProvider` uses only
  the standard library so `dependencies = []` is preserved.
- `packages/planner/forge_planner/policy.py` — the deterministic admission gate (ADR-006).
- `packages/planner/forge_planner/service.py` — query derivation, FTS top-K retrieval, plan
  assembly, and the `plan.json` / `plan.md` artifacts under `<FORGE_HOME>/plans/<plan-id>/`.
- `forge plan "<goal>" [--provider stub|anthropic] [--model ...] [--candidates N]`.

Skill file contents are never sent to a provider; only id, name, source, and a truncated
description are. No database migration was required, so schema version stays at 3.

### What is deliberately absent

Historical evidence lookup, exploration slots, conditional Skill rules, and composition DAG
metadata all belong to V2.2 and are not stubbed out. `plan.json` reserves `exploration` and
`historicalEvidence` fields so V2.2 can populate them without a schema break.

### Verification

```text
python -m unittest discover                                    PASS (41 tests, 20 new)
Policy gate drops an invented Skill id                         PASS (unit + demo)
Policy gate refuses a Skill with no cached immutable hash       PASS (unit + CLI integration)
Policy gate raises "low" to "high" from a payment goal          PASS (unit)
Warning-level audit is admitted but flagged for review          PASS (unit)
Malformed / fenced provider JSON degrades without crashing      PASS (unit)
CLI plan writes plan.json + plan.md with gate accounting        PASS (integration)
Unknown provider exits non-zero and writes no plan              PASS (integration)
```

Observed demo, using a provider deliberately built to lie: 3 Skills nominated, 1 admitted,
1 rejected as an invented id, 1 rejected for having no cached hash.

### Limitations, stated plainly

- The tests ran on Python 3.10 through a test-only `datetime.UTC` shim because this sandbox
  could not obtain a 3.12 interpreter. The repository still targets 3.12 and was not modified
  for 3.10. A 3.12 run on the user's machine is still required.
- `AnthropicProvider` has no live-API verification. Its request shape, error handling, and
  parsing are covered by unit tests only.
- Plan quality is capped by FTS retrieval quality. Vol.2 §8 hybrid retrieval is unimplemented.
- `StubProvider` output is lexical overlap. It is not a measurement of Forge's planning value,
  and Vol.2 §38 baseline comparison has not been run.

## Vol.2 Milestone V2.1b details (planner benchmark)

Vol.2 §38 requires a baseline comparison before Forge can claim planning value. This slice
builds the measurement, runs it, and records the result — including results that are
unfavourable to Forge.

### What is implemented

- `packages/benchmark/forge_benchmark/fixtures.py` — loads and validates the authored fixture,
  and materializes it into an isolated throwaway registry. The benchmark never touches the
  user's real registry; an integration test asserts this.
- `probes.py` — `RetrievalOnlyProvider` (variant A, the no-model floor) and six adversarial
  probes, one per ADR-006 invariant.
- `metrics.py` — graded scoring plus the retrieval-ceiling and ranking-gap metrics that
  separate a retrieval failure from a ranking failure.
- `runner.py` — variant × scenario execution, determinism re-runs, artifact rendering.
- `forge benchmark [--external-provider ...] [--fixtures ...] [--output ...]`, exiting
  non-zero when a policy probe regresses.
- `tests/fixtures/planner-benchmark/` — 26 synthetic Skills, 12 graded scenarios.

`PlanResult` gained a `candidate_ids` field so a caller can tell "the reranker chose badly"
apart from "retrieval never offered it". That is the only change to V2.1 planner behaviour,
and it is additive.

### Results

| Variant | Role recall | Retrieval ceiling | Ranking gap | Irrelevant rate | Mean admitted | Passed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A — retrieval-only | 0.95 | 0.95 | 0.00 | 0.126 | 3.92 | 7 / 12 |
| B — stub lexical | 0.95 | 0.95 | 0.00 | 0.121 | 3.75 | 8 / 12 |
| C — LLM `gpt-5.6-luna` | 0.95 | 0.95 | 0.00 | 0.000 | 1.58 | 11 / 12 |

Policy probes: 6 / 6 pass. Determinism: both deterministic variants reproduce exactly.
Explanation coverage: 1.00. Verified on Python 3.12.10.

Recall is flat and the ranking gap is zero everywhere: reranking does not find more of the
right Skills. Precision is where it matters: the LLM variant eliminated irrelevant selections
entirely and cut selection size by 60%. It also admitted zero Skills in the scenario where no
correct Skill was available, which both offline variants filled with unrelated substitutes.

### Open defects

- **F6** — on the live 9,610-entry catalog, five of six LLM nominations were rejected for
  having no cached hash. `forge plan` returns one Skill and a list of `forge inspect` homework.
  Highest practical impact. The authored fixture is ~90% cached and never surfaced this.
- **F7** — `scan_project` reports `stack: ['supabase']` and `domains: ['quant', 'payments']`
  for this repository because those words appear in prose and fixtures. Three of eight live
  retrieval queries were spent on domains the project does not have.
- **F1** — the policy gate's audit hard block is unreachable from the shipped static auditor,
  which emits only `pass/low`, `warn/low`, `warn/medium`, and from external audit import,
  which never writes to `skill_versions`. Currently dead code.
- **F2** — FTS has no stemming. `search("redesign")` returns 0 results while
  `search("design")` returns 5. Caps recall for every variant.
- **F3** — weak proposers substitute adjacent roles silently. Downgraded after the LLM variant
  declined to substitute; the fix is a coverage marker, not a gate change.

F6 and F7 were found by running Forge on Forge against the real catalog. The 12-scenario
fixture scored 6/6 on policy probes and surfaced neither.

### Recommendation

**FIX V2.1 FIRST**, with revised reasoning. The earlier argument — "ranking gap is 0.00, so
V2.2 has nothing to optimize" — is **withdrawn**: it was a recall-only conclusion, and the LLM
variant showed a decisive precision effect. The recommendation stands on F6, F7, F2, and F1
instead. See [the benchmark findings](PLANNER_BENCHMARK.md) for the evidence and order.

### Limitations

- The fixture is ~90% cached; the real catalog is not. Treat all fixture numbers as an upper
  bound — this gap hid F6 entirely.
- Ground truth encodes one defensible opinion, written by the same author as the fixture.
- Variant C is one run, one model, 12 scenarios, no repeats. No variance or cost accounting.
- The Anthropic provider still has no live verification.
- The benchmark measures plan quality, not implementation quality.

## Vol.2 Milestone V2.1c details (real-catalog hardening)

Closes the five findings from the benchmark and from Forge-on-Forge dogfooding, in the order
of practical impact rather than the order they were discovered.

### F7 — project signals (`packages/project/forge_project/signals.py`)

Evidence is weighted by origin: manifest 1.0, import 0.9, config 0.85, project name 0.35,
README 0.20, prose 0.05, summed once per kind so repeating a word cannot fake a dependency.
A technology is `used` at >= 0.5 and `mentioned` otherwise. `tests/fixtures/**`,
`artifacts/**`, `.forge/**`, `node_modules/**`, `vendor/**`, and `examples/**` are excluded
from signal extraction entirely. Only `used` technologies expand a planner retrieval query.

Measured on this repository: `stack` went from `['supabase']` to `[]`, `domains` from
`['quant', 'payments', 'ai', 'saas']` to `[]`, and a landing-page goal from 8 queries with 3
wasted to 5 with none wasted.

Project context is now `schemaVersion: 2`; `mentioned` and `signals` are additive and
`stack`/`domains` keep their shape.

### F6 — lazy detail fetch (`packages/planner/forge_planner/fetch.py`)

`forge plan --fetch-missing [--fetch-budget N]`. Gate rejections now carry structured codes,
and only `detail-not-cached` is eligible for a fetch. Eligibility also requires membership in
the retrieved candidate set, so a provider cannot cause a network request for an arbitrary id.
Detail is stored through `store_detail`, the same path `forge inspect` uses. After fetching,
the gate is re-run from scratch rather than patched.

### F1 — audit hard block reachability (`packages/registry/forge_registry/database.py`)

`store_external_audits` now escalates the worst partner verdict onto `skill_versions`, which
is the table the gate reads. Escalate only: a partner cannot soften a local static warning.
Proven by an integration test that runs `create_plan` end to end.

### F2 — retrieval (`packages/planner/forge_planner/service.py`)

Conservative affix stripping in stdlib — no NLP dependency — with a four-character minimum
stem, plus a relevance floor that prefers candidates matching a goal-derived term over ones
matching only a project-context term. Retrieval ceiling rose from 0.95 to 1.00.

### F3 — coverage marker

`plan.json` and `plan.md` state covered and uncovered roles and attribute each loss to a
Skill and a rejection code. The policy gate is unchanged.

### Benchmark: before and after V2.1c

| Variant | Ceiling | Recall | Irrelevant | Admitted | Passed |
| --- | --- | --- | --- | --- | --- |
| A — retrieval-only | 0.95 → 1.00 | 0.95 → 1.00 | 0.126 → 0.155 | 3.92 → 4.17 | 7 → 7 |
| B — stub lexical | 0.95 → 1.00 | 0.95 → 1.00 | 0.121 → 0.136 | 3.75 → 3.92 | 8 → 8 |
| C — LLM `gpt-5.6-luna` | 0.95 → 1.00 | 0.95 → **1.00** | 0.000 → **0.000** | 1.58 → 1.58 | 11 → **12** |

Policy probes remain 6/6 and both deterministic variants remain reproducible. The offline
precision cost is expected — better retrieval surfaces more true candidates and more noise,
and neither offline variant can filter. The LLM variant absorbed the noise entirely and
converted the recall gain into a perfect score.

### Live verification (2026-08-12)

Against the real 9,610-entry catalog and the live OpenAI endpoint:

```text
forge plan "landing page conversion redesign" --provider openai --model gpt-5.6-luna
  nominated=5  admitted=1  rejected=4      coverage 1/6 roles

  ... --fetch-missing
  fetched_for_plan=5  failed=0  skipped=0
  nominated=6  admitted=6  rejected=0      coverage 4/7 roles
```

The same run exposed one more defect. Live queries were
`landing, page, conversion, redesign, python, land, lande, design`. `design` is the F2 fix
working; `lande` is a harmless non-word; `land` is a real word matching unrelated Skills that
the relevance floor was scoring as highly as `landing`. Fixed by ranking literal goal-term
matches above stemmed-variant matches, with a regression test.

### Verification

```text
python -m unittest discover                     PASS (100 tests, 24 new)
python -m compileall -q apps packages tests     PASS
forge benchmark                                 PASS (6/6 probes, exit 0)
forge benchmark --external-provider openai      PASS (variant C 12/12)
forge scan .  (Forge on Forge)                  contamination eliminated
forge plan --fetch-missing (live catalog)       1 admission -> 6
```

### Outstanding — carried to V2.2, none blocking

- **Duplicate role assignment.** The live 6-Skill plan gave `conversion-audit` to two Skills
  and `visual-design` to two more. Coverage is correct; composition ordering has no opinion.
- **No aggregate license warning.** Every fetched Skill reported "No license was detected".
  Per-Skill cautions appear, but a plan built entirely from unlicensed Skills says nothing at
  the plan level.
- **Unstable role decomposition.** The same goal produced 6 roles on one run and 7 on the next,
  so coverage percentages are not comparable across runs — which matters once V2.2 starts
  accumulating historical evidence.
- Affix stripping still produces non-words (`plann`, `lande`, `commendation`). They cost one
  FTS lookup each and match nothing.
- `forge recommend` inherits the stricter `stack`/`domains` and returns fewer results for
  documentation-heavy projects. Intended correction, not a regression.
- The Anthropic provider has still never made a live call.

## Commit ledger

| Milestone | Commit | Push |
| --- | --- | --- |
| Phase 0–3 initial vertical slice | `914dc4b`, `3ef4ea8`, `12d75e3` | Pushed to `origin/main` |
| Phase 4 recommendation + lock | `fe57624` | Pushed to `origin/main` |
| Phase 5 collections + composition | `b358335` | Pushed to `origin/main` |
| Phase 6 version lifecycle + safety | `ec1be3d` | Pushed to `origin/main` |
| Phase 7 generic filesystem adapter baseline | `13ebe3b` | Pushed to `origin/main` |
