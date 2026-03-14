"""
Tests for the canonical SSE event system.

Covers:
  - Event envelope schema (all required fields present and typed)
  - SSE wire-format correctness (multi-line data, id field, retry directive)
  - Reconnect replays missed events via Last-Event-ID
  - Heartbeat presence during long streams
  - Run lifecycle endpoints (create, status, replay, cancel)
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest

from src.core.models import (
    RunStatus,
    SSEEvent,
    SSEEventType,
    SpikeEvent,
    SpikeType,
)
from src.core.persistence import RunRepository, init_db
from src.core.models import AttributionRun


# ── Helpers ───────────────────────────────────────────────────────────

def _make_event(
    run_id: UUID | None = None,
    sequence: int = 0,
    event_type: SSEEventType = SSEEventType.AGENT_ACTION,
    stage: str = "attribution_streaming",
    payload: dict | None = None,
) -> SSEEvent:
    return SSEEvent(
        run_id=run_id or uuid4(),
        stage=stage,
        event_type=event_type,
        sequence=sequence,
        payload=payload or {"test": True},
    )


def _parse_sse_frames(raw: str) -> list[dict]:
    """Parse raw SSE text into a list of event dicts."""
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


def _seed_run_with_events(repo: RunRepository, n_events: int = 5):
    """Create a run and seed it with SSE events. Returns (run, events)."""
    run = AttributionRun(
        spike_event_id=uuid4(),
        market_id=uuid4(),
        status=RunStatus.COMPLETED,
        metadata={"market_title": "Test Market"},
    )
    repo.create_run(run)

    events = []
    for i in range(n_events):
        evt = _make_event(run_id=run.id, sequence=i)
        repo.save_sse_event(evt)
        events.append(evt)

    return run, events


# ══════════════════════════════════════════════════════════════════════
#  1. Event envelope schema
# ══════════════════════════════════════════════════════════════════════

class TestEventEnvelopeSchema:
    """Every SSE event must contain all canonical envelope fields."""

    def test_envelope_has_all_required_fields(self):
        from src.api.server import format_sse_frame

        evt = _make_event()
        frame_str = format_sse_frame(evt)
        frames = _parse_sse_frames(frame_str)
        assert len(frames) == 1

        data = frames[0]["data"]
        required_fields = {
            "event_id", "run_id", "stage", "event_type",
            "sequence", "payload", "timestamp",
        }
        assert required_fields.issubset(data.keys()), (
            f"Missing fields: {required_fields - data.keys()}"
        )

    def test_event_id_is_valid_uuid(self):
        from src.api.server import format_sse_frame

        evt = _make_event()
        frame_str = format_sse_frame(evt)
        data = _parse_sse_frames(frame_str)[0]["data"]
        UUID(data["event_id"])  # raises if invalid

    def test_sequence_is_int(self):
        from src.api.server import format_sse_frame

        evt = _make_event(sequence=42)
        data = _parse_sse_frames(format_sse_frame(evt))[0]["data"]
        assert data["sequence"] == 42
        assert isinstance(data["sequence"], int)

    def test_timestamp_is_iso8601(self):
        from src.api.server import format_sse_frame

        evt = _make_event()
        data = _parse_sse_frames(format_sse_frame(evt))[0]["data"]
        datetime.fromisoformat(data["timestamp"])  # raises if invalid

    def test_event_type_matches_enum(self):
        from src.api.server import format_sse_frame

        for et in SSEEventType:
            evt = _make_event(event_type=et)
            frame = _parse_sse_frames(format_sse_frame(evt))[0]
            assert frame["event"] == et.value
            assert frame["data"]["event_type"] == et.value

    def test_payload_contains_custom_data(self):
        from src.api.server import format_sse_frame

        evt = _make_event(payload={"agent": "macro", "confidence": 0.82})
        data = _parse_sse_frames(format_sse_frame(evt))[0]["data"]
        assert data["payload"]["agent"] == "macro"
        assert data["payload"]["confidence"] == 0.82


# ══════════════════════════════════════════════════════════════════════
#  2. SSE wire format
# ══════════════════════════════════════════════════════════════════════

class TestSSEWireFormat:
    """Verify SSE frames are correctly formatted per the spec."""

    def test_frame_has_id_field(self):
        from src.api.server import format_sse_frame

        evt = _make_event(sequence=7)
        frame_str = format_sse_frame(evt)
        assert "id: 7\n" in frame_str

    def test_frame_has_retry_directive(self):
        from src.api.server import format_sse_frame

        evt = _make_event()
        frame_str = format_sse_frame(evt)
        assert "retry: 3000\n" in frame_str

    def test_frame_has_event_type_line(self):
        from src.api.server import format_sse_frame

        evt = _make_event(event_type=SSEEventType.HEARTBEAT)
        frame_str = format_sse_frame(evt)
        assert "event: heartbeat\n" in frame_str

    def test_frame_ends_with_double_newline(self):
        from src.api.server import format_sse_frame

        evt = _make_event()
        frame_str = format_sse_frame(evt)
        assert frame_str.endswith("\n\n")

    def test_multiline_json_doesnt_break_event(self):
        """Regression: payload with newlines must not split the SSE event."""
        from src.api.server import format_sse_frame

        # Payload with literal newlines in a string value
        evt = _make_event(payload={"content": "line1\nline2\nline3"})
        frame_str = format_sse_frame(evt)

        # Parse it back — should produce exactly one frame
        frames = _parse_sse_frames(frame_str)
        assert len(frames) == 1, f"Expected 1 frame, got {len(frames)}: {frame_str!r}"

        # The JSON should parse correctly
        data = frames[0]["data"]
        assert data["payload"]["content"] == "line1\nline2\nline3"

    def test_every_data_line_prefixed(self):
        """Every line containing data must start with 'data: '."""
        from src.api.server import format_sse_frame

        evt = _make_event()
        frame_str = format_sse_frame(evt)

        for line in frame_str.strip().split("\n"):
            if not line:
                continue
            assert any(line.startswith(p) for p in ("id: ", "event: ", "data: ", "retry: ")), (
                f"Unprefixed line in SSE frame: {line!r}"
            )


# ══════════════════════════════════════════════════════════════════════
#  3. Reconnect / replay
# ══════════════════════════════════════════════════════════════════════

class TestReconnect:
    """Last-Event-ID reconnect replays missed events."""

    def setup_method(self):
        self.conn = init_db(":memory:", check_same_thread=False)
        self.repo = RunRepository(self.conn)

    def test_replay_returns_all_events(self):
        """GET /replay returns all events for a completed run."""
        from fastapi.testclient import TestClient
        from src.api.server import app, _get_repo

        run, events = _seed_run_with_events(self.repo, n_events=5)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/replay")

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["events"]) == 5
        assert body["events"][0]["sequence"] == 0
        assert body["events"][4]["sequence"] == 4

    def test_replay_respects_after_sequence(self):
        """GET /replay?after_sequence=2 skips events 0-2."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, events = _seed_run_with_events(self.repo, n_events=5)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/replay?after_sequence=2")

        body = resp.json()
        assert len(body["events"]) == 2  # sequences 3 and 4
        assert body["events"][0]["sequence"] == 3

    def test_replay_event_envelope_schema(self):
        """Each replayed event has the canonical envelope."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, _ = _seed_run_with_events(self.repo, n_events=3)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/replay")

        for evt in resp.json()["events"]:
            required = {"event_id", "run_id", "stage", "event_type", "sequence", "payload", "timestamp"}
            assert required.issubset(evt.keys())

    def test_stream_completed_run_replays_events(self):
        """GET /stream on a completed run replays stored events."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, events = _seed_run_with_events(self.repo, n_events=3)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        # Should have at least the 3 stored events
        assert len(frames) >= 3

    def test_stream_with_last_event_id_skips_old(self):
        """Reconnect with Last-Event-ID skips already-seen events."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, events = _seed_run_with_events(self.repo, n_events=5)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            with client.stream(
                "GET", f"/api/runs/{run.id}/stream",
                headers={"Last-Event-ID": "2"},
            ) as resp:
                raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        # Should replay events with sequence > 2 (sequences 3, 4) + possible terminal
        sequences = [f["data"]["sequence"] for f in frames if "data" in f and "sequence" in f.get("data", {})]
        assert all(s > 2 for s in sequences if s < 100)  # heartbeats/terminal can have higher seqs


# ══════════════════════════════════════════════════════════════════════
#  4. Heartbeat
# ══════════════════════════════════════════════════════════════════════

class TestHeartbeat:
    """Heartbeat events are emitted during active streaming."""

    def test_heartbeat_event_has_correct_type(self):
        from src.api.server import format_sse_frame

        hb = _make_event(event_type=SSEEventType.HEARTBEAT, stage="heartbeat",
                         payload={"ts": "2025-01-01T00:00:00"})
        frame_str = format_sse_frame(hb)
        frame = _parse_sse_frames(frame_str)[0]
        assert frame["event"] == "heartbeat"
        assert frame["data"]["event_type"] == "heartbeat"

    def test_heartbeat_has_envelope(self):
        from src.api.server import format_sse_frame

        hb = _make_event(event_type=SSEEventType.HEARTBEAT, stage="heartbeat",
                         payload={"ts": "2025-01-01T00:00:00"})
        data = _parse_sse_frames(format_sse_frame(hb))[0]["data"]
        required = {"event_id", "run_id", "stage", "event_type", "sequence", "payload", "timestamp"}
        assert required.issubset(data.keys())


# ══════════════════════════════════════════════════════════════════════
#  5. Run lifecycle endpoints
# ══════════════════════════════════════════════════════════════════════

class TestRunEndpoints:
    """Test the run-centric REST endpoints."""

    def setup_method(self):
        self.conn = init_db(":memory:", check_same_thread=False)
        self.repo = RunRepository(self.conn)

    def test_create_run(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post("/api/runs", json={
                "market_title": "Will BTC hit 100k?",
                "timestamp": "2025-01-15T12:00:00Z",
                "direction": "up",
                "magnitude": 0.15,
                "price_before": 0.45,
                "price_after": 0.60,
                "depth": 2,
            })

        assert resp.status_code == 200
        body = resp.json()
        assert "run_id" in body
        assert body["status"] == "created"
        assert "/stream" in body["stream_url"]

        # Verify persisted
        run = self.repo.get_run(body["run_id"])
        assert run is not None
        assert run.status == RunStatus.CREATED

    def test_create_run_persists_spike_timestamp_for_hydration(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post("/api/runs", json={
                "market_title": "Will BTC hit 100k?",
                "timestamp": "2025-01-15T12:00:00Z",
                "direction": "up",
                "magnitude": 0.15,
                "price_before": 0.45,
                "price_after": 0.60,
                "depth": 2,
            })

        run = self.repo.get_run(resp.json()["run_id"])
        assert run is not None
        assert run.metadata["timestamp"] == "2025-01-15T12:00:00Z"
        assert run.metadata["spike_event"]["metadata"]["timestamp"] == "2025-01-15T12:00:00Z"
        assert run.metadata["spike_event"]["detected_at"] == "2025-01-15T12:00:00Z"

    def test_create_run_rejects_invalid_timestamp(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post("/api/runs", json={
                "market_title": "Will BTC hit 100k?",
                "timestamp": "not-a-date",
                "direction": "up",
                "magnitude": 0.15,
                "price_before": 0.45,
                "price_after": 0.60,
                "depth": 2,
            })

        assert resp.status_code == 422
        assert "Invalid timestamp" in resp.json()["detail"]

    def test_get_run_not_found(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{uuid4()}")
        assert resp.status_code == 404

    def test_get_run_status(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, _ = _seed_run_with_events(self.repo, n_events=1)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["run_id"] == str(run.id)
        assert body["status"] == "completed"

    def test_cancel_run(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(), market_id=uuid4(),
            status=RunStatus.ATTRIBUTION_STREAMING,
        )
        self.repo.create_run(run)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post(f"/api/runs/{run.id}/cancel")

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        updated = self.repo.get_run(str(run.id))
        assert updated.status == RunStatus.CANCELLED
        assert updated.error_message == "Run cancelled by user."

    def test_stream_persists_orchestrator_failure_message(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.CREATED,
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)

        class FailingOrchestrator:
            async def execute_run(self, **kwargs):
                raise RuntimeError("upstream evidence fetch failed")

        with patch("src.api.server._get_repo", return_value=self.repo), \
             patch("src.api.server._get_orchestrator", return_value=FailingOrchestrator()):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

            status_resp = client.get(f"/api/runs/{run.id}/status")
            run_resp = client.get(f"/api/runs/{run.id}")

        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames
        assert error_frames[0]["data"]["payload"]["error"] == "RuntimeError: upstream evidence fetch failed"
        assert error_frames[0]["data"]["payload"]["status"] == "failed_terminal"

        updated = self.repo.get_run(str(run.id))
        assert updated is not None
        assert updated.status == RunStatus.FAILED_TERMINAL
        assert updated.error_message == "RuntimeError: upstream evidence fetch failed"
        assert status_resp.json()["error_message"] == "RuntimeError: upstream evidence fetch failed"
        assert run_resp.json()["run"]["error_message"] == "RuntimeError: upstream evidence fetch failed"

    def test_stream_classifies_retryable_wrapper_failure(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.CREATED,
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)

        class FailingOrchestrator:
            async def execute_run(self, **kwargs):
                raise TimeoutError("upstream timed out")

        with patch("src.api.server._get_repo", return_value=self.repo), \
             patch("src.api.server._get_orchestrator", return_value=FailingOrchestrator()):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        updated = self.repo.get_run(str(run.id))
        assert updated is not None
        assert updated.status == RunStatus.FAILED_RETRYABLE
        assert updated.error_message == "TimeoutError: upstream timed out"
        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames[0]["data"]["payload"]["status"] == "failed_retryable"

    def test_stream_classifies_terminal_wrapper_failure(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.CREATED,
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)

        class FailingOrchestrator:
            async def execute_run(self, **kwargs):
                raise ValueError("bad payload")

        with patch("src.api.server._get_repo", return_value=self.repo), \
             patch("src.api.server._get_orchestrator", return_value=FailingOrchestrator()):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        updated = self.repo.get_run(str(run.id))
        assert updated is not None
        assert updated.status == RunStatus.FAILED_TERMINAL
        assert updated.error_message == "ValueError: bad payload"
        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames[0]["data"]["payload"]["status"] == "failed_terminal"

    def test_stream_invalid_ontology_payload_persists_useful_error(self):
        from src.core.run_orchestrator import RunOrchestrator

        async def malformed_stream(*args, **kwargs):
            yield {"step": "context", "data": {"market_title": "Test Market", "category": "crypto", "entities": []}}
            yield {"step": "ontology", "data": {
                "entity_count": 1,
                "relationship_count": 0,
                "search_queries": 1,
                "entities": ["BTC"],
            }}

        spike_event = SpikeEvent(
            market_id=uuid4(),
            spike_type=SpikeType.UP,
            magnitude=0.25,
            threshold_used=0.1,
            metadata={"market_title": "Test Market", "timestamp": "2025-01-15T12:00:00Z"},
        )
        captured: list[SSEEvent] = []
        orch = RunOrchestrator(self.repo)

        async def on_event(evt: SSEEvent) -> None:
            captured.append(evt)

        with patch("src.core.bace_parallel.attribute_spike_streaming", malformed_stream):
            result = asyncio.run(orch.execute_run(str(uuid4()), spike_event, on_event))

        updated = self.repo.get_run(str(result.id))
        assert updated is not None
        assert updated.status == RunStatus.FAILED_TERMINAL
        assert updated.error_message == "ValueError: Invalid ontology payload: entities[0] expected object, got str"
        assert captured[-1].event_type == SSEEventType.ERROR
        assert captured[-1].payload["error"] == updated.error_message

    def test_stream_uses_full_ontology_payload_for_graph_persistence(self):
        from src.core.run_orchestrator import RunOrchestrator

        async def valid_stream(*args, **kwargs):
            yield {"step": "context", "data": {"market_title": "Test Market", "category": "crypto", "entities": []}}
            yield {"step": "ontology", "data": {
                "entity_count": 1,
                "relationship_count": 0,
                "search_queries": 1,
                "entities": ["BTC"],
                "full_entities": [
                    {
                        "id": "btc",
                        "name": "BTC",
                        "entity_type": "Market",
                        "description": "Bitcoin",
                        "search_terms": ["BTC"],
                        "relevance_score": 0.9,
                    },
                ],
                "full_relationships": [],
            }}
            yield {"step": "result", "data": {
                "agent_hypotheses": [],
                "attribution": {"most_likely_cause": "No cause survived"},
                "elapsed_seconds": 0.1,
                "bace_metadata": {},
            }}

        spike_event = SpikeEvent(
            market_id=uuid4(),
            spike_type=SpikeType.UP,
            magnitude=0.25,
            threshold_used=0.1,
            metadata={"market_title": "Test Market", "timestamp": "2025-01-15T12:00:00Z"},
        )
        captured: list[SSEEvent] = []
        orch = RunOrchestrator(self.repo)

        async def on_event(evt: SSEEvent) -> None:
            captured.append(evt)

        with patch("src.core.bace_parallel.attribute_spike_streaming", valid_stream):
            result = asyncio.run(orch.execute_run(str(uuid4()), spike_event, on_event))

        updated = self.repo.get_run(str(result.id))
        assert updated is not None
        assert updated.status == RunStatus.COMPLETED
        assert updated.error_message is None
        assert any(evt.event_type == SSEEventType.RUN_COMPLETED for evt in captured)
        graph = self.repo.get_graph_nodes(str(result.id))
        assert len(graph) == 1
        assert graph[0].label == "BTC"

    def test_terminal_failed_run_stream_replays_persisted_error_message(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.FAILED_RETRYABLE,
            error_message="TimeoutError: upstream timed out",
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames
        payload = error_frames[0]["data"]["payload"]
        assert payload["status"] == "failed_retryable"
        assert payload["error"] == "TimeoutError: upstream timed out"

    def test_terminal_run_recovers_historical_null_error_from_sse_events(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.FAILED_TERMINAL,
            error_message=None,
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)
        self.repo.save_sse_event(SSEEvent(
            run_id=run.id,
            stage="error",
            event_type=SSEEventType.ERROR,
            sequence=0,
            payload={"run_id": str(run.id), "status": "failed_terminal", "error": "RuntimeError: recovered from event log"},
        ))

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        updated = self.repo.get_run(str(run.id))
        assert updated is not None
        assert updated.error_message == "RuntimeError: recovered from event log"
        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames[0]["data"]["payload"]["error"] == "RuntimeError: recovered from event log"

    def test_terminal_run_without_error_detail_uses_explicit_fallback(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run = AttributionRun(
            spike_event_id=uuid4(),
            market_id=uuid4(),
            status=RunStatus.FAILED_TERMINAL,
            error_message=None,
            metadata={"market_title": "Test Market"},
        )
        self.repo.create_run(run)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            with client.stream("GET", f"/api/runs/{run.id}/stream") as resp:
                raw = resp.read().decode()

        updated = self.repo.get_run(str(run.id))
        assert updated is not None
        assert updated.error_message is None
        frames = _parse_sse_frames(raw)
        error_frames = [f for f in frames if f.get("event") == "error"]
        assert error_frames[0]["data"]["payload"]["error"] == "Run failed."

    def test_cancel_completed_run_is_noop(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, _ = _seed_run_with_events(self.repo, n_events=1)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post(f"/api/runs/{run.id}/cancel")

        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_get_full_run(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, _ = _seed_run_with_events(self.repo, n_events=2)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run.id}")

        assert resp.status_code == 200
        body = resp.json()
        assert "run" in body
        assert "scenarios" in body
        assert "actions" in body
        assert "evidence" in body
        assert "graph_deltas" in body

    def test_resume_completed_run(self):
        from fastapi.testclient import TestClient
        from src.api.server import app

        run, _ = _seed_run_with_events(self.repo, n_events=1)

        with patch("src.api.server._get_repo", return_value=self.repo):
            client = TestClient(app)
            resp = client.post(f"/api/runs/{run.id}/resume")

        assert resp.status_code == 200
        assert "terminal" in resp.json()["message"]


# ══════════════════════════════════════════════════════════════════════
#  6. Legacy compat endpoint
# ══════════════════════════════════════════════════════════════════════

class TestLegacyCompat:
    """Legacy /api/attribute/stream wraps events in canonical envelopes."""

    def test_legacy_stream_uses_canonical_envelope(self):
        """Events from the legacy endpoint have the full envelope."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        async def mock_streaming(spike, llm_fast=None, llm_strong=None, depth=2, **kw):
            yield {"step": "context", "data": {"market_title": "Test", "category": "crypto"}}
            yield {"step": "result", "data": {
                "agent_hypotheses": [],
                "attribution": {"most_likely_cause": "test"},
                "bace_metadata": {},
            }}

        with patch("src.core.bace_parallel.attribute_spike_streaming", mock_streaming), \
             patch("src.api.server._get_llm", return_value=(lambda x: "ok", lambda x: "ok")):
            client = TestClient(app)
            with client.stream("GET", "/api/attribute/stream", params={
                "market_title": "Test",
                "timestamp": "2025-01-01T00:00:00Z",
                "direction": "up",
                "magnitude": 0.1,
                "price_before": 0.4,
                "price_after": 0.5,
            }) as resp:
                raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        assert len(frames) >= 2  # at least context + result + terminal

        for frame in frames:
            assert "id" in frame, f"Missing id: in frame: {frame}"
            assert "event" in frame, f"Missing event: in frame: {frame}"
            assert "data" in frame, f"Missing data in frame: {frame}"
            assert "retry" in frame, f"Missing retry: in frame: {frame}"

            data = frame["data"]
            required = {"event_id", "run_id", "stage", "event_type", "sequence", "payload", "timestamp"}
            assert required.issubset(data.keys()), f"Missing envelope fields: {required - data.keys()}"

    def test_legacy_stream_has_terminal_event(self):
        """Legacy stream ends with a run_completed event."""
        from fastapi.testclient import TestClient
        from src.api.server import app

        async def mock_streaming(spike, llm_fast=None, llm_strong=None, depth=2, **kw):
            yield {"step": "context", "data": {"market_title": "Test"}}

        with patch("src.core.bace_parallel.attribute_spike_streaming", mock_streaming), \
             patch("src.api.server._get_llm", return_value=(lambda x: "ok", lambda x: "ok")):
            client = TestClient(app)
            with client.stream("GET", "/api/attribute/stream", params={
                "market_title": "T", "timestamp": "2025-01-01T00:00:00Z",
                "direction": "up", "magnitude": 0.1,
                "price_before": 0.4, "price_after": 0.5,
            }) as resp:
                raw = resp.read().decode()

        frames = _parse_sse_frames(raw)
        last_frame = frames[-1]
        assert last_frame["event"] == "run_completed"
