from __future__ import annotations

from forge_registry.database import Registry


def search_skills(registry: Registry, query: str, *, limit: int = 20):
    """Keep CLI ranking consumers decoupled from SQLite storage details."""
    return registry.search(query, limit=limit)

