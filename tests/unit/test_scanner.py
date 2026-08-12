import json
import tempfile
import unittest
from pathlib import Path

from forge_project.scanner import scan_project, select_representative_readme, write_project_context


class ScannerTests(unittest.TestCase):
    def test_legacy_collector_prefers_root_markdown_readme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.txt").write_text("Useful text fallback", encoding="utf-8")
            (root / "README.md").write_text("# Preferred documentation", encoding="utf-8")

            selected = select_representative_readme(root)

            self.assertEqual(root / "README.md", selected)

    def test_legacy_collector_skips_project_when_preferred_readme_is_stub(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("Placeholder", encoding="utf-8")
            (root / "README.txt").write_text("Useful fallback is not used by legacy collector", encoding="utf-8")

            self.assertIsNone(select_representative_readme(root))

    def test_scan_excludes_env_and_derives_safe_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "sample-quant"
            root.mkdir()
            (root / "README.md").write_text(
                "# Sample\nPython backtesting for Korean stock market data using CREON.", encoding="utf-8"
            )
            (root / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
            (root / ".env").write_text("PRODUCTION_SECRET=never-read", encoding="utf-8")
            docs = root / "docs"
            docs.mkdir()
            (docs / "architecture.md").write_text("Strategy plugin with validation kernel", encoding="utf-8")

            context = scan_project(root)
            output = write_project_context(context)

            self.assertIn("python", context["languages"])
            # `quant` clears the threshold: the project is named sample-quant and its README
            # describes market data. `backtesting` and `kr-equity` rest on a single README
            # sentence each, which schema 2 records as "mentioned" rather than promoting to a
            # project fact. The previous assertions encoded the behaviour that let a
            # documentation example become a declared domain.
            self.assertIn("quant", context["domains"])
            self.assertNotIn("backtesting", context["domains"])
            self.assertNotIn("kr-equity", context["domains"])
            self.assertIn("backtesting", context["mentioned"])
            self.assertIn("kr-equity", context["mentioned"])
            self.assertNotIn(".env", context["detectedDocuments"])
            self.assertNotIn("never-read", json.dumps(context))
            self.assertTrue(output.is_file())
            self.assertEqual(context["name"], json.loads(output.read_text(encoding="utf-8"))["name"])

    def test_secret_changes_do_not_change_scanner_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("# Safe project", encoding="utf-8")
            secret = root / ".env.local"
            secret.write_text("TOKEN=one", encoding="utf-8")

            first = scan_project(root)["sourceFingerprint"]
            secret.write_text("TOKEN=two", encoding="utf-8")
            second = scan_project(root)["sourceFingerprint"]

            self.assertEqual(first, second)

