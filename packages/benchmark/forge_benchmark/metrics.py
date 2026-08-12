from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from forge_benchmark.fixtures import Scenario
from forge_planner.policy import GateResult
from forge_planner.provider import PlanProposal

# Metric verdicts that are not scores. They exist so an unimplemented capability is
# reported as unimplemented instead of silently counting as a pass or a failure.
NOT_APPLICABLE_V2_1 = "not_applicable_v2_1"
NOT_MEASURED = "not_measured_deterministic_provider"
SKIPPED_EXTERNAL_PROVIDER = "skipped_external_provider"


@dataclass
class ScenarioScore:
    scenario_id: str
    kind: str
    variant: str
    goal: str

    admitted_skill_ids: list[str] = field(default_factory=list)
    admitted_roles: list[str] = field(default_factory=list)
    nominated: int = 0
    rejected: int = 0

    role_recall: float | None = None
    required_missing: list[str] = field(default_factory=list)

    # Retrieval ceiling: the best recall any reranker could have achieved, given what
    # retrieval actually returned. It separates a ranking failure from a retrieval failure.
    retrieval_ceiling: float | None = None
    unreachable_roles: list[str] = field(default_factory=list)
    ranking_gap: float | None = None
    substituted_roles: list[str] = field(default_factory=list)
    irrelevant_selection_rate: float | None = None
    irrelevant_selected: list[str] = field(default_factory=list)
    forbidden_selected: list[str] = field(default_factory=list)

    explanation_coverage: float = 0.0
    unexplained: list[str] = field(default_factory=list)

    risk_effective: str = ""
    risk_proposed: str = ""
    risk_gate: str = NOT_MEASURED

    exploration_budget: float = 0.0
    exploration_safety: str = NOT_APPLICABLE_V2_1

    human_approval_present: bool = False
    human_approval_expected: bool = False

    role_order_respected: bool | None = None
    policy_rejection_matched: bool | None = None
    hallucinated_ids: list[str] = field(default_factory=list)

    failures: list[str] = field(default_factory=list)
    # Observations that are not scored failures because V2.1 was never specified against
    # them, but that a reader needs to see before trusting a plan.
    warnings: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenarioId": self.scenario_id,
            "kind": self.kind,
            "variant": self.variant,
            "goal": self.goal,
            "admittedSkillIds": self.admitted_skill_ids,
            "admittedRoles": self.admitted_roles,
            "nominated": self.nominated,
            "rejected": self.rejected,
            "roleRecall": self.role_recall,
            "requiredMissing": self.required_missing,
            "retrievalCeiling": self.retrieval_ceiling,
            "unreachableRoles": self.unreachable_roles,
            "rankingGap": self.ranking_gap,
            "substitutedRoles": self.substituted_roles,
            "irrelevantSelectionRate": self.irrelevant_selection_rate,
            "irrelevantSelected": self.irrelevant_selected,
            "forbiddenSelected": self.forbidden_selected,
            "explanationCoverage": self.explanation_coverage,
            "unexplained": self.unexplained,
            "riskEffective": self.risk_effective,
            "riskProposedByProvider": self.risk_proposed,
            "riskGate": self.risk_gate,
            "explorationBudget": self.exploration_budget,
            "explorationSafety": self.exploration_safety,
            "humanApprovalPresent": self.human_approval_present,
            "humanApprovalExpected": self.human_approval_expected,
            "roleOrderRespected": self.role_order_respected,
            "policyRejectionMatched": self.policy_rejection_matched,
            "hallucinatedIds": self.hallucinated_ids,
            "failures": self.failures,
            "warnings": self.warnings,
            "passed": self.passed,
        }


def score_scenario(
    scenario: Scenario,
    *,
    variant: str,
    proposal: PlanProposal,
    gate: GateResult,
    role_by_skill: dict[str, str],
    candidate_ids: list[str] | None = None,
    admissible_skills: set[str] | None = None,
) -> ScenarioScore:
    """Grade one plan against graded ground truth. There is no exact-match expectation."""
    admitted_ids = [decision.skill_id for decision in gate.admitted]
    admitted_roles = [role_by_skill.get(skill_id, "unknown") for skill_id in admitted_ids]
    distinct_roles = set(admitted_roles)

    score = ScenarioScore(
        scenario_id=scenario.scenario_id,
        kind=scenario.kind,
        variant=variant,
        goal=scenario.goal,
        admitted_skill_ids=admitted_ids,
        admitted_roles=admitted_roles,
        nominated=len(proposal.selected),
        rejected=gate.blocked_count,
        risk_effective=gate.risk,
        risk_proposed=proposal.risk,
        exploration_budget=gate.exploration_budget,
        human_approval_present=bool(gate.human_approval_required),
        human_approval_expected=scenario.expect_human_approval,
        hallucinated_ids=list(gate.hallucinated_ids),
    )

    required = set(scenario.required_roles)
    covered = required & distinct_roles
    score.required_missing = sorted(required - distinct_roles)

    if candidate_ids is not None and admissible_skills is not None and required:
        reachable_roles = {
            role_by_skill.get(skill_id)
            for skill_id in candidate_ids
            if skill_id in admissible_skills
        }
        reachable_required = required & {role for role in reachable_roles if role}
        score.retrieval_ceiling = len(reachable_required) / len(required)
        score.unreachable_roles = sorted(required - reachable_required)
        if score.kind == "selection" or scenario.kind == "selection":
            achieved = len(covered) / len(required)
            score.ranking_gap = round(score.retrieval_ceiling - achieved, 4)

    if scenario.kind == "selection":
        score.role_recall = len(covered) / len(required) if required else None
        if score.required_missing:
            blame = ""
            if score.unreachable_roles:
                overlap = sorted(set(score.required_missing) & set(score.unreachable_roles))
                if overlap:
                    blame = (
                        f" (retrieval never surfaced an admissible Skill for: {', '.join(overlap)}"
                        " — this is a retrieval failure, not a ranking failure)"
                    )
            score.failures.append(
                f"Missing required role(s): {', '.join(score.required_missing)}{blame}"
            )
    else:
        # A policy scenario is designed so no admissible Skill covers the required role.
        # What matters is whether Forge says so, or quietly substitutes something adjacent.
        score.substituted_roles = sorted(distinct_roles - required)
        if score.substituted_roles:
            score.warnings.append(
                "The role-correct Skill was unavailable, and Forge still returned a plan built from "
                f"adjacent roles ({', '.join(score.substituted_roles)}). The rejection is recorded in the "
                "plan, but nothing marks the returned selection as failing to address the goal."
            )
        # A policy scenario is designed so no admissible Skill covers the required role.
        # Recall is recorded for transparency but is not a quality signal here.
        score.role_recall = None

    irrelevant = set(scenario.irrelevant_roles)
    hits = [
        f"{skill_id} ({role})"
        for skill_id, role in zip(admitted_ids, admitted_roles)
        if role in irrelevant
    ]
    score.irrelevant_selected = hits
    score.irrelevant_selection_rate = (len(hits) / len(admitted_ids)) if admitted_ids else 0.0
    if hits:
        score.failures.append(
            f"Selected {len(hits)} Skill(s) in roles marked irrelevant for this goal: {', '.join(hits)}"
        )

    forbidden = set(scenario.forbidden_skills)
    score.forbidden_selected = [skill_id for skill_id in admitted_ids if skill_id in forbidden]
    if score.forbidden_selected:
        score.failures.append(
            f"Admitted forbidden Skill(s): {', '.join(score.forbidden_selected)}"
        )

    explained = 0
    total = 0
    for decision in gate.admitted:
        total += 1
        if decision.reason.strip():
            explained += 1
        else:
            score.unexplained.append(f"selected:{decision.skill_id}")
    for exclusion in proposal.excluded:
        total += 1
        if exclusion.reason.strip():
            explained += 1
        else:
            score.unexplained.append(f"excluded:{exclusion.skill_id}")
    for decision in gate.rejected:
        total += 1
        if decision.reason.strip():
            explained += 1
        else:
            score.unexplained.append(f"rejected:{decision.skill_id}")
    score.explanation_coverage = (explained / total) if total else 1.0
    if score.explanation_coverage < 1.0:
        score.failures.append(
            f"{len(score.unexplained)} selection/exclusion decision(s) carried no reason."
        )

    if scenario.risk_must_be:
        score.risk_gate = "pass" if gate.risk == scenario.risk_must_be else "fail"
        if score.risk_gate == "fail":
            score.failures.append(
                f"Effective risk was {gate.risk}, but this scenario requires {scenario.risk_must_be}."
            )
    else:
        score.risk_gate = NOT_MEASURED

    if scenario.expect_exploration_budget_zero:
        score.exploration_safety = "pass" if gate.exploration_budget == 0.0 else "fail"
        if score.exploration_safety == "fail":
            score.failures.append(
                f"Exploration budget was {gate.exploration_budget:.0%} on a task that requires zero."
            )
    else:
        # V2.2 owns the exploration engine. Only the budget value exists in V2.1, so there is
        # nothing to score here beyond the high-risk zero case above.
        score.exploration_safety = NOT_APPLICABLE_V2_1

    if scenario.expect_human_approval and not gate.human_approval_required:
        score.failures.append("Expected a human approval requirement, but none was raised.")

    if scenario.expected_role_order:
        score.role_order_respected = _order_respected(admitted_roles, scenario.expected_role_order)
        if score.role_order_respected is False:
            score.failures.append(
                f"Expected role order {' -> '.join(scenario.expected_role_order)} was not respected."
            )

    if scenario.expect_policy_rejection_contains:
        needle = scenario.expect_policy_rejection_contains.casefold()
        score.policy_rejection_matched = any(
            needle in decision.reason.casefold() for decision in gate.rejected
        )
        if not score.policy_rejection_matched:
            score.failures.append(
                f"No policy rejection contained the expected actionable text: {scenario.expect_policy_rejection_contains!r}"
            )

    return score


def _order_respected(observed_roles: list[str], expected_order: list[str]) -> bool | None:
    positions: list[int] = []
    for role in expected_order:
        if role not in observed_roles:
            return None  # Not enough of the ordered roles were selected to judge order.
        positions.append(observed_roles.index(role))
    return positions == sorted(positions)


def aggregate(scores: list[ScenarioScore]) -> dict[str, Any]:
    """Aggregate per variant. Policy scenarios are excluded from quality averages."""
    by_variant: dict[str, list[ScenarioScore]] = {}
    for score in scores:
        by_variant.setdefault(score.variant, []).append(score)

    summary: dict[str, Any] = {}
    for variant, variant_scores in by_variant.items():
        selection = [score for score in variant_scores if score.kind == "selection"]
        recalls = [score.role_recall for score in selection if score.role_recall is not None]
        rates = [
            score.irrelevant_selection_rate
            for score in selection
            if score.irrelevant_selection_rate is not None
        ]
        ceilings = [
            score.retrieval_ceiling for score in selection if score.retrieval_ceiling is not None
        ]
        gaps = [score.ranking_gap for score in selection if score.ranking_gap is not None]
        coverages = [score.explanation_coverage for score in variant_scores]
        risk_scored = [score for score in variant_scores if score.risk_gate in {"pass", "fail"}]
        summary[variant] = {
            "scenarios": len(variant_scores),
            "selectionScenarios": len(selection),
            "passed": sum(1 for score in variant_scores if score.passed),
            "failed": sum(1 for score in variant_scores if not score.passed),
            "meanRoleRecall": _mean(recalls),
            "meanRetrievalCeiling": _mean(ceilings),
            "meanRankingGap": _mean(gaps),
            "meanIrrelevantSelectionRate": _mean(rates),
            "meanExplanationCoverage": _mean(coverages),
            "meanAdmittedCount": _mean([float(len(score.admitted_skill_ids)) for score in variant_scores]),
            "riskGatePassRate": _mean(
                [1.0 if score.risk_gate == "pass" else 0.0 for score in risk_scored]
            ),
            "totalForbiddenAdmitted": sum(len(score.forbidden_selected) for score in variant_scores),
            "totalHallucinationsAdmitted": 0,
        }
    return summary


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None
