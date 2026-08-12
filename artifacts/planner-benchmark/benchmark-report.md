# Forge planner benchmark

Generated: 2026-08-12T09:12:15.817310Z
Milestone: Vol.2 V2.1 planner foundation

This benchmark measures the V2.1 planner against an authored fixture catalog. It does not
measure whether Forge improves a final implementation; that requires agent execution and is
explicitly out of scope for V2.1.

## Runtime

- Sandbox runtime: Python 3.10.12 + temporary compatibility shim
- Target runtime: Python 3.12
- Local 3.12 verification required: true
- This run did not execute on the repository's target interpreter. Treat the results as indicative and re-run on Python 3.12 before relying on them.

## Fixture

- Catalog: 26 synthetic Skills
- Scenarios: 12
- ORACROSS artifact import: `blocked_external_fixture`

The ORACROSS report artifacts referenced in vol2.md Appendix A live outside this workspace and were never read. Scenario design used only the narrative in the Vol.2 document. No synthetic file was presented as an ORACROSS artifact.

## Variants

| Variant | Status | What it isolates |
| --- | --- | --- |
| A-retrieval-only | ran | Raw FTS order, no model. The floor. |
| B-stub-lexical | ran | Lexical overlap rerank over the same candidates. |
| C-llm-provider | skipped_external_provider: no external provider requested | Semantic rerank over the same candidates. |

Every variant runs through the identical retrieval and the identical policy gate, so any
difference is attributable to ranking alone.

## Aggregate metrics

| Variant | Scenarios | Passed | Role recall | Retrieval ceiling | Ranking gap | Irrelevant rate | Mean admitted | Explanations | Risk gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| A-retrieval-only | 12 | 7 | 1.00 | 1.00 | 0.00 | 0.15 | 4.17 | 1.00 | 1.00 |
| B-stub-lexical | 12 | 8 | 1.00 | 1.00 | 0.00 | 0.14 | 3.92 | 1.00 | 1.00 |

**Role recall** counts required roles covered. **Retrieval ceiling** is the best recall any
reranker could have reached given what retrieval actually returned. **Ranking gap** is
ceiling minus recall — it is the part of the shortfall a better reranker could fix. A recall
below the ceiling is a ranking problem; a ceiling below 1.00 is a retrieval problem that no
provider, however good, can repair. **Irrelevant rate** is the share of admitted Skills whose
role the scenario marks as wrong for the goal; lower is better.

## Policy probes

6 of 6 adversarial probes passed.

| Probe | Invariant | Result |
| --- | --- | --- |
| `P1-invented-skill-id` | A provider cannot introduce a Skill id that retrieval never produced. | PASS |
| `P2-uncached-skill` | A Skill without an immutable content hash cannot enter a plan. | PASS |
| `P3-hard-blocked-audit` | A hard audit block cannot be argued past by a confident provider. | PASS |
| `P4-risk-downgrade` | Forge may raise risk from the goal text; a provider cannot lower it. | PASS |
| `P5-duplicate-nomination` | Duplicate nominations collapse to a single admission. | PASS |
| `P6-real-skill-outside-candidates` | Registry existence is not sufficient. The candidate-set check is a separate and independently enforced boundary. | PASS |

## Determinism

- `A-retrieval-only`: reproducible across two consecutive runs on identical input.
- `B-stub-lexical`: reproducible across two consecutive runs on identical input.

## Per-scenario results

### A-retrieval-only

| Scenario | Kind | Recall | Ceiling | Irrelevant | Admitted | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| S01-landing-conversion-redesign | selection | 1.00 | 1.00 | 0.17 | 6 | Selected 1 Skill(s) in roles marked irrelevant for this goal: acme/security/auth-architecture (auth) |
| S02-component-api-boolean-props | selection | 1.00 | 1.00 | 0.00 | 6 | pass |
| S03-mobile-overflow-touch-targets | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S04-postgres-slow-joins | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S05-add-payment-flow | selection | 1.00 | 1.00 | 0.00 | 2 | pass |
| S06-documentation-wording | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S07-authentication-architecture | selection | 1.00 | 1.00 | 0.60 | 5 | Selected 3 Skill(s) in roles marked irrelevant for this goal: acme/docs/technical-writing (documentation), acme/perf/frontend-bundle-size (performance), acme/web/component-architecture (component-architecture) |
| S08-positioning-before-copy | selection | 1.00 | 1.00 | 0.40 | 5 | Selected 2 Skill(s) in roles marked irrelevant for this goal: acme/data/postgres-rls-safety (database-security), acme/quant/backtesting-reproducibility (quant) |
| S09-e2e-signup-funnel-tests | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S10-bundle-size-load-performance | selection | 1.00 | 1.00 | 0.33 | 6 | Selected 2 Skill(s) in roles marked irrelevant for this goal: acme/docs/technical-writing (documentation), acme/data/postgres-query-performance (database-performance) |
| S11-rls-before-production-rollout | selection | 1.00 | 1.00 | 0.20 | 5 | Selected 1 Skill(s) in roles marked irrelevant for this goal: acme/marketing/product-marketing-context (positioning) |
| S12-backup-retention-uncached-only | policy | n/a | 0.00 | 0.00 | 3 | pass |

Warnings (not scored as failures):

- `S12-backup-retention-uncached-only`: The role-correct Skill was unavailable, and Forge still returned a plan built from adjacent roles (database-performance, database-security, testing). The rejection is recorded in the plan, but nothing marks the returned selection as failing to address the goal.

### B-stub-lexical

| Scenario | Kind | Recall | Ceiling | Irrelevant | Admitted | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| S01-landing-conversion-redesign | selection | 1.00 | 1.00 | 0.17 | 6 | Selected 1 Skill(s) in roles marked irrelevant for this goal: acme/infra/ci-pipeline (infrastructure) |
| S02-component-api-boolean-props | selection | 1.00 | 1.00 | 0.00 | 6 | pass |
| S03-mobile-overflow-touch-targets | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S04-postgres-slow-joins | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S05-add-payment-flow | selection | 1.00 | 1.00 | 0.00 | 2 | pass |
| S06-documentation-wording | selection | 1.00 | 1.00 | 0.00 | 2 | pass |
| S07-authentication-architecture | selection | 1.00 | 1.00 | 0.75 | 4 | Selected 3 Skill(s) in roles marked irrelevant for this goal: acme/docs/technical-writing (documentation), acme/perf/frontend-bundle-size (performance), acme/web/component-architecture (component-architecture) |
| S08-positioning-before-copy | selection | 1.00 | 1.00 | 0.25 | 4 | Selected 1 Skill(s) in roles marked irrelevant for this goal: acme/data/postgres-rls-safety (database-security) |
| S09-e2e-signup-funnel-tests | selection | 1.00 | 1.00 | 0.00 | 3 | pass |
| S10-bundle-size-load-performance | selection | 1.00 | 1.00 | 0.33 | 6 | Selected 2 Skill(s) in roles marked irrelevant for this goal: acme/docs/technical-writing (documentation), acme/data/postgres-query-performance (database-performance) |
| S11-rls-before-production-rollout | selection | 1.00 | 1.00 | 0.00 | 5 | pass |
| S12-backup-retention-uncached-only | policy | n/a | 0.00 | 0.00 | 3 | pass |

Warnings (not scored as failures):

- `S12-backup-retention-uncached-only`: The role-correct Skill was unavailable, and Forge still returned a plan built from adjacent roles (database-performance, database-security, testing). The rejection is recorded in the plan, but nothing marks the returned selection as failing to address the goal.

## Claims this benchmark does not support

- Whether LLM reranking beats retrieval-only on real Skills is unmeasured; variant C requires an API key.
- Whether a Forge plan improves final implementation quality versus a plain prompt is unmeasured; that needs agent execution, which V2.1 does not perform.
- Whether historical evidence improves recommendation is unmeasured; V2.2 owns it.
- Whether adaptive exploration finds good new Skills is unmeasured; V2.2 owns it.
- Fixture retrieval difficulty is authored, not sampled from the live 9,610-entry catalog.

---

Forge's current state is a policy-bounded planner foundation. The gate results below are
evidence. The selection quality numbers are measurements against an authored fixture, not
proof that Forge produces better software.
