import tempfile
import unittest
from pathlib import Path

from forge_core.models import SkillMetadata
from forge_core.errors import ValidationError
from forge_registry.database import Registry


def metadata(skill_id: str = "acme/skills/postgres") -> SkillMetadata:
    return SkillMetadata(
        id=skill_id,
        slug="postgres",
        name="Postgres Production",
        description="Production postgres safety and reliability checks.",
        source="acme/skills",
        installs=42,
        source_type="github",
        install_url="https://github.com/acme/skills",
        skills_sh_url="https://skills.sh/acme/skills/postgres",
    )


class RegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.registry = Registry(Path(self.temp_dir.name) / "forge.db")
        self.registry.migrate()
        self.source_id = self.registry.ensure_source(
            name="skills-sh", source_type="skills_sh", base_url="https://skills.sh"
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.temp_dir.cleanup()

    def test_metadata_upsert_is_searchable_and_idempotent(self) -> None:
        first = self.registry.upsert_metadata_page(
            self.source_id, [metadata()], next_page=1, run_id=self.registry.start_sync_run(self.source_id)
        )
        first_seen = self.registry.get_skill("acme/skills/postgres")["last_seen_at"]
        second = self.registry.upsert_metadata_page(
            self.source_id, [metadata()], next_page=None, run_id=self.registry.start_sync_run(self.source_id)
        )

        results = self.registry.search("postgres production")

        self.assertEqual({"discovered": 1, "inserted": 1, "updated": 0, "unchanged": 0}, first)
        self.assertEqual({"discovered": 1, "inserted": 0, "updated": 0, "unchanged": 1}, second)
        self.assertEqual(1, len(results))
        self.assertEqual("acme/skills/postgres", results[0]["id"])
        self.assertEqual(first_seen, self.registry.get_skill("acme/skills/postgres")["last_seen_at"])

    def test_metadata_change_updates_only_the_changed_row(self) -> None:
        run_id = self.registry.start_sync_run(self.source_id)
        self.registry.upsert_metadata_page(self.source_id, [metadata()], next_page=None, run_id=run_id)
        changed = SkillMetadata(
            id="acme/skills/postgres",
            slug="postgres",
            name="Postgres Production",
            description="Changed metadata",
            source="acme/skills",
            installs=42,
        )

        counts = self.registry.upsert_metadata_page(
            self.source_id, [changed], next_page=None, run_id=self.registry.start_sync_run(self.source_id)
        )

        self.assertEqual({"discovered": 1, "inserted": 0, "updated": 1, "unchanged": 0}, counts)
        self.assertEqual("Changed metadata", self.registry.get_skill("acme/skills/postgres")["description"])

    def test_detail_versions_are_immutable_and_scripts_are_only_flagged(self) -> None:
        run_id = self.registry.start_sync_run(self.source_id)
        self.registry.upsert_metadata_page(self.source_id, [metadata()], next_page=None, run_id=run_id)
        snapshots = Path(self.temp_dir.name) / "snapshots"

        version_id, content_hash = self.registry.store_detail(
            "acme/skills/postgres",
            {
                "hash": "content-v1",
                "files": [
                    {"path": "SKILL.md", "contents": "# Postgres"},
                    {"path": "scripts/check.sh", "contents": "echo not executed"},
                ],
            },
            snapshots_root=snapshots,
        )

        skill = self.registry.get_skill("acme/skills/postgres")
        files = self.registry.get_files("acme/skills/postgres")
        self.assertEqual("content-v1", content_hash)
        self.assertEqual(version_id, skill["latest_seen_version_id"])
        self.assertTrue((snapshots / "skills-sh").exists())
        self.assertTrue(any(file["is_script"] for file in files))

    def test_detail_rejects_path_traversal(self) -> None:
        run_id = self.registry.start_sync_run(self.source_id)
        self.registry.upsert_metadata_page(self.source_id, [metadata()], next_page=None, run_id=run_id)

        with self.assertRaises(ValidationError):
            self.registry.store_detail(
                "acme/skills/postgres",
                {"files": [{"path": "../outside.txt", "contents": "no"}]},
                snapshots_root=Path(self.temp_dir.name) / "snapshots",
            )

        with self.assertRaises(ValidationError):
            self.registry.store_detail(
                "acme/skills/postgres",
                {"files": [{"path": "..\\outside.txt", "contents": "no"}]},
                snapshots_root=Path(self.temp_dir.name) / "snapshots",
            )
