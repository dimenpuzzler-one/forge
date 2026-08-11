import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_core.auth import resolve_skills_sh_auth


class AuthResolutionTests(unittest.TestCase):
    def test_process_environment_has_priority(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            home.mkdir()
            (home / "credentials.env").write_text("VERCEL_OIDC_TOKEN=forge-token\n", encoding="utf-8")

            auth = resolve_skills_sh_auth(home=home, environ={"VERCEL_OIDC_TOKEN": "process-token"}, install_root=Path(temp_dir))

            self.assertEqual("process-token", auth.token)
            self.assertEqual("process-env", auth.source)

    def test_forge_credentials_ignore_target_project_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "forge-home"
            home.mkdir()
            (home / "credentials.env").write_text("VERCEL_OIDC_TOKEN=forge-token\n", encoding="utf-8")
            project = root / "target-project"
            project.mkdir()
            (project / ".env").write_text("VERCEL_OIDC_TOKEN=project-token\n", encoding="utf-8")

            previous = Path.cwd()
            try:
                os.chdir(project)
                auth = resolve_skills_sh_auth(home=home, environ={}, install_root=root / "not-forge")
            finally:
                os.chdir(previous)

            self.assertEqual("forge-token", auth.token)
            self.assertEqual("forge-local-env", auth.source)

    def test_doctor_reports_source_without_printing_token(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            home.mkdir()
            (home / "credentials.env").write_text("VERCEL_OIDC_TOKEN=do-not-print\n", encoding="utf-8")
            output = io.StringIO()

            with redirect_stdout(output):
                self.assertEqual(0, main(["--forge-home", str(home), "doctor"]))

            self.assertIn("skills.sh auth: available", output.getvalue())
            self.assertIn("auth source: forge-local-env", output.getvalue())
            self.assertNotIn("do-not-print", output.getvalue())
