import tempfile
import unittest
from pathlib import Path

from forge_benchmark.fixtures import Scenario, build_fixture_registry, load_fixture
from forge_benchmark.metrics import (
    NOT_APPLICABLE_V2_1,
    NOT_MEASURED,
    aggregate,
    score_scenario,
)
from forge_benchmark.probes import RetrievalOnlyProvider, adversarial_probes
from forge_planner.policy import GateDecision, GateResult
from forge_planner.provider import Exclusion, PlanProposal, PlanRequest, SkillCandidate


ROLE_BY_SKILL = {
    "a/b/cro": "conversion",
    "a/b/design": "visual-design",
    "a/b/db": "database-performance",
    "a/b/copy": "copy",
}


def _scenario(**overrides) -> Scenario:
    base = dict(
        scenario_id="T01",
        kind="selection",
        goal="redesign the landing page",
        project_context={},
        required_roles=["conversion", "visual-design"],
        acceptable_roles=["copy"],
        irrelevant_roles=["database-performance"],
        forbidden_skills=[],
        risk_must_be=None,
        expect_exploration_budget_zero=False,
        expect_human_approval=False,
        expected_role_order=[],
        expect_policy_rejection_contains=None,
        note="",
    )
    base.update(overrides)
    return Scenario(**base)


def _gate(admitted: list[str], *, risk: str = "medium", budget: float = 0.15, approval=None) -> GateResult:
    return GateResult(
        admitted=[
            GateDecision(skill_id=skill_id, admitted=True, reason="because", role="general", content_hash="h")
            for skill_id in admitted
        ],
        rejected=[],
        hallucinated_ids=[],
        risk=risk,
        exploration_budget=budget,
        human_approval_required=approval or [],
    )


def _proposal(risk: str = "medium") -> PlanProposal:
    return PlanProposal(risk=risk, excluded=[Exclusion(skill_id="a/b/other", reason="not needed")])


class RetrievalCeilingTests(unittest.TestCase):
    def test_ceiling_separates_retrieval_failure_from_ranking_failure(self) -> None:
        # visual-design was never retrieved, so no reranker could have covered it.
        score = score_scenario(
            _scenario(),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro"]),
            role_by_skill=ROLE_BY_SKILL,
            candidate_ids=["a/b/cro", "a/b/copy"],
            admissible_skills={"a/b/cro", "a/b/copy"},
        )

        self.assertEqual(0.5, score.role_recall)
        self.assertEqual(0.5, score.retrieval_ceiling)
        self.assertEqual(0.0, score.ranking_gap)
        self.assertEqual(["visual-design"], score.unreachable_roles)
        self.assertIn("retrieval failure, not a ranking failure", score.failures[0])

    def test_ranking_gap_appears_when_the_candidate_was_available_but_unchosen(self) -> None:
        score = score_scenario(
            _scenario(),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro"]),
            role_by_skill=ROLE_BY_SKILL,
            candidate_ids=["a/b/cro", "a/b/design"],
            admissible_skills={"a/b/cro", "a/b/design"},
        )

        self.assertEqual(0.5, score.role_recall)
        self.assertEqual(1.0, score.retrieval_ceiling)
        self.assertEqual(0.5, score.ranking_gap)
        self.assertEqual([], score.unreachable_roles)
        self.assertNotIn("retrieval failure", score.failures[0])

    def test_uncached_skill_does_not_count_toward_the_ceiling(self) -> None:
        score = score_scenario(
            _scenario(required_roles=["visual-design"], acceptable_roles=[]),
            variant="A",
            proposal=_proposal(),
            gate=_gate([]),
            role_by_skill=ROLE_BY_SKILL,
            candidate_ids=["a/b/design"],
            admissible_skills=set(),
        )

        self.assertEqual(0.0, score.retrieval_ceiling)
        self.assertEqual(["visual-design"], score.unreachable_roles)


class GradedGroundTruthTests(unittest.TestCase):
    def test_irrelevant_selection_is_penalized_and_acceptable_is_not(self) -> None:
        score = score_scenario(
            _scenario(),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro", "a/b/design", "a/b/copy", "a/b/db"]),
            role_by_skill=ROLE_BY_SKILL,
            candidate_ids=["a/b/cro", "a/b/design", "a/b/copy", "a/b/db"],
            admissible_skills={"a/b/cro", "a/b/design", "a/b/copy", "a/b/db"},
        )

        self.assertEqual(1.0, score.role_recall)
        self.assertEqual(0.25, score.irrelevant_selection_rate)
        self.assertEqual(["a/b/db (database-performance)"], score.irrelevant_selected)

    def test_forbidden_skill_is_a_hard_failure(self) -> None:
        score = score_scenario(
            _scenario(forbidden_skills=["a/b/db"]),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro", "a/b/design", "a/b/db"]),
            role_by_skill=ROLE_BY_SKILL,
        )

        self.assertEqual(["a/b/db"], score.forbidden_selected)
        self.assertFalse(score.passed)

    def test_risk_is_scored_only_when_the_scenario_declares_it(self) -> None:
        unscored = score_scenario(
            _scenario(), variant="A", proposal=_proposal(), gate=_gate(["a/b/cro", "a/b/design"]),
            role_by_skill=ROLE_BY_SKILL,
        )
        failed = score_scenario(
            _scenario(risk_must_be="high"),
            variant="A",
            proposal=_proposal(risk="low"),
            gate=_gate(["a/b/cro", "a/b/design"], risk="medium"),
            role_by_skill=ROLE_BY_SKILL,
        )

        self.assertEqual(NOT_MEASURED, unscored.risk_gate)
        self.assertEqual("fail", failed.risk_gate)
        self.assertFalse(failed.passed)

    def test_exploration_is_reported_as_not_applicable_rather_than_faked(self) -> None:
        score = score_scenario(
            _scenario(), variant="A", proposal=_proposal(), gate=_gate(["a/b/cro", "a/b/design"]),
            role_by_skill=ROLE_BY_SKILL,
        )
        enforced = score_scenario(
            _scenario(expect_exploration_budget_zero=True),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro", "a/b/design"], risk="high", budget=0.0),
            role_by_skill=ROLE_BY_SKILL,
        )

        self.assertEqual(NOT_APPLICABLE_V2_1, score.exploration_safety)
        self.assertEqual("pass", enforced.exploration_safety)

    def test_role_order_is_unjudged_when_the_roles_are_not_both_present(self) -> None:
        partial = score_scenario(
            _scenario(required_roles=["conversion"], expected_role_order=["positioning", "copy"]),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro"]),
            role_by_skill=ROLE_BY_SKILL,
        )
        self.assertIsNone(partial.role_order_respected)

    def test_policy_scenario_warns_about_silent_substitution(self) -> None:
        score = score_scenario(
            _scenario(kind="policy", required_roles=["database-performance"], irrelevant_roles=[]),
            variant="A",
            proposal=_proposal(),
            gate=_gate(["a/b/cro"]),
            role_by_skill=ROLE_BY_SKILL,
        )

        self.assertIsNone(score.role_recall)
        self.assertEqual(["conversion"], score.substituted_roles)
        self.assertTrue(score.warnings)
        self.assertTrue(score.passed, "substitution is a warning, not a scored failure")


class AggregateTests(unittest.TestCase):
    def test_policy_scenarios_are_excluded_from_quality_averages(self) -> None:
        good = score_scenario(
            _scenario(), variant="A", proposal=_proposal(), gate=_gate(["a/b/cro", "a/b/design"]),
            role_by_skill=ROLE_BY_SKILL,
        )
        policy = score_scenario(
            _scenario(kind="policy"), variant="A", proposal=_proposal(), gate=_gate([]),
            role_by_skill=ROLE_BY_SKILL,
        )

        summary = aggregate([good, policy])["A"]
        self.assertEqual(2, summary["scenarios"])
        self.assertEqual(1, summary["selectionScenarios"])
        self.assertEqual(1.0, summary["meanRoleRecall"])


class FixtureTests(unittest.TestCase):
    def test_shipped_fixture_loads_and_validates(self) -> None:
        fixture = load_fixture()
        self.assertGreaterEqual(len(fixture.scenarios), 8)
        self.assertGreaterEqual(len(fixture.catalog), 12)
        self.assertTrue(any(not skill.cached for skill in fixture.catalog))
        self.assertTrue(any(skill.force_version_state for skill in fixture.catalog))

    def test_fixture_registry_is_isolated_and_reproduces_declared_hashes(self) -> None:
        fixture = load_fixture()
        with tempfile.TemporaryDirectory() as temp_dir:
            registry = build_fixture_registry(fixture, home=Path(temp_dir))
            try:
                cached = next(skill for skill in fixture.catalog if skill.cached and not skill.force_version_state)
                uncached = next(skill for skill in fixture.catalog if not skill.cached)
                blocked = next(skill for skill in fixture.catalog if skill.force_version_state)
                self.assertEqual(cached.content_hash, registry.get_skill(cached.skill_id)["content_hash"])
                self.assertIsNone(registry.get_skill(uncached.skill_id)["latest_seen_version_id"])
                self.assertEqual("fail", registry.get_skill(blocked.skill_id)["security_status"])
            finally:
                registry.close()


class ProbeShapeTests(unittest.TestCase):
    def test_every_probe_declares_an_invariant_and_an_expectation(self) -> None:
        probes = adversarial_probes()
        self.assertGreaterEqual(len(probes), 5)
        for probe in probes:
            self.assertTrue(probe.invariant.strip(), probe.probe_id)
            self.assertTrue(probe.proposal.selected, probe.probe_id)

    def test_retrieval_only_baseline_preserves_retrieval_order(self) -> None:
        candidates = [SkillCandidate(f"a/b/{i}", f"S{i}", "a/b", "d") for i in range(10)]
        proposal = RetrievalOnlyProvider(depth=3).propose(
            PlanRequest(goal="g", project_context={}, candidates=candidates)
        )

        self.assertEqual(["a/b/0", "a/b/1", "a/b/2"], [p.skill_id for p in proposal.selected])
        self.assertEqual(7, len(proposal.excluded))
        self.assertTrue(all(p.confidence == 0.0 for p in proposal.selected))


if __name__ == "__main__":
    unittest.main()
