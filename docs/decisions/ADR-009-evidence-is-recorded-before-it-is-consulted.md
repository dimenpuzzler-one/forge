# ADR-009: Evidence is recorded before it is consulted

## Status

Accepted, 2026-08-12. Implemented as registry schema 4, `forge_planner.roles`,
`forge_planner.evidence`, `forge learn`, and `forge skills usage`.

## Context

Vol.2 Milestone V2.2 lists "historical Skill evidence lookup" as its first item. The
components that *produce* that evidence — `forge finalize` in V2.4 and `forge learn` in V2.5 —
come later in the same roadmap. Implementing V2.2 in the stated order would mean writing a
query against a table nothing ever writes to, which `AGENTS.md` names directly: prefer a
tested vertical slice over empty future packages or unverified roadmap claims.

Two further problems had to be settled before any evidence could accumulate usefully.

**Roles were unstable.** The same goal, run twice against the live catalog, produced six roles
then seven, with `conversion-audit`, `conversion-validation`, and `copywriting` appearing where
`conversion` and `copy` would do. Evidence keyed on role would fragment across names that mean
the same thing, and coverage percentages would not be comparable between runs.

**Evidence quality varies enormously.** Vol.2 section 17 is explicit that an agent's opinion of
its own work is weak, and section 40 Risk C describes the failure mode: an agent rates its own
output highly, that rating selects the same Skill next time, and the loop closes on itself.

## Decision

Build the smallest honest producer first, then let V2.2 consume it.

**Schema 4** adds `tasks`, `task_skills`, and `skill_evaluations` — the minimal subset of
Vol.2 section 16. `forge plan` writes a task row and its admitted Skills automatically. That is
provenance only: it records that a plan was produced, never that it worked.

**Only human evidence is writable.** `record_contribution` accepts `human` and rejects
`inferred` with an explanation. `observed` exists in the schema but has no producer, because
Forge does not execute agents and therefore has nothing observed to record. Reserving both
means adding them later needs no migration and no reinterpretation of stored rows.

**Selection is never treated as endorsement.** A Skill selected ten times with no recorded
contribution reports exactly that: `"Selected in 10 plan(s), but never evaluated. Selection is
not evidence of contribution."` Plans say `no contribution has ever been recorded for it`
rather than leaving an unevaluated Skill looking as proven as an evaluated one.

**History is shown, not injected.** The planner reads history and puts it in `plan.json` and
`plan.md` for a human to weigh. It is deliberately *not* added to the provider prompt. Feeding
a Skill's selection history to the model that decides whether to select it again is precisely
the corruption loop of Risk C. Whether to inject it, behind an exploration budget, is a V2.2
decision that should be made with this data in hand rather than assumed now.

**Roles come from a published vocabulary.** Forge defines canonical roles and puts them in the
provider system prompt. Anything outside the list is still accepted, recorded verbatim, and
marked `custom:` so it stays out of aggregate evidence until a human promotes it. Vol.2
section 8 requires the taxonomy stay open; this keeps it open without letting it drift silently.

Normalization is mechanical only — case, separators, whitespace. There is no synonym table.
Mapping `conversion-audit` onto `conversion` would assert an equivalence the provider never
stated, and would hide exactly the drift this is meant to surface. Providers are told the
vocabulary instead of being second-guessed after the fact.

## Consequences

- V2.2 can now query real rows. The circular dependency is broken with roughly 200 lines rather
  than by building all of V2.4 and V2.5 first.
- Evidence only accumulates when a human runs `forge learn`. Adoption is the limit on how fast
  the record grows, which is the correct constraint: the alternative is filling the table with
  self-assessments that mean nothing.
- Any Skill whose role the provider invents lands in a `custom:` bucket and contributes nothing
  to aggregates until reviewed. Early runs will produce more custom roles than later ones as
  providers converge on the published list.
- Re-evaluating a Skill on the same plan replaces the previous verdict rather than accumulating
  two, so a corrected judgement does not double-count.
- `contribution` is a four-value scale (`none`, `low`, `medium`, `high`), not a number.
  Vol.2 section 17 explicitly refuses to collapse relevance, safety, implementation impact, and
  human preference into one score.

## Alternatives rejected

**Implement V2.2 in the stated order and stub the lookup.** Rejected: it produces a query with
no data, a metric with no meaning, and no way to tell whether the feature works.

**Let agents record their own contribution.** Rejected by Vol.2 section 40 Risk C. It is the
fastest way to fill the table and the fastest way to make it worthless.

**Infer contribution from selection frequency.** Rejected: it is popularity bias with extra
steps (Risk B), and it would make a Skill that is retrieved often look proven.

**Maintain a synonym table for roles.** Rejected: it hides drift instead of correcting it, and
it makes Forge responsible for guessing what a provider meant. Publishing the vocabulary
addresses the cause rather than the symptom.
