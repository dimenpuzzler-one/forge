from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable

from forge_project.signals import collect_signals, mentioned, used


README_PATTERN = re.compile(r"^README(?:[_-].*)?(?:\..*)?$", re.IGNORECASE)
DOCUMENT_NAMES = {"AGENTS.md", "CLAUDE.md", "pyproject.toml", "package.json", "turbo.json", "pnpm-workspace.yaml"}
DOCUMENT_SUFFIXES = {".md", ".mdx", ".txt"}
MAX_DOCUMENT_BYTES = 128 * 1024
MAX_DOCUMENTS = 64
SENSITIVE_FILE_NAMES = {
    "credentials",
    "credentials.json",
    "secrets",
    "secrets.json",
    "id_rsa",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
}
EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".forge",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "build",
    "dist",
    "coverage",
    "__pycache__",
}


def is_sensitive_path(path: Path) -> bool:
    """Return whether a path must never be read or listed as project context."""
    lowered_parts = {part.casefold() for part in path.parts}
    name = path.name.casefold()
    return (
        bool(lowered_parts & EXCLUDED_DIRECTORY_NAMES)
        or name == ".env"
        or name.startswith(".env.")
        or name in SENSITIVE_FILE_NAMES
        or name.endswith((".pem", ".key", ".pfx", ".p12"))
    )


def is_stub_readme(text: str) -> bool:
    trimmed = text.strip()
    return not trimmed or (
        len(trimmed) <= 200
        and re.search(r"(only if needed|run in CI|placeholder|to\s*do|tbd|coming soon)", trimmed, re.I)
        is not None
    )


def _readme_sort_key(path: Path) -> tuple[int, str]:
    priorities = {".md": 0, ".mdx": 1, ".txt": 2}
    return (priorities.get(path.suffix.casefold(), 3), path.name.casefold())


def select_representative_readme(project_root: Path) -> Path | None:
    """Port the legacy collector's root-README selection and stub exclusion logic."""
    candidates = sorted(
        (
            path
            for path in project_root.iterdir()
            if path.is_file() and README_PATTERN.match(path.name) and not is_sensitive_path(path)
        ),
        key=_readme_sort_key,
    )
    if not candidates:
        return None
    candidate = candidates[0]
    text = read_text(candidate)
    return candidate if text is not None and not is_stub_readme(text) else None


def read_text(path: Path) -> str | None:
    if is_sensitive_path(path):
        return None
    try:
        if path.stat().st_size > MAX_DOCUMENT_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def find_project_root(start: Path) -> Path:
    """Prefer the nearest Git or project-marker root, falling back to the supplied directory."""
    start = start.expanduser().resolve()
    if start.is_file():
        start = start.parent
    if not start.is_dir():
        raise ValueError(f"Project path does not exist or is not a directory: {start}")

    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
    markers = {"pyproject.toml", "package.json", "README.md", "README"}
    for candidate in (start, *start.parents):
        if any((candidate / marker).exists() for marker in markers):
            return candidate
    return start


def _candidate_documents(root: Path) -> Iterable[Path]:
    root_files = sorted((path for path in root.iterdir() if path.is_file()), key=lambda path: path.name.casefold())
    for path in root_files:
        if is_sensitive_path(path):
            continue
        if README_PATTERN.match(path.name) or path.name in DOCUMENT_NAMES or path.name.startswith("requirements"):
            yield path

    docs_root = root / "docs"
    if not docs_root.is_dir() or is_sensitive_path(docs_root):
        return
    for path in sorted(docs_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or is_sensitive_path(path):
            continue
        if path.suffix.casefold() in DOCUMENT_SUFFIXES and len(path.relative_to(docs_root).parts) <= 3:
            yield path


def _detect_languages(root: Path) -> list[str]:
    markers = {
        "python": ("pyproject.toml", "requirements.txt", "setup.py"),
        "typescript": ("tsconfig.json",),
        "javascript": ("package.json",),
        "go": ("go.mod",),
        "rust": ("Cargo.toml",),
    }
    return [language for language, names in markers.items() if any((root / name).exists() for name in names)]


def _load_json(path: Path) -> dict[str, object]:
    text = read_text(path)
    if text is None:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _detect_architecture(text: str) -> list[str]:
    corpus = text.casefold()
    patterns = {
        "monorepo": ("monorepo", "turborepo"),
        "strategy-plugin": ("strategy plugin", "strategy-plugin"),
        "deterministic-llm-boundary": ("deterministic", "llm"),
        "shared-validation-kernel": ("validation kernel", "shared validation"),
    }
    return [name for name, terms in patterns.items() if all(term in corpus for term in terms)]


def _detect_test_commands(root: Path, languages: list[str]) -> dict[str, list[str]]:
    commands: dict[str, list[str]] = {}
    if "python" in languages:
        pyproject_text = read_text(root / "pyproject.toml") if (root / "pyproject.toml").is_file() else ""
        requirements = read_text(root / "requirements.txt") if (root / "requirements.txt").is_file() else ""
        if "pytest" in (pyproject_text or "").casefold() or "pytest" in (requirements or "").casefold():
            commands["test"] = ["python -m pytest -q"]
        else:
            commands["test"] = ["python -m unittest discover"]
    package_json = _load_json(root / "package.json") if (root / "package.json").is_file() else {}
    scripts = package_json.get("scripts")
    if isinstance(scripts, dict) and "test" in scripts:
        commands["test"] = ["npm test"]
    return commands


def scan_project(path: str | Path | None = None, *, cwd: str | Path | None = None) -> dict[str, object]:
    """Collect a bounded, secret-safe, machine-readable project context without executing code."""
    start = Path(path) if path is not None else Path(cwd) if cwd is not None else Path.cwd()
    root = find_project_root(start)
    documents: list[Path] = []
    text_parts: list[str] = []
    digest = hashlib.sha256()
    for candidate in _candidate_documents(root):
        if len(documents) >= MAX_DOCUMENTS:
            break
        content = read_text(candidate)
        if content is None:
            continue
        relative = candidate.relative_to(root)
        documents.append(candidate)
        text_parts.append(content)
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(content.encode("utf-8"))
        digest.update(b"\0")

    representative = select_representative_readme(root)
    if representative is not None and representative not in documents:
        content = read_text(representative)
        if content is not None:
            documents.insert(0, representative)
            text_parts.insert(0, content)
            digest.update(representative.relative_to(root).as_posix().encode("utf-8"))
            digest.update(content.encode("utf-8"))

    corpus = "\n".join(text_parts)
    languages = _detect_languages(root)
    readme_relative = representative.relative_to(root).as_posix() if representative is not None else None
    signals = collect_signals(
        root,
        documents=[
            (path.relative_to(root).as_posix(), text) for path, text in zip(documents, text_parts)
        ],
        readme_relative=readme_relative,
    )
    return {
        # Schema 2 narrows `stack` and `domains` to technologies with strong evidence and adds
        # `signals` with the full evidence trail. A prose mention no longer becomes a project fact.
        "schemaVersion": 2,
        "name": root.name,
        "root": str(root),
        "languages": languages,
        "stack": used(signals, "stack"),
        "domains": used(signals, "domain"),
        "mentioned": mentioned(signals),
        "signals": [signal.as_dict() for signal in sorted(signals, key=lambda item: item.technology)],
        "architecture": _detect_architecture(corpus),
        "commands": _detect_test_commands(root, languages),
        "detectedDocuments": [path.relative_to(root).as_posix() for path in documents],
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "sourceFingerprint": digest.hexdigest(),
    }


def write_project_context(context: dict[str, object]) -> Path:
    root = Path(str(context["root"]))
    output = root / ".forge" / "project.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output
