# Planner benchmark: findings and recommendation

Run date: 2026-08-12
Scope: Vol.2 V2.1 planner foundation
Command: `forge benchmark`
Artifacts: [`artifacts/planner-benchmark/`](../../artifacts/planner-benchmark/)

This document records what the benchmark measured, what it did not measure, and the
resulting recommendation. It exists because Vol.2 §40 Risk A — "Forge is slower than a good
prompt and the results are no better" — cannot be closed by architecture review.

## What the harness does

Three variants run over the same 12 scenarios, through the same retrieval and the same
policy gate. Only the ranking step differs, so any measured difference is attributable to
ranking alone.

| Variant | Ranking | Purpose |
| --- | --- | --- |
| A — retrieval-only | none; raw FTS order | the no-model floor |
| B — stub lexical | goal-term overlap | what a trivial reranker adds |
| C — LLM provider | semantic | what a real reranker adds |

Variant C is implemented and wired for both `anthropic` and `openai`. It did not run: no API
key is configured, and the harness recorded `skipped_external_provider` with the provider's
own error text rather than substituting a stand-in. If a network provider fails partway
through a run, that variant is dropped whole and recorded as `external_provider_failed`; the
offline results survive, because a partially completed variant is not comparable.

To run it:

```powershell
$env:OPENAI_API_KEY = "sk-..."
forge benchmark --external-provider openai --model gpt-5.6-luna
```

Ground truth is graded, not exact-match. Each scenario declares `requiredRoles`,
`acceptableRoles`, `irrelevantRoles`, and `forbiddenSkills`, because more than one
defensible Skill team exists for most goals.

## Headline metric: the ranking gap

The benchmark computes a **retrieval ceiling** — the best role recall any reranker could
have achieved given what retrieval actually returned — and a **ranking gap** of ceiling
minus achieved recall.

| Variant | Role recall | Retrieval ceiling | Ranking gap | Irrelevant rate | Scenarios passed |
| --- | ---: | ---: | ---: | ---: | ---: |
| A — retrieval-only | 0.95 | 0.95 | **0.00** | 0.126 | 7 / 12 |
| B — stub lexical | 0.95 | 0.95 | **0.00** | 0.121 | 8 / 12 |
| C — LLM provider | — | — | — | — | `skipped_external_provider` |

A ranking gap of exactly zero across both variants means every recall shortfall was caused
by retrieval, not by ranking. At this fixture size, **reranking recovered nothing that
retrieval had not already surfaced**, and the two variants differ by 0.5 percentage points
on the irrelevant-selection rate, which is one Skill in one scenario. That is not a signal.

## Findings

### F1 — The audit hard-block branch is unreachable in production

`policy.py` blocks a Skill when its version state is `security_status == "fail"` or
`risk_level == "high"`. The shipped static auditor in `registry/database.py::_static_audit`
emits only `pass/low`, `warn/low`, and `warn/medium`. `store_external_audits` writes to the
`security_audits` table and never propagates to `skill_versions`, which is the table the
gate reads.

Consequence: no real Skill can currently reach the hard-block branch. The benchmark reaches
it only because the fixture builder writes that version state directly, which is labelled in
`catalog.json` and in the builder.

Severity: the strongest-sounding safety guarantee in ADR-006 is, today, dead code.
This is a correctness gap, not a benchmark artifact.

### F2 — Retrieval has no stemming, and it is the binding constraint

Measured directly:

```text
search("redesign") -> 0 results
search("design")   -> 5 results, including the correct visual-design Skill
```

The goal "Redesign a public landing page for stronger conversion" retrieved 4 candidates
and never surfaced the one visual-design Skill, capping recall at 0.50 for that scenario.
Rephrasing the same goal as "Improve the visual design of the landing page" retrieves it.

A user phrasing a goal naturally gets a materially worse plan, and no provider can repair
it, because the candidate never reaches the provider. Vol.2 §8 anticipates hybrid retrieval;
this quantifies why it is not optional.

### F3 — Forge silently substitutes adjacent Skills when the right one is unavailable

Scenario S12 asks for backup retention. The only role-correct Skill is deliberately
uncached, so the gate correctly rejects it with an actionable message. Forge then returns a
plan built from `database-performance`, `database-security`, and `testing` — none of which
address the goal.

The rejection is recorded, so the information is present. But nothing in `plan.json` or
`plan.md` marks the returned selection as failing to cover the requested work. A reader
skimming the selected list sees a plausible plan.

Recorded as a warning rather than a scored failure, because V2.1 was never specified against
this behaviour.

### F4 — Irrelevant selection is ~12%, and the worst case is much worse

Both variants admit wrong-domain Skills at roughly one in eight. Scenario S07 ("Improve
authentication architecture") is the worst case: variant A admitted 5 Skills of which 3 were
irrelevant, variant B admitted 4 of which 3 were irrelevant. The stub reranker made that
scenario *worse*, not better.

Cause: `derive_queries` ORs its tokens, so a Skill matching any single token enters the
candidate set, and neither variant has a relevance threshold — both take a fixed top-N.

### F5 — What did hold

All six adversarial probes passed, and both deterministic variants reproduced exactly across
consecutive runs.

| Probe | Invariant | Result |
| --- | --- | --- |
| P1 | An invented Skill id cannot enter a plan | PASS |
| P2 | A Skill with no immutable cached hash cannot enter a plan | PASS |
| P3 | A hard audit block cannot be argued past | PASS (via injected state; see F1) |
| P4 | A provider cannot lower risk; Forge raised "low" to "high" on a payment goal | PASS |
| P5 | Duplicate nominations collapse to one admission | PASS |
| P6 | Registry existence is not sufficient; the candidate-set check is independent | PASS |

Explanation coverage was 1.00 for every variant: every admitted, excluded, and rejected
Skill carried a reason.

## Recommendation: FIX V2.1 FIRST

Evidence:

1. **Ranking gap is 0.00.** V2.2 adds historical evidence and exploration, both of which
   operate on the reranking stage. The benchmark shows that stage currently has nothing to
   recover. Building V2.2 now optimizes a component that is not the bottleneck.
2. **F2 caps the whole pipeline.** Recall cannot exceed the retrieval ceiling. Historical
   evidence about a Skill is worthless if the goal phrasing never retrieves that Skill.
3. **F1 is a safety correctness gap**, and Vol.2 §26 explicitly requires that Forge not
   weaken its own trust boundaries. Shipping more planning capability on top of an
   unreachable block branch inverts that principle.
4. **F3 will compound.** V2.2 exploration adds more Skills to a selection. Adding
   exploration to a planner that already substitutes silently makes the plan harder to
   audit, not easier.

Suggested order before V2.2:

1. Make the audit hard block reachable — propagate external audit results into
   `skill_versions`, or move the gate to read `security_audits` directly. Add a test that
   fails if the block branch becomes unreachable again.
2. Improve retrieval: stemming or prefix matching, plus a relevance floor so a single weak
   token match does not admit a candidate. Re-run the benchmark and confirm the ceiling rises.
3. Mark coverage explicitly in the plan artifact: when no admitted Skill addresses a
   decomposed role, say so in `plan.md` rather than leaving the reader to infer it.
4. Set `OPENAI_API_KEY` (or `ANTHROPIC_API_KEY`) and run variant C. Until then, whether
   semantic reranking beats lexical retrieval is genuinely unknown — the harness is ready, the
   measurement is not. This is also the only way to verify that either network provider's
   request shape is accepted by a real endpoint.

Reconsider GO V2.2 once the ranking gap is non-zero. A non-zero gap is the evidence that a
better reranker has something to recover, which is precisely what V2.2 is designed to supply.

## Limits of this benchmark

- The fixture catalog is authored, not sampled from the live 9,610-entry skills.sh catalog.
  Retrieval difficulty is therefore synthetic and probably easier than production.
- Ground truth role labels were written by the same author as the fixture. They encode one
  defensible opinion, not a consensus.
- Variant C never ran. Every claim about LLM reranking remains unmeasured.
- The benchmark measures plan quality, not implementation quality. Vol.2 §38's real
  question — does a Forge plan produce better code than a plain prompt — requires agent
  execution and is out of scope for V2.1.
- Neither network provider has ever made a live API call. Their request shape, error
  translation, and response parsing are covered by tests that replace the `_post` seam, which
  proves the code is internally consistent, not that a real endpoint accepts it. In
  particular `max_completion_tokens` and `response_format` are unverified; an HTTP 400 from
  either carries a hint pointing at `json_mode=False` and `OPENAI_BASE_URL`.

### Runtime verification

The first run used Python 3.10 with a temporary, uncommitted `datetime.UTC` shim, because the
sandbox could not obtain a 3.12 interpreter. The benchmark was subsequently re-run on the
target interpreter:

```text
Python 3.12.10 — recall 0.95 / ceiling 0.95 / gap 0.00 / irrelevant 0.126 and 0.121
                 probes 6/6 · both deterministic variants reproducible
```

The numbers are identical to the shimmed run, so the shim did not distort the result and the
FIX-V2.1-FIRST recommendation stands on target-runtime evidence.

## ORACROSS artifact import

Status: `blocked_external_fixture`.

The report artifacts referenced in Vol.2 Appendix A live at
`C:\Users\beric\.forge\history\oracross\2026-08-12-growth-visual-redesign\` and are outside
this workspace. They were never read. Scenario design used only the narrative in
`forge-development-plan-vol2.md` §4, and no synthetic file is presented as an ORACROSS
artifact. Scenarios S01 and S08 encode the shape of that case; their ground truth is
authored, not imported.

TODO: when the real artifacts are reachable, import them as a benchmark scenario and compare
the recorded Skill contribution ratings against what the planner selects.
