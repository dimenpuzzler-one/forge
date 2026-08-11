import json
import tempfile
import unittest
from pathlib import Path

from forge_registry.database import Registry
from forge_sources.skills_sh import SkillsShAdapter, sync_metadata
from forge_project.lockfile import load_lockfile, pin_skill
from forge_project.recommend import recommend_skills


class FakeTransport:
    def __init__(self, responses):
        self.responses = list(responses)

    def get(self, url, headers, timeout):
        return self.responses.pop(0)


class VerticalSliceTests(unittest.TestCase):
    def test_sync_search_and_inspect_cache_flow(self) -> None:
        first_page = json.dumps(
            {
                "data": [
                    {
                        "id": "acme/skills/postgres",
                        "slug": "postgres",
                        "name": "Postgres Production",
                        "description": "production database safety",
                        "source": "acme/skills",
                        "installs": 3,
                        "sourceType": "github",
                    }
                ],
                "pagination": {"page": 0, "hasMore": False},
            }
        ).encode()
        detail = json.dumps(
            {
                "id": "acme/skills/postgres",
                "hash": "skill-hash",
                "files": [{"path": "SKILL.md", "contents": "# Production Postgres"}],
            }
        ).encode()
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            registry = Registry(home / "forge.db")
            registry.migrate()
            adapter = SkillsShAdapter(transport=FakeTransport([(200, {}, first_page), (200, {}, detail)]), token="test")

            stats = sync_metadata(registry, adapter)
            self.assertEqual(1, stats["inserted"])
            self.assertEqual(1, len(registry.search("postgres production")))
            registry.store_detail("acme/skills/postgres", adapter.fetch_skill("acme/skills/postgres"), snapshots_root=home / "snapshots")

            skill = registry.get_skill("acme/skills/postgres")
            self.assertEqual("skill-hash", skill["content_hash"])
            self.assertEqual("# Production Postgres", registry.get_files("acme/skills/postgres")[0]["contents"])

            recommendations = recommend_skills(
                registry,
                {"stack": ["supabase"], "domains": [], "languages": ["python"]},
            )
            self.assertTrue(recommendations)
            project = home / "sample-project"
            project.mkdir()
            pin_skill(
                project,
                skill_id="acme/skills/postgres",
                source="acme/skills",
                content_hash=str(skill["content_hash"]),
                reason="integration selection",
            )
            self.assertEqual("skill-hash", load_lockfile(project)["skills"][0]["hash"])
            registry.close()
