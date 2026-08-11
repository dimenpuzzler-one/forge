from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SkillMetadata:
    id: str
    slug: str
    name: str
    source: str
    description: str = ""
    installs: int = 0
    source_type: str = ""
    install_url: str | None = None
    skills_sh_url: str | None = None
    is_duplicate: bool = False

    @classmethod
    def from_api(cls, item: dict[str, Any]) -> "SkillMetadata":
        skill_id = str(item.get("id", ""))
        source = str(item.get("source", ""))
        slug = str(item.get("slug", ""))
        if not skill_id or not source or not slug:
            raise ValueError("skills.sh metadata is missing id, source, or slug")
        return cls(
            id=skill_id,
            slug=slug,
            name=str(item.get("name") or slug),
            source=source,
            description=str(item.get("description") or ""),
            installs=int(item.get("installs") or 0),
            source_type=str(item.get("sourceType") or ""),
            install_url=item.get("installUrl"),
            skills_sh_url=item.get("url"),
            is_duplicate=bool(item.get("isDuplicate", False)),
        )

