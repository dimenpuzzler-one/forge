import json
import tempfile
import unittest
from pathlib import Path

from forge_core.models import SkillMetadata
from forge_registry.database import Registry
from forge_runtime.generic_filesystem import materialize_bundle, render_instructions


class RuntimeBundleTests(unittest.TestCase):
    def test_bundle_materializes_cached_files_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            registry = Registry(root / "forge.db")
            registry.migrate()
            source_id = registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
            run_id = registry.start_sync_run(source_id)
            registry.upsert_metadata_page(
                source_id,
                [SkillMetadata(id="acme/skills/example", slug="example", name="Example", source="acme/skills")],
                next_page=None,
                run_id=run_id,
            )
            registry.store_detail(
                "acme/skills/example",
                {"hash": "v1", "files": [{"path": "scripts/run.sh", "contents": "echo never executed"}]},
                snapshots_root=root / "snapshots",
            )

            session = materialize_bundle(
                registry,
                sessions_root=root / "sessions",
                project_context={"name": "project"},
                skills=[{"id": "acme/skills/example", "hash": "v1", "role": "reference"}],
                goal="review",
            )

            manifest = json.loads((session / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["executeScripts"])
            self.assertTrue(any((session / "skills").rglob("run.sh")))
            self.assertIn("do not execute scripts", render_instructions(session))
            registry.close()
