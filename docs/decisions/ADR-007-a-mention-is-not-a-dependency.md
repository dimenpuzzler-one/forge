# ADR-007: A mention is not a dependency

## Status

Accepted, 2026-08-12. Implemented in `forge_project.signals`; project context is schema 2.

## Context

`scan_project` derived a project's stack and domains by concatenating every document it had
read into one string and testing for term membership. Any occurrence anywhere became a
project fact.

Forge found the consequence by scanning itself. It reported `stack: ['supabase']` and
`domains: ['quant', 'payments', 'ai', 'saas']`. Forge uses none of those. The terms came from
an implementation brief, a development log, a planning document, and the planner benchmark's
authored fixtures — which describe *other* projects by design.

This was not cosmetic. The planner expands its retrieval queries with the project's declared
stack and domains, so a live `forge plan` spent three of eight queries on `supabase`, `quant`,
and `payments`, and the 60-candidate ceiling filled partly with noise. Every downstream stage
inherited the error, and nothing in the output indicated it had happened.

The general shape: a documentation-heavy repository is penalised in proportion to how well it
documents itself, and a repository that discusses technologies it rejected is penalised for
recording the decision.

## Decision

Technology detection is evidence-weighted, and the weight depends on where the evidence was
found rather than on how many times the term appears.

| Evidence | Weight | Examples |
| --- | ---: | --- |
| manifest | 1.00 | a declared dependency in `package.json`, `pyproject.toml`, `requirements*.txt`, `go.mod`, `Cargo.toml` |
| import | 0.90 | an actual `import` or `require` in source |
| config | 0.85 | `next.config.ts`, `supabase/config.toml`, `turbo.json` |
| project-name | 0.35 | the directory name contains the term |
| readme | 0.20 | the primary README |
| prose | 0.05 | planning notes, development logs, architecture documents |

Each kind contributes at most once, so repeating a word in prose cannot accumulate into a
dependency. A technology at total confidence >= 0.5 is classified `used`; anything below is
`mentioned`.

These paths contribute no signal at all: `tests/fixtures/**`, `test/fixtures/**`,
`artifacts/**`, `.forge/**`, `node_modules/**`, `vendor/**`, `third_party/**`, `examples/**`.
They contain descriptions of other projects by construction.

`stack` and `domains` contain only `used` technologies. `mentioned` and `signals` are new
fields; `signals` carries the classification, confidence, contributing source files, and
evidence kinds for every technology detected, so a surprising classification can be audited
rather than guessed at.

**Only `used` technologies expand a planner retrieval query.** A mention is recorded and never
searched for.

## Consequences

- Measured on this repository, `stack` went from `['supabase']` to `[]` and `domains` from
  `['quant', 'payments', 'ai', 'saas']` to `[]`. A landing-page goal went from 8 retrieval
  queries with 3 wasted to 5 with none wasted.
- `forge recommend` returns fewer results for documentation-heavy projects, because its rules
  read `stack` and `domains`. This is the correction working: recommending payment-security
  Skills to Forge because its README uses "payment" in an example was wrong.
- Detection is now conservative in the other direction. A project that genuinely uses a
  technology without declaring it in a manifest, importing it, or carrying its config file
  will be classified `mentioned`. Under-claiming is the safer failure: an omitted query costs
  recall, an invented one silently corrupts every later stage.
- One scanner test changed. It asserted that `backtesting` and `kr-equity` entered `domains`
  from a single README sentence. That assertion encoded the defect, and now asserts the
  opposite along with their presence in `mentioned`.
- Adding a technology now means declaring its packages, modules, configs, and terms in one
  table rather than editing branching logic.

## Alternatives rejected

**Count occurrences and threshold.** Rejected: it separates nothing. Forge's README mentions
"payment" about as often as a small payments project's README does.

**Trust the README as strong evidence.** Rejected for the same reason. A README that explains
a decision or gives an example mentions technologies the project does not use, and Forge's
does exactly that.

**Ask a language model to classify the project.** Rejected: it inverts ADR-006. Project
context is an input to the deterministic gate, so deriving it from a model would make the
gate's inputs untrusted.
