import json
import tempfile
import unittest
from pathlib import Path

from forge_core.models import SkillMetadata
from forge_project.lockfile import load_lockfile, pin_skill
from forge_project.recommend import recommend_skills
from forge_registry.database import Registry


class RecommendationAndLockfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.registry = Registry(self.root / "forge.db")
        self.registry.migrate()
        self.source_id = self.registry.ensure_source(
            name="skills-sh", source_type="skills_sh", base_url="https://skills.sh"
        )
        run_id = self.registry.start_sync_run(self.source_id)
        self.registry.upsert_metadata_page(
            self.source_id,
            [
                SkillMetadata(
                    id="acme/skills/supabase-safety",
                    slug="supabase-safety",
                    name="Supabase RLS and Postgres safety",
                    description="Supabase postgres RLS production safety",
                    source="acme/skills",
                ),
                SkillMetadata(
                    id="acme/skills/payment-idempotency",
                    slug="payment-idempotency",
                    name="Payment idempotency",
                    description="Payment security and idempotency practices",
                    source="acme/skills",
                ),
            ],
            next_page=None,
            run_id=run_id,
        )

    def tearDown(self) -> None:
        self.registry.close()
        self.temp_dir.cleanup()

    def test_recommendations_are_driven_by_project_evidence(self) -> None:
        recommendations = recommend_skills(
            self.registry,
            {"stack": ["supabase"], "domains": ["payments"], "languages": ["typescript"]},
        )

        self.assertEqual(
            ["acme/skills/supabase-safety", "acme/skills/payment-idempotency"],
            [recommendation.skill_id for recommendation in recommendations],
        )
        self.assertIn("Supabase", recommendations[0].reason)
        self.assertIn("payment-domain", recommendations[1].evidence[0])
        self.assertTrue(recommendations[0].risks)

    def test_pin_writes_explicit_hash_and_replaces_only_same_skill(self) -> None:
        project = self.root / "project"
        project.mkdir()
        output = pin_skill(
            project,
            skill_id="acme/skills/supabase-safety",
            source="acme/skills",
            content_hash="hash-v1",
            reason="RLS review",
        )
        pin_skill(
            project,
            skill_id="acme/skills/supabase-safety",
            source="acme/skills",
            content_hash="hash-v2",
            reason="Explicitly promoted after review",
        )

        lock = load_lockfile(project)
        self.assertEqual(project / ".forge" / "skills.lock", output)
        self.assertEqual(1, len(lock["skills"]))
        self.assertEqual("hash-v2", lock["skills"][0]["hash"])
        self.assertEqual("reference", lock["skills"][0]["mode"])
        self.assertEqual(lock, json.loads(output.read_text(encoding="utf-8")))

