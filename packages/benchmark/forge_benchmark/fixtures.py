from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from forge_core.errors import ValidationError
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


@dataclass(frozen=True)
class CatalogSkill:
    skill_id: str
    name: str
    description: str
    source: str
    role: str
    cached: bool
    content_hash: str | None
    extra_files: list[dict[str, str]] = field(default_factory=list)
    force_version_state: dict[str, str] | None = None


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    kind: str
    goal: str
    project_context: dict[str, Any]
    required_roles: list[str]
    acceptable_roles: list[str]
    irrelevant_roles: list[str]
    forbidden_skills: list[str]
    risk_must_be: str | None
    expect_exploration_budget_zero: bool
    expect_human_approval: bool
    expected_role_order: list[str]
    expect_policy_rejection_contains: str | None
    note: str


@dataclass(frozen=True)
class BenchmarkFixture:
    catalog: list[CatalogSkill]
    scenarios: list[Scenario]
    role_vocabulary: list[str]
    provenance: str

    @property
    def role_by_skill(self) -> dict[str, str]:
        return {skill.skill_id: skill.role for skill in self.catalog}


def default_fixture_root() -> Path:
    """Locate the fixture directory from this module, never from the current directory."""
    for candidate in Path(__file__).resolve().parents:
        fixtures = candidate / "tests" / "fixtures" / "planner-benchmark"
        if fixtures.is_dir():
            return fixtures
    raise ValidationError(
        "Could not locate tests/fixtures/planner-benchmark. Pass an explicit fixture root."
    )


def load_fixture(root: Path | None = None) -> BenchmarkFixture:
    fixture_root = root or default_fixture_root()
    catalog_document = _read_json(fixture_root / "catalog.json")
    scenario_document = _read_json(fixture_root / "scenarios.json")

    catalog: list[CatalogSkill] = []
    for entry in catalog_document.get("skills", []):
        cached = bool(entry.get("cached", False))
        content_hash = entry.get("hash")
        if cached and not isinstance(content_hash, str):
            raise ValidationError(f"Cached fixture Skill {entry.get('id')!r} must declare a hash.")
        catalog.append(
            CatalogSkill(
                skill_id=str(entry["id"]),
                name=str(entry["name"]),
                description=str(entry.get("description", "")),
                source=str(entry["source"]),
                role=str(entry["role"]),
                cached=cached,
                content_hash=content_hash if cached else None,
                extra_files=list(entry.get("extraFiles", [])),
                force_version_state=entry.get("forceVersionState"),
            )
        )

    scenarios: list[Scenario] = []
    for entry in scenario_document.get("scenarios", []):
        scenarios.append(
            Scenario(
                scenario_id=str(entry["id"]),
                kind=str(entry.get("kind", "selection")),
                goal=str(entry["goal"]),
                project_context=dict(entry.get("projectContext", {})),
                required_roles=[str(role) for role in entry.get("requiredRoles", [])],
                acceptable_roles=[str(role) for role in entry.get("acceptableRoles", [])],
                irrelevant_roles=[str(role) for role in entry.get("irrelevantRoles", [])],
                forbidden_skills=[str(value) for value in entry.get("forbiddenSkills", [])],
                risk_must_be=entry.get("riskMustBe"),
                expect_exploration_budget_zero=bool(entry.get("expectExplorationBudgetZero", False)),
                expect_human_approval=bool(entry.get("expectHumanApproval", False)),
                expected_role_order=[str(role) for role in entry.get("expectedRoleOrder", [])],
                expect_policy_rejection_contains=entry.get("expectPolicyRejectionContains"),
                note=str(entry.get("note", "")),
            )
        )

    fixture = BenchmarkFixture(
        catalog=catalog,
        scenarios=scenarios,
        role_vocabulary=[str(role) for role in catalog_document.get("roleVocabulary", [])],
        provenance=str(catalog_document.get("provenance", "")),
    )
    _validate(fixture)
    return fixture


def build_fixture_registry(fixture: BenchmarkFixture, *, home: Path) -> Registry:
    """Materialize the synthetic catalog into an isolated registry.

    The benchmark never reads or writes the user's real registry. `home` should be a
    throwaway directory owned by the caller.
    """
    registry = Registry(home / "forge.db")
    registry.migrate()
    source_id = registry.ensure_source(
        name="benchmark-fixture", source_type="fixture", base_url="fixture://planner-benchmark"
    )
    run_id = registry.start_sync_run(source_id)
    registry.upsert_metadata_page(
        source_id,
        [
            SkillMetadata(
                id=skill.skill_id,
                slug=skill.skill_id.rsplit("/", 1)[-1],
                name=skill.name,
                description=skill.description,
                source=skill.source,
            )
            for skill in fixture.catalog
        ],
        next_page=None,
        run_id=run_id,
    )
    for skill in fixture.catalog:
        if not skill.cached:
            continue
        files = [{"path": "SKILL.md", "contents": f"# {skill.name}\n\n{skill.description}\n"}]
        files.extend({"path": str(f["path"]), "contents": str(f["contents"])} for f in skill.extra_files)
        registry.store_detail(
            skill.skill_id,
            {"hash": skill.content_hash, "files": files},
            snapshots_root=home / "snapshots",
        )
        if skill.force_version_state:
            # The shipped static auditor cannot emit fail/high (benchmark finding F1), so the
            # hard-block branch of the policy gate is only reachable by writing this state directly.
            registry.connection.execute(
                "UPDATE skill_versions SET security_status = ?, risk_level = ? "
                "WHERE skill_id = ? AND content_hash = ?",
                (
                    skill.force_version_state.get("security_status", "unknown"),
                    skill.force_version_state.get("risk_level", "unknown"),
                    skill.skill_id,
                    skill.content_hash,
                ),
            )
            registry.connection.commit()
    return registry


def _validate(fixture: BenchmarkFixture) -> None:
    known_roles = set(fixture.role_vocabulary)
    known_skills = {skill.skill_id for skill in fixture.catalog}
    for skill in fixture.catalog:
        if skill.role not in known_roles:
            raise ValidationError(f"Fixture Skill {skill.skill_id} uses role {skill.role!r} outside the vocabulary.")
    if not fixture.scenarios:
        raise ValidationError("The benchmark fixture declares no scenarios.")
    for scenario in fixture.scenarios:
        if scenario.kind not in {"selection", "policy"}:
            raise ValidationError(f"Scenario {scenario.scenario_id} has an unknown kind: {scenario.kind}")
        for label, roles in (
            ("requiredRoles", scenario.required_roles),
            ("acceptableRoles", scenario.acceptable_roles),
            ("irrelevantRoles", scenario.irrelevant_roles),
            ("expectedRoleOrder", scenario.expected_role_order),
        ):
            unknown = [role for role in roles if role not in known_roles]
            if unknown:
                raise ValidationError(
                    f"Scenario {scenario.scenario_id} {label} references unknown roles: {', '.join(unknown)}"
                )
        overlap = set(scenario.required_roles) & set(scenario.irrelevant_roles)
        if overlap:
            raise ValidationError(
                f"Scenario {scenario.scenario_id} marks the same role required and irrelevant: {', '.join(sorted(overlap))}"
            )
        missing = [value for value in scenario.forbidden_skills if value not in known_skills]
        if missing:
            raise ValidationError(
                f"Scenario {scenario.scenario_id} forbids unknown Skill ids: {', '.join(missing)}"
            )
        if not scenario.required_roles:
            raise ValidationError(f"Scenario {scenario.scenario_id} declares no required roles.")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError(f"Benchmark fixture file is missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
