from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from forge_core.errors import ForgeError
from forge_planner.policy import REJECT_DETAIL_NOT_CACHED, GateResult
from forge_registry.database import Registry

DEFAULT_MAX_FETCH = 8


class DetailFetcher(Protocol):
    """The narrow capability the planner is allowed to use to resolve missing detail."""

    def fetch_skill(self, skill_id: str) -> dict[str, Any]: ...


@dataclass
class FetchOutcome:
    skill_id: str
    status: str  # "fetched" | "failed" | "skipped-over-budget"
    detail: str = ""
    content_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.skill_id,
            "status": self.status,
            "detail": self.detail,
            "hash": self.content_hash,
        }


@dataclass
class FetchReport:
    attempted: list[FetchOutcome] = field(default_factory=list)
    enabled: bool = False
    budget: int = DEFAULT_MAX_FETCH

    @property
    def fetched(self) -> list[FetchOutcome]:
        return [outcome for outcome in self.attempted if outcome.status == "fetched"]

    @property
    def failed(self) -> list[FetchOutcome]:
        return [outcome for outcome in self.attempted if outcome.status == "failed"]

    @property
    def over_budget(self) -> list[FetchOutcome]:
        return [outcome for outcome in self.attempted if outcome.status == "skipped-over-budget"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "budget": self.budget,
            "fetchedForPlan": len(self.fetched),
            "failed": len(self.failed),
            "skippedOverBudget": len(self.over_budget),
            "outcomes": [outcome.as_dict() for outcome in self.attempted],
        }


def resolve_missing_detail(
    registry: Registry,
    gate: GateResult,
    *,
    fetcher: DetailFetcher,
    candidate_ids: set[str],
    snapshots_root: Path,
    budget: int = DEFAULT_MAX_FETCH,
) -> FetchReport:
    """Fetch detail for nominated Skills that were rejected only for lacking a cached version.

    This is a retrieval step, not an admission step. It never decides that a Skill is
    acceptable; it only makes the facts the policy gate needs available, after which the
    caller re-runs the gate from scratch. Three boundaries are enforced here:

    1. Only Skills the deterministic retrieval already produced are eligible. A provider
       cannot name an arbitrary id and cause a network request.
    2. Only the `detail-not-cached` rejection code is eligible. A Skill blocked by audit,
       or one that does not exist, is never re-fetched to try for a different answer.
    3. Detail is stored through the same `store_detail` path as `forge inspect`, so path
       validation, size limits, hashing, snapshotting, and the static audit all still apply.
    """
    report = FetchReport(enabled=True, budget=budget)
    eligible = [
        decision.skill_id
        for decision in gate.rejected
        if decision.code == REJECT_DETAIL_NOT_CACHED and decision.skill_id in candidate_ids
    ]
    seen: set[str] = set()
    for skill_id in eligible:
        if skill_id in seen:
            continue
        seen.add(skill_id)
        if len(report.attempted) >= budget:
            report.attempted.append(
                FetchOutcome(skill_id, "skipped-over-budget", f"Fetch budget of {budget} was exhausted.")
            )
            continue
        if registry.get_skill(skill_id) is None:
            report.attempted.append(
                FetchOutcome(skill_id, "failed", "The Skill is not present in the local registry.")
            )
            continue
        try:
            detail = fetcher.fetch_skill(skill_id)
            _, content_hash = registry.store_detail(skill_id, detail, snapshots_root=snapshots_root)
        except ForgeError as error:
            report.attempted.append(FetchOutcome(skill_id, "failed", str(error)))
            continue
        except (OSError, ValueError, KeyError, TypeError) as error:
            report.attempted.append(FetchOutcome(skill_id, "failed", f"{type(error).__name__}: {error}"))
            continue
        report.attempted.append(FetchOutcome(skill_id, "fetched", "", content_hash))
    return report
