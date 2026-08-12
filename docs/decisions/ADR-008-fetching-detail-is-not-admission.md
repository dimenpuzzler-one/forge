# ADR-008: Fetching detail is not admission

## Status

Accepted, 2026-08-12. Implemented in `forge_planner.fetch`; exposed as `forge plan --fetch-missing`.

## Context

ADR-006 requires that a Skill carry a cached immutable content hash before it can enter a
plan. The rule is correct and load-bearing: without it, a plan references something that could
change underneath it.

Its practical effect on the real catalog was not anticipated. A live `forge plan` against the
9,610-entry skills.sh catalog:

```text
Retrieved candidates: 60
Policy gate: nominated=6, admitted=1, rejected=5
```

All five rejections were `detail-not-cached`. The language model had nominated reasonable
Skills; Forge simply had never fetched their detail. The user receives one Skill and an
instruction to run `forge inspect` five times and try again.

The planner benchmark did not catch this. Its authored fixture is roughly 90% cached, so the
constraint that dominates real use was structurally absent. The benchmark scored 6/6 on policy
probes while missing the defect with the largest practical impact.

`forge inspect` already performs exactly the needed operation — an on-demand, validated,
hash-computing, snapshot-writing fetch — but only when a human types it.

## Decision

`forge plan --fetch-missing` adds one stage between two gate evaluations:

```text
retrieve -> provider nominates -> gate -> fetch missing detail -> gate again
```

The second evaluation is a full re-run from scratch, not a patch of the first. Five boundaries
make this a retrieval step rather than an admission step:

1. **Candidate-set membership is required.** Only ids the deterministic retrieval already
   produced are eligible. A provider cannot name an arbitrary Skill and cause a network
   request, which would otherwise turn nomination into a server-side request forgery
   primitive.
2. **Only one rejection code is eligible.** `detail-not-cached` and nothing else. An
   audit-blocked Skill, an unknown Skill, and a Skill outside the candidate set are never
   re-fetched. Fetching must not become a way to ask the gate for a second opinion.
3. **Detail is stored through `store_detail`.** The same path `forge inspect` uses, so path
   traversal rejection, size limits, content hashing, snapshot writing, and the static audit
   all still run. The planner gets no privileged ingestion route.
4. **Failure preserves the rejection.** A fetch error is recorded as `fetch_failed` with its
   message; the Skill stays rejected. Partial failure is normal and does not abort the plan.
5. **The fetch is budgeted.** Default 8, maximum 25, and skipped candidates are reported as
   `skipped-over-budget` rather than silently dropped.

Opt-in. Without the flag `forge plan` makes no network request, preserving the previous strict
behaviour for anyone who depends on it.

Rejections now carry structured codes — `detail-not-cached`, `audit-blocked`,
`not-in-candidate-set`, `unknown-skill`, `duplicate-nomination` — so this stage selects its
targets by code rather than by matching human-readable reason text. A wording change must not
be able to alter which Skills get fetched.

## Consequences

- The planner becomes usable against a sparsely cached registry, which is every real registry.
- `forge plan --fetch-missing` performs network I/O and can be slow. That is why it is opt-in
  and budgeted.
- Fetching populates the local cache as a side effect, so subsequent plans over similar goals
  need fewer fetches.
- The ADR-006 invariants are unchanged. A fetched Skill is admitted only if it then passes
  every check, including a static audit computed from content that did not exist locally when
  the provider nominated it.
- The benchmark still cannot exercise this path realistically. Verifying it requires a live
  catalog run, and that gap is recorded rather than papered over with a fixture that pretends
  otherwise.

## Alternatives rejected

**Fetch every retrieved candidate.** Rejected: 60 fetches per plan, mostly for Skills no
provider will nominate.

**Admit uncached Skills and resolve the hash later.** Rejected: it breaks the immutability
guarantee that makes a plan reproducible, in exchange for convenience.

**Let the provider request a fetch.** Rejected: it hands a network capability to untrusted
output. Forge decides what to fetch, from a set the provider cannot influence.
