from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from pathlib import Path

from forge_core.errors import ForgeError
from forge_core.paths import database_path, ensure_forge_home, forge_home
from forge_project.scanner import scan_project, write_project_context
from forge_registry.database import Registry
from forge_search.service import search_skills
from forge_sources.skills_sh import SkillsShAdapter, sync_metadata


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Local-first skill exploration and project-context toolkit.",
    )
    parser.add_argument(
        "--forge-home",
        help="Override the global Forge data directory for this command (default: FORGE_HOME or ~/.forge).",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    doctor = subcommands.add_parser("doctor", help="Check local Forge prerequisites without exposing secrets.")
    doctor.add_argument("--project", help="Optional project path to validate.")

    scan = subcommands.add_parser("scan", help="Create a secret-safe .forge/project.json context file.")
    scan.add_argument("path", nargs="?", help="Project path (default: current directory).")

    sync = subcommands.add_parser("sync", help="Synchronize external skill metadata into the local registry.")
    sync.add_argument("--source", default="skills-sh", choices=["skills-sh"])
    sync.add_argument("--metadata-only", action="store_true", help="Required for MVP; do not fetch full skill files.")
    sync.add_argument("--per-page", type=int, default=100, help="skills.sh page size (1-500).")

    search = subcommands.add_parser("search", help="Search locally synchronized skill metadata with SQLite FTS5.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)

    inspect = subcommands.add_parser("inspect", help="Show local metadata and cache detail on demand.")
    inspect.add_argument("skill_id")
    inspect.add_argument("--no-fetch", action="store_true", help="Do not request missing detail from skills.sh.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "scan":
            return _scan(args)
        if args.command == "sync":
            return _sync(args)
        if args.command == "search":
            return _search(args)
        if args.command == "inspect":
            return _inspect(args)
    except (ForgeError, ValueError, sqlite3.Error, OSError) as error:
        print(f"Forge error: {error}", file=sys.stderr)
        return 2
    return 2


def _registry(home_override: str | None) -> tuple[Path, Registry]:
    home = ensure_forge_home(home_override)
    registry = Registry(database_path(home))
    registry.migrate()
    return home, registry


def _doctor(args: argparse.Namespace) -> int:
    home = ensure_forge_home(args.forge_home)
    db_path = database_path(home)
    registry = Registry(db_path)
    try:
        registry.migrate()
        fts5 = registry.connection.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')").fetchone()[0]
    finally:
        registry.close()
    project_state = "not checked"
    if args.project:
        project = Path(args.project).expanduser()
        project_state = "found" if project.is_dir() else "not found"
    print("Forge doctor")
    print(f"Forge home: {home}")
    print(f"Registry DB: {db_path}")
    print("Registry schema: OK")
    print(f"SQLite FTS5: {'available' if fts5 else 'unavailable'}")
    print(f"Python: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
    print(f"skills.sh authentication: {'configured' if os.environ.get('VERCEL_OIDC_TOKEN') else 'not configured'}")
    print(f"Project path: {project_state}")
    if not os.environ.get("VERCEL_OIDC_TOKEN"):
        print("Note: skills.sh API sync currently requires VERCEL_OIDC_TOKEN; local scan/search remain available.")
    return 0


def _scan(args: argparse.Namespace) -> int:
    context = scan_project(args.path)
    output = write_project_context(context)
    print(f"Scanned project: {context['name']}")
    print(f"Context written: {output}")
    print(f"Languages: {', '.join(context['languages']) or 'unknown'}")
    print(f"Documents: {len(context['detectedDocuments'])}")
    return 0


def _sync(args: argparse.Namespace) -> int:
    if not args.metadata_only:
        raise ValueError("MVP sync supports --metadata-only only; full detail is fetched by forge inspect.")
    if not 1 <= args.per_page <= 500:
        raise ValueError("--per-page must be between 1 and 500")
    home, registry = _registry(args.forge_home)
    try:
        stats = sync_metadata(registry, SkillsShAdapter(), per_page=args.per_page)
    finally:
        registry.close()
    print(
        "Metadata sync complete: "
        f"{stats['discovered']} discovered, {stats['inserted']} inserted, {stats['updated']} updated, "
        f"{stats['pages']} page(s)."
    )
    print(f"Registry: {database_path(home)}")
    return 0


def _search(args: argparse.Namespace) -> int:
    if args.limit < 1 or args.limit > 200:
        raise ValueError("--limit must be between 1 and 200")
    _, registry = _registry(args.forge_home)
    try:
        results = search_skills(registry, args.query, limit=args.limit)
    finally:
        registry.close()
    if not results:
        print("No local matches. Run `forge sync --source skills-sh --metadata-only` first.")
        return 0
    for index, result in enumerate(results, start=1):
        description = str(result["description"] or "").replace("\n", " ").strip()
        if len(description) > 160:
            description = f"{description[:157]}..."
        print(f"{index}. {result['id']} — {result['name']}")
        print(f"   source: {result['source_repo']} | installs: {result['install_count']}")
        if description:
            print(f"   {description}")
    return 0


def _inspect(args: argparse.Namespace) -> int:
    home, registry = _registry(args.forge_home)
    try:
        skill = registry.get_skill(args.skill_id)
        if skill is None:
            raise ValueError(f"Skill not found locally: {args.skill_id}. Run `forge search` or `forge sync` first.")
        if skill["latest_seen_version_id"] is None and not args.no_fetch:
            adapter = SkillsShAdapter()
            detail = adapter.fetch_skill(args.skill_id)
            registry.store_detail(args.skill_id, detail, snapshots_root=home / "snapshots")
            skill = registry.get_skill(args.skill_id)
            assert skill is not None
        files = registry.get_files(args.skill_id)
    finally:
        registry.close()
    print(f"ID: {skill['id']}")
    print(f"Name: {skill['name']}")
    print(f"Source: {skill['source_repo']}")
    print(f"Installs: {skill['install_count']}")
    print(f"Description: {skill['description'] or '(none)'}")
    print(f"Cached detail: {'yes' if skill['latest_seen_version_id'] is not None else 'no'}")
    if skill["content_hash"]:
        print(f"Current hash: {skill['content_hash']}")
    if not files:
        print("No cached files. Re-run without --no-fetch after configuring skills.sh authentication.")
        return 0
    print("Files:")
    for file in files:
        marker = " [script: not executed]" if file["is_script"] else ""
        print(f"  - {file['path']}{marker}")
    entrypoint = next((file for file in files if file["is_entrypoint"]), None)
    if entrypoint is not None:
        print("\nSKILL.md:\n")
        print(entrypoint["contents"])
    return 0
