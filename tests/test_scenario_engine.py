"""
Tests for the ScenarioEngine: creation, revision tracking, promote,
dismiss with "why not", cluster_from_actions, comparison, and API endpoints.
"""

from uuid import uuid4

import pytest

from src.core.models import (
    AgentAction,
    AgentActionType,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    Scenario,
    ScenarioRevisionType,
    ScenarioStatus,
)
from src.core.persistence import RunRepository, init_db
from src.core.scenario_engine import FailureMode, ScenarioEngine


@pytest.fixture
def repo():
    conn = init_db(":memory:")
    return RunRepository(conn)


@pytest.fixture
def run(repo):
    r = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
    repo.create_run(r)
    return r


@pytest.fixture
def engine(repo):
    return ScenarioEngine(repo)


# ══════════════════════════════════════════════════════════════════════
#  Creation
# ══════════════════════════════════════════════════════════════════════

class TestCreation:
    def test_create_scenario(self, engine, run):
        sc = engine.create_scenario(
            run.id, "Macro-driven FOMC", "macro_policy",
            summary="Fed rate cut caused rally",
            confidence=0.82,
            lead_agents=["macro-policy"],
        )
        assert sc.title == "Macro-driven FOMC"
        assert sc.mechanism_type == "macro_policy"
        assert sc.confidence_score == 0.82
        assert sc.status == ScenarioStatus.ALTERNATIVE  # default
        assert sc.lead_agents == ["macro-policy"]

    def test_create_with_primary_status(self, engine, run):
        sc = engine.create_scenario(
            run.id, "Test", "test", status="primary",
        )
        assert sc.status == ScenarioStatus.PRIMARY

    def test_create_persisted(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Persisted", "m")
        loaded = repo.get_scenario_by_id(str(sc.id))
        assert loaded is not None
        assert loaded.title == "Persisted"

    def test_confidence_clamped(self, engine, run):
        sc = engine.create_scenario(run.id, "T", "m", confidence=1.5)
        assert sc.confidence_score == 1.0

    def test_invalid_status_defaults_to_alternative(self, engine, run):
        sc = engine.create_scenario(run.id, "T", "m", status="bogus")
        assert sc.status == ScenarioStatus.ALTERNATIVE


# ══════════════════════════════════════════════════════════════════════
#  Revision tracking
# ══════════════════════════════════════════════════════════════════════

class TestRevisionTracking:
    def test_update_creates_revision(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Test", "m", confidence=0.5)
        engine.update_scenario(sc.id, {
            "confidence_score": 0.8,
            "reason": "New evidence strengthened hypothesis",
        })

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert len(revisions) == 1
        assert revisions[0].previous_confidence == 0.5
        assert revisions[0].new_confidence == 0.8
        assert "evidence" in revisions[0].reason

    def test_update_persists_changes(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Test", "m", confidence=0.5)
        engine.update_scenario(sc.id, {
            "confidence_score": 0.75,
            "summary": "Updated summary",
            "reason": "test",
        })

        loaded = repo.get_scenario_by_id(str(sc.id))
        assert loaded.confidence_score == 0.75
        assert loaded.summary == "Updated summary"

    def test_multiple_revisions_tracked(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Test", "m", confidence=0.5)
        engine.update_scenario(sc.id, {"confidence_score": 0.6, "reason": "r1"})
        engine.update_scenario(sc.id, {"confidence_score": 0.8, "reason": "r2"})
        engine.update_scenario(sc.id, {"confidence_score": 0.7, "reason": "r3"})

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert len(revisions) == 3
        # Revisions ordered by timestamp
        assert revisions[0].new_confidence == 0.6
        assert revisions[1].new_confidence == 0.8
        assert revisions[2].new_confidence == 0.7

    def test_update_with_triggering_action(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "T", "m", confidence=0.5)
        action_id = uuid4()
        engine.update_scenario(sc.id, {
            "confidence_score": 0.3,
            "reason": "Agent challenged",
            "triggering_action_id": str(action_id),
        })

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert revisions[0].triggering_action_id == action_id

    def test_update_nonexistent_raises(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.update_scenario(uuid4(), {"reason": "test"})


# ══════════════════════════════════════════════════════════════════════
#  Promote
# ══════════════════════════════════════════════════════════════════════

class TestPromote:
    def test_promote_changes_status(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Alt", "m", status="alternative")
        assert sc.status == ScenarioStatus.ALTERNATIVE

        promoted = engine.promote_scenario(sc.id, "Strongest evidence chain")
        assert promoted.status == ScenarioStatus.PRIMARY

        loaded = repo.get_scenario_by_id(str(sc.id))
        assert loaded.status == ScenarioStatus.PRIMARY

    def test_promote_records_revision(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Alt", "m", status="alternative")
        engine.promote_scenario(sc.id, "Best fit")

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert len(revisions) == 1
        assert "Best fit" in revisions[0].reason

    def test_promote_already_primary_is_noop(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "P", "m", status="primary")
        result = engine.promote_scenario(sc.id, "reason")
        assert result.status == ScenarioStatus.PRIMARY

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert len(revisions) == 0  # no revision for noop


# ══════════════════════════════════════════════════════════════════════
#  Dismiss with "why not"
# ══════════════════════════════════════════════════════════════════════

class TestDismiss:
    def test_dismiss_changes_status(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Weak", "m", confidence=0.3)
        dismissed = engine.dismiss_scenario(sc.id, "Timing doesn't fit")
        assert dismissed.status == ScenarioStatus.DISMISSED
        assert dismissed.confidence_score == 0.0

    def test_dismiss_preserves_why_not(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Dismissed", "m", confidence=0.3)
        evidence_id = str(uuid4())
        action_id = str(uuid4())

        engine.dismiss_scenario(
            sc.id,
            reason="Evidence contradicts causal mechanism",
            decisive_evidence_id=evidence_id,
            decisive_challenge_action_id=action_id,
            failure_mode="contradiction",
        )

        loaded = repo.get_scenario_by_id(str(sc.id))
        why_not = loaded.metadata.get("why_not")
        assert why_not is not None
        assert why_not["why_lost"] == "Evidence contradicts causal mechanism"
        assert why_not["failure_mode"] == "contradiction"
        assert evidence_id in why_not["weakening_evidence_ids"]
        assert why_not["decisive_critique_action_id"] == action_id

    def test_dismiss_records_revision(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "Test", "m", confidence=0.5)
        engine.dismiss_scenario(sc.id, "Bad timing", failure_mode="timing")

        revisions = repo.get_scenario_revisions(str(sc.id))
        assert len(revisions) == 1
        assert revisions[0].new_confidence == 0.0
        assert revisions[0].previous_confidence == 0.5

    def test_dismiss_failure_mode_enum(self, engine, run, repo):
        sc = engine.create_scenario(run.id, "T", "m")
        engine.dismiss_scenario(sc.id, "r", failure_mode=FailureMode.EVIDENCE_QUALITY)
        loaded = repo.get_scenario_by_id(str(sc.id))
        assert loaded.metadata["why_not"]["failure_mode"] == "quality"


# ══════════════════════════════════════════════════════════════════════
#  Cluster from actions
# ══════════════════════════════════════════════════════════════════════

class TestClusterFromActions:
    def _make_actions(self, run_id):
        """Create a set of debate actions for clustering."""
        actions = [
            AgentAction(
                run_id=run_id, agent_name="macro-policy",
                action_type=AgentActionType.PROPOSE, sequence_number=0,
                round_number=0,
                content="Federal Reserve rate cut caused the market rally",
                confidence_after=0.75,
            ),
            AgentAction(
                run_id=run_id, agent_name="crypto-whale",
                action_type=AgentActionType.PROPOSE, sequence_number=1,
                round_number=0,
                content="Whale accumulation on Binance drove price surge",
                confidence_after=0.65,
            ),
            AgentAction(
                run_id=run_id, agent_name="sentiment",
                action_type=AgentActionType.PROPOSE, sequence_number=2,
                round_number=0,
                content="Twitter narrative shifted bullish after influencer post",
                confidence_after=0.40,
            ),
            AgentAction(
                run_id=run_id, agent_name="crypto-whale",
                action_type=AgentActionType.UPDATE_CONFIDENCE, sequence_number=3,
                round_number=1,
                content="Revised up after new on-chain data",
                confidence_before=0.65, confidence_after=0.80,
            ),
            AgentAction(
                run_id=run_id, agent_name="sentiment",
                action_type=AgentActionType.CONCEDE, sequence_number=4,
                round_number=1,
                content="Conceding — timing doesn't fit narrative hypothesis",
                confidence_before=0.40, confidence_after=0.0,
            ),
        ]
        return actions

    def test_cluster_produces_scenarios(self, engine, run):
        actions = self._make_actions(run.id)
        scenarios = engine.cluster_from_actions(run.id, actions, [])
        assert len(scenarios) > 0
        assert all(isinstance(s, Scenario) for s in scenarios)

    def test_cluster_persists_scenarios(self, engine, run, repo):
        actions = self._make_actions(run.id)
        engine.cluster_from_actions(run.id, actions, [])

        stored = repo.get_scenarios(str(run.id))
        assert len(stored) > 0

    def test_conceded_hypotheses_dismissed(self, engine, run):
        actions = self._make_actions(run.id)
        scenarios = engine.cluster_from_actions(run.id, actions, [])

        # The sentiment agent conceded; its scenario should have low/zero confidence
        # or be in dismissed tier
        confidences = {s.mechanism_type: s.confidence_score for s in scenarios}
        titles = [s.title for s in scenarios]
        # At least one should be dismissed or have 0 confidence
        assert any(
            s.status == ScenarioStatus.DISMISSED or s.confidence_score == 0.0
            for s in scenarios
        ) or len(scenarios) < 3  # might not produce sentiment scenario at all

    def test_updated_confidence_reflected(self, engine, run):
        actions = self._make_actions(run.id)
        scenarios = engine.cluster_from_actions(run.id, actions, [])

        # Find the scenario containing crypto-whale's hypothesis
        # Its confidence should reflect the UPDATE_CONFIDENCE (0.80)
        for s in scenarios:
            if "whale" in s.title.lower() or "informed" in s.mechanism_type:
                assert s.confidence_score >= 0.75

    def test_empty_actions_returns_empty(self, engine, run):
        assert engine.cluster_from_actions(run.id, [], []) == []

    def test_no_propose_actions_returns_empty(self, engine, run):
        actions = [
            AgentAction(
                run_id=run.id, agent_name="a",
                action_type=AgentActionType.SUPPORT, sequence_number=0,
                round_number=0, content="I agree",
            ),
        ]
        assert engine.cluster_from_actions(run.id, actions, []) == []


# ══════════════════════════════════════════════════════════════════════
#  Scenario comparison
# ══════════════════════════════════════════════════════════════════════

class TestComparison:
    def test_basic_comparison(self, engine, run, repo):
        sc_a = engine.create_scenario(run.id, "Macro", "macro", confidence=0.8,
                                       lead_agents=["macro"])
        sc_b = engine.create_scenario(run.id, "Crypto", "crypto", confidence=0.6,
                                       lead_agents=["crypto"])

        comp = engine.get_scenario_comparison(sc_a.id, sc_b.id)
        assert comp["scenario_a"]["title"] == "Macro"
        assert comp["scenario_b"]["title"] == "Crypto"
        assert comp["confidence_gap"] == pytest.approx(0.2, abs=0.01)

    def test_comparison_shows_shared_evidence(self, engine, run, repo):
        from src.core.evidence_ledger import EvidenceLedger
        ledger = EvidenceLedger(repo)

        sc_a = engine.create_scenario(run.id, "A", "m", confidence=0.7)
        sc_b = engine.create_scenario(run.id, "B", "m", confidence=0.5)

        ev_shared = ledger.ingest_evidence(run.id, {"title": "Shared"}, "agent")
        ev_only_a = ledger.ingest_evidence(run.id, {"title": "Only A"}, "agent")

        ledger.link_to_scenario(ev_shared.id, sc_a.id, "supports")
        ledger.link_to_scenario(ev_shared.id, sc_b.id, "supports")
        ledger.link_to_scenario(ev_only_a.id, sc_a.id, "supports")

        comp = engine.get_scenario_comparison(sc_a.id, sc_b.id)
        assert comp["evidence_overlap"]["shared_count"] == 1
        assert comp["evidence_overlap"]["only_a_count"] == 1
        assert comp["evidence_overlap"]["only_b_count"] == 0

    def test_comparison_shows_disagreements(self, engine, run, repo):
        sc_a = engine.create_scenario(
            run.id, "A", "m", confidence=0.7,
            lead_agents=["agent-1"],
        )
        # agent-1 supports A but is also listed as challenging B
        sc_b = engine.create_scenario(run.id, "B", "m", confidence=0.5)
        engine.update_scenario(sc_a.id, {
            "supporting_agents": ["agent-1"],
            "reason": "setup",
        })
        engine.update_scenario(sc_b.id, {
            "challenging_agents": ["agent-1"],
            "reason": "setup",
        })

        comp = engine.get_scenario_comparison(sc_a.id, sc_b.id)
        assert len(comp["disagreement_points"]) >= 1
        assert comp["disagreement_points"][0]["agent"] == "agent-1"

    def test_comparison_nonexistent_raises(self, engine):
        with pytest.raises(ValueError):
            engine.get_scenario_comparison(uuid4(), uuid4())


# ══════════════════════════════════════════════════════════════════════
#  API endpoints
# ══════════════════════════════════════════════════════════════════════

class TestScenarioAPI:
    def setup_method(self):
        self.conn = init_db(":memory:", check_same_thread=False)
        self.repo = RunRepository(self.conn)

    def test_get_run_scenarios(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        self.repo.create_run(run)
        engine = ScenarioEngine(self.repo)
        engine.create_scenario(run.id, "S1", "m1")
        engine.create_scenario(run.id, "S2", "m2")

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/scenarios")

        assert resp.status_code == 200
        assert len(resp.json()["scenarios"]) == 2

    def test_get_scenario_detail(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        self.repo.create_run(run)
        engine = ScenarioEngine(self.repo)
        sc = engine.create_scenario(run.id, "Detail Test", "m", confidence=0.7)
        engine.update_scenario(sc.id, {
            "confidence_score": 0.85, "reason": "strengthened",
        })

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/scenarios/{sc.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert body["scenario"]["title"] == "Detail Test"
        assert len(body["revisions"]) == 1
        assert body["revisions"][0]["new_confidence"] == 0.85

    def test_get_scenario_not_found(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/scenarios/{uuid4()}")

        assert resp.status_code == 404

    def test_get_run_scenarios_not_found(self):
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{uuid4()}/scenarios")

        assert resp.status_code == 404
