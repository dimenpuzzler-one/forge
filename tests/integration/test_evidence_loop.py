"""V2.2-prep: the evidence loop, and the role vocabulary it accumulates against.

V2.2 needs historical evidence, but the components that produce it (`finalize`, `learn`) come
later in the roadmap than the component that reads it. These tests cover the minimum producer
that breaks that circle, and the role taxonomy that stops the evidence fragmenting.
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.errors import ValidationError
from forge_core.models import SkillMetadata
from forge_planner.evidence import (
    CONTRIBUTIONS,
    load_history,
    record_contribution,
    resolve_plan_id,
)
from forge_planner.roles import CANONICAL_ROLES, display, is_custom, normalize_role
from forge_planner.service import create_plan
from forge_registry.database import Registry
from tests.integration.test_plan_hardening import ScriptedProvider


def _seed(home: Path) -> Registry:
    registry = Registry(home / "forge.db")
    registry.migrate()
    source_id = registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
    run_id = registry.start_sync_run(source_id)
    registry.upsert_metadata_page(
        source_id,
        [
            SkillMetadata(id="acme/skills/cro", slug="cro", name="Landing conversion",
                          description="landing page conversion CTA hierarchy", source="acme/skills"),
            SkillMetadata(id="acme/skills/copy", slug="copy", name="Landing copy",
                          description="landing page copywriting headline", source="acme/skills"),
        ],
        next_page=None,
        run_id=run_id,
    )
    for slug, content_hash in (("cro", "cro-v1"), ("copy", "copy-v1")):
        registry.store_detail(
            f"acme/skills/{slug}",
            {"hash": content_hash, "files": [{"path": "SKILL.md", "contents": f"# {slug}"}]},
            snapshots_root=home / "snapshots",
        )
    return registry


class RoleVocabularyTests(unittest.TestCase):
    def test_canonical_roles_pass_through_unchanged(self) -> None:
        for role in CANONICAL_ROLES:
            resolved = normalize_role(role)
            self.assertEqual(role, resolved.storage_key)
            self.assertFalse(resolved.custom)

    def test_mechanical_variation_is_normalized(self) -> None:
        for raw in ("Visual Design", "visual_design", " VISUAL-DESIGN ", "visual/design"):
            self.assertEqual("visual-design", normalize_role(raw).storage_key, raw)

    def test_an_unlisted_role_is_kept_and_marked_custom(self) -> None:
        resolved = normalize_role("conversion-audit")

        self.assertTrue(resolved.custom)
        self.assertEqual("custom:conversion-audit", resolved.storage_key)
        self.assertTrue(is_custom(resolved.storage_key))
        self.assertEqual("conversion-audit (custom)", display(resolved.storage_key))

    def test_forge_does_not_invent_synonyms(self) -> None:
        # Mapping conversion-audit onto conversion would assert an equivalence the provider
        # never stated, and would hide the taxonomy drift this module exists to surface.
        self.assertNotEqual("conversion", normalize_role("conversion-audit").name)
        self.assertNotEqual("copy", normalize_role("copywriting").name)

    def test_empty_and_prefixed_input_degrade_safely(self) -> None:
        self.assertEqual("general", normalize_role("").storage_key)
        self.assertEqual("general", normalize_role("   ").storage_key)
        self.assertEqual("custom:odd-role", normalize_role("custom:odd-role").storage_key)

    def test_the_vocabulary_reaches_the_provider_prompt(self) -> None:
        from forge_planner.provider import SYSTEM_PROMPT

        for role in ("positioning", "visual-design", "accessibility", "payments"):
            self.assertIn(role, SYSTEM_PROMPT)
        self.assertIn('"taskType"', SYSTEM_PROMPT, "the JSON schema must survive prompt assembly")


class EvidenceRecordingTests(unittest.TestCase):
    def test_planning_records_provenance_without_claiming_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                result = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"], roles=["conversion"]),
                    goal="landing page conversion", project_context={"name": "demo"},
                    plans_root=home / "plans",
                )
                task = registry.get_task(result.plan_id)
                history = load_history(registry, "acme/skills/cro")
            finally:
                registry.close()

            self.assertIsNotNone(task)
            self.assertEqual("demo", task["project"])
            self.assertEqual(1, history.selected_in_tasks)
            self.assertFalse(history.evaluated, "selection alone is never evidence of contribution")
            self.assertIn("never evaluated", history.summary_line())

    def test_the_loop_closes_and_a_later_plan_sees_the_verdict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                first = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro", "acme/skills/copy"], roles=["conversion", "copy"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
                record_contribution(
                    registry, plan_id=first.plan_id, skill_id="acme/skills/cro",
                    contribution="high", note="CTA hierarchy drove it",
                )
                second = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro", "acme/skills/copy"], roles=["conversion", "copy"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
            finally:
                registry.close()

            document = json.loads((second.directory / "plan.json").read_text(encoding="utf-8"))
            by_id = {entry["id"]: entry["historicalEvidence"] for entry in document["selectedSkills"]}

            self.assertIn("human contribution high: 1", by_id["acme/skills/cro"])
            self.assertIn(
                "no contribution has ever been recorded for it",
                by_id["acme/skills/copy"],
                "an unevaluated Skill must say so rather than look equally proven",
            )

    def test_only_human_evidence_can_be_written(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                result = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
                with self.assertRaises(ValidationError) as caught:
                    record_contribution(
                        registry, plan_id=result.plan_id, skill_id="acme/skills/cro",
                        contribution="high", evidence_class="inferred",
                    )
            finally:
                registry.close()

            self.assertIn("agent's opinion of its own work is not accepted", str(caught.exception))

    def test_a_skill_outside_the_plan_cannot_be_evaluated_against_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                result = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
                with self.assertRaises(ValidationError):
                    record_contribution(
                        registry, plan_id=result.plan_id, skill_id="acme/skills/copy", contribution="high"
                    )
            finally:
                registry.close()

    def test_an_invalid_contribution_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                result = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
                with self.assertRaises(ValidationError):
                    record_contribution(
                        registry, plan_id=result.plan_id, skill_id="acme/skills/cro", contribution="amazing"
                    )
            finally:
                registry.close()

    def test_re_evaluating_replaces_rather_than_accumulates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                result = create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"]),
                    goal="landing page conversion", project_context={}, plans_root=home / "plans",
                )
                for contribution in ("high", "low"):
                    record_contribution(
                        registry, plan_id=result.plan_id, skill_id="acme/skills/cro", contribution=contribution
                    )
                history = load_history(registry, "acme/skills/cro")
            finally:
                registry.close()

            self.assertEqual({"low": 1}, history.human_verdicts)

    def test_latest_resolves_to_the_most_recent_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = _seed(home)
            try:
                create_plan(
                    registry, ScriptedProvider(["acme/skills/cro"]),
                    goal="first goal", project_context={}, plans_root=home / "plans",
                )
                second = create_plan(
                    registry, ScriptedProvider(["acme/skills/copy"]),
                    goal="second goal", project_context={}, plans_root=home / "plans",
                )
                self.assertEqual(second.plan_id, resolve_plan_id(registry, "latest"))
            finally:
                registry.close()

    def test_history_of_an_unknown_skill_is_empty_not_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = _seed(Path(temp_dir))
            try:
                history = load_history(registry, "nobody/knows/this")
            finally:
                registry.close()

            self.assertEqual(0, history.selected_in_tasks)
            self.assertEqual([], history.as_plan_evidence())
            self.assertIn("Never selected", history.summary_line())


class EvidenceCliTests(unittest.TestCase):
    def test_learn_and_usage_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home, project = root / "home", root / "project"
            home.mkdir()
            project.mkdir()
            (project / "README.md").write_text("# Project", encoding="utf-8")
            _seed(home).close()

            printed = io.StringIO()
            with redirect_stdout(printed):
                self.assertEqual(0, main([
                    "--forge-home", str(home), "plan", "landing page conversion",
                    "--project", str(project), "--provider", "stub",
                ]))
                self.assertEqual(0, main([
                    "--forge-home", str(home), "learn", "latest", "acme/skills/cro",
                    "--contribution", "high", "--note", "drove the redesign",
                ]))
                self.assertEqual(0, main(["--forge-home", str(home), "skills", "usage", "acme/skills/cro"]))

            output = printed.getvalue()
            self.assertIn("Evidence class: human", output)
            self.assertIn("not a measurement Forge took", output)
            self.assertIn("human verdicts: high=1", output)

    def test_usage_of_a_selected_but_unevaluated_skill_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home, project = root / "home", root / "project"
            home.mkdir()
            project.mkdir()
            (project / "README.md").write_text("# Project", encoding="utf-8")
            _seed(home).close()

            printed = io.StringIO()
            with redirect_stdout(printed):
                main([
                    "--forge-home", str(home), "plan", "landing page conversion",
                    "--project", str(project), "--provider", "stub",
                ])
                main(["--forge-home", str(home), "skills", "usage", "acme/skills/cro"])

            self.assertIn("Selection is not evidence of contribution", printed.getvalue())

    def test_learn_rejects_an_unknown_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(2, main([
                    "--forge-home", temp_dir, "learn", "plan-does-not-exist",
                    "acme/skills/cro", "--contribution", "high",
                ]))

    def test_contribution_choices_match_the_evidence_module(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main([
                        "--forge-home", temp_dir, "learn", "latest", "a/b/c", "--contribution", "excellent",
                    ])
        self.assertEqual(("none", "low", "medium", "high"), CONTRIBUTIONS)


class SchemaMigrationTests(unittest.TestCase):
    def test_migration_to_schema_four_is_additive_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "forge.db"
            first = Registry(path)
            first.migrate()
            version = first.connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in first.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            first.close()

            second = Registry(path)
            second.migrate()
            second_version = second.connection.execute("PRAGMA user_version").fetchone()[0]
            second.close()

            self.assertEqual(4, version)
            self.assertEqual(4, second_version)
            self.assertLessEqual({"tasks", "task_skills", "skill_evaluations"}, tables)
            self.assertLessEqual({"skills", "skill_versions", "compositions"}, tables)


if __name__ == "__main__":
    unittest.main()
