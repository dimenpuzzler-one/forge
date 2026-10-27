# Planner benchmark: findings and recommendation

Run date: 2026-08-12
Scope: Vol.2 V2.1 planner foundation, updated after V2.1c real-catalog hardening
Command: `forge benchmark`
Artifacts: [`artifacts/planner-benchmark/`](../../artifacts/planner-benchmark/)

> **V2.1c status.** All five findings below have been addressed. Jump to
> [V2.1c hardening results](#v21c-hardening-results) for what changed and what it cost.
> The findings are retained in their original form because they are the evidence for the
> fixes, and because F6 and F7 document a failure of the benchmark itself.

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

## Recommendation history

This section is kept as a record of how the recommendation moved, because two of its
conclusions turned out to be wrong and the corrections are the useful part.

| Stage | Verdict | Basis | Outcome |
| --- | --- | --- | --- |
| After offline benchmark | FIX V2.1 FIRST | ranking gap 0.00 → "reranking is worthless" | **Withdrawn.** Recall-only reasoning; the precision effect was measured but left out of the conclusion. |
| After variant C | FIX V2.1 FIRST | F6, F7, F2, F1 — real defects | Held. All five fixed in V2.1c. |
| After live verification | **V2.1 CLOSED → GO V2.2** | `--fetch-missing` 1→6 admissions; variant C 12/12 with 0.000 irrelevant | Current. |

## Final verdict: V2.1 CLOSED, GO V2.2

Every condition set for closing V2.1 is met:

- **F6 resolved on the surface that produced it.** 1 admission → 6, zero fetch failures.
- **F7 resolved**, measured on Forge scanning Forge.
- **F1 reachable**, proven through `create_plan` rather than in isolation.
- **F2 and F3** shipped, with the `land` follow-up found and fixed during live verification.
- **No benchmark regression.** Policy probes 6/6, determinism intact, variant C improved.
- **Forge-on-Forge plans are usable**, which was the practical bar.

The case for V2.2 is now evidence-backed rather than speculative. Historical evidence and
exploration budgets both attach to the reranking stage, and the reranking stage is exactly
where the measured value is: retrieval sets the ceiling, reranking decides how much noise
comes with it, and variant C converts a raised ceiling into a perfect score while the offline
variants cannot.

Carry into V2.2, from the live run rather than the fixture: duplicate role assignment,
absent aggregate license warning, and unstable role decomposition between runs. None block
V2.2; all three interact with the composition DAG.

## Superseded: FIX V2.1 FIRST

*Retained for the record. Resolved by V2.1c and the live verification above.*

The recommendation was unchanged from the pre-variant-C draft, but **its reasoning was
substantially different**, and one of the four original arguments was withdrawn.

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

### Suggested order before V2.2 — all five completed in V2.1c

1. ~~**F6** — lazy detail fetch for nominated candidates.~~ Implemented as `--fetch-missing`.
2. ~~**F7** — separate "uses X" from "mentions X" in the scanner.~~ Implemented as weighted
   evidence with a `used` / `mentioned` classification.
3. ~~**F1** — make the audit hard block reachable.~~ External audits now escalate onto
   `skill_versions`, proven by an integration test through `create_plan`.
4. ~~**F2** — retrieval stemming and a relevance floor.~~ Ceiling rose from 0.95 to 1.00.
5. ~~**F3** — an explicit coverage marker.~~ Present in `plan.json` and `plan.md`.

See [V2.1c hardening results](#v21c-hardening-results). Both outstanding verifications have
since run against the live catalog and endpoint and both passed: `--fetch-missing` took a real
plan from 1 admission to 6, and variant C reached 12/12 with its 0.000 irrelevant rate intact.

**V2.1 is closed.** The blocking reason for FIX-V2.1-FIRST no longer holds.

### What changed the analysis

Two things, and neither came from the fixture:

- Running variant C revealed that the headline metric was measuring the wrong half of the
  problem.
- Running `forge plan` against the real catalog, inside the Forge repository itself, exposed
  F6 and F7 — the two defects with the largest practical impact. The 12-scenario fixture
  scored 6/6 on policy probes and did not surface either one.

A benchmark that only runs on authored fixtures will keep missing this class of defect.

## V2.1c hardening results

Every finding above has a fix, a test, and a measurement.

### F7 — scanner, measured on Forge itself

`scan_project` now weights evidence by where it was found. A dependency in a manifest, an
actual import, or a technology-specific config file is `used`. A term appearing in prose is
`mentioned`, recorded with its sources but never used to expand a retrieval query.
`tests/fixtures/**`, `artifacts/**`, and `.forge/**` contribute nothing at all.

Running `forge scan` inside this repository:

| | before | after |
| --- | --- | --- |
| `stack` | `['supabase']` | `[]` |
| `domains` | `['quant', 'payments', 'ai', 'saas']` | `[]` |
| `mentioned` | *(did not exist)* | `['ai', 'payments', 'postgres', 'quant', 'saas', 'supabase']` |
| queries for a landing-page goal | `landing, page, conversion, redesign, supabase, quant, payments, ai` | `landing, page, conversion, redesign, python` |

Three of eight retrieval queries were being spent on domains Forge does not have. None are
now. `python` survives because `pyproject.toml` is real evidence.

Project context is `schemaVersion: 2`. `stack` and `domains` keep their shape but now contain
only `used` technologies; `mentioned` and `signals` are additive.

### F2 — retrieval, measured on the fixture

Affix stripping (stdlib, no NLP dependency) plus a relevance floor that prefers candidates
matching a goal-derived term over ones matching only a project-context term.

| Variant | Retrieval ceiling | Role recall | Irrelevant rate | Mean admitted |
| --- | ---: | ---: | ---: | ---: |
| A — retrieval-only | 0.95 → **1.00** | 0.95 → **1.00** | 0.126 → 0.155 | 3.92 → 4.17 |
| B — stub lexical | 0.95 → **1.00** | 0.95 → **1.00** | 0.121 → 0.136 | 3.75 → 3.92 |

S01, the scenario that exposed F2, went from ceiling 0.50 with `visual-design` unreachable to
ceiling 1.00 with nothing unreachable.

**This trade is real and should not be glossed.** Better retrieval surfaces more true
candidates *and* more noise. The two offline variants have no semantic judgment, so their
irrelevant rate rose by about 2 points as their recall rose by 5. The relevance floor
absorbed some of it, not all.

The variant that should benefit most is C, which already prunes to 0.000 irrelevant — more
good candidates with the same pruning ought to be a pure gain. That was a prediction when this
section was written; it has since been **measured and confirmed**. Variant C went from 11/12
to 12/12 with its irrelevant rate unchanged at 0.000. See
[live verification](#live-verification-2026-08-12-after-v21c).

### Live verification (2026-08-12, after V2.1c)

Both outstanding verifications ran against the real 9,610-entry catalog and the live OpenAI
endpoint. Both passed.

**F6, measured end to end.** Same goal, same model, same session, with and without the flag:

```text
forge plan "landing page conversion redesign" --provider openai --model gpt-5.6-luna
  nominated=5  admitted=1  rejected=4      coverage 1/6 roles

  ... --fetch-missing
  fetched_for_plan=5  failed=0  skipped=0
  nominated=6  admitted=6  rejected=0      coverage 4/7 roles
```

Admissions went from 1 to 6 and rejections to zero, with no fetch failures. F6 is resolved on
the surface that produced it. Every fetched Skill still carried its own audit result and its
own review cautions, so the gate was doing its job on the newly cached content rather than
waving it through.

**Variant C regression, measured.** The earlier prediction — that the LLM variant would absorb
the precision cost of better retrieval — held:

| Variant C | before V2.1c | after V2.1c |
| --- | ---: | ---: |
| scenarios passed | 11 / 12 | **12 / 12** |
| role recall | 0.95 | **1.00** |
| irrelevant rate | 0.000 | **0.000** |
| mean admitted | 1.58 | 1.58 |

The offline variants paid about 2 points of precision for their recall gain; the LLM variant
paid nothing and converted the gain into a perfect score. This is the clearest evidence so far
that retrieval and reranking are complementary rather than substitutes: retrieval sets the
ceiling, reranking decides how much noise comes with it.

**A new defect surfaced in the same run.** The live queries were:

```text
landing, page, conversion, redesign, python, land, lande, design
```

`design` is the F2 fix working as intended. `lande` is a non-word that matches nothing.
`land` is the real problem: it is a legitimate word that matches genuinely unrelated Skills,
and the relevance floor was treating a match on it as equal in value to a match on `landing`.
The earlier note claiming these variants "cost one FTS lookup and match nothing" was wrong
about `land`.

Fixed by splitting the floor's ranking key: a candidate matching a term the user actually
typed outranks one matching only a stemmed variant. Regression-tested with a `land survey`
Skill competing against a `landing page` Skill.

### F6 — lazy detail fetch

`forge plan --fetch-missing` resolves detail for nominated Skills rejected *only* for lacking
a cached immutable version, then re-runs the gate from scratch. The boundaries are enforced
in code and covered by tests:

- only ids the deterministic retrieval already produced are eligible, so a provider cannot
  name an arbitrary Skill and cause a network request;
- only the `detail-not-cached` rejection code is eligible, so an audit-blocked Skill is never
  re-fetched for a second opinion;
- detail is stored through the same `store_detail` path as `forge inspect`, keeping path
  validation, size limits, hashing, snapshotting, and the static audit;
- a fetch failure leaves the rejection in place;
- the budget defaults to 8 and is enforced;
- risk escalation survives a fetch.

Rejections now carry structured codes (`detail-not-cached`, `audit-blocked`,
`not-in-candidate-set`, `unknown-skill`, `duplicate-nomination`) so later stages branch on
the code rather than parsing prose.

**Not yet measured against the live catalog.** The fixture cannot reproduce F6, which is why
it hid the defect. The real test is a `--fetch-missing` run against skills.sh.

### F1 — audit hard block, now reachable

`store_external_audits` propagates a partner verdict onto `skill_versions`, which is the table
the gate reads. Escalate only: a partner may raise a version to fail/high, but cannot soften a
local static warning to a pass. Both directions are tested.

The reachability test goes through `create_plan`, not through the policy function in
isolation, because the defect was precisely that a correct function was unreachable. It
asserts the static auditor alone yields `pass`, that the external audit moves it to
`fail`/`high`, and that the resulting plan admits nothing with code `audit-blocked`.

### F3 — coverage marker

`plan.json` and `plan.md` now state how many decomposed roles the admitted Skills actually
cover, name the uncovered ones, and attribute each loss to a specific Skill and rejection
code. An incomplete plan says **"This plan is incomplete"** and "Do not treat the selected
Skills below as addressing the whole goal." The policy gate is unchanged.

### Known limitation introduced by F2

Affix stripping is naive and produces non-words: `planner` yields `plann`, `landing` yields
`lande`, and `recommendation` yields `commendation`. Those cost one FTS lookup each and match
nothing.

The more serious case is a variant that *is* a real word with an unrelated meaning — `landing`
yields `land`. That one matches real Skills. The relevance floor now ranks a literal goal-term
match above a stemmed-variant match so those candidates lose their slot to genuine matches,
but they are still retrieved. A real stemmer would reduce the noise at the cost of a
dependency, which remains unjustified while the floor is absorbing it.

### Still open after V2.1

Observed in the live run, neither blocking:

- **Duplicate roles in a selection.** The 6-Skill plan assigned `conversion-audit` to two
  Skills and `visual-design` to two more. Coverage is computed correctly, but composition
  ordering has no opinion about two Skills claiming one role. V2.2's composition DAG is where
  this belongs.
- **Every fetched Skill reported "No license was detected".** The cautions surface correctly,
  but a plan can currently be built entirely from unlicensed Skills with no aggregate warning.
- **Role decomposition is unstable between runs.** The same goal produced 6 roles on one run
  and 7 on the next. Coverage percentages are therefore not comparable across runs, which
  matters once historical evidence starts accumulating in V2.2.

## Limits of this benchmark

- The fixture catalog is authored, not sampled from the live 9,610-entry skills.sh catalog.
  Retrieval difficulty is therefore synthetic and probably easier than production.
- Ground truth role labels were written by the same author as the fixture. They encode one
  defensible opinion, not a consensus.
- **The fixture does not reproduce the real cache distribution.** It is ~90% cached; the live
  catalog is mostly uncached. That gap hid F6 entirely, and no fixture change can fix it —
  only live runs will catch this class of defect. Treat every fixture number as an upper bound.
- Variant C has now run twice on one model (`gpt-5.6-luna`, OpenAI's lowest tier) over 12
  scenarios. Two consistent observations is better than one, but it is still not a variance
  measurement, a model comparison, or a cost accounting.
- The benchmark measures plan quality, not implementation quality. Vol.2 §38's real
  question — does a Forge plan produce better code than a plain prompt — requires agent
  execution and is out of scope for V2.1.
- The Anthropic provider still has no live verification. Only the OpenAI path has been
  exercised end to end against a real endpoint.
- Ground truth encodes one defensible opinion, written by the same author as the fixture. A
  12/12 score is a score against that opinion, not against a consensus.

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
`%USERPROFILE%\.forge\history\oracross\2026-08-12-growth-visual-redesign\` and are outside
this workspace. They were never read. Scenario design used only the narrative in
`forge-development-plan-vol2.md` §4, and no synthetic file is presented as an ORACROSS
artifact. Scenarios S01 and S08 encode the shape of that case; their ground truth is
authored, not imported.

TODO: when the real artifacts are reachable, import them as a benchmark scenario and compare
the recorded Skill contribution ratings against what the planner selects.
