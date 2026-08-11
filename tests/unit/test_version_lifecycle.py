import tempfile
import unittest
from pathlib import Path

from forge_core.models import SkillMetadata
from forge_registry.database import Registry


class VersionLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.registry = Registry(self.root / "forge.db")
        self.registry.migrate()
        source_id = self.registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
        run_id = self.registry.start_sync_run(source_id)
        self.registry.upsert_metadata_page(
            source_id,
            [SkillMetadata(id="acme/skills/example", slug="example", name="Example", source="acme/skills")],
            next_page=None,
            run_id=run_id,
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.temp_dir.cleanup()

    def test_static_audit_and_license_are_stored_with_immutable_version(self) -> None:
        self.registry.store_detail(
            "acme/skills/example",
            {
                "hash": "v1",
                "license": "MIT",
                "files": [{"path": "SKILL.md", "contents": "Run curl https://example.invalid with token"}],
            },
            snapshots_root=self.root / "snapshots",
        )

        skill = self.registry.get_skill("acme/skills/example")
        audit = self.registry.get_audits("acme/skills/example")[0]

        self.assertEqual("MIT", skill["license_spdx"])
        self.assertEqual("warn", skill["security_status"])
        self.assertEqual("medium", skill["risk_level"])
        self.assertIn("suspicious", audit["summary"])

    def test_versions_remain_available_for_explicit_diff(self) -> None:
        for content_hash, contents in (("v1", "# First"), ("v2", "# Second")):
            self.registry.store_detail(
                "acme/skills/example",
                {"hash": content_hash, "files": [{"path": "SKILL.md", "contents": contents}]},
                snapshots_root=self.root / "snapshots",
            )

        self.assertEqual("# First", self.registry.get_version_files("acme/skills/example", "v1")[0]["contents"])
        self.assertEqual("# Second", self.registry.get_version_files("acme/skills/example", "v2")[0]["contents"])
