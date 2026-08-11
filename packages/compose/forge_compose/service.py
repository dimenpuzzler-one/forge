from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_registry.database import Registry


@dataclass(frozen=True)
class CompositionAnalysis:
    name: str
    goal: str
    skill_count: int
    sources: list[str]
    warnings: list[str]
    order: list[dict[str, str]]


def add_skill_to_composition(
    registry: Registry, *, name: str, skill_id: str, role: str = "general"
) -> None:
    skill = registry.get_skill(skill_id)
    if skill is None:
        raise ValueError(f"Skill not found locally: {skill_id}. Search and inspect it before composing.")
    if skill["content_hash"] is None:
        raise ValueError(
            "Skill detail is not cached. Run `forge inspect <skill-id>` before composing an immutable manifest."
        )
    registry.add_composition_skill(
        name=name,
        skill_id=skill_id,
        content_hash=str(skill["content_hash"]),
        role=role,
    )


def analyze_composition(registry: Registry, *, name: str, goal: str | None = None) -> CompositionAnalysis:
    composition = registry.get_composition(name)
    if composition is None:
        raise ValueError(f"Composition not found: {name}")
    skills = registry.get_composition_skills(name)
    roles = [str(skill["role"]) for skill in skills]
    duplicate_roles = sorted({role for role in roles if roles.count(role) > 1 and role != "general"})
    sources = sorted({str(skill["source_repo"]) for skill in skills})
    warnings: list[str] = []
    if not skills:
        warnings.append("The composition has no Skills yet.")
    if duplicate_roles:
        warnings.append(f"Multiple Skills use the same explicit role: {', '.join(duplicate_roles)}.")
    scripts = [str(skill["skill_id"]) for skill in skills if skill["has_scripts"]]
    if scripts:
        warnings.append("Some selected Skills contain scripts; Forge will not execute them automatically.")
    if len(sources) > 1:
        warnings.append("This composition spans multiple sources; inspect provenance and licenses before sharing it.")
    return CompositionAnalysis(
        name=name,
        goal=goal or str(composition["goal"] or ""),
        skill_count=len(skills),
        sources=sources,
        warnings=warnings,
        order=[{"skillId": str(skill["skill_id"]), "role": str(skill["role"])} for skill in skills],
    )


def manifest(registry: Registry, name: str) -> dict[str, Any]:
    composition = registry.get_composition(name)
    if composition is None:
        raise ValueError(f"Composition not found: {name}")
    skills = registry.get_composition_skills(name)
    return {
        "schemaVersion": 1,
        "name": str(composition["name"]),
        "goal": str(composition["goal"] or ""),
        "skills": [
            {
                "id": str(skill["skill_id"]),
                "source": str(skill["source_repo"]),
                "hash": str(skill["content_hash"]),
                "role": str(skill["role"]),
            }
            for skill in skills
        ],
    }
