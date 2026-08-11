import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


class Phase4CliTests(unittest.TestCase):
    def test_recommend_then_pin_uses_local_evidence_and_cached_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            (project / "package.json").write_text(
                '{"dependencies":{"@supabase/supabase-js":"2.0.0"}}', encoding="utf-8"
            )
            (project / "README.md").write_text("# Production application", encoding="utf-8")
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
                        id="acme/skills/supabase-postgres",
                        slug="supabase-postgres",
                        name="Supabase Postgres Safety",
                        description="Supabase postgres RLS production review",
                        source="acme/skills",
                    )
                ],
                next_page=None,
                run_id=run_id,
            )
            registry.store_detail(
                "acme/skills/supabase-postgres",
                {"hash": "pinned-hash", "files": [{"path": "SKILL.md", "contents": "# Safe"}]},
                snapshots_root=home / "snapshots",
            )
            registry.close()

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--forge-home", str(home), "recommend", str(project)]))
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            str(home),
                            "pin",
                            "acme/skills/supabase-postgres",
                            "--project",
                            str(project),
                            "--reason",
                            "production RLS review",
                        ]
                    ),
                )

            text = output.getvalue()
            self.assertIn("Supabase/Postgres production safety", text)
            self.assertIn("Pinned acme/skills/supabase-postgres at pinned-hash.", text)
            self.assertIn("pinned-hash", (project / ".forge" / "skills.lock").read_text(encoding="utf-8"))

