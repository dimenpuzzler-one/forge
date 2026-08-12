# ADR-006: An LLM planner cannot override the policy gate

## Status

Accepted, 2026-08-12. Implemented in `forge_planner` for `forge plan`.

## Context

Vol.2 introduces a planner that turns a natural-language goal into a Skill selection.
The only component capable of judging whether a Skill is semantically relevant to a goal
is a language model. But a language model can also state, fluently and confidently, that
a Skill exists when it does not, that it is safe when no audit ran, or that a task is
low-risk when it touches payments.

ADR-004 already established that the core is deterministic and the LLM is optional
enrichment. That framing is not sufficient once the LLM is the component choosing which
procedural knowledge enters an agent's context. A recommendation is no longer decoration;
it decides what the agent reads.

## Decision

The planner is split into two stages with opposite trust properties.

**Stage 1 — proposal.** A `PlanProvider` receives a goal, a trimmed project context, and
a candidate list that a deterministic FTS retrieval already produced. It returns a
`PlanProposal`. It never touches the registry, the filesystem, or the network beyond its
own API. It never sees Skill file contents. Everything it returns is untrusted.

**Stage 2 — admission.** `apply_policy_gate` verifies every nomination against local
facts before any Skill can enter a plan. A nomination is admitted only if all four hold:

1. the id was in the retrieved candidate set,
2. the Skill exists in the local registry,
3. its detail is cached at an immutable content hash,
4. its static audit is not a hard block (`fail` status or `high` risk level).

Anything else is rejected with a recorded reason. Rejections are written to the plan
artifact alongside admissions, so a plan is auditable after the fact.

Two asymmetries are deliberate:

- **Forge may raise risk; it never lowers it.** If the goal text contains a high-risk
  marker (auth, payment, credential, secret, migration, billing, production), the task is
  high-risk regardless of what the provider reported. A provider that calls a payment
  change "low risk" does not get to relax the gate.
- **A soft signal degrades to review, not to silence.** Unknown audits, warnings,
  duplicate flags, and missing licenses do not block admission, but they attach review
  notes that surface in both `plan.json` and `plan.md`.

Invented ids are counted and reported. If a provider names a Skill that was never
retrieved, the plan says so explicitly and tells the reader to discount the rest of that
provider's reasoning.

## Consequences

- Provider quality affects which real Skills are chosen. It cannot affect which Skills
  are permitted, what hash is used, or whether a high-risk task requires approval.
- Forge ships a `StubProvider` that runs offline with no API key. It performs lexical
  overlap only and labels itself as such in every artifact it produces, so the pipeline
  and the gate are testable without a network call and without a false quality signal.
- A plan can legitimately admit zero Skills. That is a real outcome, not an error, and it
  is reported as a blocker rather than papered over with a weaker selection.
- Retrieval quality becomes the ceiling on plan quality. If FTS does not surface a Skill,
  no provider can rescue it. Hybrid retrieval (vector similarity, skill graph, historical
  performance) is the intended follow-up, per Vol.2 §8.

## Alternatives rejected

**Let the provider select directly from the full catalog.** Rejected: it puts ~9,600
Skills in context, makes invented ids indistinguishable from real ones, and gives the
model the permission decision.

**Trust the provider's risk assessment.** Rejected: the failure mode is silent and the
cost is asymmetric. Wrongly raising risk costs one human review. Wrongly lowering it
costs an unreviewed change to payment or auth code.

**Treat a warning-level audit as a block.** Rejected: most Skills carrying scripts trip
the static heuristic, and Forge does not execute scripts anyway. Blocking there would
push users to disable the gate, which is worse than surfacing the warning.
