import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from forge.cli import main
from forge_benchmark.runner import run_benchmark
from forge_planner.provider import ProviderError, StubProvider


class BenchmarkCliTests(unittest.TestCase):
    def test_benchmark_writes_both_artifacts_and_reports_probe_results(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "artifacts" / "planner-benchmark"
            printed = io.StringIO()
            with redirect_stdout(printed):
                exit_code = main(["benchmark", "--output", str(output)])

            self.assertEqual(0, exit_code, "all policy probes are expected to pass")
            text = printed.getvalue()
            self.assertIn("A-retrieval-only", text)
            self.assertIn("B-stub-lexical", text)
            self.assertIn("skipped_external_provider", text)
            self.assertIn("Policy probes:", text)

            summary = json.loads((output / "benchmark-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(1, summary["schemaVersion"])
            self.assertTrue(summary["policyProbes"]["allPassed"])
            self.assertEqual(
                "blocked_external_fixture", summary["fixture"]["oracrossArtifactImport"]["status"]
            )
            self.assertTrue(summary["unprovenClaims"])
            for variant in ("A-retrieval-only", "B-stub-lexical"):
                self.assertTrue(summary["determinism"][variant]["reproducible"])

            report = (output / "benchmark-report.md").read_text(encoding="utf-8")
            self.assertIn("# Forge planner benchmark", report)
            self.assertIn("Retrieval ceiling", report)
            self.assertIn("Claims this benchmark does not support", report)

    def test_missing_external_provider_is_recorded_not_silently_ignored(self) -> None:
        run = run_benchmark(external_provider=None, external_provider_skip_reason="no API key configured")

        self.assertIn("skipped_external_provider", run.variants["C-llm-provider"])
        self.assertIn("no API key configured", run.variants["C-llm-provider"])
        self.assertNotIn("C-llm-provider", {score.variant for score in run.scores})

    def test_benchmark_never_touches_the_user_registry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir) / "home"
            home.mkdir()
            output = Path(temp_dir) / "out"
            with redirect_stdout(io.StringIO()):
                main(["--forge-home", str(home), "benchmark", "--output", str(output)])

            self.assertFalse((home / "forge.db").exists(), "the benchmark must use an isolated registry")

    def test_every_policy_probe_holds(self) -> None:
        run = run_benchmark()

        failed = [probe.probe_id for probe in run.probes if not probe.passed]
        self.assertEqual([], failed, f"ADR-006 invariants regressed: {failed}")

    def test_a_failing_external_provider_does_not_destroy_the_offline_results(self) -> None:
        class FailingProvider:
            name = "exploding"

            def __init__(self) -> None:
                self.calls = 0

            def propose(self, request):
                self.calls += 1
                if self.calls > 2:
                    raise ProviderError("simulated rate limit")
                return StubProvider().propose(request)

        run = run_benchmark(external_provider=FailingProvider())

        self.assertIn("external_provider_failed", run.variants["C-llm-provider"])
        self.assertIn("simulated rate limit", run.variants["C-llm-provider"])
        self.assertNotIn("C-llm-provider", {score.variant for score in run.scores})
        # A and B must survive intact.
        self.assertEqual(
            {"A-retrieval-only", "B-stub-lexical"}, {score.variant for score in run.scores}
        )
        self.assertTrue(run.probes_passed)

    def test_bad_fixture_path_fails_loudly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(
                    2, main(["benchmark", "--fixtures", str(Path(temp_dir) / "nope"), "--output", temp_dir])
                )


if __name__ == "__main__":
    unittest.main()
