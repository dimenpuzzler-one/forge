from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from forge_core.errors import ValidationError
from forge_core.models import SkillMetadata
from forge_registry.database import MAX_SKILL_FILE_BYTES, MAX_SKILL_TOTAL_BYTES, Registry


LOCAL_ID_PREFIX = "local"
LOCAL_SOURCE_TYPE = "local"
ENTRYPOINT_NAME = "skill.md"
MAX_DISCOVERY_DEPTH = 8
MAX_SKILLS_PER_IMPORT = 2000
SKIPPED_DIRECTORY_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".forge",
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
    ".next",
}
SENSITIVE_FILE_NAMES = {
    "credentials",
    "credentials.env",
    "credentials.json",
    "secrets",
    "secrets.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_UNSAFE_ID_CHARACTERS = re.compile(r"[^a-z0-9._-]+")


@dataclass(frozen=True)
class LocalSkill:
    metadata: SkillMetadata
    detail: dict[str, Any]
    directory: str


@dataclass
class Discovery:
    skills: list[LocalSkill] = field(default_factory=list)
    skipped_files: list[tuple[str, str]] = field(default_factory=list)
    rejected_skills: list[tuple[str, str]] = field(default_factory=list)


def default_label(root: Path) -> str:
    candidate = _UNSAFE_ID_CHARACTERS.sub("-", root.resolve().name.casefold()).strip("-.")
    return candidate or "skills"


def validate_label(label: str) -> str:
    if not _LABEL_PATTERN.match(label):
        raise ValueError("--label must be 1-64 characters of letters, digits, '.', '_' or '-', starting with a letter or digit.")
    return label


def discover_skills(root: str | Path, *, label: str) -> Discovery:
    """Find Agent Skills under a local directory and read them as untrusted text data.

    A Skill is any directory containing a SKILL.md. Its files are every readable text file
    beneath it, excluding nested Skills, secret-looking files, symlinks, and dependency or
    VCS folders. Nothing found here is executed; script files are only marked as scripts
    when the registry stores them.
    """
    base = Path(root).expanduser().resolve()
    if not base.is_dir():
        raise ValueError(f"Not a directory: {base}")
    validate_label(label)
    discovery = Discovery()
    skill_directories = _find_skill_directories(base)
    if len(skill_directories) > MAX_SKILLS_PER_IMPORT:
        raise ValidationError(
            f"Found {len(skill_directories)} SKILL.md files; one import is limited to {MAX_SKILLS_PER_IMPORT}. "
            "Import a narrower directory."
        )
    nested = set(skill_directories)
    for directory in skill_directories:
        relative = directory.relative_to(base).as_posix()
        display = relative if relative != "." else base.name
        try:
            skill = _read_skill(base, directory, label=label, nested=nested, discovery=discovery)
        except ValidationError as error:
            discovery.rejected_skills.append((display, str(error)))
            continue
        discovery.skills.append(skill)
    return discovery


def import_skills(registry: Registry, root: str | Path, *, label: str, snapshots_root: Path) -> dict[str, Any]:
    """Register discovered Skills under one local source and cache each as an immutable version.

    Metadata is written only for Skills whose detail already passed validation, so a local
    Skill is never left in the registry without a cached version that `inspect` would then
    try to fetch from a remote source.
    """
    base = Path(root).expanduser().resolve()
    discovery = discover_skills(base, label=label)
    source_id = registry.ensure_source(
        name=f"{LOCAL_ID_PREFIX}:{label}", source_type=LOCAL_SOURCE_TYPE, base_url=base.as_uri()
    )
    run_id = registry.start_sync_run(source_id)
    previous = {
        skill.metadata.id: (registry.get_skill(skill.metadata.id) or {"content_hash": None})["content_hash"]
        for skill in discovery.skills
    }
    try:
        counts = registry.upsert_metadata_page(
            source_id, [skill.metadata for skill in discovery.skills], next_page=None, run_id=run_id
        )
        results: list[dict[str, str]] = []
        for skill in discovery.skills:
            _, content_hash = registry.store_detail(
                skill.metadata.id, skill.detail, snapshots_root=snapshots_root, snapshot_namespace="local"
            )
            before = previous[skill.metadata.id]
            if before is None:
                state = "new"
            elif before == content_hash:
                state = "unchanged"
            else:
                state = "new-version"
            stored = registry.get_skill(skill.metadata.id)
            assert stored is not None
            results.append(
                {
                    "id": skill.metadata.id,
                    "directory": skill.directory,
                    "state": state,
                    "hash": content_hash,
                    "security": f"{stored['security_status']} / {stored['risk_level']}",
                }
            )
        registry.mark_source_synced(source_id)
        registry.finish_sync_run(run_id, request_count=0)
    except Exception:
        registry.finish_sync_run(run_id, error_count=1, request_count=0)
        raise
    return {
        "source": f"{LOCAL_ID_PREFIX}:{label}",
        "root": str(base),
        "skills": results,
        "metadata": counts,
        "skippedFiles": discovery.skipped_files,
        "rejectedSkills": discovery.rejected_skills,
    }


def parse_frontmatter(text: str) -> dict[str, str]:
    """Read the flat string fields of a SKILL.md YAML frontmatter block without a YAML dependency.

    Supports `key: value`, quoted values, and `|` / `>` block scalars. Nested mappings and
    lists are ignored; Forge needs only name, description, and license.
    """
    lines = text.lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(index for index in range(1, len(lines)) if lines[index].strip() in {"---", "..."})
    except StopIteration:
        return {}
    fields: dict[str, str] = {}
    index = 1
    while index < end:
        line = lines[index]
        index += 1
        match = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$", line)
        if match is None:
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        if value[:1] in {"|", ">"}:
            block: list[str] = []
            while index < end and (not lines[index].strip() or lines[index][:1] in {" ", "\t"}):
                block.append(lines[index].strip())
                index += 1
            joiner = "\n" if value.startswith("|") else " "
            fields[key] = joiner.join(block).strip()
            continue
        if not value:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        fields[key] = value
    return fields


def _find_skill_directories(base: Path) -> list[Path]:
    found: list[Path] = []
    for current, directories, files in os.walk(base, followlinks=False):
        current_path = Path(current)
        depth = len(current_path.relative_to(base).parts)
        directories[:] = sorted(
            name
            for name in directories
            if name.casefold() not in SKIPPED_DIRECTORY_NAMES
            and depth < MAX_DISCOVERY_DEPTH
            and not (current_path / name).is_symlink()
        )
        if any(name.casefold() == ENTRYPOINT_NAME for name in files):
            found.append(current_path)
    return sorted(found)


def _read_skill(base: Path, directory: Path, *, label: str, nested: set[Path], discovery: Discovery) -> LocalSkill:
    files: list[dict[str, str]] = []
    total = 0
    for current, directories, names in os.walk(directory, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name
            for name in directories
            if name.casefold() not in SKIPPED_DIRECTORY_NAMES
            and not (current_path / name).is_symlink()
            and (current_path / name) not in nested
        )
        for name in sorted(names):
            path = current_path / name
            relative = path.relative_to(directory).as_posix()
            shown = path.relative_to(base).as_posix()
            if path.is_symlink():
                discovery.skipped_files.append((shown, "symlink"))
                continue
            if _is_sensitive_name(name):
                discovery.skipped_files.append((shown, "secret-like file name"))
                continue
            size = path.stat().st_size
            if size > MAX_SKILL_FILE_BYTES:
                discovery.skipped_files.append((shown, "larger than 1 MiB"))
                continue
            raw = path.read_bytes()
            if b"\x00" in raw:
                discovery.skipped_files.append((shown, "binary"))
                continue
            try:
                contents = raw.decode("utf-8")
            except UnicodeDecodeError:
                discovery.skipped_files.append((shown, "not UTF-8 text"))
                continue
            total += len(raw)
            if total > MAX_SKILL_TOTAL_BYTES:
                raise ValidationError("Skill is larger than the 5 MiB safety limit.")
            files.append({"path": relative, "contents": contents})

    entrypoint = next((item for item in files if PurePosixPath(item["path"]).name.casefold() == ENTRYPOINT_NAME and "/" not in item["path"]), None)
    if entrypoint is None:
        raise ValidationError("SKILL.md could not be read as UTF-8 text.")
    frontmatter = parse_frontmatter(entrypoint["contents"])
    relative_directory = directory.relative_to(base).as_posix()
    name = frontmatter.get("name") or directory.name
    if relative_directory == ".":
        path_part = _id_segment(name)
    else:
        path_part = "/".join(_id_segment(part) for part in PurePosixPath(relative_directory).parts)
    skill_id = f"{LOCAL_ID_PREFIX}/{label}/{path_part}"
    description = frontmatter.get("description") or _first_body_line(entrypoint["contents"])
    metadata = SkillMetadata(
        id=skill_id,
        slug=_id_segment(name),
        name=name,
        source=f"{LOCAL_ID_PREFIX}:{label}",
        description=description,
        source_type=LOCAL_SOURCE_TYPE,
    )
    detail: dict[str, Any] = {"files": sorted(files, key=lambda item: item["path"])}
    if frontmatter.get("license"):
        detail["license"] = frontmatter["license"]
    return LocalSkill(metadata=metadata, detail=detail, directory=relative_directory)


def _is_sensitive_name(name: str) -> bool:
    lowered = name.casefold()
    return (
        lowered == ".env"
        or lowered.startswith(".env.")
        or lowered in SENSITIVE_FILE_NAMES
        or lowered.endswith((".pem", ".key", ".pfx", ".p12"))
    )


def _id_segment(value: str) -> str:
    return _UNSAFE_ID_CHARACTERS.sub("-", value.casefold()).strip("-.") or "skill"


def _first_body_line(text: str) -> str:
    body = text
    if text.lstrip("﻿").startswith("---"):
        parts = text.split("\n---", 1)
        body = parts[1].split("\n", 1)[1] if len(parts) == 2 and "\n" in parts[1] else ""
    for line in body.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped[:300]
    return ""
