# Forge

Forge is a local-first Skill exploration and engineering toolkit. It indexes publicly available Agent Skills, lets you search and inspect the locally cached registry, and builds a safe, machine-readable context for the software project you are working on.

It is deliberately more than a skills.sh downloader: the long-term product connects versioned Skill knowledge with project context, explicit pins, composition experiments, audits, and agent adapters.

```text
forge scan
forge sync --source skills-sh --metadata-only
forge search "postgres production"
forge inspect <skill-id>
forge plan "landing page conversion redesign"
forge learn latest <skill-id> --contribution high
forge benchmark
```

**Core thesis.** A language model judges what a goal means. Forge enforces what is true: which
Skills exist, at which immutable hash, from which source, having passed which audit, and at
what risk level. A model's selection is a proposal; admission is a separate deterministic
decision that the model cannot influence.

**Current honest status.** The safety boundary is demonstrated by tests — six adversarial
probes covering every ADR-006 invariant pass, across 133 tests that make no network call. On
planning quality the benchmark shows a real but one-sided effect: a semantic reranker does not
find more of the right Skills, but it removes nearly all the wrong ones.

Five defects found by the benchmark and by running Forge against itself are fixed and verified
against the live catalog ([V2.1c](#v21c-real-catalog-hardening)). Forge is a policy-bounded
planner foundation — not a system that has been shown to produce better software than a good
prompt.

## Quickstart

No account, token, or network access is needed after installation. Python 3.12+.

```bash
pip install "git+https://github.com/dimenpuzzler-one/forge"
git clone https://github.com/anthropics/skills   # or any folder of Skills, e.g. ~/.claude/skills

forge import skills --label anthropic            # register every SKILL.md it contains
forge search "pdf forms"
forge inspect local/anthropic/skills/pdf         # file list, license, hash, static audit
cd path/to/your-project
forge scan && forge recommend
forge plan "extract tables from invoices"        # proposal only; Forge admits
forge pin local/anthropic/skills/pdf --reason "invoice import"
```

Skill ids follow the folder layout, so `forge search` shows the exact id to use. Re-running
`forge import` with the same `--label` records a new immutable version only for Skills whose
content changed; existing pins never move.

### Use Forge from Claude Code

This repository is also a Claude Code plugin marketplace. The `forge-skills` plugin teaches
the agent to drive Forge and adds a review checklist for third-party Skills:

```text
/plugin marketplace add dimenpuzzler-one/forge
/plugin install forge-skills@forge
```

| Skill | Use it to |
| --- | --- |
| `forge` | find, inspect, plan, and pin Skills with the Forge CLI, relaying evidence instead of deciding for you |
| `skill-audit` | review a third-party Skill (scripts, hooks, `allowed-tools`, exfiltration and override patterns) before adopting it |

The Skills live in [`plugins/forge-skills/skills/`](plugins/forge-skills/skills/), so
`forge import plugins/forge-skills/skills --label forge` also works as an offline demo.
Forge's own static audit rates `skill-audit` `warn / medium`, because the checklist names the
`curl` and credential patterns it looks for. That is the expected limit of a lexical scan:
it flags, a human decides.

## Safety and storage boundaries

- Forge source code and external Skill data are separate. Registry data lives in `FORGE_HOME`, or `~/.forge` when it is unset.
- skills.sh auth is global: Forge uses `VERCEL_OIDC_TOKEN` from the process first, then `<FORGE_HOME>/credentials.env`, then the known Forge checkout `.env.local` for development compatibility. It never searches the current project or target project for `.env` files.
- A planning provider is a proposer, never an authority. It receives only Skill metadata — id, name, source, truncated description — never Skill file contents, and it cannot admit a Skill, choose a version hash, or lower a task's risk level. See [ADR-006](docs/decisions/ADR-006-llm-planner-cannot-override-the-policy-gate.md).
- External `SKILL.md` files and scripts are untrusted data. Forge does not execute them during sync, search, or inspect.
- Detail caching validates paths and size before writing an immutable snapshot. Script files are explicitly marked, never run.
- Project scanning excludes `.env*`, credentials, private keys, Git internals, dependency folders, build outputs, binary data, and large files.
- Metadata sync discovers updates; it never applies or pins a newer Skill to a project automatically.

## Install and run

Requires Python 3.12+. Forge has no runtime dependencies.

```bash
pip install "git+https://github.com/dimenpuzzler-one/forge"   # latest main
# or, for development
git clone https://github.com/dimenpuzzler-one/forge && cd forge
python -m pip install --no-deps -e .
forge doctor
```

Use a throwaway data directory while evaluating Forge:

```bash
export FORGE_HOME="$PWD/.forge-data"        # bash / zsh
```

```powershell
$env:FORGE_HOME = "$PWD\.forge-data"         # PowerShell
```

`FORGE_HOME` is global registry storage; it is not the `.forge` directory that `forge scan` creates inside a scanned project.

For persistent local skills.sh authentication, put only the required token in the global, Git-unrelated file:

```text
~/.forge/credentials.env                     # macOS / Linux
%USERPROFILE%\.forge\credentials.env         # Windows
```

`forge doctor` reports only `skills.sh auth: available|missing` and `auth source: process-env|forge-local-env|none`; it never prints the token.

## Commands

Phases 0–7 (`scan`, `sync`, `search`, `inspect`, `recommend`, `pin`, `collection`, `compose`,
`bundle`, `use`, `diff`, `outdated`, `audit-skill`, `doctor`, `status`) are the plumbing layer.
`plan` and `benchmark` are the Vol.2 porcelain built on top of it.

### Scan a project

```powershell
cd C:\dev\stockback
forge scan
```

The command writes `.forge\project.json` with a bounded, reproducible context: project root, detected languages and stack, domain/architecture hints, test-command hints, and the safe documents considered. It does not execute project code.

**A mention is not a use.** Technology signals are weighted by where the evidence was found. A
dependency in a manifest, an actual import, or a technology-specific config file is classified
`used`. A term appearing only in prose is `mentioned` — recorded with its sources, never
treated as a project fact, and never used to expand a planner retrieval query. Authored test
fixtures, generated artifacts, and `.forge/` contribute nothing at all.

Forge found this defect by scanning itself: documentation examples and benchmark fixtures had
promoted `supabase`, `quant`, and `payments` into the declared stack, which then spent three of
eight retrieval queries on domains the project does not have.

```json
{
  "technology": "supabase",
  "classification": "mentioned",
  "confidence": 0.05,
  "sources": ["docs/development-log/2026-08-11.md"],
  "evidenceKinds": ["prose"]
}
```

Context files are `schemaVersion: 2`. `stack` and `domains` keep their shape but now contain
only `used` technologies; `mentioned` and `signals` are additive.

### Import local Skills

```bash
forge import ~/.claude/skills --label personal
forge import ./vendor/skills --label vendor
```

Every directory that contains a `SKILL.md` becomes one Skill with the id
`local/<label>/<path>`. Its files are read as UTF-8 text and stored through the same path as
`forge inspect`: path validation, 1 MiB per file and 5 MiB per Skill, content hashing,
immutable snapshots, and the static audit. Nothing is executed.

The import deliberately leaves out symlinks, `.git`/`node_modules`/virtualenv folders, binary
files, and secret-looking names (`.env*`, `*.pem`, `*.key`, `credentials*`, SSH keys). It
lists each skipped file with its reason. A nested `SKILL.md` is a separate Skill, never part
of its parent. A Skill over the size limit is rejected as a whole, so no metadata row is left
without a cached version.

Forge stores text only. A Skill that ships fonts, images, or archives is cached without them,
so `forge use` and `forge bundle` produce reference material, not a complete install; use the
upstream folder itself to run such a Skill.

`name`, `description`, and `license` come from the SKILL.md frontmatter. Locally imported
Skills have no upstream audit, so `forge audit-skill` reports Forge's static result, and
`forge inspect --refresh` tells you to re-import instead of contacting skills.sh.

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

Since schema 2 those signals require strong evidence, so a documentation-heavy project returns
fewer recommendations than it used to. That is the intended correction: recommending
payment-security Skills to a project because its README uses "payment" in an example was wrong.

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

**Forge retrieves.** Stop words are dropped; only technologies the scanner classified as `used`
expand the query; conservative affix stripping is applied so `redesign` also searches `design`;
SQLite FTS returns a bounded candidate list, and a relevance floor prefers candidates matching
a goal term over ones matching only a project-context term. No network, no model.

**A provider proposes.** It receives the goal, a trimmed project context, and that candidate
list — id, name, source, truncated description only. Skill file contents are never sent. It
returns task roles, a selection with reasons, exclusions, a risk level, and a verification plan.
Everything it returns is untrusted.

**Forge admits.** Each nomination must clear four deterministic checks: it was in the retrieved
candidate set, it exists in the local registry, its detail is cached at an immutable hash, and
its static audit is not a hard block. Anything else is rejected with a recorded reason and a
structured code, and invented Skill ids are counted and reported. Forge may raise the risk
level from the goal text (auth, payment, credential, secret, migration, billing, production)
but never lowers what the provider reported.
See [ADR-006](docs/decisions/ADR-006-llm-planner-cannot-override-the-policy-gate.md).

Rejection codes are part of the contract, so a later stage branches on the code rather than
parsing prose:

| Code | Meaning |
| --- | --- |
| `not-in-candidate-set` | The provider named an id retrieval never produced |
| `unknown-skill` | No such Skill exists in the local registry |
| `detail-not-cached` | No immutable version hash yet — the only code `--fetch-missing` acts on |
| `audit-blocked` | Static or partner audit returned fail/high |
| `duplicate-nomination` | The same Skill was nominated more than once |

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

Every plan writes `<FORGE_HOME>\plans\<plan-id>\plan.json` and `plan.md`. `plan.json` is
normalized data for later stages; `plan.md` is the human review surface and separates observed
local facts from inferred model judgment. A plan can legitimately admit zero Skills; that is
reported as a blocker rather than filled in with a weaker selection.

`plan.json` top-level keys: `retrieval` (queries and candidate ids), `selectedSkills`,
`excludedSkills` (each with `excludedBy` and a rejection `code`), `policyGate` (counts plus
`rejectionCodes` and `hallucinatedIds`), `coverage`, `detailFetch`, `verificationPlan`,
`humanApprovalRequired`, and `evidence` split into observed / inferred / human-required.

`forge plan` does not compose, bundle, or run anything. It produces a reviewable proposal.

#### Missing detail: `--fetch-missing`

A Skill with no cached immutable version cannot enter a plan. On the real catalog most Skills
are uncached, so a plan can come back as one Skill and a list of `forge inspect` homework.

```powershell
forge plan "landing page conversion redesign" --fetch-missing --fetch-budget 8
```

This resolves detail for nominated Skills that were rejected *only* for lacking a cached
version, then re-runs the gate from scratch. Fetching is not admission:

- only ids the deterministic retrieval already produced are eligible, so a provider cannot
  name an arbitrary Skill and cause a network request;
- an audit-blocked Skill is never re-fetched for a second opinion;
- detail goes through the same path as `forge inspect`, keeping path validation, size limits,
  hashing, snapshotting, and the static audit;
- a fetch failure leaves the rejection in place;
- risk escalation and every other policy check are re-applied afterwards.

Without the flag, `forge plan` never touches the network.

#### Coverage

Every plan states how much of the decomposed goal it actually covers, names the uncovered
roles, and attributes each loss to a specific Skill and rejection code:

```text
Coverage: INCOMPLETE — 1/2 roles covered.
  missing role: visual-design (lost to: acme/skills/design (detail-not-cached))
```

An incomplete plan is labelled as incomplete rather than left to read as a finished one.

### Record what a Skill actually contributed

```powershell
forge plan "landing page conversion redesign"
# ... review the plan, do the work, then judge it
forge learn latest coreyhaines31/marketingskills/page-cro --contribution high --note "CTA hierarchy drove it"
forge skills usage coreyhaines31/marketingskills/page-cro
```

`forge plan` records provenance automatically — which Skills were admitted, at which hash, in
which role. That is *not* a claim that the plan worked. `forge learn` attaches your judgement
of a Skill's contribution to a specific plan, and later plans surface it:

```text
- Past record: selected in 3 prior plan(s); human contribution high: 2, low: 1
- Past record: selected in 3 prior plan(s); no contribution has ever been recorded for it
```

Three rules make this record worth trusting:

- **Only human evidence can be written.** Forge does not execute agents, so it has nothing
  observed to record, and an agent's opinion of its own work is refused outright. Recording it
  would be the feedback loop where a model rates its own output highly and thereby selects the
  same Skill next time.
- **Selection is never endorsement.** A Skill chosen ten times with no recorded contribution
  reports exactly that, rather than looking proven by repetition.
- **History is shown, not injected.** Past evidence appears in `plan.json` and `plan.md` for a
  human to weigh. It is deliberately not added to the provider prompt — that decision belongs
  to V2.2, made with real data rather than assumed now.

See [ADR-009](docs/decisions/ADR-009-evidence-is-recorded-before-it-is-consulted.md).

#### Roles

Evidence accumulates per role, so an unstable role vocabulary scatters it. The same goal
produced six roles on one live run and seven on the next. Forge therefore publishes a canonical
role vocabulary in the provider prompt — `positioning`, `copy`, `conversion`, `visual-design`,
`component-architecture`, `responsive`, `accessibility`, `performance`, `testing`, `security`,
`auth`, `payments`, and others.

Anything outside the list is still accepted, recorded verbatim, and marked `custom:` so it
stays out of aggregates until a human promotes it. Forge applies mechanical normalization only
(case, separators) and keeps no synonym table: mapping `conversion-audit` onto `conversion`
would assert an equivalence the provider never stated and would hide the drift.

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

#### What the measurements say

Measured before the V2.1c retrieval change:

| Variant | Role recall | Ranking gap | Irrelevant rate | Mean admitted | Passed |
| --- | ---: | ---: | ---: | ---: | ---: |
| A — retrieval-only | 0.95 | 0.00 | 0.126 | 3.92 | 7 / 12 |
| B — stub lexical | 0.95 | 0.00 | 0.121 | 3.75 | 8 / 12 |
| C — LLM (`gpt-5.6-luna`) | 0.95 | 0.00 | **0.000** | **1.58** | **11 / 12** |

The two halves say opposite things, and both are true.

**Reranking does not improve recall.** All three variants sat at 0.95 with a ranking gap of
0.00 — every shortfall was caused by retrieval, and no provider can raise that ceiling.

**Reranking is decisive for precision.** The LLM variant took the irrelevant-selection rate to
zero and cut the selection from ~3.9 Skills to 1.6. It also declined to select anything in the
scenario where no correct Skill was available, where both offline variants substituted three
unrelated ones.

After V2.1c the retrieval ceiling rose to 1.00 and every variant reached 1.00 recall. The
offline variants paid about 2 points of precision for it, because more retrieval surfaces more
noise and they cannot filter. The LLM variant paid nothing: 11/12 → **12/12** with its
irrelevant rate unchanged at **0.000**.

#### What it does not prove

Variant C ran once, on one model, on 12 authored scenarios, with no repeat runs — a strong
single observation, not a stable measurement. Whether a Forge plan produces better *code* than
a plain prompt is unmeasured; that needs agent execution, which V2.1 does not perform.

More importantly, **the fixture is ~90% cached and the real catalog is not.** A live run
against 9,610 Skills had five of six nominations rejected for having no cached hash, which the
fixture never surfaced and structurally cannot. `--fetch-missing` exists because of that run.
No fixture change fixes this class of blind spot — only live runs will. Treat the fixture
numbers as an upper bound.

The full evidence, including the two defects the fixture missed entirely and a withdrawn
earlier conclusion, is in [the benchmark findings](docs/roadmap/PLANNER_BENCHMARK.md).

## Development

The repository uses a small Python monorepo boundary:

- `apps/cli/` — CLI entry point
- `packages/benchmark/` — planner measurement harness, fixtures, adversarial policy probes
- `packages/compose/` — composition manifests and deterministic analysis
- `packages/core/` — paths, errors, auth resolution, shared models
- `packages/planner/` — provider abstraction, policy gate, lazy detail fetch, plan artifacts
- `packages/project/` — secret-safe Project Scanner and weighted technology signals
- `packages/registry/` — SQLite migrations, versions, snapshots, audits
- `packages/runtime/` — generic filesystem session bundles
- `packages/search/` — local search boundary
- `packages/sources/` — skills.sh adapter, local directory source, and sync resilience

Run the checks after an editable install (`python -m pip install --no-deps -e .`):

```bash
python -m compileall -q apps packages tests
python -m unittest discover -s tests -t . -v
forge benchmark --output "$(mktemp -d)"   # exits non-zero if an ADR-006 policy probe regresses
```

CI runs the same commands on Linux, macOS, and Windows for Python 3.12 and 3.13. See
[CONTRIBUTING.md](CONTRIBUTING.md).

All 133 tests run offline. The two network providers expose a `_post` seam that the tests
replace, so request shape, error translation, and response parsing are verified without a key.

That cannot prove a live endpoint accepts the request, so the OpenAI path was additionally
verified for real: `forge benchmark --external-provider openai --model gpt-5.6-luna` completed
end to end, confirming `max_completion_tokens` and `response_format` are accepted. **The
Anthropic path has never made a live call.**

## Roadmap

Current milestone: **Vol.2 V2.1 planner foundation, its benchmark, and V2.1c hardening.**

### V2.1c real-catalog hardening

Five defects, all found by measurement rather than review — the two most damaging by running
Forge against itself and against the live catalog, neither of which the authored fixture could
surface:

| | Defect | Fix | ADR |
| --- | --- | --- | --- |
| F6 | On the live catalog, five of six nominations were rejected for having no cached hash | `forge plan --fetch-missing` resolves detail for exactly those, then re-runs the gate | [ADR-008](docs/decisions/ADR-008-fetching-detail-is-not-admission.md) |
| F7 | The scanner read document mentions as project facts, wasting 3 of 8 queries | Weighted evidence; only `used` technologies expand a query | [ADR-007](docs/decisions/ADR-007-a-mention-is-not-a-dependency.md) |
| F1 | The audit hard block was unreachable dead code | External audits escalate onto the version row the gate reads | — |
| F2 | `search("redesign")` returned 0 results while `search("design")` returned 5 | Affix stripping and a relevance floor | — |
| F3 | An incomplete plan looked complete | Coverage marker naming uncovered roles and what each was lost to | — |

Measured effect:

| | before | after |
| --- | --- | --- |
| Retrieval ceiling (fixture) | 0.95 | **1.00** |
| Role recall, all variants | 0.95 | **1.00** |
| Irrelevant rate, offline variants | 0.126 / 0.121 | 0.155 / 0.136 |
| Irrelevant rate, LLM variant | 0.000 | **0.000** |
| Benchmark scenarios passed, LLM variant | 11 / 12 | **12 / 12** |
| `forge scan` on this repo — `stack` | `['supabase']` | `[]` |
| `forge scan` on this repo — `domains` | `['quant','payments','ai','saas']` | `[]` |
| Retrieval queries for a landing goal | 8, three of them wrong | 5, none wrong |

Better retrieval surfaces more true candidates *and* more noise. The offline variants have no
way to filter, so they paid about 2 points of precision for their recall gain. The LLM variant
paid nothing and converted the gain into a perfect score — retrieval sets the ceiling,
reranking decides how much noise comes with it.

### Live verification

Both fixes were confirmed against the real 9,610-entry catalog, not just the fixture:

```text
forge plan "landing page conversion redesign" --provider openai --model gpt-5.6-luna
  nominated=5  admitted=1  rejected=4      coverage 1/6 roles

  ... --fetch-missing
  fetched_for_plan=5  failed=0
  nominated=6  admitted=6  rejected=0      coverage 4/7 roles
```

**V2.1 is closed.**

### V2.2-prep: breaking the evidence cycle

V2.2's first item is historical evidence lookup, but the components that *produce* that
evidence come later in the roadmap. Building V2.2 in the stated order would mean querying a
table nothing writes to. So the producer came first:

| | What |
| --- | --- |
| Schema 4 | `tasks`, `task_skills`, `skill_evaluations` — the minimal subset of Vol.2 §16 |
| `forge plan` | records provenance automatically; not a claim the plan worked |
| `forge learn` | attaches a human contribution judgement to a specific plan |
| `forge skills usage` | shows what is recorded, including when nothing is |
| Role vocabulary | canonical list in the provider prompt; unlisted roles kept and marked `custom:` |

Role decomposition instability — one of the three items carried out of V2.1 — is addressed by
the vocabulary. The other two remain open: duplicate role assignment within one selection, and
no aggregate warning when every selected Skill is unlicensed. Both belong with V2.2's
composition DAG.

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

Forge's own source code is licensed under the [Apache License 2.0](LICENSE). That license covers this repository only; it does not extend to external Skills that Forge indexes or caches.
