from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_core.errors import ValidationError
from forge_registry.database import Registry

# Vol.2 section 3.3 and 17. Not all evidence is worth the same, so the class is stored
# alongside the value and never collapsed into a single score.
#
#   human    a person judged this after seeing the result          strongest available today
#   observed a command, test, or browser check produced it         not yet produced by Forge
#   inferred an agent's opinion of its own work                    weakest; never auto-promoted
#
# Only `human` can be written at present. Forge does not execute agents, so it has nothing
# observed to record, and an agent self-report would be the corruption vector Vol.2 section 40
# Risk C describes. The other classes exist in the schema so that adding them later does not
# require a migration or a re-interpretation of rows already stored.
EVIDENCE_CLASSES = ("human", "observed", "inferred")
WRITABLE_EVIDENCE_CLASSES = ("human",)

# Ordered worst to best so a caller can compare without a lookup table.
CONTRIBUTIONS = ("none", "low", "medium", "high")
CONTRIBUTION_RANK = {value: index for index, value in enumerate(CONTRIBUTIONS)}


@dataclass(frozen=True)
class SkillHistory:
    skill_id: str
    selected_in_tasks: int
    evaluated: bool
    contributions: list[dict[str, Any]]
    roles: list[dict[str, Any]]
    common_pairings: list[dict[str, Any]]

    @property
    def human_verdicts(self) -> dict[str, int]:
        return {
            str(entry["contribution"]): int(entry["count"])
            for entry in self.contributions
            if entry["evidenceClass"] == "human"
        }

    def summary_line(self) -> str:
        """One line stating what is known, including when nothing is."""
        if not self.selected_in_tasks:
            return "Never selected in a recorded plan."
        if not self.evaluated:
            return (
                f"Selected in {self.selected_in_tasks} plan(s), but never evaluated. "
                "Selection is not evidence of contribution."
            )
        verdicts = self.human_verdicts
        parts = [f"{contribution}={verdicts[contribution]}" for contribution in reversed(CONTRIBUTIONS) if contribution in verdicts]
        return f"Selected in {self.selected_in_tasks} plan(s); human verdicts: {', '.join(parts)}."

    def as_plan_evidence(self) -> list[str]:
        """The compact form embedded in a plan artifact."""
        if not self.selected_in_tasks:
            return []
        entries = [f"selected in {self.selected_in_tasks} prior plan(s)"]
        for contribution, count in sorted(
            self.human_verdicts.items(), key=lambda item: -CONTRIBUTION_RANK.get(item[0], 0)
        ):
            entries.append(f"human contribution {contribution}: {count}")
        if not self.evaluated:
            entries.append("no contribution has ever been recorded for it")
        return entries


def load_history(registry: Registry, skill_id: str) -> SkillHistory:
    raw = registry.skill_history(skill_id)
    return SkillHistory(
        skill_id=raw["skillId"],
        selected_in_tasks=raw["selectedInTasks"],
        evaluated=raw["evaluated"],
        contributions=raw["contributions"],
        roles=raw["roles"],
        common_pairings=raw["commonPairings"],
    )


def record_contribution(
    registry: Registry,
    *,
    plan_id: str,
    skill_id: str,
    contribution: str,
    note: str = "",
    evidence_class: str = "human",
) -> None:
    """Attach a human judgement of one Skill's contribution to one recorded plan."""
    if contribution not in CONTRIBUTIONS:
        raise ValidationError(
            f"Contribution must be one of: {', '.join(CONTRIBUTIONS)}. Received: {contribution!r}"
        )
    if evidence_class not in WRITABLE_EVIDENCE_CLASSES:
        raise ValidationError(
            f"Only {', '.join(WRITABLE_EVIDENCE_CLASSES)} evidence can be recorded today. "
            "Forge does not execute agents, so it has no observed result to store, and an "
            "agent's opinion of its own work is not accepted as evidence."
        )
    task = registry.get_task(plan_id)
    if task is None:
        raise ValidationError(
            f"No recorded plan with id {plan_id}. Run `forge plan` first, or use `latest`."
        )
    registry.record_evaluation(
        task_id=int(task["id"]),
        skill_id=skill_id,
        contribution=contribution,
        evidence_class=evidence_class,
        note=note,
    )


def resolve_plan_id(registry: Registry, plan_id: str) -> str:
    """Accept `latest` as an alias for the most recently recorded plan."""
    if plan_id.strip().casefold() != "latest":
        return plan_id
    task = registry.latest_task()
    if task is None:
        raise ValidationError("No plan has been recorded yet. Run `forge plan` first.")
    return str(task["plan_id"])
