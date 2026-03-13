"""
Tests for GraphManager: delta recording, graph reconstruction, snapshots,
replay determinism, and API endpoints.
"""

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.core.models import (
    AttributionRun,
    GraphDeltaType,
    GraphEntityType,
    SSEEvent,
    SSEEventType,
)
from src.core.graph_manager import GraphManager
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
def gm(repo):
    return GraphManager(db=repo)


# ── Sample ontology data ─────────────────────────────────────────────

def _sample_ontology():
    return {
        "entities": [
            {
                "id": "fed",
                "name": "Federal Reserve",
                "entity_type": "Organization",
                "description": "US central bank",
                "search_terms": ["Fed", "FOMC"],
                "relevance_score": 0.9,
            },
            {
                "id": "powell",
                "name": "Jerome Powell",
                "entity_type": "Person",
                "description": "Fed Chair",
                "search_terms": ["Powell"],
                "relevance_score": 0.85,
            },
            {
                "id": "rate-cut",
                "name": "Rate Cut",
                "entity_type": "Policy",
                "description": "Interest rate reduction",
                "search_terms": ["rate cut"],
                "relevance_score": 0.8,
            },
        ],
        "relationships": [
            {
                "source_id": "powell",
                "target_id": "fed",
                "relationship_type": "influences",
                "description": "Chair of",
                "strength": 0.9,
            },
            {
                "source_id": "fed",
                "target_id": "rate-cut",
                "relationship_type": "announced",
                "description": "FOMC decision",
                "strength": 0.8,
            },
        ],
    }


# ══════════════════════════════════════════════════════════════════════
#  Delta recording
# ══════════════════════════════════════════════════════════════════════

class TestDeltaRecording:
    def test_record_node_delta(self, gm, run):
        node_id = uuid4()
        delta = gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, node_id,
            {"entity_type": "Organization", "label": "Federal Reserve"},
            sequence=0,
        )
        assert delta.delta_type == GraphDeltaType.NODE_CREATED
        assert delta.sequence_number == 0

    def test_record_delta_materialises_node(self, gm, run, repo):
        node_id = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, node_id,
            {"entity_type": "Organization", "label": "Federal Reserve"},
            sequence=0,
        )
        node = repo.get_graph_node_by_id(str(node_id))
        assert node is not None
        assert node.label == "Federal Reserve"
        assert node.entity_type == GraphEntityType.ORGANIZATION

    def test_record_delta_materialises_edge(self, gm, run, repo):
        n1 = uuid4()
        n2 = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, n1,
            {"entity_type": "Person", "label": "Powell"}, sequence=0,
        )
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, n2,
            {"entity_type": "Organization", "label": "Fed"}, sequence=1,
        )
        edge_id = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.EDGE_CREATED, edge_id,
            {"source": str(n1), "target": str(n2), "type": "influences", "weight": 0.9},
            sequence=2,
        )
        edges = repo.get_graph_edges(str(run.id))
        assert len(edges) == 1
        assert edges[0].relationship_type == "influences"
        assert edges[0].weight == 0.9

    def test_record_delta_persists_to_deltas_table(self, gm, run, repo):
        node_id = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, node_id,
            {"entity_type": "Person", "label": "X"}, sequence=0,
        )
        deltas = repo.get_graph_deltas(str(run.id))
        assert len(deltas) == 1
        assert deltas[0].target_id == node_id

    def test_record_delta_string_type(self, gm, run):
        delta = gm.record_delta(
            run.id, "node_created", uuid4(),
            {"entity_type": "Person", "label": "X"}, sequence=0,
        )
        assert delta.delta_type == GraphDeltaType.NODE_CREATED


# ══════════════════════════════════════════════════════════════════════
#  Graph reconstruction
# ══════════════════════════════════════════════════════════════════════

class TestGraphReconstruction:
    def test_get_run_graph_empty(self, gm, run):
        graph = gm.get_run_graph(str(run.id))
        assert graph["nodes"] == []
        assert graph["edges"] == []

    def test_get_run_graph_with_nodes_and_edges(self, gm, run):
        n1 = uuid4()
        n2 = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, n1,
            {"entity_type": "Person", "label": "Powell"}, sequence=0,
        )
        gm.record_delta(
            run.id, GraphDeltaType.NODE_CREATED, n2,
            {"entity_type": "Organization", "label": "Fed"}, sequence=1,
        )
        edge_id = uuid4()
        gm.record_delta(
            run.id, GraphDeltaType.EDGE_CREATED, edge_id,
            {"source": str(n1), "target": str(n2), "type": "influences"},
            sequence=2,
        )

        graph = gm.get_run_graph(str(run.id))
        assert len(graph["nodes"]) == 2
        assert len(graph["edges"]) == 1
        assert graph["edges"][0]["relationship_type"] == "influences"

    def test_reconstruction_matches_expected(self, gm, run):
        """Verify that reconstruction is deterministic and complete."""
        ontology = _sample_ontology()
        nodes, edges, deltas = gm.record_ontology(run.id, ontology, 0)

        graph = gm.get_run_graph(str(run.id))
        assert len(graph["nodes"]) == 3
        assert len(graph["edges"]) == 2

        # Node labels should match input
        labels = {n["label"] for n in graph["nodes"]}
        assert labels == {"Federal Reserve", "Jerome Powell", "Rate Cut"}

        # Edge types should match input
        edge_types = {e["relationship_type"] for e in graph["edges"]}
        assert edge_types == {"influences", "announced"}


# ══════════════════════════════════════════════════════════════════════
#  Ontology recording
# ══════════════════════════════════════════════════════════════════════

class TestOntologyRecording:
    def test_record_ontology(self, gm, run):
        ontology = _sample_ontology()
        nodes, edges, deltas = gm.record_ontology(run.id, ontology, 0)

        assert len(nodes) == 3
        assert len(edges) == 2
        assert len(deltas) == 5  # 3 nodes + 2 edges

    def test_record_ontology_deltas_sequential(self, gm, run, repo):
        ontology = _sample_ontology()
        gm.record_ontology(run.id, ontology, 10)

        deltas = repo.get_graph_deltas(str(run.id))
        seqs = [d.sequence_number for d in deltas]
        assert seqs == sorted(seqs)
        assert seqs[0] == 10

    def test_record_ontology_empty(self, gm, run):
        nodes, edges, deltas = gm.record_ontology(run.id, {}, 0)
        assert nodes == []
        assert edges == []
        assert deltas == []

    def test_record_ontology_missing_relationship_source(self, gm, run):
        """Relationships with invalid source/target IDs are skipped."""
        ontology = {
            "entities": [
                {"id": "a", "name": "A", "entity_type": "Person"},
            ],
            "relationships": [
                {"source_id": "a", "target_id": "nonexistent", "relationship_type": "x"},
            ],
        }
        nodes, edges, deltas = gm.record_ontology(run.id, ontology, 0)
        assert len(nodes) == 1
        assert len(edges) == 0
        assert len(deltas) == 1  # only node delta


# ══════════════════════════════════════════════════════════════════════
#  Deltas retrieval
# ══════════════════════════════════════════════════════════════════════

class TestGetDeltas:
    def test_get_deltas_all(self, gm, run):
        ontology = _sample_ontology()
        gm.record_ontology(run.id, ontology, 0)

        deltas = gm.get_deltas(str(run.id))
        assert len(deltas) == 5

    def test_get_deltas_after_sequence(self, gm, run):
        ontology = _sample_ontology()
        gm.record_ontology(run.id, ontology, 0)

        deltas = gm.get_deltas(str(run.id), after_sequence=3)
        # Should include seq 3 and 4 (total 5 deltas: 0,1,2,3,4)
        assert all(d.sequence_number >= 3 for d in deltas)


# ══════════════════════════════════════════════════════════════════════
#  Snapshots
# ══════════════════════════════════════════════════════════════════════

class TestSnapshots:
    def test_save_snapshot(self, gm, run):
        ontology = _sample_ontology()
        gm.record_ontology(run.id, ontology, 0)

        snapshot = gm.save_snapshot(str(run.id))
        assert snapshot.node_count == 3
        assert snapshot.edge_count == 2
        assert snapshot.delta_sequence_at == 4  # 0-indexed, last is 4
        assert len(snapshot.nodes_json["nodes"]) == 3
        assert len(snapshot.edges_json["edges"]) == 2

    def test_snapshot_persisted(self, gm, run, repo):
        ontology = _sample_ontology()
        gm.record_ontology(run.id, ontology, 0)

        gm.save_snapshot(str(run.id))
        loaded = repo.get_latest_graph_snapshot(str(run.id))
        assert loaded is not None
        assert loaded.node_count == 3

    def test_snapshot_empty_graph(self, gm, run):
        snapshot = gm.save_snapshot(str(run.id))
        assert snapshot.node_count == 0
        assert snapshot.edge_count == 0


# ══════════════════════════════════════════════════════════════════════
#  Replay determinism
# ══════════════════════════════════════════════════════════════════════

class TestReplayDeterminism:
    def test_replay_produces_same_events(self, repo, run):
        """Same run_id always produces identical event sequence from DB."""
        # Seed some SSE events
        for i in range(5):
            evt = SSEEvent(
                run_id=run.id,
                stage="attribution_streaming",
                event_type=SSEEventType.AGENT_ACTION,
                sequence=i,
                payload={"action": f"action_{i}"},
            )
            repo.save_sse_event(evt)

        # Replay twice
        events1 = repo.get_sse_events(str(run.id))
        events2 = repo.get_sse_events(str(run.id))

        assert len(events1) == len(events2) == 5
        for e1, e2 in zip(events1, events2):
            assert e1.sequence == e2.sequence
            assert e1.event_type == e2.event_type
            assert e1.payload == e2.payload

    def test_filtered_replay_deterministic(self, repo, run):
        """Filtered replay also deterministic."""
        for i, et in enumerate([
            SSEEventType.AGENT_ACTION,
            SSEEventType.GRAPH_DELTA,
            SSEEventType.AGENT_ACTION,
            SSEEventType.EVIDENCE_ADDED,
            SSEEventType.GRAPH_DELTA,
        ]):
            evt = SSEEvent(
                run_id=run.id, stage="test",
                event_type=et, sequence=i, payload={},
            )
            repo.save_sse_event(evt)

        filtered1 = repo.get_sse_events_filtered(
            str(run.id), event_types=["agent_action", "graph_delta"],
        )
        filtered2 = repo.get_sse_events_filtered(
            str(run.id), event_types=["agent_action", "graph_delta"],
        )

        assert len(filtered1) == len(filtered2) == 4
        for e1, e2 in zip(filtered1, filtered2):
            assert e1.sequence == e2.sequence

    def test_graph_reconstruction_deterministic(self, gm, run):
        """Graph reconstruction from deltas is deterministic."""
        gm.record_ontology(run.id, _sample_ontology(), 0)

        g1 = gm.get_run_graph(str(run.id))
        g2 = gm.get_run_graph(str(run.id))

        assert g1["nodes"] == g2["nodes"]
        assert g1["edges"] == g2["edges"]


# ══════════════════════════════════════════════════════════════════════
#  API endpoints
# ══════════════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    @pytest.fixture
    def client(self, monkeypatch):
        import src.api.server as server_mod

        conn = init_db(":memory:", check_same_thread=False)
        test_repo = RunRepository(conn)

        mock_llm_fn = MagicMock(return_value="mock")

        def fake_get_repo():
            return test_repo

        def fake_get_llm():
            return mock_llm_fn, mock_llm_fn

        monkeypatch.setattr(server_mod, "_repo", test_repo)
        monkeypatch.setattr(server_mod, "_get_repo", fake_get_repo)
        monkeypatch.setattr(server_mod, "_get_llm", fake_get_llm)
        monkeypatch.setattr(server_mod, "_graph_manager", None)
        monkeypatch.setattr(server_mod, "_interrogation_engine", None)

        return TestClient(server_mod.app), test_repo

    def _seed_run_with_graph(self, repo):
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)
        gm = GraphManager(db=repo)
        gm.record_ontology(run.id, _sample_ontology(), 0)
        return run

    def _seed_run_with_events(self, repo):
        run = AttributionRun(spike_event_id=uuid4(), market_id=uuid4())
        repo.create_run(run)
        for i, et in enumerate([
            SSEEventType.RUN_STARTED,
            SSEEventType.AGENT_ACTION,
            SSEEventType.GRAPH_DELTA,
            SSEEventType.AGENT_ACTION,
            SSEEventType.EVIDENCE_ADDED,
            SSEEventType.RUN_COMPLETED,
        ]):
            evt = SSEEvent(
                run_id=run.id, stage="test",
                event_type=et, sequence=i, payload={"i": i},
            )
            repo.save_sse_event(evt)
        return run

    def test_graph_endpoint(self, client):
        tc, repo = client
        run = self._seed_run_with_graph(repo)

        resp = tc.get(f"/api/runs/{run.id}/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] == 3
        assert data["edge_count"] == 2
        assert len(data["nodes"]) == 3

    def test_graph_endpoint_not_found(self, client):
        tc, _ = client
        resp = tc.get(f"/api/runs/{uuid4()}/graph")
        assert resp.status_code == 404

    def test_graph_deltas_endpoint(self, client):
        tc, repo = client
        run = self._seed_run_with_graph(repo)

        resp = tc.get(f"/api/runs/{run.id}/graph/deltas")
        assert resp.status_code == 200
        data = resp.json()
        assert data["delta_count"] == 5

    def test_graph_deltas_after_sequence(self, client):
        tc, repo = client
        run = self._seed_run_with_graph(repo)

        resp = tc.get(f"/api/runs/{run.id}/graph/deltas?after_sequence=3")
        assert resp.status_code == 200
        data = resp.json()
        assert all(d["sequence_number"] >= 3 for d in data["deltas"])

    def test_replay_endpoint_all_events(self, client):
        tc, repo = client
        run = self._seed_run_with_events(repo)

        resp = tc.get(f"/api/runs/{run.id}/replay")
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 6
        # Events in sequence order
        seqs = [e["sequence"] for e in data["events"]]
        assert seqs == sorted(seqs)

    def test_replay_endpoint_filtered(self, client):
        tc, repo = client
        run = self._seed_run_with_events(repo)

        resp = tc.get(
            f"/api/runs/{run.id}/replay?event_types=agent_action,graph_delta"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_count"] == 3
        for e in data["events"]:
            assert e["event_type"] in ("agent_action", "graph_delta")

    def test_replay_endpoint_after_sequence(self, client):
        tc, repo = client
        run = self._seed_run_with_events(repo)

        resp = tc.get(f"/api/runs/{run.id}/replay?after_sequence=3")
        assert resp.status_code == 200
        data = resp.json()
        assert all(e["sequence"] > 3 for e in data["events"])

    def test_replay_endpoint_not_found(self, client):
        tc, _ = client
        resp = tc.get(f"/api/runs/{uuid4()}/replay")
        assert resp.status_code == 404

    def test_replay_deterministic_across_calls(self, client):
        tc, repo = client
        run = self._seed_run_with_events(repo)

        resp1 = tc.get(f"/api/runs/{run.id}/replay")
        resp2 = tc.get(f"/api/runs/{run.id}/replay")
        assert resp1.json()["events"] == resp2.json()["events"]
