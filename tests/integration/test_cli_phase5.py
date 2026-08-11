import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


class Phase5CliTests(unittest.TestCase):
    def test_collection_and_composition_cli_use_cached_skill_versions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            registry = Registry(home / "forge.db")
            registry.migrate()
            source_id = registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
            run_id = registry.start_sync_run(source_id)
            registry.upsert_metadata_page(
                source_id,
                [
                    SkillMetadata(
                        id="acme/skills/review",
                        slug="review",
                        name="Review",
                        source="acme/skills",
                    )
                ],
                next_page=None,
                run_id=run_id,
            )
            registry.store_detail(
                "acme/skills/review",
                {"hash": "review-v1", "files": [{"path": "SKILL.md", "contents": "# Review"}]},
                snapshots_root=home / "snapshots",
            )
            registry.close()

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--forge-home", str(home), "collection", "create", "quality"]))
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            str(home),
                            "collection",
                            "add",
                            "quality",
                            "acme/skills/review",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            str(home),
                            "compose",
                            "create",
                            "review-stack",
                            "--goal",
                            "quality review",
                        ]
                    ),
                )
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            str(home),
                            "compose",
                            "add",
                            "review-stack",
                            "acme/skills/review",
                            "--role",
                            "quality",
                        ]
                    ),
                )
                self.assertEqual(0, main(["--forge-home", str(home), "compose", "show", "review-stack"]))
                self.assertEqual(0, main(["--forge-home", str(home), "compose", "analyze", "review-stack"]))

            text = output.getvalue()
            self.assertIn("Added acme/skills/review to collection quality.", text)
            self.assertIn("quality: acme/skills/review @ review-v1", text)
            self.assertIn("Skills: 1", text)
