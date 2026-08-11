from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


LOCKFILE_NAME = "skills.lock"


def lockfile_path(project_root: str | Path) -> Path:
    return Path(project_root) / ".forge" / LOCKFILE_NAME


def load_lockfile(project_root: str | Path) -> dict[str, Any]:
    path = lockfile_path(project_root)
    if not path.exists():
        return {"schemaVersion": 1, "skills": []}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read Forge lockfile at {path}: {error}") from error
    if not isinstance(parsed, dict) or parsed.get("schemaVersion") != 1 or not isinstance(parsed.get("skills"), list):
        raise ValueError(f"Forge lockfile at {path} has an unsupported schema.")
    return parsed


def pin_skill(
    project_root: str | Path,
    *,
    skill_id: str,
    source: str,
    content_hash: str,
    reason: str,
    mode: str = "reference",
) -> Path:
    """Write only an explicit user-selected version; never resolve or update it implicitly."""
    if not content_hash:
        raise ValueError("A cached immutable Skill version is required before pinning.")
    lock = load_lockfile(project_root)
    entry = {
        "id": skill_id,
        "source": source,
        "hash": content_hash,
        "pinnedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "reason": reason,
        "mode": mode,
    }
    skills = [item for item in lock["skills"] if isinstance(item, dict) and item.get("id") != skill_id]
    skills.append(entry)
    lock["skills"] = sorted(skills, key=lambda item: str(item.get("id", "")))
    path = lockfile_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path

