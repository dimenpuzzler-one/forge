from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge_planner.fetch import (
    DEFAULT_MAX_FETCH,
    DetailFetcher,
    FetchReport,
    resolve_missing_detail,
)
from forge_planner.policy import GateResult, apply_policy_gate
from forge_planner.provider import (
    PlanProvider,
    PlanProposal,
    PlanRequest,
    SkillCandidate,
)
from forge_registry.database import Registry

PLAN_SCHEMA_VERSION = 1
DEFAULT_CANDIDATE_LIMIT = 60
MAX_QUERIES = 8
# Variants are additive, so the expanded set is allowed to be larger than MAX_QUERIES, but it
# is still bounded: each query is one FTS lookup.
MAX_EXPANDED_QUERIES = 20

# Stop words are dropped before FTS retrieval so a natural-language goal does not
# degrade into a match-everything query.
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how", "in", "into",
    "is", "it", "make", "of", "on", "or", "our", "so", "that", "the", "then", "this",
    "to", "up", "we", "what", "with",
    "그리고", "그것", "하는", "해줘", "해라", "하기", "위해", "이번", "다시", "좀",
}


@dataclass(frozen=True)
class PlanResult:
    plan_id: str
    goal: str
    directory: Path
    retrieved: int
    proposal: PlanProposal
    gate: GateResult
    provider_name: str
    queries: list[str]
    # Exposed so a caller can distinguish "the reranker chose badly" from "retrieval never
    # offered the right Skill". Without this the two failure modes are indistinguishable.
    candidate_ids: list[str] = field(default_factory=list)
    fetch_report: FetchReport = field(default_factory=FetchReport)
    coverage: dict[str, Any] = field(default_factory=dict)


def coverage_of(proposal: PlanProposal, gate: GateResult) -> dict[str, Any]:
    """State plainly how much of the decomposed work the admitted Skills actually cover.

    A plan that admits three Skills for a six-role decomposition looks complete in a list of
    selections. Recording the uncovered roles alongside the reason each was lost keeps an
    incomplete plan from reading as a finished one.
    """
    required = [role for role in dict.fromkeys(proposal.roles) if role]
    admitted_roles = {decision.role for decision in gate.admitted}
    covered = [role for role in required if role in admitted_roles]
    missing = [role for role in required if role not in admitted_roles]
    lost: dict[str, list[str]] = {}
    for decision in gate.rejected:
        if decision.role in missing:
            lost.setdefault(decision.role, []).append(f"{decision.skill_id} ({decision.code})")
    return {
        "requiredRoles": required,
        "coveredRoles": covered,
        "missingRoles": missing,
        "complete": bool(required) and not missing,
        "unknown": not required,
        "lostTo": lost,
        "admittedSkillCount": len(gate.admitted),
    }


def goal_terms(goal: str) -> list[str]:
    tokens = [
        token
        for token in "".join(character if character.isalnum() else " " for character in goal.casefold()).split()
        if len(token) > 1 and token not in STOP_WORDS
    ]
    ordered: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token not in seen:
            seen.add(token)
            ordered.append(token)
    return ordered


def morphological_variants(token: str) -> list[str]:
    """Cheap affix stripping so a natural phrasing still reaches the right Skill.

    SQLite FTS5 tokenizes on exact words with no stemmer, so `search("redesign")` returned
    nothing while `search("design")` returned five results. Rather than add an NLP dependency,
    Forge strips a short list of common English affixes and searches the variants too.

    Deliberately conservative: only affixes that preserve meaning, and never a stem shorter
    than four characters, because short stems produce noise rather than recall.
    """
    variants: list[str] = []
    lowered = token.casefold()
    for prefix in ("re", "un", "pre", "de"):
        if lowered.startswith(prefix) and len(lowered) - len(prefix) >= 4:
            variants.append(lowered[len(prefix) :])
    for suffix, replacement in (
        ("ations", ""), ("ation", ""), ("ments", ""), ("ment", ""),
        ("ingly", ""), ("ing", ""), ("ies", "y"), ("ers", ""), ("er", ""),
        ("ed", ""), ("es", ""), ("s", ""),
    ):
        if lowered.endswith(suffix) and len(lowered) - len(suffix) >= 4:
            stem = lowered[: len(lowered) - len(suffix)]
            variants.append(stem + replacement)
            if suffix in {"ing", "ed", "ation", "ations"} and not stem.endswith("e"):
                # optimized -> optimiz is not a word; optimize is. An unmatched variant costs
                # one FTS lookup and nothing else, so emitting both is the cheaper bet.
                variants.append(f"{stem}e")
            break
    return [variant for variant in dict.fromkeys(variants) if variant and variant != lowered]


def derive_queries(goal: str, project_context: dict[str, Any]) -> list[str]:
    """Deterministic retrieval terms. This runs before any provider call.

    Only technologies the scanner classified as *used* expand the query. A term the project
    merely mentions in prose is recorded in the project context but never searched for, because
    doing so previously spent three of eight queries on domains Forge does not have.
    """
    queries: list[str] = []
    seen: set[str] = set()
    for token in goal_terms(goal):
        if token not in seen:
            seen.add(token)
            queries.append(token)
    for key in ("stack", "domains", "languages"):
        for value in project_context.get(key, []):
            term = str(value).casefold()
            if term and term not in seen:
                seen.add(term)
                queries.append(term)
    return queries[:MAX_QUERIES]


def expand_queries(queries: list[str], goal: str) -> list[str]:
    """Add morphological variants of goal terms, keeping the original order first."""
    goal_set = set(goal_terms(goal))
    expanded = list(queries)
    seen = set(queries)
    for query in queries:
        if query not in goal_set:
            continue
        for variant in morphological_variants(query):
            if variant not in seen:
                seen.add(variant)
                expanded.append(variant)
    return expanded[:MAX_EXPANDED_QUERIES]


def retrieve_candidates(
    registry: Registry,
    queries: list[str],
    *,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    goal: str = "",
) -> list[SkillCandidate]:
    """FTS top-K over local metadata only. No network, no provider, no semantic opinion.

    Applies a relevance floor: when more candidates are available than the limit allows, a
    candidate that matched no goal-derived term is dropped in favour of one that did. A Skill
    surfaced only by a project-context term such as `python` is not about this particular goal,
    and previously such candidates filled the top-K and crowded out real matches.
    """
    literal = set(goal_terms(goal)) if goal else set()
    # A stemmed variant is a guess, so it scores below a term the user actually typed.
    # "landing" yields "land", which matches real but unrelated Skills; without this split the
    # relevance floor treats that match as being as good as a match on "landing" itself.
    derived = {variant for term in literal for variant in morphological_variants(term)} - literal

    found: dict[str, SkillCandidate] = {}
    literal_hits: dict[str, int] = {}
    derived_hits: dict[str, int] = {}
    total_hits: dict[str, int] = {}
    order: dict[str, int] = {}

    for query in queries:
        for row in registry.search(query, limit=limit):
            skill_id = str(row["id"])
            if skill_id not in found:
                found[skill_id] = SkillCandidate(
                    skill_id=skill_id,
                    name=str(row["name"]),
                    source=str(row["source_repo"]),
                    description=str(row["description"] or ""),
                )
                order[skill_id] = len(order)
                literal_hits[skill_id] = derived_hits[skill_id] = total_hits[skill_id] = 0
            total_hits[skill_id] += 1
            if query in literal:
                literal_hits[skill_id] += 1
            elif query in derived:
                derived_hits[skill_id] += 1

    if len(found) <= limit:
        return [found[skill_id] for skill_id in sorted(found, key=lambda item: order[item])]

    ranked = sorted(
        found,
        key=lambda item: (
            -min(literal_hits[item], 1),        # matched a word the user typed
            -min(derived_hits[item], 1),        # else matched a stemmed variant
            -literal_hits[item],
            -derived_hits[item],
            -total_hits[item],
            order[item],
        ),
    )
    return [found[skill_id] for skill_id in ranked[:limit]]


def create_plan(
    registry: Registry,
    provider: PlanProvider,
    *,
    goal: str,
    project_context: dict[str, Any],
    plans_root: Path,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    detail_fetcher: DetailFetcher | None = None,
    snapshots_root: Path | None = None,
    fetch_budget: int = DEFAULT_MAX_FETCH,
) -> PlanResult:
    """Retrieve deterministically, judge semantically, then admit deterministically.

    When `detail_fetcher` is supplied, one extra stage runs between two gate evaluations:
    Skills the provider nominated that were rejected *only* for lacking a cached immutable
    version are fetched through the ordinary inspect pipeline, then the gate is re-run from
    scratch. Fetching is not admission. The second evaluation is exactly as strict as the
    first, and every other rejection code is left alone.
    """
    if not goal.strip():
        raise ValueError("A plan needs a goal. Example: forge plan \"redesign the landing page for conversion\"")

    queries = expand_queries(derive_queries(goal, project_context), goal)
    candidates = retrieve_candidates(registry, queries, limit=candidate_limit, goal=goal)
    candidate_ids = {candidate.skill_id for candidate in candidates}
    request = PlanRequest(goal=goal, project_context=project_context, candidates=candidates)
    proposal = provider.propose(request)
    gate = apply_policy_gate(registry, proposal, candidate_ids=candidate_ids, goal=goal)

    fetch_report = FetchReport()
    if detail_fetcher is not None:
        fetch_report = resolve_missing_detail(
            registry,
            gate,
            fetcher=detail_fetcher,
            candidate_ids=candidate_ids,
            snapshots_root=snapshots_root or (plans_root.parent / "snapshots"),
            budget=fetch_budget,
        )
        if fetch_report.fetched:
            # Re-run the entire gate rather than patching the previous result, so a newly
            # cached Skill still clears every check including its fresh static audit.
            gate = apply_policy_gate(registry, proposal, candidate_ids=candidate_ids, goal=goal)

    plan_id = _plan_id(goal)
    directory = plans_root / plan_id
    directory.mkdir(parents=True, exist_ok=True)
    document = _plan_document(
        plan_id=plan_id,
        goal=goal,
        project_context=project_context,
        provider_name=getattr(provider, "name", "unknown"),
        queries=queries,
        candidates=candidates,
        proposal=proposal,
        gate=gate,
        fetch_report=fetch_report,
    )
    (directory / "plan.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (directory / "plan.md").write_text(render_plan_markdown(document), encoding="utf-8")

    return PlanResult(
        plan_id=plan_id,
        goal=goal,
        directory=directory,
        retrieved=len(candidates),
        proposal=proposal,
        gate=gate,
        provider_name=getattr(provider, "name", "unknown"),
        queries=queries,
        candidate_ids=[candidate.skill_id for candidate in candidates],
        fetch_report=fetch_report,
        coverage=coverage_of(proposal, gate),
    )


def _plan_document(
    *,
    plan_id: str,
    goal: str,
    project_context: dict[str, Any],
    provider_name: str,
    queries: list[str],
    candidates: list[SkillCandidate],
    proposal: PlanProposal,
    gate: GateResult,
    fetch_report: FetchReport,
) -> dict[str, Any]:
    return {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "planId": plan_id,
        "createdAt": _utc_now(),
        "goal": goal,
        "project": {
            "name": project_context.get("name"),
            "root": project_context.get("root"),
            "languages": project_context.get("languages", []),
            "stack": project_context.get("stack", []),
            "domains": project_context.get("domains", []),
        },
        "provider": {
            "name": provider_name,
            "role": "semantic proposal only; it cannot admit a Skill or grant permission",
        },
        "retrieval": {
            "queries": queries,
            "candidateCount": len(candidates),
            "candidateIds": [candidate.skill_id for candidate in candidates],
        },
        "taskType": proposal.task_type,
        "risk": gate.risk,
        "riskProposedByProvider": proposal.risk,
        "explorationBudget": gate.exploration_budget,
        "roles": proposal.roles,
        "selectedSkills": [
            {
                "id": decision.skill_id,
                "role": decision.role,
                "reason": decision.reason,
                "confidence": decision.confidence,
                "source": decision.source,
                "hash": decision.content_hash,
                "securityStatus": decision.security_status,
                "riskLevel": decision.risk_level,
                "requiresReview": decision.requires_review,
                "reviewNotes": decision.review_notes,
                "exploration": False,
                "historicalEvidence": [],
            }
            for decision in gate.admitted
        ],
        "excludedSkills": [
            {"id": exclusion.skill_id, "reason": exclusion.reason, "excludedBy": "provider"}
            for exclusion in proposal.excluded
        ]
        + [
            {
                "id": decision.skill_id,
                "reason": decision.reason,
                "excludedBy": "policy-gate",
                "code": decision.code,
            }
            for decision in gate.rejected
        ],
        "policyGate": {
            "nominated": len(proposal.selected),
            "admitted": len(gate.admitted),
            "rejected": gate.blocked_count,
            "hallucinatedIds": gate.hallucinated_ids,
            "rejectionCodes": _rejection_codes(gate),
        },
        "coverage": coverage_of(proposal, gate),
        "detailFetch": fetch_report.as_dict(),
        "dependencies": [],
        "verificationPlan": proposal.verification_plan,
        "humanApprovalRequired": gate.human_approval_required,
        "evidence": {
            "observed": [
                "Candidate retrieval, registry existence, immutable hashes, and audit state are local facts.",
            ],
            "inferred": [
                "Skill relevance, role assignment, task type, and confidence are provider judgments.",
            ],
            "humanRequired": gate.human_approval_required,
        },
        "providerNotes": proposal.notes,
    }


def render_plan_markdown(document: dict[str, Any]) -> str:
    lines = [
        f"# Forge plan: {document['goal']}",
        "",
        f"- Plan id: `{document['planId']}`",
        f"- Created: {document['createdAt']}",
        f"- Project: {document['project'].get('name') or '(unknown)'}",
        f"- Provider: `{document['provider']['name']}` (proposal only)",
        f"- Risk: **{document['risk']}** (provider proposed: {document['riskProposedByProvider']})",
        f"- Exploration budget: {document['explorationBudget']:.0%}",
        "",
        "## Retrieval",
        "",
        f"Queries: {', '.join(f'`{query}`' for query in document['retrieval']['queries']) or '(none)'}",
        "",
        f"Local FTS returned {document['retrieval']['candidateCount']} candidate(s).",
        "",
        "## Policy gate",
        "",
        f"- Nominated by provider: {document['policyGate']['nominated']}",
        f"- Admitted by Forge: {document['policyGate']['admitted']}",
        f"- Rejected by Forge: {document['policyGate']['rejected']}",
    ]
    if document["policyGate"]["hallucinatedIds"]:
        lines.append(
            f"- Ids the provider invented: {', '.join(f'`{value}`' for value in document['policyGate']['hallucinatedIds'])}"
        )
    for code, count in sorted(document["policyGate"].get("rejectionCodes", {}).items()):
        lines.append(f"- Rejected as `{code}`: {count}")

    coverage = document.get("coverage", {})
    lines += ["", "## Coverage", ""]
    if coverage.get("unknown"):
        lines.append(
            "The provider did not decompose the goal into roles, so coverage cannot be assessed. "
            "Treat this plan as unverified against the goal."
        )
    elif coverage.get("complete"):
        lines.append(
            f"All {len(coverage['requiredRoles'])} decomposed role(s) are covered by an admitted Skill."
        )
    else:
        lines.append(
            f"**This plan is incomplete.** {len(coverage.get('coveredRoles', []))} of "
            f"{len(coverage.get('requiredRoles', []))} decomposed role(s) are covered."
        )
        lines += ["", "Uncovered roles:", ""]
        for role in coverage.get("missingRoles", []):
            lost = coverage.get("lostTo", {}).get(role)
            suffix = f" — lost to: {', '.join(lost)}" if lost else " — no candidate was nominated for it"
            lines.append(f"- `{role}`{suffix}")
        lines += [
            "",
            "Do not treat the selected Skills below as addressing the whole goal.",
        ]

    fetch = document.get("detailFetch", {})
    if fetch.get("enabled"):
        lines += [
            "",
            "## Detail fetch",
            "",
            f"- Fetched for this plan: {fetch.get('fetchedForPlan', 0)}",
            f"- Failed: {fetch.get('failed', 0)}",
            f"- Skipped over budget: {fetch.get('skippedOverBudget', 0)} (budget {fetch.get('budget')})",
        ]
        for outcome in fetch.get("outcomes", []):
            if outcome["status"] != "fetched":
                lines.append(f"- `{outcome['id']}` — {outcome['status']}: {outcome['detail']}")

    lines += ["", "## Selected Skills", ""]
    if not document["selectedSkills"]:
        lines.append("None. No Skill survived the policy gate.")
    for skill in document["selectedSkills"]:
        lines += [
            f"### `{skill['id']}`",
            "",
            f"- Role: {skill['role']}",
            f"- Source: {skill['source']}",
            f"- Pinned hash: `{skill['hash']}`",
            f"- Static audit: {skill['securityStatus']} / {skill['riskLevel']}",
            f"- Provider confidence: {skill['confidence']:.2f} (inferred, not evidence)",
            f"- Reason: {skill['reason']}",
        ]
        for note in skill["reviewNotes"]:
            lines.append(f"- Caution: {note}")
        lines.append("")
    lines += ["## Excluded", ""]
    if not document["excludedSkills"]:
        lines.append("Nothing was explicitly excluded.")
    for exclusion in document["excludedSkills"]:
        lines.append(f"- `{exclusion['id']}` — [{exclusion['excludedBy']}] {exclusion['reason']}")
    lines += ["", "## Verification plan", ""]
    if not document["verificationPlan"]:
        lines.append("The provider did not propose verification steps. Define them before execution.")
    for step in document["verificationPlan"]:
        lines.append(f"- [ ] {step}")
    lines += ["", "## Human validation required", ""]
    if not document["humanApprovalRequired"]:
        lines.append("Nothing was flagged for mandatory human approval.")
    for item in document["humanApprovalRequired"]:
        lines.append(f"- {item}")
    lines += [
        "",
        "## Evidence classes",
        "",
        "**Observed (local fact):**",
    ]
    lines += [f"- {item}" for item in document["evidence"]["observed"]]
    lines += ["", "**Inferred (provider judgment, not proof):**"]
    lines += [f"- {item}" for item in document["evidence"]["inferred"]]
    if document["providerNotes"]:
        lines += ["", "## Provider notes", "", document["providerNotes"]]
    lines += [
        "",
        "---",
        "",
        "This plan is a proposal. Skill selection reasoning came from a language model and is not",
        "verified engineering evidence. Hashes, audit state, and registry existence are local facts.",
        "",
    ]
    return "\n".join(lines)


def _rejection_codes(gate: GateResult) -> dict[str, int]:
    counts: dict[str, int] = {}
    for decision in gate.rejected:
        counts[decision.code or "unspecified"] = counts.get(decision.code or "unspecified", 0) + 1
    return counts


def _plan_id(goal: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(f"{goal}{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:8]
    return f"plan-{stamp}-{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
