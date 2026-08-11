import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.models import SkillMetadata
from forge_project.lockfile import pin_skill
from forge_registry.database import Registry


class Phase6CliTests(unittest.TestCase):
    def test_diff_and_outdated_keep_project_pin_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# Project", encoding="utf-8")
            registry = Registry(home / "forge.db")
            registry.migrate()
            source_id = registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
            run_id = registry.start_sync_run(source_id)
            registry.upsert_metadata_page(
                source_id,
                [SkillMetadata(id="acme/skills/example", slug="example", name="Example", source="acme/skills")],
                next_page=None,
                run_id=run_id,
            )
            for content_hash, contents in (("v1", "# First"), ("v2", "# Second")):
                registry.store_detail(
                    "acme/skills/example",
                    {"hash": content_hash, "files": [{"path": "SKILL.md", "contents": contents}]},
                    snapshots_root=home / "snapshots",
                )
            pin_skill(
                project,
                skill_id="acme/skills/example",
                source="acme/skills",
                content_hash="v1",
                reason="first review",
            )
            registry.close()

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--forge-home", str(home), "outdated", "--project", str(project)]))
                self.assertEqual(0, main(["--forge-home", str(home), "diff", "acme/skills/example", "v1", "v2"]))

            self.assertIn("Update available: acme/skills/example", output.getvalue())
            self.assertIn("-# First", output.getvalue())
            self.assertIn("+# Second", output.getvalue())
            self.assertIn('"hash": "v1"', (project / ".forge" / "skills.lock").read_text(encoding="utf-8"))
