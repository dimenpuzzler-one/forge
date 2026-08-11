from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from forge_registry.database import Registry


@dataclass(frozen=True)
class Recommendation:
    skill_id: str
    name: str
    source: str
    reason: str
    evidence: list[str]
    risks: list[str]


RULES = (
    (
        "supabase",
        ("supabase postgres rls",),
        "Supabase/Postgres production safety",
        "The project context declares Supabase.",
    ),
    (
        "payments",
        ("payment security idempotency",),
        "Payment safety and idempotency",
        "The project context contains payment-domain evidence.",
    ),
    (
        "web",
        ("nextjs react", "playwright e2e testing"),
        "Web quality and end-to-end testing",
        "The project context declares a web framework.",
    ),
    (
        "ai",
        ("structured output llm",),
        "Structured LLM reliability",
        "The project context contains AI/LLM evidence.",
    ),
    (
        "python",
        ("python testing",),
        "Python testing and reliability",
        "The project context declares Python.",
    ),
    (
        "quant",
        ("backtesting reproducible", "market microstructure"),
        "Reproducible quantitative research",
        "The project context contains quant/backtesting evidence.",
    ),
)


def recommend_skills(registry: Registry, context: dict[str, Any], *, limit: int = 10) -> list[Recommendation]:
    """Explainable feature rules; popularity alone never creates a recommendation."""
    stack = {str(value).casefold() for value in context.get("stack", [])}
    domains = {str(value).casefold() for value in context.get("domains", [])}
    languages = {str(value).casefold() for value in context.get("languages", [])}
    active = {
        "supabase": "supabase" in stack,
        "payments": "payments" in domains,
        "web": bool({"nextjs", "react"} & stack),
        "ai": "ai" in domains,
        "python": "python" in languages,
        "quant": bool({"quant", "backtesting", "kr-equity"} & domains),
    }
    recommendations: list[Recommendation] = []
    seen: set[str] = set()
    for key, queries, title, evidence in RULES:
        if not active[key]:
            continue
        for query in queries:
            for skill in registry.search(query, limit=limit):
                skill_id = str(skill["id"])
                if skill_id in seen:
                    continue
                seen.add(skill_id)
                risks = []
                if skill["is_duplicate"]:
                    risks.append("The source marks this Skill as a possible duplicate.")
                if skill["latest_seen_version_id"] is None:
                    risks.append("Detail is not cached locally yet; inspect before pinning.")
                recommendations.append(
                    Recommendation(
                        skill_id=skill_id,
                        name=str(skill["name"]),
                        source=str(skill["source_repo"]),
                        reason=title,
                        evidence=[evidence, f"Matched local query: {query}"],
                        risks=risks,
                    )
                )
                if len(recommendations) >= limit:
                    return recommendations
    return recommendations
