"""
Tests for InterrogationEngine: session creation, context building,
message persistence, answer modes, API endpoints, and edge cases.
"""

import asyncio
import json
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    AgentAction,
    AgentActionType,
    AnswerMode,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    GovernanceDecision,
    GovernanceDecisionType,
    GraphEdge,
    GraphEntityType,
    GraphNode,
    InterrogationTargetType,
    Scenario,
    ScenarioEvidenceLink,
    ScenarioEvidenceLinkType,
    ScenarioStatus,
)
from src.core.interrogation import InterrogationEngine
from src.core.persistence import RunRepository, init_db


# ── Fixtures ─────────────────────────────────────────────────────────

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
def mock_llm():
    return MagicMock(return_value="This is the LLM response about the artifact.")


@pytest.fixture
def engine(repo, mock_llm):
    return InterrogationEngine(db=repo, llm_client=mock_llm)


# ══════════════════════════════════════════════════════════════════════
#  Session creation
# ══════════════════════════════════════════════════════════════════════

class TestSessionCreation:
    def test_create_session(self, engine, run):
        target_id = uuid4()
        session = engine.create_session(run.id, "scenario", target_id)
        assert session.run_id == run.id
        assert session.target_type == InterrogationTargetType.SCENARIO
        assert session.target_id == target_id

    def test_create_session_persisted(self, engine, run, repo):
        target_id = uuid4()
        session = engine.create_session(run.id, "evidence", target_id)
        loaded = repo.get_interrogation_session(str(session.id))
        assert loaded is not None
        assert loaded.target_type == InterrogationTargetType.EVIDENCE

    def test_invalid_target_type(self, engine, run):
        with pytest.raises(ValueError, match="Invalid target_type"):
            engine.create_session(run.id, "bogus", uuid4())

    def test_all_target_types(self, engine, run):
        for tt in InterrogationTargetType:
            session = engine.create_session(run.id, tt.value, uuid4())
            assert session.target_type == tt


# ══════════════════════════════════════════════════════════════════════
#  Context building
# ══════════════════════════════════════════════════════════════════════

class TestContextBuilding:
    def _seed_scenario(self, repo, run):
        sc = Scenario(
            run_id=run.id,
            title="FOMC Rate Cut",
            mechanism_type="macro_policy",
            summary="Fed cut rates unexpectedly",
            confidence_score=0.8,
            lead_agents=["macro-policy"],
            what_breaks_this=["Fed reversal"],
        )
        repo.save_scenario(sc)
        return sc

    def _seed_evidence(self, repo, run):
        ev = EvidenceItem(
            run_id=run.id,
            title="Reuters: Fed Cuts Rates",
            source_type=EvidenceSourceType.NEWS_ARTICLE,
            summary="The Federal Reserve cut rates by 50bps",
            relevance_score=0.9,
        )
        repo.save_evidence(ev)
        return ev

    def _seed_action(self, repo, run, scenario=None, evidence=None):
        action = AgentAction(
            run_id=run.id,
            agent_name="macro-policy",
            action_type=AgentActionType.PROPOSE,
            sequence_number=0,
            round_number=0,
            content="Proposing FOMC rate cut scenario",
            target_scenario_id=scenario.id if scenario else None,
            evidence_ids=[evidence.id] if evidence else [],
        )
        repo.save_action(action)
        return action

    def _seed_graph(self, repo, run):
        node = GraphNode(
            run_id=run.id,
            entity_type=GraphEntityType.ORGANIZATION,
            label="Federal Reserve",
            properties={"role": "central_bank"},
        )
        repo.save_graph_node(node)

        node2 = GraphNode(
            run_id=run.id,
            entity_type=GraphEntityType.POLICY,
            label="Rate Cut",
        )
        repo.save_graph_node(node2)

        edge = GraphEdge(
            run_id=run.id,
            source_node_id=node.id,
            target_node_id=node2.id,
            relationship_type="ENACTED",
            weight=0.9,
        )
        repo.save_graph_edge(edge)
        return node, node2, edge

    def _seed_governance(self, repo, run):
        decision = GovernanceDecision(
            run_id=run.id,
            decision_type=GovernanceDecisionType.AUTO_RELAY,
            stage="attribution_complete",
            input_context={"confidence": 0.8},
            outcome="Approved for relay",
        )
        repo.save_governance_decision(decision)
        return decision

    def test_scenario_context(self, engine, repo, run):
        sc = self._seed_scenario(repo, run)
        ev = self._seed_evidence(repo, run)
        action = self._seed_action(repo, run, scenario=sc, evidence=ev)

        link = ScenarioEvidenceLink(
            scenario_id=sc.id,
            evidence_id=ev.id,
            link_type=ScenarioEvidenceLinkType.SUPPORTS,
            agent_name="macro-policy",
        )
        repo.save_evidence_link(link)

        ctx = engine.build_context(str(run.id), "scenario", str(sc.id))
        assert ctx["target_type"] == "scenario"
        assert ctx["scenario"]["title"] == "FOMC Rate Cut"
        assert len(ctx["evidence_chain"]) == 1
        assert len(ctx["actions"]) == 1
        assert ctx["what_breaks_this"] == ["Fed reversal"]

    def test_agent_context(self, engine, repo, run):
        sc = self._seed_scenario(repo, run)
        ev = self._seed_evidence(repo, run)
        self._seed_action(repo, run, scenario=sc, evidence=ev)

        ctx = engine.build_context(str(run.id), "agent", "macro-policy")
        assert ctx["target_type"] == "agent"
        assert ctx["agent_name"] == "macro-policy"
        assert len(ctx["actions"]) == 1
        assert len(ctx["evidence"]) == 1
        assert len(ctx["related_scenarios"]) == 1

    def test_evidence_context(self, engine, repo, run):
        ev = self._seed_evidence(repo, run)
        sc = self._seed_scenario(repo, run)
        self._seed_action(repo, run, scenario=sc, evidence=ev)

        link = ScenarioEvidenceLink(
            scenario_id=sc.id,
            evidence_id=ev.id,
            link_type=ScenarioEvidenceLinkType.SUPPORTS,
            agent_name="macro-policy",
        )
        repo.save_evidence_link(link)

        ctx = engine.build_context(str(run.id), "evidence", str(ev.id))
        assert ctx["target_type"] == "evidence"
        assert ctx["evidence"]["title"] == "Reuters: Fed Cuts Rates"
        assert len(ctx["scenario_links"]) == 1
        assert len(ctx["referencing_actions"]) == 1

    def test_node_context(self, engine, repo, run):
        node, _, edge = self._seed_graph(repo, run)
        ctx = engine.build_context(str(run.id), "node", str(node.id))
        assert ctx["target_type"] == "node"
        assert ctx["node"]["label"] == "Federal Reserve"
        assert len(ctx["edges"]) == 1

    def test_edge_context(self, engine, repo, run):
        node1, node2, edge = self._seed_graph(repo, run)
        ctx = engine.build_context(str(run.id), "edge", str(edge.id))
        assert ctx["target_type"] == "edge"
        assert ctx["edge"]["relationship_type"] == "ENACTED"
        assert ctx["source_node"] is not None
        assert ctx["target_node"] is not None

    def test_action_context(self, engine, repo, run):
        sc = self._seed_scenario(repo, run)
        ev = self._seed_evidence(repo, run)
        action = self._seed_action(repo, run, scenario=sc, evidence=ev)

        ctx = engine.build_context(str(run.id), "action", str(action.id))
        assert ctx["target_type"] == "action"
        assert ctx["action"]["agent_name"] == "macro-policy"
        assert len(ctx["evidence"]) == 1
        assert ctx["target_scenario"] is not None

    def test_governance_context(self, engine, repo, run):
        decision = self._seed_governance(repo, run)
        ctx = engine.build_context(str(run.id), "governance", str(decision.id))
        assert ctx["target_type"] == "governance"
        assert ctx["decision"]["outcome"] == "Approved for relay"

    def test_unknown_target_type(self, engine, run):
        ctx = engine.build_context(str(run.id), "nonexistent", str(uuid4()))
        assert "error" in ctx

    def test_missing_scenario(self, engine, run):
        ctx = engine.build_context(str(run.id), "scenario", str(uuid4()))
        assert ctx.get("error") == "Scenario not found"

    def test_missing_evidence(self, engine, run):
        ctx = engine.build_context(str(run.id), "evidence", str(uuid4()))
        assert ctx.get("error") == "Evidence not found"

    def test_missing_node(self, engine, run):
        ctx = engine.build_context(str(run.id), "node", str(uuid4()))
        assert ctx.get("error") == "Graph node not found"


# ══════════════════════════════════════════════════════════════════════
#  Message persistence and answer modes
# ══════════════════════════════════════════════════════════════════════

class TestMessagePersistence:
    def test_ask_persists_messages(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="Test", mechanism_type="test",
            confidence_score=0.5,
        )
        repo.save_scenario(sc)

        session = engine.create_session(run.id, "scenario", sc.id)

        # Run the async generator to completion
        chunks = []
        async def collect():
            async for chunk in engine.ask(str(session.id), "Why is this scenario likely?"):
                chunks.append(chunk)

        asyncio.get_event_loop().run_until_complete(collect())

        # Verify messages persisted
        messages = repo.get_interrogation_messages(str(session.id))
        assert len(messages) == 2
        assert messages[0].role.value == "user"
        assert messages[0].content == "Why is this scenario likely?"
        assert messages[1].role.value == "assistant"
        assert messages[1].content == mock_llm.return_value

    def test_ask_streams_chunks(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)
        session = engine.create_session(run.id, "scenario", sc.id)

        chunks = []
        async def collect():
            async for chunk in engine.ask(str(session.id), "test"):
                chunks.append(chunk)

        asyncio.get_event_loop().run_until_complete(collect())

        # Last chunk should be [DONE]
        assert chunks[-1] == "data: [DONE]\n\n"
        # Other chunks should have text
        for c in chunks[:-1]:
            parsed = json.loads(c.replace("data: ", "").strip())
            assert "text" in parsed

    def test_invalid_session_id(self, engine):
        with pytest.raises(ValueError, match="not found"):
            asyncio.get_event_loop().run_until_complete(
                engine.ask("nonexistent", "hello").__anext__()
            )

    def test_answer_mode_in_prompt(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)
        session = engine.create_session(run.id, "scenario", sc.id)

        async def collect():
            async for _ in engine.ask(
                str(session.id), "test", answer_mode="evidence_first"
            ):
                pass

        asyncio.get_event_loop().run_until_complete(collect())

        # Check that LLM was called with evidence_first mode
        prompt = mock_llm.call_args[0][0]
        assert "evidence_first" in prompt
        assert "Lead with evidence citations" in prompt

    def test_all_answer_modes(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)

        for mode in AnswerMode:
            session = engine.create_session(run.id, "scenario", sc.id)

            async def collect():
                async for _ in engine.ask(
                    str(session.id), "q", answer_mode=mode.value
                ):
                    pass

            asyncio.get_event_loop().run_until_complete(collect())
            prompt = mock_llm.call_args[0][0]
            assert mode.value in prompt

    def test_invalid_answer_mode_defaults_to_concise(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)
        session = engine.create_session(run.id, "scenario", sc.id)

        async def collect():
            async for _ in engine.ask(
                str(session.id), "test", answer_mode="bogus"
            ):
                pass

        asyncio.get_event_loop().run_until_complete(collect())
        prompt = mock_llm.call_args[0][0]
        assert "concise" in prompt


# ══════════════════════════════════════════════════════════════════════
#  Get session
# ══════════════════════════════════════════════════════════════════════

class TestGetSession:
    def test_get_session_with_messages(self, engine, repo, run, mock_llm):
        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)
        session = engine.create_session(run.id, "scenario", sc.id)

        async def collect():
            async for _ in engine.ask(str(session.id), "Why?"):
                pass

        asyncio.get_event_loop().run_until_complete(collect())

        result = engine.get_session(str(session.id))
        assert "session" in result
        assert "messages" in result
        assert len(result["messages"]) == 2

    def test_get_session_not_found(self, engine):
        with pytest.raises(ValueError, match="not found"):
            engine.get_session("nonexistent")


# ══════════════════════════════════════════════════════════════════════
#  API endpoints
# ══════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    @pytest.fixture
    def client(self, monkeypatch):
        """TestClient with mocked LLM and in-memory DB."""
        import src.api.server as server_mod

        conn = init_db(":memory:", check_same_thread=False)
        test_repo = RunRepository(conn)

        mock_llm_fn = MagicMock(return_value="Mocked LLM response.")

        def fake_get_repo():
            return test_repo

        def fake_get_llm():
            return mock_llm_fn, mock_llm_fn

        # Reset singletons
        monkeypatch.setattr(server_mod, "_repo", test_repo)
        monkeypatch.setattr(server_mod, "_get_repo", fake_get_repo)
        monkeypatch.setattr(server_mod, "_get_llm", fake_get_llm)
        monkeypatch.setattr(server_mod, "_interrogation_engine", None)

        return TestClient(server_mod.app), test_repo

    def test_create_session_endpoint(self, client):
        tc, repo = client
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)

        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)

        resp = tc.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "scenario",
            "target_id": str(sc.id),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["target_type"] == "scenario"
        assert data["run_id"] == str(run.id)

    def test_create_session_run_not_found(self, client):
        tc, _ = client
        resp = tc.post("/api/interrogation/session", json={
            "run_id": str(uuid4()),
            "target_type": "scenario",
            "target_id": str(uuid4()),
        })
        assert resp.status_code == 404

    def test_create_session_invalid_target_type(self, client):
        tc, repo = client
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)

        resp = tc.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "invalid",
            "target_id": str(uuid4()),
        })
        assert resp.status_code == 400

    def test_message_endpoint_streams(self, client):
        tc, repo = client
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)

        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)

        # Create session
        resp = tc.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "scenario",
            "target_id": str(sc.id),
        })
        session_id = resp.json()["id"]

        # Send message
        resp = tc.post("/api/interrogation/message", json={
            "session_id": session_id,
            "question": "Why is this scenario likely?",
        })
        assert resp.status_code == 200
        body = resp.text
        assert "data: " in body
        assert "[DONE]" in body

    def test_message_endpoint_session_not_found(self, client):
        tc, _ = client
        resp = tc.post("/api/interrogation/message", json={
            "session_id": str(uuid4()),
            "question": "test",
        })
        assert resp.status_code == 404

    def test_get_session_endpoint(self, client):
        tc, repo = client
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)

        sc = Scenario(
            run_id=run.id, title="T", mechanism_type="t", confidence_score=0.5,
        )
        repo.save_scenario(sc)

        # Create session
        resp = tc.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "scenario",
            "target_id": str(sc.id),
        })
        session_id = resp.json()["id"]

        # Send a message first
        tc.post("/api/interrogation/message", json={
            "session_id": session_id,
            "question": "test question",
        })

        # Get session
        resp = tc.get(f"/api/interrogation/session/{session_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert "session" in data
        assert "messages" in data
        assert len(data["messages"]) == 2  # user + assistant

    def test_get_session_endpoint_not_found(self, client):
        tc, _ = client
        resp = tc.get(f"/api/interrogation/session/{uuid4()}")
        assert resp.status_code == 404
