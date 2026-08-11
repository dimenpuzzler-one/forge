from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .paths import forge_home, forge_install_root


@dataclass(frozen=True)
class SkillsShAuth:
    token: str | None
    source: str


def resolve_skills_sh_auth(
    *,
    home: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    install_root: Path | None = None,
) -> SkillsShAuth:
    """Resolve only Forge-owned auth locations; never inspect a target project's environment files."""
    environment = os.environ if environ is None else environ
    process_token = environment.get("VERCEL_OIDC_TOKEN", "").strip()
    if process_token:
        return SkillsShAuth(process_token, "process-env")

    forge_credentials = forge_home(home) / "credentials.env"
    token = _read_token(forge_credentials)
    if token:
        return SkillsShAuth(token, "forge-local-env")

    root = install_root if install_root is not None else forge_install_root()
    if root is not None:
        token = _read_token(root / ".env.local")
        if token:
            return SkillsShAuth(token, "forge-local-env")
    return SkillsShAuth(None, "none")


def _read_token(path: Path) -> str | None:
    """Read one known infrastructure file and return only the requested key without logging its value."""
    try:
        if not path.is_file() or path.stat().st_size > 64 * 1024:
            return None
        for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if separator and key.strip() == "VERCEL_OIDC_TOKEN":
                return value.strip().strip('"').strip("'") or None
    except OSError:
        return None
    return None
