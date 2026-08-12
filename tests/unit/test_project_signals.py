"""F7 regression tests: a project's documentation is not a description of its dependencies.

Forge found this by scanning itself. Documentation examples and benchmark fixtures promoted
supabase, quant, and payments into the declared stack, which then spent three of eight planner
retrieval queries on domains the project does not have.
"""

import json
import tempfile
import unittest
from pathlib import Path

from forge_planner.service import derive_queries
from forge_project.scanner import scan_project
from forge_project.signals import contributes_signal


def _project(root: Path, files: dict[str, str]) -> None:
    for relative, contents in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")


class MentionsAreNotUsesTests(unittest.TestCase):
    def test_a_documentation_mention_does_not_enter_the_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "docs-only"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Docs only\nA Python CLI.\n",
                    "pyproject.toml": "[project]\nname='docs-only'\n",
                    "docs/design.md": "We considered Supabase and rejected it. Stripe was also discussed.",
                },
            )

            context = scan_project(root)

            self.assertNotIn("supabase", context["stack"])
            self.assertNotIn("payments", context["domains"])
            self.assertIn("supabase", context["mentioned"])
            self.assertIn("payments", context["mentioned"])

    def test_benchmark_fixtures_and_artifacts_contribute_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "fixture-heavy"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Fixture heavy\nA Python project.\n",
                    "pyproject.toml": "[project]\nname='fixture-heavy'\n",
                    "docs/notes.md": "Nothing notable here.",
                    "tests/fixtures/catalog.json": json.dumps(
                        {"skills": [{"role": "payments", "description": "stripe payment idempotency"}]}
                    ),
                    "artifacts/report.md": "quant backtesting supabase saas subscription",
                },
            )

            context = scan_project(root)

            for contaminant in ("payments", "quant", "saas", "supabase"):
                self.assertNotIn(contaminant, context["domains"], contaminant)
                self.assertNotIn(contaminant, context["stack"], contaminant)
            self.assertEqual([], context["mentioned"], "excluded paths must not even register a mention")

    def test_excluded_prefixes_are_path_scoped_not_substring_matched(self) -> None:
        self.assertFalse(contributes_signal("tests/fixtures/catalog.json"))
        self.assertFalse(contributes_signal("artifacts/planner-benchmark/summary.json"))
        self.assertFalse(contributes_signal(".forge/history/oracross/report.md"))
        self.assertTrue(contributes_signal("tests/unit/test_scanner.py"))
        self.assertTrue(contributes_signal("docs/artifacts-explained.md"))
        self.assertTrue(contributes_signal("src/examples_of_use.py"))


class StrongEvidencePromotesTests(unittest.TestCase):
    def test_a_manifest_dependency_enters_the_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "web-app"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Web app\n",
                    "package.json": json.dumps(
                        {"dependencies": {"next": "15.0.0", "react": "19.0.0", "@supabase/supabase-js": "2.0.0"}}
                    ),
                },
            )

            context = scan_project(root)

            self.assertIn("nextjs", context["stack"])
            self.assertIn("react", context["stack"])
            self.assertIn("supabase", context["stack"])

    def test_an_actual_import_enters_the_stack(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "api"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# API\n",
                    "pyproject.toml": "[project]\nname='api'\n",
                    "src/main.py": "from fastapi import FastAPI\nimport stripe\n\napp = FastAPI()\n",
                },
            )

            context = scan_project(root)

            self.assertIn("fastapi", context["stack"])
            self.assertIn("payments", context["domains"])

    def test_evidence_accumulates_across_kinds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "combined"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Combined\nBuilt with FastAPI.\n",
                    "pyproject.toml": "[project]\nname='combined'\ndependencies=['fastapi>=0.1']\n",
                    "src/app.py": "from fastapi import FastAPI\n",
                },
            )

            context = scan_project(root)
            fastapi = next(s for s in context["signals"] if s["technology"] == "fastapi")

            self.assertEqual("used", fastapi["classification"])
            self.assertGreaterEqual(fastapi["confidence"], 0.9)
            # The manifest and the import are the evidence that matters; the README mention
            # only adds to an already-strong signal.
            self.assertIn("manifest", fastapi["evidenceKinds"])
            self.assertIn("import", fastapi["evidenceKinds"])
            self.assertIn("readme", fastapi["evidenceKinds"])

    def test_signals_record_their_sources_for_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "traceable"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Traceable\n",
                    "pyproject.toml": "[project]\nname='traceable'\n",
                    "docs/adr.md": "Supabase was evaluated.",
                },
            )

            context = scan_project(root)
            supabase = next(s for s in context["signals"] if s["technology"] == "supabase")

            self.assertEqual("mentioned", supabase["classification"])
            self.assertEqual(["docs/adr.md"], supabase["sources"])
            self.assertEqual(["prose"], supabase["evidenceKinds"])


class QueryExpansionTests(unittest.TestCase):
    def test_only_used_technologies_expand_a_retrieval_query(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "mixed"
            root.mkdir()
            _project(
                root,
                {
                    "README.md": "# Mixed\n",
                    "package.json": json.dumps({"dependencies": {"react": "19.0.0"}}),
                    "docs/history.md": "We once used Supabase and Stripe and did some quant work.",
                },
            )

            context = scan_project(root)
            queries = derive_queries("improve the checkout page", context)

            self.assertIn("react", queries)
            for contaminant in ("supabase", "payments", "quant"):
                self.assertNotIn(contaminant, queries, contaminant)


if __name__ == "__main__":
    unittest.main()
