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

Variant C is implemented for both `anthropic` and `openai` and **ran successfully** against
`gpt-5.6-luna` via the OpenAI Chat Completions path. The unverified request parameters
(`max_completion_tokens`, `response_format`) were accepted by the live endpoint.

If a network provider fails partway through a run, that variant is dropped whole and recorded
as `external_provider_failed`; the offline results survive, because a partially completed
variant is not comparable.

To reproduce:

```powershell
$env:OPENAI_API_KEY = "sk-..."
forge benchmark --external-provider openai --model gpt-5.6-luna
```

Ground truth is graded, not exact-match. Each scenario declares `requiredRoles`,
`acceptableRoles`, `irrelevantRoles`, and `forbiddenSkills`, because more than one
defensible Skill team exists for most goals.

## Results

The benchmark computes a **retrieval ceiling** — the best role recall any reranker could
have achieved given what retrieval actually returned — and a **ranking gap** of ceiling
minus achieved recall.

| Variant | Role recall | Retrieval ceiling | Ranking gap | Irrelevant rate | Mean admitted | Scenarios passed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| A — retrieval-only | 0.95 | 0.95 | 0.00 | 0.126 | 3.92 | 7 / 12 |
| B — stub lexical | 0.95 | 0.95 | 0.00 | 0.121 | 3.75 | 8 / 12 |
| C — LLM (`gpt-5.6-luna`) | 0.95 | 0.95 | 0.00 | **0.000** | **1.58** | **11 / 12** |

Read the two halves of that table separately, because they say opposite things.

**Recall is flat at 0.95 across all three variants, and the ranking gap is 0.00 everywhere.**
Every recall shortfall was caused by retrieval, not by ranking. A semantic reranker recovered
nothing that retrieval had not already surfaced. Retrieval is the ceiling, and no provider
can raise it.

**Precision is where the reranker is decisive.** The LLM variant drove the irrelevant
selection rate from ~0.12 to exactly 0.00, cut the mean selection size from 3.9 Skills to
1.6, and passed 11 of 12 scenarios against 7 and 8. Its single failure is S01, and the
harness attributes it correctly: *"retrieval never surfaced an admissible Skill for
visual-design — this is a retrieval failure, not a ranking failure."*

### Correction to the earlier conclusion

An earlier version of this document concluded from the 0.00 ranking gap that "reranking
recovered nothing" and therefore had no value. **That was wrong**, and the error is worth
recording because it is the kind this project is supposed to catch.

The ranking gap is a recall-only metric. The irrelevant-selection rate was measured from the
start, but the GO/FIX recommendation was hung on the recall gap alone, so a large precision
effect was reported in a side column and omitted from the headline. Reranking does not find
more of the right Skills; it removes the wrong ones, decisively. Both statements are true and
only one of them was in the conclusion.

### The LLM variant also fixed F3 on its own

Scenario S12 is the case where the only role-correct Skill is uncached. Variants A and B both
returned a plan built from three adjacent, unrelated Skills. **The LLM variant admitted
zero.** So the silent-substitution behaviour recorded as F3 is a property of weak proposers,
not of the gate or the plan schema. It still deserves an explicit coverage marker in the plan
artifact, but it is no longer evidence of a structural defect.

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

### F3 — Weak proposers silently substitute adjacent Skills when the right one is unavailable

*Downgraded after the LLM variant ran: the LLM proposer admitted zero Skills in this case.
This is a proposer-quality issue, not a structural one. The recommended fix is now an
explicit coverage marker in the plan artifact rather than a change to the gate.*

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

### F6 — In the real catalog, the cached-hash rule starves the planner

The fixture is ~90% cached, so it hides the constraint that dominates real use. A live run
against the 9,610-entry skills.sh catalog:

```text
forge plan "landing page conversion redesign" --provider openai --model gpt-5.6-luna

Retrieved candidates: 60
Policy gate: nominated=6, admitted=1, rejected=5
  x autonnel/autonnel-skills/landing-page-conversion-audit  -> detail not cached
  x kostja94/marketing-skills/conversion-optimization       -> detail not cached
  x onewave-ai/claude-skills/landing-page-copywriter        -> detail not cached
  x skills-101/superpowers/landing-page-design              -> detail not cached
  x leonxlnx/taste-skill/redesign-existing-projects         -> detail not cached
```

Five of six nominations died on the cached-hash rule. The rule itself is correct — ADR-006
depends on it — but its practical effect is that `forge plan` degrades into a list of Skills
the user must `forge inspect` by hand before planning again. The provider did its job well
and the output is still nearly unusable.

`forge inspect` is already an on-demand fetch, so the planner could resolve nominated
candidates lazily behind an explicit flag (`--fetch-missing`), keeping the immutability
guarantee while removing the manual round trip. That is the highest-impact V2.1 fix; it is
worth more than anything in V2.2.

This finding also indicts the fixture: authored catalogs do not reproduce the cache
distribution of a real registry, and this benchmark scored 6/6 on policy probes while
completely missing the constraint that matters most in practice.

### F7 — The scanner reads document mentions as project facts

The same live run derived these retrieval queries inside the Forge repository itself:

```text
landing, page, conversion, redesign, supabase, quant, payments, ai
```

Forge does not use Supabase and is not a payments or quant project. `scan_project` reported
`stack: ['supabase']` and `domains: ['quant', 'payments', 'ai', 'saas']` because those words
appear in prose and fixtures — `FORGE_CODEX_IMPLEMENTATION_BRIEF.md`, the development log,
`forge-development-plan-vol2.md`, and the benchmark fixture files.

Three of eight retrieval queries were therefore spent on unrelated domains, and the candidate
list hit its 60-item ceiling partly with noise. Adding the benchmark fixtures made this worse,
but the cause predates them: the scanner does not distinguish "this project uses X" from
"this project's documentation mentions X".

This is a recursive-dogfooding find. It surfaced only because Forge was pointed at Forge, and
it silently degrades every plan for any documentation-heavy repository.

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

The recommendation is unchanged from the pre-variant-C draft, but **its reasoning is
substantially different**, and one of the four original arguments has been withdrawn.

### Withdrawn

> ~~Ranking gap is 0.00, so V2.2 would optimize a stage with nothing to recover.~~

The LLM variant took the irrelevant-selection rate to 0.00 and cut selection size by 60%.
The reranking stage demonstrably does real work; it just does it on precision rather than
recall. V2.2's historical evidence attaches to exactly that stage, so it now has somewhere
useful to attach.

### Still standing

1. **F6 makes the planner impractical on the real catalog.** Five of six nominations died on
   the cached-hash rule in a live run. A user gets one Skill and a homework list. No amount of
   V2.2 intelligence improves a pipeline whose output is mostly "go run `forge inspect` five
   times".
2. **F2 caps recall for every variant.** All three sit at 0.95 with a 0.00 gap. Historical
   evidence about a Skill is worthless if the goal phrasing never retrieves it, and
   `search("redesign")` returning 0 results is not an exotic edge case.
3. **F7 poisons the input to everything downstream.** Three of eight live queries were spent
   on domains the project does not have. Every later stage inherits that error.
4. **F1 remains a safety correctness gap.** Vol.2 §26 requires that Forge not weaken its own
   trust boundaries; shipping more capability on top of an unreachable block branch inverts
   that.

### Suggested order before V2.2

1. **F6 — lazy detail fetch for nominated candidates** behind an explicit flag. Highest
   practical impact by a wide margin. Preserves immutability; removes the manual round trip.
2. **F7 — separate "uses X" from "mentions X"** in the scanner. Weight code, manifests, and
   lockfiles above prose, and exclude `tests/fixtures/` and `artifacts/` from signal
   extraction.
3. **F1 — make the audit hard block reachable.** Propagate external audit results into
   `skill_versions`, or have the gate read `security_audits` directly. Add a test that fails
   if the branch becomes unreachable again.
4. **F2 — retrieval stemming and a relevance floor.** Re-run and confirm the ceiling rises.
5. **F3 — an explicit coverage marker** in `plan.md` when no admitted Skill addresses a
   decomposed role.

Then reconsider GO V2.2. The precision result is genuine evidence that the reranking stage is
worth investing in — but only once its inputs and outputs are not being wasted.

### What changed the analysis

Two things, and neither came from the fixture:

- Running variant C revealed that the headline metric was measuring the wrong half of the
  problem.
- Running `forge plan` against the real catalog, inside the Forge repository itself, exposed
  F6 and F7 — the two defects with the largest practical impact. The 12-scenario fixture
  scored 6/6 on policy probes and did not surface either one.

A benchmark that only runs on authored fixtures will keep missing this class of defect.

## Limits of this benchmark

- The fixture catalog is authored, not sampled from the live 9,610-entry skills.sh catalog.
  Retrieval difficulty is therefore synthetic and probably easier than production.
- Ground truth role labels were written by the same author as the fixture. They encode one
  defensible opinion, not a consensus.
- **The fixture does not reproduce the real cache distribution.** It is ~90% cached; the live
  catalog is mostly uncached. That gap hid F6 entirely, which is the defect with the largest
  practical impact. Treat every fixture number as an upper bound.
- Variant C ran once, on one model (`gpt-5.6-luna`, OpenAI's lowest tier), on 12 scenarios,
  with no repeat runs. The precision result is a strong single observation, not a stable
  measurement — no variance, no model comparison, no cost accounting.
- The benchmark measures plan quality, not implementation quality. Vol.2 §38's real
  question — does a Forge plan produce better code than a plain prompt — requires agent
  execution and is out of scope for V2.1.
- The Anthropic provider still has no live verification. Only the OpenAI path has been
  exercised end to end against a real endpoint.

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
