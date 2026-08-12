import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


class PlanCliTests(unittest.TestCase):
    def _seed(self, home: Path) -> None:
        registry = Registry(home / "forge.db")
        registry.migrate()
        source_id = registry.ensure_source(
            name="skills-sh", source_type="skills_sh", base_url="https://skills.sh"
        )
        run_id = registry.start_sync_run(source_id)
        registry.upsert_metadata_page(
            source_id,
            [
                SkillMetadata(
                    id="acme/skills/landing-conversion",
                    slug="landing-conversion",
                    name="Landing conversion",
                    description="Landing page conversion copy and CTA hierarchy",
                    source="acme/skills",
                ),
                SkillMetadata(
                    id="acme/skills/backup-scheduler",
                    slug="backup-scheduler",
                    name="Backup scheduler",
                    description="Postgres backup scheduling and retention",
                    source="acme/skills",
                ),
            ],
            next_page=None,
            run_id=run_id,
        )
        registry.store_detail(
            "acme/skills/landing-conversion",
            {"hash": "conv-v1", "files": [{"path": "SKILL.md", "contents": "# Conversion\nOne primary CTA."}]},
            snapshots_root=home / "snapshots",
        )
        registry.close()

    def test_plan_writes_artifacts_and_records_the_policy_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home, project = root / "home", root / "project"
            project.mkdir()
            (project / "README.md").write_text("# Project", encoding="utf-8")
            home.mkdir()
            self._seed(home)

            output = io.StringIO()
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--forge-home",
                        str(home),
                        "plan",
                        "landing conversion redesign",
                        "--project",
                        str(project),
                        "--provider",
                        "stub",
                    ]
                )

            self.assertEqual(0, exit_code)
            printed = output.getvalue()
            self.assertIn("acme/skills/landing-conversion @ conv-v1", printed)
            self.assertIn("Policy gate:", printed)

            plans = sorted((home / "plans").iterdir())
            self.assertEqual(1, len(plans))
            document = json.loads((plans[0] / "plan.json").read_text(encoding="utf-8"))
            self.assertEqual(1, document["schemaVersion"])
            self.assertEqual("landing conversion redesign", document["goal"])
            self.assertEqual("stub", document["provider"]["name"])
            self.assertEqual(
                ["acme/skills/landing-conversion"], [skill["id"] for skill in document["selectedSkills"]]
            )
            self.assertEqual("conv-v1", document["selectedSkills"][0]["hash"])
            self.assertEqual([], document["policyGate"]["hallucinatedIds"])
            self.assertIn("landing", document["retrieval"]["queries"])

            markdown = (plans[0] / "plan.md").read_text(encoding="utf-8")
            self.assertIn("# Forge plan: landing conversion redesign", markdown)
            self.assertIn("This plan is a proposal.", markdown)
            self.assertIn("verified engineering evidence", markdown)

    def test_uncached_candidate_is_rejected_and_never_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home, project = root / "home", root / "project"
            project.mkdir()
            (project / "README.md").write_text("# Project", encoding="utf-8")
            home.mkdir()
            self._seed(home)

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            str(home),
                            "plan",
                            "postgres backup scheduling retention",
                            "--project",
                            str(project),
                            "--provider",
                            "stub",
                        ]
                    ),
                )

            printed = output.getvalue()
            self.assertIn("Rejected by Forge:", printed)
            self.assertIn("forge inspect acme/skills/backup-scheduler", printed)
            self.assertIn("(none survived the policy gate)", printed)

            document = json.loads(
                (sorted((home / "plans").iterdir())[0] / "plan.json").read_text(encoding="utf-8")
            )
            self.assertEqual([], document["selectedSkills"])
            self.assertEqual(
                ["policy-gate"],
                sorted({exclusion["excludedBy"] for exclusion in document["excludedSkills"]}),
            )

    def test_unknown_provider_fails_without_writing_a_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home, project = root / "home", root / "project"
            project.mkdir()
            home.mkdir()

            self.assertEqual(
                2,
                main(
                    [
                        "--forge-home",
                        str(home),
                        "plan",
                        "anything",
                        "--project",
                        str(project),
                        "--provider",
                        "not-a-provider",
                    ]
                ),
            )
            self.assertFalse((home / "plans").exists())


if __name__ == "__main__":
    unittest.main()
