from __future__ import annotations

from dataclasses import dataclass, field

from forge_planner.provider import PlanProposal, SkillProposal
from forge_registry.database import Registry

# Risk tiers that force human approval before any agent handoff.
HIGH_RISK_MARKERS = ("auth", "payment", "credential", "secret", "migration", "billing", "production")

# Vol.2 §3.5. The budget is recorded now and enforced by the composer in V2.2; the gate
# never lets a high-risk task carry exploration.
EXPLORATION_BUDGET = {"low": 0.30, "medium": 0.15, "high": 0.0}


@dataclass(frozen=True)
class GateDecision:
    """One deterministic verdict about one Skill the provider proposed."""

    skill_id: str
    admitted: bool
    reason: str
    role: str = "general"
    confidence: float = 0.0
    source: str | None = None
    content_hash: str | None = None
    security_status: str | None = None
    risk_level: str | None = None
    requires_review: bool = False
    review_notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateResult:
    admitted: list[GateDecision]
    rejected: list[GateDecision]
    hallucinated_ids: list[str]
    risk: str
    exploration_budget: float
    human_approval_required: list[str]

    @property
    def blocked_count(self) -> int:
        return len(self.rejected)


def apply_policy_gate(
    registry: Registry,
    proposal: PlanProposal,
    *,
    candidate_ids: set[str],
    goal: str = "",
) -> GateResult:
    """Verify an LLM proposal against local facts.

    The provider cannot admit a Skill. It can only nominate one. Every nomination must
    survive four deterministic checks: it was in the retrieved candidate set, it exists
    in the local registry, its detail is cached at an immutable hash, and its audit state
    is not a hard block. Anything else is rejected with a recorded reason.
    """
    risk = _effective_risk(proposal.risk, goal)
    admitted: list[GateDecision] = []
    rejected: list[GateDecision] = []
    hallucinated: list[str] = []
    seen: set[str] = set()

    for nomination in proposal.selected:
        if nomination.skill_id in seen:
            rejected.append(
                _reject(nomination, "The provider nominated this Skill more than once; the duplicate was dropped.")
            )
            continue
        seen.add(nomination.skill_id)

        if nomination.skill_id not in candidate_ids:
            hallucinated.append(nomination.skill_id)
            rejected.append(
                _reject(
                    nomination,
                    "Not present in the retrieved candidate set. Forge treats an unrequested id as "
                    "an unverifiable provider claim and drops it.",
                )
            )
            continue

        skill = registry.get_skill(nomination.skill_id)
        if skill is None:
            hallucinated.append(nomination.skill_id)
            rejected.append(
                _reject(nomination, "No such Skill exists in the local registry.")
            )
            continue

        if skill["latest_seen_version_id"] is None or not skill["content_hash"]:
            rejected.append(
                _reject(
                    nomination,
                    "Detail is not cached, so no immutable version hash exists yet. "
                    f"Run `forge inspect {nomination.skill_id}` before this Skill can enter a plan.",
                    source=str(skill["source_repo"]),
                )
            )
            continue

        security_status = str(skill["security_status"] or "unknown").casefold()
        risk_level = str(skill["risk_level"] or "unknown").casefold()
        review_notes: list[str] = []

        if security_status == "fail" or risk_level == "high":
            rejected.append(
                _reject(
                    nomination,
                    f"Blocked by the audit gate: static security status is {security_status} "
                    f"and risk level is {risk_level}.",
                    source=str(skill["source_repo"]),
                    content_hash=str(skill["content_hash"]),
                    security_status=security_status,
                    risk_level=risk_level,
                )
            )
            continue

        if security_status == "unknown":
            review_notes.append("The Skill has no completed static audit; review it before executing.")
        if security_status == "warn":
            review_notes.append(f"Static audit returned a warning at risk level {risk_level}.")
        if skill["is_duplicate"]:
            review_notes.append("The upstream source marks this Skill as a possible duplicate.")
        if not skill["license_spdx"]:
            review_notes.append("No license was detected for this Skill version.")
        if risk == "high" and security_status != "pass":
            review_notes.append(
                "This is a high-risk task, so anything short of a passing audit requires explicit human approval."
            )

        admitted.append(
            GateDecision(
                skill_id=nomination.skill_id,
                admitted=True,
                reason=nomination.reason,
                role=nomination.role,
                confidence=nomination.confidence,
                source=str(skill["source_repo"]),
                content_hash=str(skill["content_hash"]),
                security_status=security_status,
                risk_level=risk_level,
                requires_review=bool(review_notes),
                review_notes=review_notes,
            )
        )

    human_approval = list(proposal.human_approval_required)
    if risk == "high":
        human_approval.append(
            "Task risk is high. Forge requires explicit human approval before any agent handoff."
        )
    if hallucinated:
        human_approval.append(
            f"The provider named {len(hallucinated)} Skill id(s) that do not exist in the retrieved "
            "candidate set. Treat the rest of its reasoning with corresponding caution."
        )
    if not admitted:
        human_approval.append(
            "No Skill survived the policy gate. This plan cannot be composed or bundled as-is."
        )

    return GateResult(
        admitted=admitted,
        rejected=rejected,
        hallucinated_ids=hallucinated,
        risk=risk,
        exploration_budget=EXPLORATION_BUDGET[risk],
        human_approval_required=human_approval,
    )


def _effective_risk(proposed: str, goal: str) -> str:
    """Forge may raise risk. It never lowers what the provider reported."""
    normalized = proposed if proposed in EXPLORATION_BUDGET else "medium"
    if any(marker in goal.casefold() for marker in HIGH_RISK_MARKERS):
        return "high"
    return normalized


def _reject(
    nomination: SkillProposal,
    reason: str,
    *,
    source: str | None = None,
    content_hash: str | None = None,
    security_status: str | None = None,
    risk_level: str | None = None,
) -> GateDecision:
    return GateDecision(
        skill_id=nomination.skill_id,
        admitted=False,
        reason=reason,
        role=nomination.role,
        confidence=nomination.confidence,
        source=source,
        content_hash=content_hash,
        security_status=security_status,
        risk_level=risk_level,
    )
