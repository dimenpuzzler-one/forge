from __future__ import annotations

import json
import platform
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from forge_benchmark.fixtures import BenchmarkFixture, build_fixture_registry, load_fixture
from forge_benchmark.metrics import (
    SKIPPED_EXTERNAL_PROVIDER,
    ScenarioScore,
    aggregate,
    score_scenario,
)
from forge_benchmark.probes import RetrievalOnlyProvider, adversarial_probes
from forge_planner.policy import apply_policy_gate
from forge_planner.provider import PlanProvider, ProviderError, StubProvider  # noqa: F401
from forge_planner.service import create_plan

BENCHMARK_SCHEMA_VERSION = 1
TARGET_RUNTIME = "3.12"
PROVIDER_FAILED = "external_provider_failed"


@dataclass
class ProbeResult:
    probe_id: str
    description: str
    invariant: str
    passed: bool
    observed_admitted: list[str]
    observed_rejected: list[str]
    observed_hallucinated: list[str]
    observed_risk: str
    mismatches: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "probeId": self.probe_id,
            "description": self.description,
            "invariant": self.invariant,
            "passed": self.passed,
            "observedAdmitted": self.observed_admitted,
            "observedRejected": self.observed_rejected,
            "observedHallucinated": self.observed_hallucinated,
            "observedRisk": self.observed_risk,
            "mismatches": self.mismatches,
        }


@dataclass
class BenchmarkRun:
    scores: list[ScenarioScore]
    probes: list[ProbeResult]
    determinism: dict[str, Any]
    variants: dict[str, str]
    fixture: BenchmarkFixture
    runtime: dict[str, Any]

    @property
    def probes_passed(self) -> bool:
        return all(probe.passed for probe in self.probes)


def run_benchmark(
    *,
    fixture_root: Path | None = None,
    external_provider: PlanProvider | None = None,
    external_provider_skip_reason: str | None = None,
) -> BenchmarkRun:
    """Run every variant over every scenario in an isolated fixture registry."""
    fixture = load_fixture(fixture_root)
    role_by_skill = fixture.role_by_skill

    variants: dict[str, PlanProvider] = {
        "A-retrieval-only": RetrievalOnlyProvider(),
        "B-stub-lexical": StubProvider(),
    }
    variant_status = {
        "A-retrieval-only": "ran",
        "B-stub-lexical": "ran",
        "C-llm-provider": "ran" if external_provider is not None else SKIPPED_EXTERNAL_PROVIDER,
    }
    if external_provider is not None:
        variants["C-llm-provider"] = external_provider
    elif external_provider_skip_reason:
        variant_status["C-llm-provider"] = f"{SKIPPED_EXTERNAL_PROVIDER}: {external_provider_skip_reason}"

    scores: list[ScenarioScore] = []
    probes: list[ProbeResult] = []
    determinism: dict[str, Any] = {}

    with tempfile.TemporaryDirectory(prefix="forge-benchmark-") as workdir:
        home = Path(workdir)
        registry = build_fixture_registry(fixture, home=home)
        admissible = {skill.skill_id for skill in fixture.catalog if skill.cached and not skill.force_version_state}
        try:
            for variant_name, provider in variants.items():
                variant_scores: list[ScenarioScore] = []
                try:
                    for scenario in fixture.scenarios:
                        result = create_plan(
                            registry,
                            provider,
                            goal=scenario.goal,
                            project_context=scenario.project_context,
                            plans_root=home / "plans" / variant_name,
                        )
                        variant_scores.append(
                            score_scenario(
                                scenario,
                                variant=variant_name,
                                proposal=result.proposal,
                                gate=result.gate,
                                role_by_skill=role_by_skill,
                                candidate_ids=result.candidate_ids,
                                admissible_skills=admissible,
                            )
                        )
                except ProviderError as error:
                    # A network provider failing partway must not destroy the offline results.
                    # The variant is dropped whole, because a partial run is not comparable.
                    variant_status[variant_name] = (
                        f"{PROVIDER_FAILED}: after {len(variant_scores)} of "
                        f"{len(fixture.scenarios)} scenarios: {error}"
                    )
                    continue
                scores.extend(variant_scores)

            determinism = _check_determinism(registry, fixture, home)
            probes = _run_probes(registry)
        finally:
            registry.close()

    return BenchmarkRun(
        scores=scores,
        probes=probes,
        determinism=determinism,
        variants=variant_status,
        fixture=fixture,
        runtime=_runtime_facts(),
    )


def _check_determinism(registry: Any, fixture: BenchmarkFixture, home: Path) -> dict[str, Any]:
    """Re-run the deterministic variants and compare admitted selections exactly."""
    report: dict[str, Any] = {}
    for variant_name, provider in (
        ("A-retrieval-only", RetrievalOnlyProvider()),
        ("B-stub-lexical", StubProvider()),
    ):
        divergences: list[str] = []
        for scenario in fixture.scenarios:
            runs = []
            for attempt in range(2):
                result = create_plan(
                    registry,
                    provider,
                    goal=scenario.goal,
                    project_context=scenario.project_context,
                    plans_root=home / "determinism" / variant_name / str(attempt),
                )
                runs.append([decision.skill_id for decision in result.gate.admitted])
            if runs[0] != runs[1]:
                divergences.append(scenario.scenario_id)
        report[variant_name] = {
            "reproducible": not divergences,
            "divergentScenarios": divergences,
        }
    return report


def _run_probes(registry: Any) -> list[ProbeResult]:
    results: list[ProbeResult] = []
    for probe in adversarial_probes():
        gate = apply_policy_gate(
            registry,
            probe.proposal,
            candidate_ids=set(probe.candidate_ids),
            goal=probe.goal,
        )
        admitted = sorted({decision.skill_id for decision in gate.admitted})
        rejected = sorted({decision.skill_id for decision in gate.rejected})
        hallucinated = sorted(set(gate.hallucinated_ids))
        mismatches: list[str] = []
        if admitted != sorted(set(probe.expect_admitted)):
            mismatches.append(f"admitted {admitted}, expected {sorted(set(probe.expect_admitted))}")
        if rejected != sorted(set(probe.expect_rejected)):
            mismatches.append(f"rejected {rejected}, expected {sorted(set(probe.expect_rejected))}")
        if hallucinated != sorted(set(probe.expect_hallucinated)):
            mismatches.append(
                f"flagged as invented {hallucinated}, expected {sorted(set(probe.expect_hallucinated))}"
            )
        if probe.expect_risk and gate.risk != probe.expect_risk:
            mismatches.append(f"effective risk {gate.risk}, expected {probe.expect_risk}")
        results.append(
            ProbeResult(
                probe_id=probe.probe_id,
                description=probe.description,
                invariant=probe.invariant,
                passed=not mismatches,
                observed_admitted=admitted,
                observed_rejected=rejected,
                observed_hallucinated=hallucinated,
                observed_risk=gate.risk,
                mismatches=mismatches,
            )
        )
    return results


def _runtime_facts() -> dict[str, Any]:
    running = f"{sys.version_info.major}.{sys.version_info.minor}"
    shimmed = running != TARGET_RUNTIME
    return {
        "sandboxRuntime": f"Python {platform.python_version()}"
        + (" + temporary compatibility shim" if shimmed else ""),
        "targetRuntime": f"Python {TARGET_RUNTIME}",
        "local312VerificationRequired": shimmed,
        "note": (
            "This run did not execute on the repository's target interpreter. Treat the results as "
            "indicative and re-run on Python 3.12 before relying on them."
            if shimmed
            else "This run executed on the repository's target interpreter."
        ),
    }


def build_summary(run: BenchmarkRun) -> dict[str, Any]:
    aggregates = aggregate(run.scores)
    for variant, values in aggregates.items():
        values["totalHallucinationsAdmitted"] = sum(
            len(set(score.hallucinated_ids) & set(score.admitted_skill_ids))
            for score in run.scores
            if score.variant == variant
        )
    return {
        "schemaVersion": BENCHMARK_SCHEMA_VERSION,
        "generatedAt": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "milestone": "Vol.2 V2.1 planner foundation",
        "runtime": run.runtime,
        "fixture": {
            "catalogSize": len(run.fixture.catalog),
            "scenarioCount": len(run.fixture.scenarios),
            "roleVocabulary": run.fixture.role_vocabulary,
            "provenance": run.fixture.provenance,
            "oracrossArtifactImport": {
                "status": "blocked_external_fixture",
                "detail": (
                    "The ORACROSS report artifacts referenced in vol2.md Appendix A live outside this "
                    "workspace and were never read. Scenario design used only the narrative in the Vol.2 "
                    "document. No synthetic file was presented as an ORACROSS artifact."
                ),
            },
        },
        "variants": run.variants,
        "aggregates": aggregates,
        "determinism": run.determinism,
        "policyProbes": {
            "total": len(run.probes),
            "passed": sum(1 for probe in run.probes if probe.passed),
            "allPassed": run.probes_passed,
            "results": [probe.as_dict() for probe in run.probes],
        },
        "scenarioScores": [score.as_dict() for score in run.scores],
        "unprovenClaims": [
            "Whether LLM reranking beats retrieval-only on real Skills is unmeasured; variant C requires an API key.",
            "Whether a Forge plan improves final implementation quality versus a plain prompt is unmeasured; that needs agent execution, which V2.1 does not perform.",
            "Whether historical evidence improves recommendation is unmeasured; V2.2 owns it.",
            "Whether adaptive exploration finds good new Skills is unmeasured; V2.2 owns it.",
            "Fixture retrieval difficulty is authored, not sampled from the live 9,610-entry catalog.",
        ],
    }


def write_artifacts(run: BenchmarkRun, *, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(run)
    summary_path = output_dir / "benchmark-summary.json"
    report_path = output_dir / "benchmark-report.md"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.write_text(render_report(run, summary), encoding="utf-8")
    return summary_path, report_path


def render_report(run: BenchmarkRun, summary: dict[str, Any]) -> str:
    lines = [
        "# Forge planner benchmark",
        "",
        f"Generated: {summary['generatedAt']}",
        f"Milestone: {summary['milestone']}",
        "",
        "This benchmark measures the V2.1 planner against an authored fixture catalog. It does not",
        "measure whether Forge improves a final implementation; that requires agent execution and is",
        "explicitly out of scope for V2.1.",
        "",
        "## Runtime",
        "",
        f"- Sandbox runtime: {run.runtime['sandboxRuntime']}",
        f"- Target runtime: {run.runtime['targetRuntime']}",
        f"- Local 3.12 verification required: {str(run.runtime['local312VerificationRequired']).lower()}",
        f"- {run.runtime['note']}",
        "",
        "## Fixture",
        "",
        f"- Catalog: {summary['fixture']['catalogSize']} synthetic Skills",
        f"- Scenarios: {summary['fixture']['scenarioCount']}",
        f"- ORACROSS artifact import: `{summary['fixture']['oracrossArtifactImport']['status']}`",
        "",
        summary["fixture"]["oracrossArtifactImport"]["detail"],
        "",
        "## Variants",
        "",
        "| Variant | Status | What it isolates |",
        "| --- | --- | --- |",
        "| A-retrieval-only | "
        + run.variants["A-retrieval-only"]
        + " | Raw FTS order, no model. The floor. |",
        "| B-stub-lexical | "
        + run.variants["B-stub-lexical"]
        + " | Lexical overlap rerank over the same candidates. |",
        "| C-llm-provider | "
        + run.variants["C-llm-provider"].replace("|", "\\|")
        + " | Semantic rerank over the same candidates. |",
        "",
        "Every variant runs through the identical retrieval and the identical policy gate, so any",
        "difference is attributable to ranking alone.",
        "",
        "## Aggregate metrics",
        "",
        "| Variant | Scenarios | Passed | Role recall | Retrieval ceiling | Ranking gap | Irrelevant rate | Mean admitted | Explanations | Risk gate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for variant, values in summary["aggregates"].items():
        lines.append(
            f"| {variant} | {values['scenarios']} | {values['passed']} | "
            f"{_fmt(values['meanRoleRecall'])} | {_fmt(values['meanRetrievalCeiling'])} | "
            f"{_fmt(values['meanRankingGap'])} | {_fmt(values['meanIrrelevantSelectionRate'])} | "
            f"{_fmt(values['meanAdmittedCount'])} | {_fmt(values['meanExplanationCoverage'])} | "
            f"{_fmt(values['riskGatePassRate'])} |"
        )
    lines += [
        "",
        "**Role recall** counts required roles covered. **Retrieval ceiling** is the best recall any",
        "reranker could have reached given what retrieval actually returned. **Ranking gap** is",
        "ceiling minus recall — it is the part of the shortfall a better reranker could fix. A recall",
        "below the ceiling is a ranking problem; a ceiling below 1.00 is a retrieval problem that no",
        "provider, however good, can repair. **Irrelevant rate** is the share of admitted Skills whose",
        "role the scenario marks as wrong for the goal; lower is better.",
        "",
        "## Policy probes",
        "",
        f"{summary['policyProbes']['passed']} of {summary['policyProbes']['total']} adversarial probes passed.",
        "",
        "| Probe | Invariant | Result |",
        "| --- | --- | --- |",
    ]
    for probe in run.probes:
        lines.append(
            f"| `{probe.probe_id}` | {probe.invariant} | {'PASS' if probe.passed else 'FAIL — ' + '; '.join(probe.mismatches)} |"
        )
    lines += ["", "## Determinism", ""]
    for variant, values in run.determinism.items():
        state = "reproducible" if values["reproducible"] else f"DIVERGED on {values['divergentScenarios']}"
        lines.append(f"- `{variant}`: {state} across two consecutive runs on identical input.")
    lines += ["", "## Per-scenario results", ""]
    for variant in summary["aggregates"]:
        lines += [
            f"### {variant}",
            "",
            "| Scenario | Kind | Recall | Ceiling | Irrelevant | Admitted | Verdict |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
        for score in run.scores:
            if score.variant != variant:
                continue
            verdict = "pass" if score.passed else "; ".join(score.failures)
            lines.append(
                f"| {score.scenario_id} | {score.kind} | {_fmt(score.role_recall)} | "
                f"{_fmt(score.retrieval_ceiling)} | {_fmt(score.irrelevant_selection_rate)} | "
                f"{len(score.admitted_skill_ids)} | {verdict} |"
            )
        warned = [score for score in run.scores if score.variant == variant and score.warnings]
        if warned:
            lines += ["", "Warnings (not scored as failures):", ""]
            for score in warned:
                for warning in score.warnings:
                    lines.append(f"- `{score.scenario_id}`: {warning}")
        lines.append("")
    lines += ["## Claims this benchmark does not support", ""]
    lines += [f"- {claim}" for claim in summary["unprovenClaims"]]
    lines += [
        "",
        "---",
        "",
        "Forge's current state is a policy-bounded planner foundation. The gate results below are",
        "evidence. The selection quality numbers are measurements against an authored fixture, not",
        "proof that Forge produces better software.",
        "",
    ]
    return "\n".join(lines)


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def resolve_external_provider(name: str | None, model: str | None) -> tuple[PlanProvider | None, str | None]:
    """Return variant C's provider, or a recorded reason for skipping it."""
    if not name:
        return None, "no external provider requested"
    from forge_planner.provider import resolve_provider

    try:
        return resolve_provider(name, model=model), None
    except ProviderError as error:
        return None, str(error)
