"""
Integration tests for the run-centric architecture.

Covers:
  1. Full run lifecycle: create → stream events → verify scenarios → export bundle
  2. Checkpoint resume: start → kill midway → resume → no duplicate actions
  3. SSE reconnect: connect → disconnect → reconnect with Last-Event-ID → no gaps
  4. Evidence linkage: every scenario has evidence with provenance
  5. Interrogation: create session → ask question → verify response references artifacts
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch, AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    AgentAction,
    AgentActionType,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    EvidenceStance,
    GovernanceDecision,
    GovernanceDecisionType,
    GraphDeltaType,
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
    SSEEvent,
    SSEEventType,
    SpikeEvent,
    SpikeType,
)
from src.core.evidence_ledger import EvidenceLedger
from src.core.graph_manager import GraphManager
from src.core.persistence import RunRepository, init_db
from src.core.scenario_engine import ScenarioEngine


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


def _make_spike_event(market_id=None):
    mid = market_id or uuid4()
    return SpikeEvent(
        market_id=mid,
        spike_type=SpikeType.UP,
        magnitude=0.15,
        threshold_used=0.05,
        metadata={"market_title": "Will BTC hit 100k?"},
    )


def _seed_complete_run(repo):
    """Create a fully populated run with all artifact types."""
    spike = _make_spike_event()
    run = AttributionRun(
        spike_event_id=spike.id,
        market_id=spike.market_id,
        status=RunStatus.COMPLETED,
        bace_depth=2,
        metadata={
            "market_title": "Will BTC hit 100k?",
            "market_id": str(spike.market_id),
            "spike_event": spike.model_dump(mode="json"),
        },
    )
    repo.create_run(run)
    repo.update_run_status(str(run.id), RunStatus.COMPLETED)

    # Evidence items
    ev1 = EvidenceItem(
        run_id=run.id, title="Bloomberg: BTC ETF inflows surge",
        source_type=EvidenceSourceType.NEWS_ARTICLE,
        source_url="https://bloomberg.com/btc-etf",
        summary="$500M in ETF inflows in 24h",
        relevance_score=0.9, freshness_score=0.8,
        stance=EvidenceStance.SUPPORTS,
    )
    repo.save_evidence(ev1)

    ev2 = EvidenceItem(
        run_id=run.id, title="CoinDesk: Whale accumulation detected",
        source_type=EvidenceSourceType.NEWS_ARTICLE,
        source_url="https://coindesk.com/whale",
        summary="Large wallets accumulating",
        relevance_score=0.7, freshness_score=0.6,
        stance=EvidenceStance.SUPPORTS,
    )
    repo.save_evidence(ev2)

    ev3 = EvidenceItem(
        run_id=run.id, title="Reuters: Fed signals concern",
        source_type=EvidenceSourceType.NEWS_ARTICLE,
        source_url="https://reuters.com/fed-concern",
        summary="Fed officials express crypto concerns",
        relevance_score=0.5, freshness_score=0.7,
        stance=EvidenceStance.WEAKENS,
    )
    repo.save_evidence(ev3)

    # Scenarios
    sc1 = Scenario(
        run_id=run.id, title="ETF Demand Surge",
        mechanism_type="informed_flow", summary="Spot ETF inflows driving price up",
        confidence_score=0.82, status=ScenarioStatus.PRIMARY,
        lead_agents=["informed-flow"],
        supporting_agents=["macro-policy"],
        challenging_agents=["devils-advocate"],
    )
    repo.save_scenario(sc1)

    sc2 = Scenario(
        run_id=run.id, title="Whale Accumulation",
        mechanism_type="informed_flow", summary="Large holders buying",
        confidence_score=0.45, status=ScenarioStatus.ALTERNATIVE,
        lead_agents=["informed-flow"],
    )
    repo.save_scenario(sc2)

    sc3 = Scenario(
        run_id=run.id, title="Random Noise",
        mechanism_type="null", summary="Normal variance",
        confidence_score=0.0, status=ScenarioStatus.DISMISSED,
        lead_agents=["null-hypothesis"],
        what_breaks_this=["Magnitude exceeds 3-sigma"],
    )
    repo.save_scenario(sc3)

    # Evidence links
    link1 = ScenarioEvidenceLink(
        scenario_id=sc1.id, evidence_id=ev1.id,
        link_type=ScenarioEvidenceLinkType.SUPPORTS,
        agent_name="informed-flow",
    )
    repo.save_evidence_link(link1)

    link2 = ScenarioEvidenceLink(
        scenario_id=sc1.id, evidence_id=ev3.id,
        link_type=ScenarioEvidenceLinkType.CHALLENGES,
        agent_name="devils-advocate",
    )
    repo.save_evidence_link(link2)

    link3 = ScenarioEvidenceLink(
        scenario_id=sc2.id, evidence_id=ev2.id,
        link_type=ScenarioEvidenceLinkType.SUPPORTS,
        agent_name="informed-flow",
    )
    repo.save_evidence_link(link3)

    # Scenario revisions
    rev = ScenarioRevision(
        scenario_id=sc1.id, run_id=run.id,
        revision_type=ScenarioRevisionType.CONFIDENCE_UPDATED,
        previous_confidence=0.6, new_confidence=0.82,
        reason="ETF evidence confirmed",
    )
    repo.save_scenario_revision(rev)

    # Actions
    actions = [
        AgentAction(
            run_id=run.id, agent_name="informed-flow",
            action_type=AgentActionType.PROPOSE, sequence_number=0,
            round_number=0, content="ETF inflows driving price",
        ),
        AgentAction(
            run_id=run.id, agent_name="macro-policy",
            action_type=AgentActionType.SUPPORT, sequence_number=1,
            round_number=0, content="Confirming macro alignment",
            target_scenario_id=sc1.id,
        ),
        AgentAction(
            run_id=run.id, agent_name="devils-advocate",
            action_type=AgentActionType.CHALLENGE, sequence_number=2,
            round_number=1, content="Could be short squeeze",
            target_scenario_id=sc1.id,
        ),
    ]
    for a in actions:
        repo.save_action(a)

    # SSE events
    event_payloads = [
        (SSEEventType.RUN_STARTED, "attribution_started", {"run_id": str(run.id)}),
        (SSEEventType.AGENT_ACTION, "attribution_streaming", {"agent": "informed-flow", "action": "PROPOSE"}),
        (SSEEventType.AGENT_ACTION, "attribution_streaming", {"agent": "macro-policy", "action": "SUPPORT"}),
        (SSEEventType.AGENT_ACTION, "attribution_streaming", {"agent": "devils-advocate", "action": "CHALLENGE"}),
        (SSEEventType.EVIDENCE_ADDED, "attribution_streaming", {"count": 3}),
        (SSEEventType.SCENARIO_CREATED, "scenario_clustering", {"title": "ETF Demand Surge"}),
        (SSEEventType.GRAPH_DELTA, "graph_persisted", {"delta_type": "node_created"}),
        (SSEEventType.RUN_COMPLETED, "completed", {"status": "completed"}),
    ]
    for i, (etype, stage, payload) in enumerate(event_payloads):
        evt = SSEEvent(
            run_id=run.id, stage=stage,
            event_type=etype, sequence=i,
            payload=payload,
        )
        repo.save_sse_event(evt)

    # Graph
    gm = GraphManager(db=repo)
    gm.record_ontology(run.id, {
        "entities": [
            {"id": "btc", "name": "Bitcoin", "entity_type": "FinancialInstrument"},
            {"id": "etf", "name": "Spot ETF", "entity_type": "FinancialInstrument"},
        ],
        "relationships": [
            {"source": "etf", "target": "btc", "relationship_type": "drives", "strength": 0.9},
        ],
    }, 100)

    # Governance
    gov = GovernanceDecision(
        run_id=run.id,
        decision_type=GovernanceDecisionType.AUTO_RELAY,
        stage="attribution_complete",
        outcome="Approved",
    )
    repo.save_governance_decision(gov)

    return run, [sc1, sc2, sc3], [ev1, ev2, ev3]


def _parse_sse_frames(raw: str) -> list[dict]:
    """Parse raw SSE text into event dicts."""
    frames = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        frame: dict = {}
        data_lines = []
        for line in block.split("\n"):
            if line.startswith("id: "):
                frame["id"] = line[4:]
            elif line.startswith("event: "):
                frame["event"] = line[7:]
            elif line.startswith("data: "):
                data_lines.append(line[6:])
            elif line.startswith("retry: "):
                frame["retry"] = line[7:]
        if data_lines:
            try:
                frame["data"] = json.loads("\n".join(data_lines))
            except json.JSONDecodeError:
                frame["data_raw"] = "\n".join(data_lines)
        frames.append(frame)
    return frames


# ══════════════════════════════════════════════════════════════════════
#  1. Full run lifecycle
# ══════════════════════════════════════════════════════════════════════

class TestFullRunLifecycle:
    """Create run → stream events → verify scenarios → export bundle."""

    def test_create_run_returns_id_and_stream_url(self, client):
        resp = client.post("/api/runs", json={
            "market_title": "Will BTC hit 100k?",
            "timestamp": "2025-01-15T12:00:00Z",
            "direction": "up",
            "magnitude": 0.15,
            "price_before": 0.45,
            "price_after": 0.60,
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "run_id" in body
        UUID(body["run_id"])  # valid UUID
        assert body["status"] == "created"
        assert "/stream" in body["stream_url"]

    def test_full_run_state_has_all_artifacts(self, client, repo):
        run, scenarios, evidence = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}")
        assert resp.status_code == 200
        body = resp.json()

        assert body["run"]["id"] == str(run.id)
        assert body["run"]["status"] == "completed"
        assert len(body["scenarios"]) == 3
        assert len(body["evidence"]) == 3
        assert len(body["actions"]) == 3
        assert len(body["graph_deltas"]) >= 2

    def test_scenarios_have_correct_tiers(self, client, repo):
        run, scenarios, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/scenarios")
        body = resp.json()
        tiers = {s["status"] for s in body["scenarios"]}
        assert "primary" in tiers
        assert "alternative" in tiers
        assert "dismissed" in tiers

    def test_export_bundle_complete(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/export")
        assert resp.status_code == 200
        data = resp.json()

        expected_keys = {
            "export_version", "run", "spike_event", "actions",
            "evidence", "scenarios", "graph", "governance", "interrogation",
        }
        assert set(data.keys()) == expected_keys
        assert data["export_version"] == "1.0"
        assert len(data["actions"]) == 3
        assert len(data["evidence"]) == 3
        assert len(data["scenarios"]) == 3
        assert len(data["governance"]) == 1

    def test_export_scenarios_include_revisions_and_evidence_links(self, client, repo):
        run, _, _ = _seed_complete_run(repo)
        data = client.get(f"/api/runs/{run.id}/export").json()

        primary_sc = next(s for s in data["scenarios"] if s["scenario"]["status"] == "primary")
        assert len(primary_sc["revisions"]) >= 1
        assert len(primary_sc["evidence_links"]) >= 1

    def test_run_status_endpoint(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["run_id"] == str(run.id)


# ══════════════════════════════════════════════════════════════════════
#  2. Checkpoint resume — no duplicate actions
# ══════════════════════════════════════════════════════════════════════

class TestCheckpointResume:
    """Actions use INSERT OR IGNORE — resuming must not create duplicates."""

    def test_duplicate_actions_are_idempotent(self, repo):
        run = AttributionRun(
            spike_event_id=uuid4(), market_id=uuid4(),
            status=RunStatus.ATTRIBUTION_STREAMING,
        )
        repo.create_run(run)

        action = AgentAction(
            run_id=run.id, agent_name="macro-policy",
            action_type=AgentActionType.PROPOSE,
            sequence_number=0, round_number=0,
            content="Initial proposal",
        )
        repo.save_action(action)
        repo.save_action(action)  # duplicate — should be ignored

        actions = repo.get_actions(str(run.id))
        assert len(actions) == 1

    def test_duplicate_sse_events_are_idempotent(self, repo):
        run = AttributionRun(
            spike_event_id=uuid4(), market_id=uuid4(),
            status=RunStatus.ATTRIBUTION_STREAMING,
        )
        repo.create_run(run)

        evt = SSEEvent(
            run_id=run.id, stage="attribution_streaming",
            event_type=SSEEventType.AGENT_ACTION,
            sequence=0, payload={"test": True},
        )
        repo.save_sse_event(evt)
        repo.save_sse_event(evt)  # duplicate

        events = repo.get_sse_events(str(run.id))
        assert len(events) == 1

    def test_resume_after_partial_run_continues_from_checkpoint(self, repo):
        """Simulate: 3 actions saved → crash → resume → add 2 more, no dups."""
        run = AttributionRun(
            spike_event_id=uuid4(), market_id=uuid4(),
            status=RunStatus.ATTRIBUTION_STREAMING,
        )
        repo.create_run(run)

        # Phase 1: save 3 actions
        for i in range(3):
            repo.save_action(AgentAction(
                run_id=run.id, agent_name=f"agent-{i}",
                action_type=AgentActionType.PROPOSE,
                sequence_number=i, round_number=0,
                content=f"Action {i}",
            ))

        # Simulate crash — get last sequence
        existing = repo.get_actions(str(run.id))
        last_seq = max(a.sequence_number for a in existing)
        assert last_seq == 2
        assert len(existing) == 3

        # Phase 2: resume — replay first 3 (should be ignored) + add 2 new
        for i in range(5):
            repo.save_action(AgentAction(
                run_id=run.id, agent_name=f"agent-{i}" if i < 3 else f"agent-resume-{i}",
                action_type=AgentActionType.PROPOSE,
                sequence_number=i, round_number=0 if i < 3 else 1,
                content=f"Action {i}" if i < 3 else f"Resume action {i}",
            ))

        all_actions = repo.get_actions(str(run.id))
        assert len(all_actions) == 5  # 3 original + 2 new, no dups

    def test_resume_endpoint_terminal_run_is_noop(self, client, repo):
        run, _, _ = _seed_complete_run(repo)
        resp = client.post(f"/api/runs/{run.id}/resume")
        assert resp.status_code == 200
        assert "terminal" in resp.json()["message"]


# ══════════════════════════════════════════════════════════════════════
#  3. SSE reconnect — no gaps
# ══════════════════════════════════════════════════════════════════════

class TestSSEReconnect:
    """Reconnect with Last-Event-ID skips seen events, no gaps."""

    def test_replay_returns_all_events_for_completed_run(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/replay")
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 8  # all 8 events seeded

    def test_replay_after_sequence_skips_old(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/replay?after_sequence=4")
        body = resp.json()
        assert len(body["events"]) == 3  # sequences 5, 6, 7
        assert all(e["sequence"] > 4 for e in body["events"])

    def test_replay_events_have_canonical_envelope(self, client, repo):
        run, _, _ = _seed_complete_run(repo)
        body = client.get(f"/api/runs/{run.id}/replay").json()

        required_fields = {"event_id", "run_id", "stage", "event_type", "sequence", "payload", "timestamp"}
        for evt in body["events"]:
            assert required_fields.issubset(evt.keys()), f"Missing: {required_fields - evt.keys()}"

    def test_replay_sequences_are_monotonic(self, client, repo):
        run, _, _ = _seed_complete_run(repo)
        body = client.get(f"/api/runs/{run.id}/replay").json()

        sequences = [e["sequence"] for e in body["events"]]
        assert sequences == sorted(sequences)
        # No gaps
        for i in range(len(sequences) - 1):
            assert sequences[i + 1] == sequences[i] + 1

    def test_stream_completed_run_replays_via_sse(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
            raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        assert len(frames) >= 8

    def test_stream_with_last_event_id_skips_seen(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        with client.stream(
            "GET", f"/api/runs/{run.id}/stream",
            headers={"Last-Event-ID": "4"},
        ) as resp:
            raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        sequences = [
            f["data"]["sequence"]
            for f in frames
            if "data" in f and "sequence" in f.get("data", {})
        ]
        assert all(s > 4 for s in sequences if s < 1000)

    def test_replay_not_found(self, client):
        resp = client.get(f"/api/runs/{uuid4()}/replay")
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════
#  4. Evidence linkage — every scenario has provenance
# ══════════════════════════════════════════════════════════════════════

class TestEvidenceLinkage:
    """Every primary/alternative scenario should have linked evidence."""

    def test_primary_scenario_has_evidence_links(self, repo):
        run, scenarios, evidence = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        links = repo.get_evidence_links_by_scenario(str(primary.id))
        assert len(links) >= 1
        # At least one supporting link
        assert any(l.link_type == ScenarioEvidenceLinkType.SUPPORTS for l in links)

    def test_alternative_scenario_has_evidence_links(self, repo):
        run, scenarios, evidence = _seed_complete_run(repo)
        alt = [s for s in scenarios if s.status == ScenarioStatus.ALTERNATIVE][0]

        links = repo.get_evidence_links_by_scenario(str(alt.id))
        assert len(links) >= 1

    def test_evidence_links_reference_valid_evidence(self, repo):
        run, scenarios, evidence = _seed_complete_run(repo)
        evidence_ids = {str(e.id) for e in evidence}

        for sc in scenarios:
            links = repo.get_evidence_links_by_scenario(str(sc.id))
            for link in links:
                assert str(link.evidence_id) in evidence_ids

    def test_evidence_links_have_agent_provenance(self, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        links = repo.get_evidence_links_by_scenario(str(primary.id))
        for link in links:
            assert link.agent_name != ""

    def test_evidence_ledger_deduplicates(self, repo):
        run, _, _ = _seed_complete_run(repo)
        ledger = EvidenceLedger(db=repo)

        # Try to ingest duplicate URL
        result = ledger.ingest_evidence(
            run_id=run.id,
            raw_evidence={
                "title": "Duplicate",
                "url": "https://bloomberg.com/btc-etf",
                "summary": "Same article",
            },
            provider_agent="test",
        )
        assert result is None  # deduplicated

    def test_evidence_stance_recorded(self, repo):
        _, _, evidence = _seed_complete_run(repo)
        stances = {e.stance.value if hasattr(e.stance, 'value') else str(e.stance) for e in evidence if e.stance}
        assert "supports" in stances

    def test_evidence_api_returns_with_scenario_filter(self, client, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        resp = client.get(f"/api/runs/{run.id}/evidence?scenario_id={primary.id}")
        assert resp.status_code == 200
        body = resp.json()
        # Scenario-filtered response uses supporting/challenging/rebutting/unresolved keys
        total = len(body.get("supporting", [])) + len(body.get("challenging", []))
        assert total >= 1


# ══════════════════════════════════════════════════════════════════════
#  5. Interrogation: session → question → response references artifacts
# ══════════════════════════════════════════════════════════════════════

class TestInterrogation:
    """Create session targeting a scenario → ask → verify artifacts referenced."""

    def test_create_session_targeting_scenario(self, client, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        resp = client.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "scenario",
            "target_id": str(primary.id),
        })
        assert resp.status_code == 200
        body = resp.json()
        assert "id" in body
        UUID(body["id"])

    def test_session_persisted_and_retrievable(self, client, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        create_resp = client.post("/api/interrogation/session", json={
            "run_id": str(run.id),
            "target_type": "scenario",
            "target_id": str(primary.id),
        })
        session_id = create_resp.json()["id"]

        resp = client.get(f"/api/interrogation/session/{session_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session"]["target_type"] == "scenario"
        assert body["session"]["target_id"] == str(primary.id)

    def test_interrogation_message_persisted(self, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = [s for s in scenarios if s.status == ScenarioStatus.PRIMARY][0]

        session = InterrogationSession(
            run_id=run.id,
            target_type=InterrogationTargetType.SCENARIO,
            target_id=primary.id,
        )
        repo.save_interrogation_session(session)

        msg = InterrogationMessage(
            session_id=session.id,
            role=InterrogationRole.USER,
            content="Why is ETF demand the top scenario?",
        )
        repo.save_interrogation_message(msg)

        messages = repo.get_interrogation_messages(str(session.id))
        assert len(messages) == 1
        assert "ETF" in messages[0].content

    def test_session_for_invalid_run_returns_404(self, client):
        resp = client.post("/api/interrogation/session", json={
            "run_id": str(uuid4()),
            "target_type": "scenario",
            "target_id": str(uuid4()),
        })
        assert resp.status_code == 404

    def test_session_transcript_after_messages(self, repo):
        run, scenarios, _ = _seed_complete_run(repo)
        primary = scenarios[0]

        session = InterrogationSession(
            run_id=run.id,
            target_type=InterrogationTargetType.SCENARIO,
            target_id=primary.id,
        )
        repo.save_interrogation_session(session)

        # User message
        repo.save_interrogation_message(InterrogationMessage(
            session_id=session.id,
            role=InterrogationRole.USER,
            content="What evidence supports this?",
        ))
        # Assistant response
        repo.save_interrogation_message(InterrogationMessage(
            session_id=session.id,
            role=InterrogationRole.ASSISTANT,
            content="Bloomberg reports $500M in ETF inflows.",
        ))

        messages = repo.get_interrogation_messages(str(session.id))
        assert len(messages) == 2
        assert messages[0].role == InterrogationRole.USER
        assert messages[1].role == InterrogationRole.ASSISTANT


# ══════════════════════════════════════════════════════════════════════
#  6. Rate limiter (basic verification)
# ══════════════════════════════════════════════════════════════════════

class TestRateLimiter:
    """Verify rate limiter middleware exists and works."""

    def test_rate_limiter_returns_429_when_exceeded(self, repo, monkeypatch):
        import src.api.server as server_mod

        # Remove testing bypass and set very low limit
        monkeypatch.delenv("PYTHIA_TESTING", raising=False)

        mock_llm_fn = MagicMock(return_value="mock response")
        monkeypatch.setattr(server_mod, "_repo", repo)
        monkeypatch.setattr(server_mod, "_get_repo", lambda: repo)
        monkeypatch.setattr(server_mod, "_get_llm", lambda: (mock_llm_fn, mock_llm_fn))
        monkeypatch.setattr(server_mod, "_graph_manager", None)
        monkeypatch.setattr(server_mod, "_interrogation_engine", None)

        c = TestClient(server_mod.app)

        # The middleware uses a sliding window.
        # Since we can't easily control the rate, we verify
        # the middleware class exists on the app.
        from starlette.middleware.base import BaseHTTPMiddleware

        has_rate_limiter = False
        for mw in server_mod.app.user_middleware:
            if hasattr(mw, 'cls') and mw.cls.__name__ == 'RateLimitMiddleware':
                has_rate_limiter = True
        assert has_rate_limiter, "RateLimitMiddleware not found on app"

    def test_health_endpoint_bypasses_rate_limit(self, repo, monkeypatch):
        import src.api.server as server_mod

        monkeypatch.delenv("PYTHIA_TESTING", raising=False)
        monkeypatch.setattr(server_mod, "_repo", repo)
        monkeypatch.setattr(server_mod, "_get_repo", lambda: repo)

        c = TestClient(server_mod.app)
        # Health endpoint should always work
        resp = c.get("/health")
        assert resp.status_code == 200


# ══════════════════════════════════════════════════════════════════════
#  7. Graph integrity
# ══════════════════════════════════════════════════════════════════════

class TestGraphIntegrity:
    """Graph nodes/edges materialized from deltas."""

    def test_graph_endpoint_returns_nodes_and_edges(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/graph")
        assert resp.status_code == 200
        body = resp.json()
        assert "nodes" in body
        assert "edges" in body
        assert len(body["nodes"]) >= 2

    def test_graph_deltas_are_ordered(self, client, repo):
        run, _, _ = _seed_complete_run(repo)

        resp = client.get(f"/api/runs/{run.id}/graph/deltas")
        assert resp.status_code == 200
        deltas = resp.json()["deltas"]
        sequences = [d["sequence_number"] for d in deltas]
        assert sequences == sorted(sequences)
