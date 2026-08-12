from __future__ import annotations

import argparse
import difflib
import os
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from forge_core.errors import ForgeError
from forge_core.paths import database_path, ensure_forge_home, forge_home
from forge_core.auth import resolve_skills_sh_auth
from forge_benchmark.runner import build_summary, resolve_external_provider, run_benchmark, write_artifacts
from forge_compose.service import add_skill_to_composition, analyze_composition, manifest
from forge_planner.provider import resolve_provider
from forge_planner.service import create_plan
from forge_project.scanner import scan_project, write_project_context
from forge_project.lockfile import load_lockfile, pin_skill
from forge_project.recommend import recommend_skills
from forge_registry.database import Registry
from forge_runtime.generic_filesystem import materialize_bundle, render_instructions
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
    subcommands.add_parser("status", help="Show local registry freshness and the last successful sync.")

    scan = subcommands.add_parser("scan", help="Create a secret-safe .forge/project.json context file.")
    scan.add_argument("path", nargs="?", help="Project path (default: current directory).")

    sync = subcommands.add_parser("sync", help="Synchronize external skill metadata into the local registry.")
    sync.add_argument("--source", default="skills-sh", choices=["skills-sh"])
    sync.add_argument("--metadata-only", action="store_true", help="Required for MVP; do not fetch full skill files.")
    sync.add_argument("--per-page", type=int, default=500, help="skills.sh page size (1-500; default: 500).")
    sync.add_argument("--if-stale", help="Skip only when the last successful catalog sync is newer than this TTL (e.g. 6h).")

    search = subcommands.add_parser("search", help="Search locally synchronized skill metadata with SQLite FTS5.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)

    inspect = subcommands.add_parser("inspect", help="Show local metadata and cache detail on demand.")
    inspect.add_argument("skill_id")
    inspect.add_argument("--no-fetch", action="store_true", help="Do not request missing detail from skills.sh.")
    inspect.add_argument("--refresh", action="store_true", help="Explicitly fetch detail again to detect a new immutable version.")

    audit_skill = subcommands.add_parser("audit-skill", help="Import available upstream audit results for a cached Skill.")
    audit_skill.add_argument("skill_id")
    outdated = subcommands.add_parser("outdated", help="Show project pins with a newer cached registry version available.")
    outdated.add_argument("--project", help="Project root (default: current directory).")
    diff = subcommands.add_parser("diff", help="Compare two cached immutable versions of one Skill.")
    diff.add_argument("skill_id")
    diff.add_argument("old_hash")
    diff.add_argument("new_hash")

    recommend = subcommands.add_parser("recommend", help="Recommend local Skills from explainable project evidence.")
    recommend.add_argument("path", nargs="?", help="Project path (default: current directory).")
    recommend.add_argument("--limit", type=int, default=10)

    pin = subcommands.add_parser("pin", help="Explicitly pin a locally cached immutable Skill version to a project.")
    pin.add_argument("skill_id")
    pin.add_argument("--project", help="Project root (default: current directory).")
    pin.add_argument("--reason", default="Explicit Forge selection")
    pin.add_argument("--mode", choices=["reference"], default="reference")

    collection = subcommands.add_parser("collection", help="Create and manage local Skill collections.")
    collection_commands = collection.add_subparsers(dest="collection_command", required=True)
    collection_create = collection_commands.add_parser("create", help="Create an empty collection.")
    collection_create.add_argument("name")
    collection_add = collection_commands.add_parser("add", help="Add a locally known Skill to a collection.")
    collection_add.add_argument("name")
    collection_add.add_argument("skill_id")
    collection_commands.add_parser("list", help="List collections.")
    collection_show = collection_commands.add_parser("show", help="Show collection members.")
    collection_show.add_argument("name")

    compose = subcommands.add_parser("compose", help="Build provenance-preserving Skill composition manifests.")
    compose_commands = compose.add_subparsers(dest="compose_command", required=True)
    compose_create = compose_commands.add_parser("create", help="Create an empty composition.")
    compose_create.add_argument("name")
    compose_create.add_argument("--goal", default="")
    compose_add = compose_commands.add_parser("add", help="Add a cached immutable Skill version to a composition.")
    compose_add.add_argument("name")
    compose_add.add_argument("skill_id")
    compose_add.add_argument("--role", default="general")
    compose_show = compose_commands.add_parser("show", help="Show a composition manifest.")
    compose_show.add_argument("name")
    compose_analyze = compose_commands.add_parser("analyze", help="Run deterministic compatibility checks.")
    compose_analyze.add_argument("name")
    compose_analyze.add_argument("--goal")

    plan = subcommands.add_parser(
        "plan", help="Turn a goal into a policy-verified Skill plan. The provider proposes; Forge admits."
    )
    plan.add_argument("goal")
    plan.add_argument("--project", help="Project root (default: current directory).")
    plan.add_argument(
        "--provider",
        default="stub",
        help="Planning provider: stub (offline, deterministic), anthropic, or openai (default: stub).",
    )
    plan.add_argument("--model", help="Override the provider model, when the provider supports one.")
    plan.add_argument("--candidates", type=int, default=60, help="FTS candidate ceiling (5-200; default: 60).")
    plan.add_argument(
        "--fetch-missing",
        action="store_true",
        help="Fetch detail for nominated Skills that lack a cached immutable version, then re-run the gate.",
    )
    plan.add_argument(
        "--fetch-budget", type=int, default=8, help="Maximum Skills to fetch in one plan (1-25; default: 8)."
    )

    benchmark = subcommands.add_parser(
        "benchmark", help="Measure planner selection quality and policy correctness against fixtures."
    )
    benchmark.add_argument(
        "--output", help="Artifact directory (default: artifacts/planner-benchmark under the current directory)."
    )
    benchmark.add_argument("--fixtures", help="Override the benchmark fixture directory.")
    benchmark.add_argument(
        "--external-provider",
        help="Run variant C with this provider: anthropic or openai. Skipped and recorded when absent.",
    )
    benchmark.add_argument(
        "--model", help="Model override for the external provider (for example: gpt-5.6-luna)."
    )

    bundle = subcommands.add_parser("bundle", help="Materialize a safe generic-agent session from a composition.")
    bundle.add_argument("composition")
    bundle.add_argument("--project", help="Project root (default: current directory).")
    bundle.add_argument("--goal", default="")
    use = subcommands.add_parser("use", help="Materialize one explicitly cached Skill for a generic agent session.")
    use.add_argument("skill_id")
    use.add_argument("--project", help="Project root (default: current directory).")
    use.add_argument("--goal", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return _doctor(args)
        if args.command == "status":
            return _status(args)
        if args.command == "scan":
            return _scan(args)
        if args.command == "sync":
            return _sync(args)
        if args.command == "search":
            return _search(args)
        if args.command == "inspect":
            return _inspect(args)
        if args.command == "audit-skill":
            return _audit_skill(args)
        if args.command == "outdated":
            return _outdated(args)
        if args.command == "diff":
            return _diff(args)
        if args.command == "recommend":
            return _recommend(args)
        if args.command == "pin":
            return _pin(args)
        if args.command == "collection":
            return _collection(args)
        if args.command == "compose":
            return _compose(args)
        if args.command == "plan":
            return _plan(args)
        if args.command == "benchmark":
            return _benchmark(args)
        if args.command == "bundle":
            return _bundle(args)
        if args.command == "use":
            return _use(args)
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
        source = registry.source_status("skills-sh")
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
    auth = resolve_skills_sh_auth(home=home)
    print(f"skills.sh auth: {'available' if auth.token else 'missing'}")
    print(f"auth source: {auth.source}")
    print(f"Project path: {project_state}")
    _print_source_freshness(source)
    if not auth.token:
        print("Note: configure VERCEL_OIDC_TOKEN or Forge-local credentials.env; local scan/search remain available.")
    return 0


def _status(args: argparse.Namespace) -> int:
    _, registry = _registry(args.forge_home)
    try:
        source = registry.source_status("skills-sh")
    finally:
        registry.close()
    _print_source_freshness(source)
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
        if args.if_stale:
            ttl_seconds = _parse_ttl(args.if_stale)
            source = registry.source_status("skills-sh")
            if _is_fresh(source, ttl_seconds):
                print(f"Metadata sync skipped: last successful sync is newer than {args.if_stale}.")
                _print_source_freshness(source)
                return 0
        stats = sync_metadata(
            registry,
            SkillsShAdapter(forge_home=str(home)),
            per_page=args.per_page,
            on_progress=lambda page, total_pages, processed, total: print(
                f"[skills-sh] page {page}/{total_pages or '?'} · {processed:,}/{total or '?'} processed",
                flush=True,
            ),
        )
    finally:
        registry.close()
    print(
        "Metadata sync complete: "
        f"discovered={stats['discovered']}, inserted={stats['inserted']}, updated={stats['updated']}, "
        f"unchanged={stats['unchanged']}, pages={stats['pages']}, duration={stats['duration_seconds']:.3f}s, "
        f"requests={stats['requests']}."
    )
    print(f"Registry: {database_path(home)}")
    return 0


def _parse_ttl(value: str) -> float:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if len(value) < 2 or value[-1].casefold() not in units:
        raise ValueError("--if-stale must be a positive duration such as 6h, 30m, or 1d.")
    try:
        amount = float(value[:-1])
    except ValueError as error:
        raise ValueError("--if-stale must be a positive duration such as 6h, 30m, or 1d.") from error
    if amount <= 0:
        raise ValueError("--if-stale must be positive.")
    return amount * units[value[-1].casefold()]


def _is_fresh(source: sqlite3.Row | None, ttl_seconds: float) -> bool:
    if source is None or source["sync_cursor"] is not None or not source["last_sync_at"]:
        return False
    synced_at = datetime.fromisoformat(str(source["last_sync_at"]).replace("Z", "+00:00"))
    return (datetime.now(UTC) - synced_at).total_seconds() < ttl_seconds


def _print_source_freshness(source: sqlite3.Row | None) -> None:
    if source is None or source["last_sync_at"] is None:
        print("skills.sh catalog: never successfully synced")
        return
    print(f"skills.sh last successful sync: {source['last_sync_at']}")
    if source["sync_cursor"] is not None:
        print(f"skills.sh resumable page: {source['sync_cursor']}")
    if source["completed_at"] is not None:
        print(
            "Last catalog sync: "
            f"discovered={source['discovered']}, inserted={source['inserted']}, updated={source['updated']}, "
            f"unchanged={source['unchanged']}, pages={source['pages']}, requests={source['request_count']}, "
            f"catalog_total={source['catalog_total']}"
        )


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
        print(f"{index}. {result['id']} - {result['name']}")
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
        if (skill["latest_seen_version_id"] is None or args.refresh) and not args.no_fetch:
            adapter = SkillsShAdapter(forge_home=str(home))
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
    print(f"License: {skill['license_spdx'] or 'unknown'}")
    print(f"Static security: {skill['security_status']} / {skill['risk_level']}")
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


def _audit_skill(args: argparse.Namespace) -> int:
    home, registry = _registry(args.forge_home)
    try:
        if registry.get_skill(args.skill_id) is None:
            raise ValueError(f"Skill not found locally: {args.skill_id}")
        audits = SkillsShAdapter(forge_home=str(home)).fetch_audit(args.skill_id)
        registry.store_external_audits(args.skill_id, audits)
        cached = registry.get_audits(args.skill_id)
    finally:
        registry.close()
    if not cached:
        print("No upstream audit is available yet. Local static checks remain available through `forge inspect`.")
        return 0
    for audit in cached:
        print(f"{audit['provider']}: {audit['status']} / {audit['risk_level'] or 'unknown'}")
        if audit["summary"]:
            print(f"  {audit['summary']}")
    return 0


def _outdated(args: argparse.Namespace) -> int:
    context = scan_project(args.project)
    lock = load_lockfile(context["root"])
    _, registry = _registry(args.forge_home)
    try:
        rows = []
        for pin in lock["skills"]:
            if not isinstance(pin, dict) or not isinstance(pin.get("id"), str):
                continue
            skill = registry.get_skill(pin["id"])
            if skill is not None and skill["content_hash"] and skill["content_hash"] != pin.get("hash"):
                rows.append((pin, skill))
    finally:
        registry.close()
    if not rows:
        print("No cached updates are available for pinned Skills.")
        return 0
    for pin, skill in rows:
        print(f"Update available: {pin['id']}")
        print(f"  pinned: {pin.get('hash')} | cached latest: {skill['content_hash']}")
        print("  Pin remains unchanged; inspect and explicitly pin to promote a new version.")
    return 0


def _diff(args: argparse.Namespace) -> int:
    _, registry = _registry(args.forge_home)
    try:
        old_files = {str(file["path"]): str(file["contents"] or "") for file in registry.get_version_files(args.skill_id, args.old_hash)}
        new_files = {str(file["path"]): str(file["contents"] or "") for file in registry.get_version_files(args.skill_id, args.new_hash)}
    finally:
        registry.close()
    if not old_files or not new_files:
        raise ValueError("Both requested cached versions must exist before diffing.")
    paths = sorted(set(old_files) | set(new_files))
    changed = [path for path in paths if old_files.get(path) != new_files.get(path)]
    if not changed:
        print("No content changes between the two cached versions.")
        return 0
    print(f"Changed files ({len(changed)}):")
    for path in changed:
        print(f"  - {path}")
    for path in changed:
        lines = list(
            difflib.unified_diff(
                old_files.get(path, "").splitlines(),
                new_files.get(path, "").splitlines(),
                fromfile=f"{args.old_hash}/{path}",
                tofile=f"{args.new_hash}/{path}",
                lineterm="",
            )
        )
        if lines:
            print("\n".join(lines[:80]))
    return 0


def _recommend(args: argparse.Namespace) -> int:
    if args.limit < 1 or args.limit > 50:
        raise ValueError("--limit must be between 1 and 50")
    context = scan_project(args.path)
    _, registry = _registry(args.forge_home)
    try:
        recommendations = recommend_skills(registry, context, limit=args.limit)
    finally:
        registry.close()
    if not recommendations:
        print("No project-aware local recommendations yet. Run `forge sync --source skills-sh --metadata-only` first.")
        return 0
    for index, recommendation in enumerate(recommendations, start=1):
        print(f"{index}. {recommendation.name} ({recommendation.skill_id})")
        print(f"   reason: {recommendation.reason}")
        for evidence in recommendation.evidence:
            print(f"   evidence: {evidence}")
        for risk in recommendation.risks:
            print(f"   caution: {risk}")
    return 0


def _pin(args: argparse.Namespace) -> int:
    context = scan_project(args.project)
    _, registry = _registry(args.forge_home)
    try:
        skill = registry.get_skill(args.skill_id)
        if skill is None:
            raise ValueError(f"Skill not found locally: {args.skill_id}. Search and inspect it before pinning.")
        if skill["content_hash"] is None:
            raise ValueError(
                "Skill detail is not cached. Run `forge inspect <skill-id>` first to select an immutable version."
            )
        output = pin_skill(
            context["root"],
            skill_id=args.skill_id,
            source=str(skill["source_repo"]),
            content_hash=str(skill["content_hash"]),
            reason=args.reason,
            mode=args.mode,
        )
    finally:
        registry.close()
    print(f"Pinned {args.skill_id} at {skill['content_hash']}.")
    print(f"Lockfile: {output}")
    return 0


def _collection(args: argparse.Namespace) -> int:
    _, registry = _registry(args.forge_home)
    try:
        if args.collection_command == "create":
            registry.create_collection(args.name)
            print(f"Created collection: {args.name}")
        elif args.collection_command == "add":
            registry.add_to_collection(args.name, args.skill_id)
            print(f"Added {args.skill_id} to collection {args.name}.")
        elif args.collection_command == "list":
            collections = registry.list_collections()
            if not collections:
                print("No collections yet. Create one with `forge collection create <name>`.")
            for collection in collections:
                print(f"{collection['name']} ({collection['skill_count']} Skills)")
        elif args.collection_command == "show":
            skills = registry.get_collection_skills(args.name)
            print(f"Collection: {args.name}")
            if not skills:
                print("  (empty)")
            for skill in skills:
                print(f"  - {skill['id']} - {skill['name']}")
    finally:
        registry.close()
    return 0


def _compose(args: argparse.Namespace) -> int:
    _, registry = _registry(args.forge_home)
    try:
        if args.compose_command == "create":
            registry.create_composition(args.name, goal=args.goal)
            print(f"Created composition: {args.name}")
        elif args.compose_command == "add":
            add_skill_to_composition(registry, name=args.name, skill_id=args.skill_id, role=args.role)
            print(f"Added {args.skill_id} to composition {args.name} as {args.role}.")
        elif args.compose_command == "show":
            composition_manifest = manifest(registry, args.name)
            print(f"Composition: {composition_manifest['name']}")
            print(f"Goal: {composition_manifest['goal'] or '(none)'}")
            for skill in composition_manifest["skills"]:
                print(f"  - {skill['role']}: {skill['id']} @ {skill['hash']}")
        elif args.compose_command == "analyze":
            analysis = analyze_composition(registry, name=args.name, goal=args.goal)
            print(f"Composition: {analysis.name}")
            print(f"Goal: {analysis.goal or '(none)'}")
            print(f"Skills: {analysis.skill_count}")
            print(f"Sources: {', '.join(analysis.sources) or '(none)'}")
            for warning in analysis.warnings:
                print(f"Caution: {warning}")
    finally:
        registry.close()
    return 0


def _plan(args: argparse.Namespace) -> int:
    if not 5 <= args.candidates <= 200:
        raise ValueError("--candidates must be between 5 and 200")
    if not 1 <= args.fetch_budget <= 25:
        raise ValueError("--fetch-budget must be between 1 and 25")
    context = scan_project(args.project)
    provider = resolve_provider(args.provider, model=args.model)
    home, registry = _registry(args.forge_home)
    fetcher = SkillsShAdapter(forge_home=str(home)) if args.fetch_missing else None
    try:
        result = create_plan(
            registry,
            provider,
            goal=args.goal,
            project_context=context,
            plans_root=home / "plans",
            candidate_limit=args.candidates,
            detail_fetcher=fetcher,
            snapshots_root=home / "snapshots",
            fetch_budget=args.fetch_budget,
        )
    finally:
        registry.close()

    gate = result.gate
    print(f"Plan: {result.plan_id}")
    print(f"Goal: {result.goal}")
    print(f"Provider: {result.provider_name} (proposal only)")
    print(f"Queries: {', '.join(result.queries) or '(none)'}")
    print(f"Retrieved candidates: {result.retrieved}")
    print(f"Risk: {gate.risk} | exploration budget: {gate.exploration_budget:.0%}")
    if result.fetch_report.enabled:
        print(
            f"Detail fetch: fetched_for_plan={len(result.fetch_report.fetched)}, "
            f"failed={len(result.fetch_report.failed)}, "
            f"skipped_over_budget={len(result.fetch_report.over_budget)}"
        )
        for outcome in result.fetch_report.failed:
            print(f"  fetch_failed {outcome.skill_id}: {outcome.detail}")
    print(
        f"Policy gate: nominated={len(result.proposal.selected)}, "
        f"admitted={len(gate.admitted)}, rejected={gate.blocked_count}"
    )
    coverage = result.coverage
    if coverage.get("unknown"):
        print("Coverage: the provider proposed no roles, so completeness cannot be assessed.")
    elif coverage.get("complete"):
        print(f"Coverage: {len(coverage['coveredRoles'])}/{len(coverage['requiredRoles'])} roles covered.")
    else:
        print(
            f"Coverage: INCOMPLETE — {len(coverage.get('coveredRoles', []))}/"
            f"{len(coverage.get('requiredRoles', []))} roles covered."
        )
        for role in coverage.get("missingRoles", []):
            lost = coverage.get("lostTo", {}).get(role)
            print(f"  missing role: {role}" + (f" (lost to: {', '.join(lost)})" if lost else ""))
    if gate.hallucinated_ids:
        print(f"Provider invented {len(gate.hallucinated_ids)} unknown Skill id(s); all were dropped:")
        for skill_id in gate.hallucinated_ids:
            print(f"  x {skill_id}")
    if result.retrieved == 0:
        print("No local candidates matched. Run `forge sync --source skills-sh --metadata-only` first.")
    print("\nSelected:")
    if not gate.admitted:
        print("  (none survived the policy gate)")
    for decision in gate.admitted:
        print(f"  - {decision.role}: {decision.skill_id} @ {decision.content_hash}")
        print(f"    reason: {decision.reason}")
        print(f"    audit: {decision.security_status} / {decision.risk_level}")
        for note in decision.review_notes:
            print(f"    caution: {note}")
    if gate.rejected:
        print("\nRejected by Forge:")
        for decision in gate.rejected:
            print(f"  x {decision.skill_id}: {decision.reason}")
    if gate.human_approval_required:
        print("\nHuman approval required:")
        for item in gate.human_approval_required:
            print(f"  ! {item}")
    print(f"\nPlan artifacts: {result.directory}")
    print("Skill selection reasoning is a model judgment, not verified evidence. Review before executing.")
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    external, skip_reason = resolve_external_provider(args.external_provider, args.model)
    run = run_benchmark(
        fixture_root=Path(args.fixtures).expanduser() if args.fixtures else None,
        external_provider=external,
        external_provider_skip_reason=skip_reason,
    )
    output_dir = Path(args.output).expanduser() if args.output else Path.cwd() / "artifacts" / "planner-benchmark"
    summary_path, report_path = write_artifacts(run, output_dir=output_dir)
    summary = build_summary(run)

    print("Forge planner benchmark")
    print(f"Runtime: {run.runtime['sandboxRuntime']} (target {run.runtime['targetRuntime']})")
    if run.runtime["local312VerificationRequired"]:
        print("Caution: this did not run on the target interpreter; re-run on Python 3.12.")
    print(f"Fixture: {summary['fixture']['catalogSize']} Skills, {summary['fixture']['scenarioCount']} scenarios")
    print("")
    for variant, status in run.variants.items():
        values = summary["aggregates"].get(variant)
        if values is None:
            print(f"{variant}: {status}")
            continue
        print(
            f"{variant}: passed {values['passed']}/{values['scenarios']} | "
            f"role recall {_metric(values['meanRoleRecall'])} | "
            f"irrelevant {_metric(values['meanIrrelevantSelectionRate'])} | "
            f"admitted {_metric(values['meanAdmittedCount'])} | "
            f"explanations {_metric(values['meanExplanationCoverage'])}"
        )
    print("")
    probes = summary["policyProbes"]
    print(f"Policy probes: {probes['passed']}/{probes['total']} passed")
    for probe in run.probes:
        if not probe.passed:
            print(f"  FAIL {probe.probe_id}: {'; '.join(probe.mismatches)}")
    for variant, values in run.determinism.items():
        state = "reproducible" if values["reproducible"] else f"diverged on {values['divergentScenarios']}"
        print(f"Determinism {variant}: {state}")
    print("")
    print(f"Summary: {summary_path}")
    print(f"Report:  {report_path}")
    return 0 if probes["allPassed"] else 1


def _metric(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _bundle(args: argparse.Namespace) -> int:
    context = scan_project(args.project)
    home, registry = _registry(args.forge_home)
    try:
        selected = manifest(registry, args.composition)
        session = materialize_bundle(
            registry,
            sessions_root=home / "sessions",
            project_context=context,
            skills=selected["skills"],
            goal=args.goal or selected["goal"],
        )
    finally:
        registry.close()
    print(f"Session bundle: {session}")
    print(render_instructions(session))
    return 0


def _use(args: argparse.Namespace) -> int:
    context = scan_project(args.project)
    home, registry = _registry(args.forge_home)
    try:
        skill = registry.get_skill(args.skill_id)
        if skill is None or skill["content_hash"] is None:
            raise ValueError("Run `forge inspect <skill-id>` before using a cached immutable Skill version.")
        session = materialize_bundle(
            registry,
            sessions_root=home / "sessions",
            project_context=context,
            skills=[{"id": args.skill_id, "hash": str(skill["content_hash"]), "role": "reference"}],
            goal=args.goal,
        )
    finally:
        registry.close()
    print(f"Session bundle: {session}")
    print(render_instructions(session))
    return 0
