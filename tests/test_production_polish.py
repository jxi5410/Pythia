"""
Tests for production polish features: export bundle, run comparison,
operator controls (rerun, patch, list), and metrics.
"""

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    AgentAction,
    AgentActionType,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    GovernanceDecision,
    GovernanceDecisionType,
    GraphDeltaType,
    GraphEntityType,
    InterrogationMessage,
    InterrogationRole,
    InterrogationSession,
    InterrogationTargetType,
    RunStatus,
    Scenario,
    ScenarioEvidenceLink,
    ScenarioEvidenceLinkType,
    ScenarioRevision,
    ScenarioRevisionType,
    ScenarioStatus,
    SpikeEvent,
    SpikeType,
)
from src.core.graph_manager import GraphManager
from src.core.persistence import RunRepository, init_db


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def repo():
    conn = init_db(":memory:", check_same_thread=False)
    return RunRepository(conn)


@pytest.fixture
def client(repo, monkeypatch):
    import src.api.server as server_mod

    monkeypatch.setenv("PYTHIA_TESTING", "1")

    mock_llm_fn = MagicMock(return_value="mock response")

    def fake_get_repo():
        return repo

    def fake_get_llm():
        return mock_llm_fn, mock_llm_fn

    monkeypatch.setattr(server_mod, "_repo", repo)
    monkeypatch.setattr(server_mod, "_get_repo", fake_get_repo)
    monkeypatch.setattr(server_mod, "_get_llm", fake_get_llm)
    monkeypatch.setattr(server_mod, "_graph_manager", None)
    monkeypatch.setattr(server_mod, "_interrogation_engine", None)

    return TestClient(server_mod.app)


def _make_run(repo, status=RunStatus.COMPLETED, depth=2, market_id=None, metadata=None):
    spike_id = uuid4()
    mid = market_id or uuid4()
    spike = SpikeEvent(
        id=spike_id, market_id=mid,
        spike_type=SpikeType.UP, magnitude=0.15, threshold_used=0.05,
        metadata={"market_title": "Test Market"},
    )
    run = AttributionRun(
        spike_event_id=spike_id,
        market_id=mid,
        status=status,
        bace_depth=depth,
        metadata=metadata or {"market_title": "Test Market", "spike_event": spike.model_dump(mode="json")},
    )
    repo.create_run(run)
    if status == RunStatus.COMPLETED:
        repo.update_run_status(str(run.id), RunStatus.COMPLETED)
    return run


def _seed_full_run(repo):
    """Seed a complete run with all artifact types."""
    run = _make_run(repo)
    run_id = run.id

    # Evidence
    ev = EvidenceItem(
        run_id=run_id, title="Reuters: Fed Cuts Rates",
        source_type=EvidenceSourceType.NEWS_ARTICLE,
        source_url="https://reuters.com/fed-cut",
        summary="50bps cut", relevance_score=0.9,
    )
    repo.save_evidence(ev)

    # Scenario
    sc = Scenario(
        run_id=run_id, title="FOMC Rate Cut",
        mechanism_type="macro_policy", summary="Fed cut rates",
        confidence_score=0.85, status=ScenarioStatus.PRIMARY,
        lead_agents=["macro-policy"],
    )
    repo.save_scenario(sc)

    # Scenario revision
    rev = ScenarioRevision(
        scenario_id=sc.id, run_id=run_id,
        revision_type=ScenarioRevisionType.CONFIDENCE_UPDATED,
        previous_confidence=0.6, new_confidence=0.85,
        reason="Evidence confirmed",
    )
    repo.save_scenario_revision(rev)

    # Evidence link
    link = ScenarioEvidenceLink(
        scenario_id=sc.id, evidence_id=ev.id,
        link_type=ScenarioEvidenceLinkType.SUPPORTS,
        agent_name="macro-policy",
    )
    repo.save_evidence_link(link)

    # Action
    action = AgentAction(
        run_id=run_id, agent_name="macro-policy",
        action_type=AgentActionType.PROPOSE,
        sequence_number=0, round_number=0,
        content="Proposing rate cut scenario",
    )
    repo.save_action(action)

    # Graph
    gm = GraphManager(db=repo)
    gm.record_ontology(run_id, {
        "entities": [
            {"id": "fed", "name": "Federal Reserve", "entity_type": "Organization"},
        ],
        "relationships": [],
    }, 0)

    # Governance
    gov = GovernanceDecision(
        run_id=run_id,
        decision_type=GovernanceDecisionType.AUTO_RELAY,
        stage="attribution_complete",
        outcome="Approved",
    )
    repo.save_governance_decision(gov)

    # Interrogation session + message
    sess = InterrogationSession(
        run_id=run_id,
        target_type=InterrogationTargetType.SCENARIO,
        target_id=sc.id,
    )
    repo.save_interrogation_session(sess)
    msg = InterrogationMessage(
        session_id=sess.id,
        role=InterrogationRole.USER,
        content="Why is this likely?",
    )
    repo.save_interrogation_message(msg)

    return run, sc, ev


# ══════════════════════════════════════════════════════════════════════
#  Export bundle
# ══════════════════════════════════════════════════════════════════════

class TestExportBundle:
    def test_export_contains_all_keys(self, client, repo):
        run, sc, ev = _seed_full_run(repo)

        resp = client.get(f"/api/runs/{run.id}/export")
        assert resp.status_code == 200
        data = resp.json()

        # All top-level keys present
        expected_keys = {
            "export_version", "run", "spike_event", "actions",
            "evidence", "scenarios", "graph", "governance", "interrogation",
        }
        assert set(data.keys()) == expected_keys

    def test_export_run_metadata(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert data["run"]["id"] == str(run.id)
        assert data["export_version"] == "1.0"

    def test_export_has_spike_event(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert data["spike_event"] is not None

    def test_export_actions(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert len(data["actions"]) == 1
        assert data["actions"][0]["agent_name"] == "macro-policy"

    def test_export_evidence_with_links(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert len(data["evidence"]) == 1
        assert "evidence" in data["evidence"][0]
        assert "scenario_links" in data["evidence"][0]
        assert len(data["evidence"][0]["scenario_links"]) == 1

    def test_export_scenarios_with_revisions(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert len(data["scenarios"]) == 1
        sc_export = data["scenarios"][0]
        assert "scenario" in sc_export
        assert "revisions" in sc_export
        assert len(sc_export["revisions"]) == 1
        assert "evidence_links" in sc_export
        assert len(sc_export["evidence_links"]) == 1

    def test_export_graph(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert "nodes" in data["graph"]
        assert len(data["graph"]["nodes"]) == 1

    def test_export_governance(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert len(data["governance"]) == 1

    def test_export_interrogation(self, client, repo):
        run, _, _ = _seed_full_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert len(data["interrogation"]) == 1
        assert len(data["interrogation"][0]["messages"]) == 1

    def test_export_not_found(self, client):
        resp = client.get(f"/api/runs/{uuid4()}/export")
        assert resp.status_code == 404

    def test_export_empty_run(self, client, repo):
        run = _make_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()
        assert data["actions"] == []
        assert data["evidence"] == []
        assert data["scenarios"] == []


# ══════════════════════════════════════════════════════════════════════
#  Run comparison
# ══════════════════════════════════════════════════════════════════════

class TestRunComparison:
    def _make_two_runs(self, repo):
        market_id = uuid4()
        run_a = _make_run(repo, market_id=market_id)
        run_b = _make_run(repo, market_id=market_id)

        # Shared scenario title with different confidence
        sc_a = Scenario(
            run_id=run_a.id, title="Rate Cut",
            mechanism_type="macro", confidence_score=0.9,
            status=ScenarioStatus.PRIMARY,
        )
        repo.save_scenario(sc_a)

        sc_b = Scenario(
            run_id=run_b.id, title="Rate Cut",
            mechanism_type="macro", confidence_score=0.7,
            status=ScenarioStatus.ALTERNATIVE,
        )
        repo.save_scenario(sc_b)

        # Unique scenarios
        sc_a2 = Scenario(
            run_id=run_a.id, title="Trade War",
            mechanism_type="geopolitical", confidence_score=0.4,
        )
        repo.save_scenario(sc_a2)

        sc_b2 = Scenario(
            run_id=run_b.id, title="Crypto Rally",
            mechanism_type="crypto", confidence_score=0.5,
        )
        repo.save_scenario(sc_b2)

        # Shared evidence URL
        ev_a = EvidenceItem(
            run_id=run_a.id, title="Reuters",
            source_url="https://reuters.com/shared", relevance_score=0.9,
        )
        repo.save_evidence(ev_a)
        ev_b = EvidenceItem(
            run_id=run_b.id, title="Reuters copy",
            source_url="https://reuters.com/shared", relevance_score=0.8,
        )
        repo.save_evidence(ev_b)

        return run_a, run_b

    def test_compare_returns_structure(self, client, repo):
        run_a, run_b = self._make_two_runs(repo)
        resp = client.get(f"/api/runs/compare?run_ids={run_a.id},{run_b.id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "run_a" in data
        assert "run_b" in data
        assert "overlapping_evidence" in data
        assert "confidence_differences" in data
        assert "divergent_scenarios" in data
        assert "primary_scenarios" in data

    def test_compare_overlapping_evidence(self, client, repo):
        run_a, run_b = self._make_two_runs(repo)
        data = client.get(f"/api/runs/compare?run_ids={run_a.id},{run_b.id}").json()
        assert len(data["overlapping_evidence"]) == 1
        assert data["overlapping_evidence"][0]["source_url"] == "https://reuters.com/shared"

    def test_compare_confidence_differences(self, client, repo):
        run_a, run_b = self._make_two_runs(repo)
        data = client.get(f"/api/runs/compare?run_ids={run_a.id},{run_b.id}").json()
        assert len(data["confidence_differences"]) == 1
        diff = data["confidence_differences"][0]
        assert diff["title"] == "Rate Cut"
        assert diff["delta"] == pytest.approx(0.2, abs=0.01)

    def test_compare_divergent_scenarios(self, client, repo):
        run_a, run_b = self._make_two_runs(repo)
        data = client.get(f"/api/runs/compare?run_ids={run_a.id},{run_b.id}").json()
        only_a = {s["title"] for s in data["divergent_scenarios"]["only_in_a"]}
        only_b = {s["title"] for s in data["divergent_scenarios"]["only_in_b"]}
        assert "Trade War" in only_a
        assert "Crypto Rally" in only_b

    def test_compare_needs_two_ids(self, client):
        resp = client.get(f"/api/runs/compare?run_ids={uuid4()}")
        assert resp.status_code == 400

    def test_compare_not_found(self, client):
        resp = client.get(f"/api/runs/compare?run_ids={uuid4()},{uuid4()}")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  Rerun
# ══════════════════════════════════════════════════════════════════════

class TestRerun:
    def test_rerun_creates_new_run(self, client, repo):
        original = _make_run(repo)
        resp = client.post(f"/api/runs/{original.id}/rerun")
        assert resp.status_code == 200
        data = resp.json()
        assert data["rerun_of"] == str(original.id)
        assert data["run_id"] != str(original.id)
        assert data["depth"] == 2

    def test_rerun_linked_to_same_spike(self, client, repo):
        original = _make_run(repo)
        data = client.post(f"/api/runs/{original.id}/rerun").json()
        new_run = repo.get_run(data["run_id"])
        assert new_run is not None
        assert new_run.spike_event_id == original.spike_event_id
        assert new_run.market_id == original.market_id

    def test_rerun_with_different_depth(self, client, repo):
        original = _make_run(repo, depth=2)
        data = client.post(
            f"/api/runs/{original.id}/rerun",
            json={"depth": 3},
        ).json()
        new_run = repo.get_run(data["run_id"])
        assert new_run.bace_depth == 3

    def test_rerun_preserves_metadata(self, client, repo):
        original = _make_run(repo)
        data = client.post(f"/api/runs/{original.id}/rerun").json()
        new_run = repo.get_run(data["run_id"])
        assert new_run.metadata.get("rerun_of") == str(original.id)

    def test_rerun_not_found(self, client):
        resp = client.post(f"/api/runs/{uuid4()}/rerun")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  Patch (operator controls)
# ══════════════════════════════════════════════════════════════════════

class TestPatch:
    def test_mark_reviewed(self, client, repo):
        run = _make_run(repo)
        resp = client.patch(f"/api/runs/{run.id}", json={"reviewed": True})
        assert resp.status_code == 200
        assert resp.json()["reviewed"] is True

        # Verify persisted
        loaded = repo.get_run(str(run.id))
        assert loaded.metadata.get("reviewed") is True

    def test_freeze_scenarios(self, client, repo):
        run = _make_run(repo)
        resp = client.patch(f"/api/runs/{run.id}", json={"frozen": True})
        assert resp.status_code == 200
        assert resp.json()["frozen"] is True

    def test_patch_both(self, client, repo):
        run = _make_run(repo)
        resp = client.patch(
            f"/api/runs/{run.id}",
            json={"reviewed": True, "frozen": True},
        )
        data = resp.json()
        assert data["reviewed"] is True
        assert data["frozen"] is True

    def test_patch_not_found(self, client):
        resp = client.patch(f"/api/runs/{uuid4()}", json={"reviewed": True})
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  List runs with filters
# ══════════════════════════════════════════════════════════════════════

class TestListRuns:
    def test_list_all(self, client, repo):
        _make_run(repo)
        _make_run(repo)
        resp = client.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2

    def test_list_filter_by_status(self, client, repo):
        _make_run(repo, status=RunStatus.COMPLETED)
        _make_run(repo, status=RunStatus.CREATED)
        resp = client.get("/api/runs?status=completed")
        data = resp.json()
        assert all(r["status"] == "completed" for r in data["runs"])

    def test_list_with_limit_offset(self, client, repo):
        for _ in range(5):
            _make_run(repo)
        resp = client.get("/api/runs?limit=2&offset=0")
        assert resp.json()["count"] == 2

    def test_list_empty(self, client):
        resp = client.get("/api/runs")
        assert resp.json()["count"] == 0


# ══════════════════════════════════════════════════════════════════════
#  Metrics
# ══════════════════════════════════════════════════════════════════════

class TestMetrics:
    def test_metrics_empty(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_runs"] == 0
        assert data["runs_by_status"] == {}

    def test_metrics_with_runs(self, client, repo):
        _make_run(repo, status=RunStatus.COMPLETED)
        _make_run(repo, status=RunStatus.COMPLETED)
        _make_run(repo, status=RunStatus.CREATED)

        data = client.get("/api/metrics").json()
        assert data["total_runs"] == 3
        assert data["runs_by_status"]["completed"] == 2
        assert data["runs_by_status"]["created"] == 1
