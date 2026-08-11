from __future__ import annotations

import os
from pathlib import Path


def forge_home(explicit: str | Path | None = None) -> Path:
    """Return the global Forge data directory without consulting project-local .forge."""
    if explicit is not None:
        return Path(explicit).expanduser().resolve()
    configured = os.environ.get("FORGE_HOME")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".forge"


def ensure_forge_home(explicit: str | Path | None = None) -> Path:
    home = forge_home(explicit)
    for directory in (home, home / "cache", home / "snapshots", home / "sessions", home / "logs"):
        directory.mkdir(parents=True, exist_ok=True)
    return home


def database_path(explicit_home: str | Path | None = None) -> Path:
    return forge_home(explicit_home) / "forge.db"


def forge_install_root() -> Path | None:
    """Find the Forge checkout only from this installed module's path, never from the current directory."""
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "apps" / "cli").is_dir():
            return candidate
    return None
