import tempfile
import unittest
from pathlib import Path

from forge_compose.service import add_skill_to_composition, analyze_composition, manifest
from forge_core.models import SkillMetadata
from forge_registry.database import Registry


class CollectionsAndCompositionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = Registry(Path(self.temp_dir.name) / "forge.db")
        self.registry.migrate()
        source_id = self.registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
        run_id = self.registry.start_sync_run(source_id)
        self.registry.upsert_metadata_page(
            source_id,
            [
                SkillMetadata(
                    id="acme/skills/database",
                    slug="database",
                    name="Database Safety",
                    description="Database safety practices",
                    source="acme/skills",
                ),
                SkillMetadata(
                    id="other/skills/security",
                    slug="security",
                    name="Security Review",
                    description="Security review practices",
                    source="other/skills",
                ),
            ],
            next_page=None,
            run_id=run_id,
        )
        self.registry.store_detail(
            "acme/skills/database",
            {
                "hash": "database-v1",
                "files": [
                    {"path": "SKILL.md", "contents": "# Database"},
                    {"path": "scripts/review.sh", "contents": "echo never execute"},
                ],
            },
            snapshots_root=Path(self.temp_dir.name) / "snapshots",
        )
        self.registry.store_detail(
            "other/skills/security",
            {"hash": "security-v1", "files": [{"path": "SKILL.md", "contents": "# Security"}]},
            snapshots_root=Path(self.temp_dir.name) / "snapshots",
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.temp_dir.cleanup()

    def test_collection_keeps_local_skill_references(self) -> None:
        self.registry.create_collection("production-saas")
        self.registry.add_to_collection("production-saas", "acme/skills/database")
        self.registry.add_to_collection("production-saas", "acme/skills/database")

        collections = self.registry.list_collections()
        skills = self.registry.get_collection_skills("production-saas")

        self.assertEqual(1, collections[0]["skill_count"])
        self.assertEqual("acme/skills/database", skills[0]["id"])

    def test_composition_preserves_hash_and_flags_scripts_without_running_them(self) -> None:
        self.registry.create_composition("production-review", goal="Safe production review")
        add_skill_to_composition(
            self.registry, name="production-review", skill_id="acme/skills/database", role="database"
        )
        add_skill_to_composition(
            self.registry, name="production-review", skill_id="other/skills/security", role="security"
        )

        rendered = manifest(self.registry, "production-review")
        analysis = analyze_composition(self.registry, name="production-review")

        self.assertEqual("database-v1", rendered["skills"][0]["hash"])
        self.assertEqual(["acme/skills", "other/skills"], analysis.sources)
        self.assertTrue(any("scripts" in warning for warning in analysis.warnings))
