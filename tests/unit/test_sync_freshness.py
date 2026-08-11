import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.models import SkillMetadata
from forge_registry.database import Registry
from forge_sources.skills_sh import SkillsShAdapter, sync_metadata


class FakeTransport:
    def __init__(self, body: bytes):
        self.body = body

    def get(self, url, headers, timeout):
        return 200, {}, self.body


class SyncFreshnessTests(unittest.TestCase):
    def test_progress_uses_pagination_total_and_status_keeps_last_sync(self) -> None:
        body = b'{"data":[{"id":"acme/skills/a","slug":"a","name":"A","source":"acme/skills"}],"pagination":{"page":0,"perPage":100,"total":161,"hasMore":false}}'
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = Registry(Path(temp_dir) / "forge.db")
            registry.migrate()
            progress = []
            stats = sync_metadata(
                registry,
                SkillsShAdapter(transport=FakeTransport(body), token="test"),
                on_progress=lambda *values: progress.append(values),
            )
            source = registry.source_status("skills-sh")

            self.assertEqual([(1, 2, 100, 161)], progress)
            self.assertEqual(1, stats["requests"])
            self.assertEqual(161, source["catalog_total"])
            self.assertIsNotNone(source["last_sync_at"])
            registry.close()

    def test_default_page_size_needs_twenty_pages_for_9610_skills(self) -> None:
        body = b'{"data":[],"pagination":{"page":0,"perPage":500,"total":9610,"hasMore":true}}'
        adapter = SkillsShAdapter(transport=FakeTransport(body), token="test")

        page = adapter.list_skills(page=0)

        self.assertEqual(500, page.per_page)
        self.assertEqual(9610, page.total)
        self.assertEqual(20, -(-page.total // page.per_page))

    def test_if_stale_skips_fresh_successful_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            registry = Registry(home / "forge.db")
            registry.migrate()
            source_id = registry.ensure_source(name="skills-sh", source_type="skills_sh", base_url="https://skills.sh")
            run_id = registry.start_sync_run(source_id)
            registry.upsert_metadata_page(
                source_id,
                [SkillMetadata(id="acme/skills/a", slug="a", name="A", source="acme/skills")],
                next_page=None,
                run_id=run_id,
            )
            registry.mark_source_synced(source_id)
            registry.finish_sync_run(run_id, request_count=1)
            registry.close()

            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(0, main(["--forge-home", str(home), "sync", "--metadata-only", "--if-stale", "6h"]))
                self.assertEqual(0, main(["--forge-home", str(home), "status"]))

            self.assertIn("Metadata sync skipped", output.getvalue())
            self.assertIn("last successful sync", output.getvalue())
