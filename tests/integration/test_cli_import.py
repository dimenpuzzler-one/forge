import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from forge.cli import main


class ImportCliTests(unittest.TestCase):
    def test_import_makes_the_offline_workflow_usable_without_a_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "home"
            skills = root / "skills"
            (skills / "postgres-review").mkdir(parents=True)
            (skills / "postgres-review" / "SKILL.md").write_text(
                "---\nname: postgres-review\ndescription: Review postgres migrations for production.\n"
                "license: MIT\n---\n# Postgres review\n",
                encoding="utf-8",
            )
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("# App", encoding="utf-8")

            output = io.StringIO()
            # Any network access during this workflow is a defect.
            with mock.patch("forge_sources.skills_sh.UrllibTransport.get", side_effect=AssertionError("network")):
                with redirect_stdout(output):
                    self.assertEqual(0, main(["--forge-home", str(home), "import", str(skills), "--label", "team"]))
                    self.assertEqual(0, main(["--forge-home", str(home), "search", "postgres"]))
                    self.assertEqual(0, main(["--forge-home", str(home), "inspect", "local/team/postgres-review"]))
                    self.assertEqual(0, main(["--forge-home", str(home), "audit-skill", "local/team/postgres-review"]))
                    self.assertEqual(
                        0,
                        main(
                            [
                                "--forge-home",
                                str(home),
                                "plan",
                                "review postgres migrations",
                                "--project",
                                str(project),
                                "--fetch-missing",
                            ]
                        ),
                    )
                    self.assertEqual(
                        0,
                        main(
                            [
                                "--forge-home",
                                str(home),
                                "pin",
                                "local/team/postgres-review",
                                "--project",
                                str(project),
                            ]
                        ),
                    )
                    self.assertEqual(0, main(["--forge-home", str(home), "status"]))

            text = output.getvalue()
            self.assertIn("[new] local/team/postgres-review", text)
            self.assertIn("License: MIT", text)
            self.assertIn("Locally imported Skills have no upstream audit", text)
            self.assertIn("admitted=1", text)
            self.assertIn("local:team: 1 Skills", text)
            self.assertIn("local/team/postgres-review", (project / ".forge" / "skills.lock").read_text(encoding="utf-8"))

    def test_refresh_of_a_local_skill_points_back_to_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "skills" / "a").mkdir(parents=True)
            (root / "skills" / "a" / "SKILL.md").write_text("---\nname: a\n---\n", encoding="utf-8")
            home = root / "home"
            with redirect_stdout(io.StringIO()):
                main(["--forge-home", str(home), "import", str(root / "skills"), "--label", "t"])
            errors = io.StringIO()
            with redirect_stderr(errors):
                self.assertEqual(2, main(["--forge-home", str(home), "inspect", "local/t/a", "--refresh"]))
            self.assertIn("re-running `forge import", errors.getvalue())

    def test_bundled_plugin_skills_import_cleanly(self) -> None:
        repository = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temp_dir:
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    0,
                    main(
                        [
                            "--forge-home",
                            temp_dir,
                            "import",
                            str(repository / "plugins" / "forge-skills" / "skills"),
                            "--label",
                            "forge",
                        ]
                    ),
                )
            text = output.getvalue()
            self.assertIn("local/forge/forge", text)
            self.assertIn("local/forge/skill-audit", text)
            self.assertIn("rejected=0", text)


if __name__ == "__main__":
    unittest.main()
