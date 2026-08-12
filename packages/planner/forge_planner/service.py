from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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


def derive_queries(goal: str, project_context: dict[str, Any]) -> list[str]:
    """Deterministic retrieval terms. This runs before any provider call."""
    tokens = [
        token
        for token in "".join(character if character.isalnum() else " " for character in goal.casefold()).split()
        if len(token) > 1 and token not in STOP_WORDS
    ]
    queries: list[str] = []
    seen: set[str] = set()
    for token in tokens:
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


def retrieve_candidates(
    registry: Registry, queries: list[str], *, limit: int = DEFAULT_CANDIDATE_LIMIT
) -> list[SkillCandidate]:
    """FTS top-K over local metadata only. No network, no provider, no ranking opinion."""
    candidates: list[SkillCandidate] = []
    seen: set[str] = set()
    for query in queries:
        for row in registry.search(query, limit=limit):
            skill_id = str(row["id"])
            if skill_id in seen:
                continue
            seen.add(skill_id)
            candidates.append(
                SkillCandidate(
                    skill_id=skill_id,
                    name=str(row["name"]),
                    source=str(row["source_repo"]),
                    description=str(row["description"] or ""),
                )
            )
            if len(candidates) >= limit:
                return candidates
    return candidates


def create_plan(
    registry: Registry,
    provider: PlanProvider,
    *,
    goal: str,
    project_context: dict[str, Any],
    plans_root: Path,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> PlanResult:
    """Retrieve deterministically, judge semantically, then admit deterministically."""
    if not goal.strip():
        raise ValueError("A plan needs a goal. Example: forge plan \"redesign the landing page for conversion\"")

    queries = derive_queries(goal, project_context)
    candidates = retrieve_candidates(registry, queries, limit=candidate_limit)
    request = PlanRequest(goal=goal, project_context=project_context, candidates=candidates)
    proposal = provider.propose(request)
    gate = apply_policy_gate(
        registry,
        proposal,
        candidate_ids={candidate.skill_id for candidate in candidates},
        goal=goal,
    )

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
            {"id": decision.skill_id, "reason": decision.reason, "excludedBy": "policy-gate"}
            for decision in gate.rejected
        ],
        "policyGate": {
            "nominated": len(proposal.selected),
            "admitted": len(gate.admitted),
            "rejected": gate.blocked_count,
            "hallucinatedIds": gate.hallucinated_ids,
        },
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


def _plan_id(goal: str) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    digest = hashlib.sha256(f"{goal}{uuid.uuid4().hex}".encode("utf-8")).hexdigest()[:8]
    return f"plan-{stamp}-{digest}"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
