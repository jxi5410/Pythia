"""
Durable run orchestrator — wraps existing BACE modules with persistence,
SSE event emission, checkpointing, and resume support.

This is an optional wrapper. Existing direct-call usage of bace_parallel.py
is unaffected.
"""

from __future__ import annotations

import asyncio
import logging
import time
import traceback
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from src.core.models import (
    AgentAction,
    AgentActionType,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    GovernanceDecision,
    GovernanceDecisionType,
    GraphDelta,
    GraphDeltaType,
    GraphEntityType,
    GraphNode,
    GraphEdge,
    RunCheckpoint,
    RunStatus,
    Scenario as PydanticScenario,
    ScenarioStatus,
    SSEEvent,
    SSEEventType,
    SpikeEvent,
)
from src.core.persistence import RunRepository

logger = logging.getLogger(__name__)

# ── Stage ordering (for resume) ──────────────────────────────────────

STAGE_ORDER = [
    "market_snapshot_complete",
    "attribution_started",
    "attribution_streaming",
    "scenario_clustering_complete",
    "graph_persisted",
    "interrogation_ready",
    "completed",
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Event-to-stage mapping ───────────────────────────────────────────

_STEP_TO_STAGE: dict[str, str] = {
    "context": "market_snapshot_complete",
    "ontology": "attribution_started",
    "evidence": "attribution_started",
    "agents": "attribution_started",
    "domain_evidence": "attribution_started",
    "proposal": "attribution_started",
    "sim_round": "attribution_streaming",
    "sim_action": "attribution_streaming",
    "sim_status": "attribution_streaming",
    "sim_complete": "attribution_streaming",
    "scenarios": "scenario_clustering_complete",
    "graph_update": "graph_persisted",
    "interaction": "attribution_streaming",
    "result": "completed",
}

# ── Retryable error classification ───────────────────────────────────

_RETRYABLE_ERRORS = (
    TimeoutError,
    ConnectionError,
    OSError,
)


def _is_retryable(exc: BaseException) -> bool:
    """Classify whether an exception warrants a retry."""
    if isinstance(exc, _RETRYABLE_ERRORS):
        return True
    msg = str(exc).lower()
    return any(tok in msg for tok in ("timeout", "rate_limit", "429", "503", "retry"))


# ── Adapters: legacy dataclasses → Pydantic models ──────────────────

def _sim_action_to_model(
    run_id: UUID, data: dict[str, Any], sequence: int,
) -> AgentAction:
    """Convert a sim_action SSE payload dict to an AgentAction model."""
    action_str = data.get("action", "PROPOSE")
    try:
        action_type = AgentActionType(action_str)
    except ValueError:
        action_type = AgentActionType.PROPOSE

    return AgentAction(
        run_id=run_id,
        agent_name=data.get("agent_name", data.get("agent", "")),
        action_type=action_type,
        sequence_number=sequence,
        round_number=data.get("round", 0),
        content=data.get("content", ""),
        confidence_before=data.get("confidence_before", 0.0),
        confidence_after=data.get("confidence_after", 0.0),
        metadata={"raw_event": data},
    )


def _evidence_to_model(
    run_id: UUID, data: dict[str, Any], agent_name: str = "",
) -> EvidenceItem:
    """Convert raw evidence dict to an EvidenceItem model."""
    source_type = EvidenceSourceType.OTHER
    raw_source = data.get("source", data.get("data_type", "other"))
    for st in EvidenceSourceType:
        if st.value == raw_source:
            source_type = st
            break

    return EvidenceItem(
        run_id=run_id,
        title=data.get("summary", data.get("title", ""))[:200],
        source_url=data.get("url"),
        source_type=source_type,
        summary=data.get("summary", ""),
        relevance_score=data.get("confidence", 0.0),
        provider_agent=agent_name or data.get("agent"),
    )


def _legacy_scenario_to_model(
    run_id: UUID, sc: dict[str, Any],
) -> PydanticScenario:
    """Convert a legacy bace_scenarios.Scenario dict to the Pydantic model."""
    tier = sc.get("tier", "primary")
    status_map = {
        "primary": ScenarioStatus.PRIMARY,
        "alternative": ScenarioStatus.ALTERNATIVE,
        "dismissed": ScenarioStatus.DISMISSED,
    }

    return PydanticScenario(
        run_id=run_id,
        title=sc.get("label", sc.get("id", "")),
        mechanism_type=sc.get("mechanism", "unknown"),
        summary=sc.get("causal_chain", ""),
        confidence_score=sc.get("confidence", 0.0),
        status=status_map.get(tier, ScenarioStatus.ALTERNATIVE),
        lead_agents=[sc["lead_agent"]] if sc.get("lead_agent") else [],
        supporting_agents=sc.get("supporting_agents", []),
        challenging_agents=sc.get("challenging_agents", []),
        what_breaks_this=[sc["what_breaks_this"]] if sc.get("what_breaks_this") else [],
        temporal_fit=sc.get("temporal_fit", ""),
        metadata={
            "hypothesis_ids": sc.get("hypothesis_ids", []),
            "evidence_urls": sc.get("evidence_urls", []),
            "impact_speed": sc.get("impact_speed", ""),
            "time_to_peak": sc.get("time_to_peak", ""),
        },
    )


def _ontology_to_graph_models(
    run_id: UUID, ontology_data: dict[str, Any], sequence_base: int,
) -> tuple[list[GraphNode], list[GraphEdge], list[GraphDelta]]:
    """Convert ontology event data to graph domain models."""
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    deltas: list[GraphDelta] = []
    seq = sequence_base

    entity_id_map: dict[str, UUID] = {}

    for ent in ontology_data.get("entities", []):
        node_id = uuid4()
        entity_id_map[ent.get("id", ent.get("name", ""))] = node_id

        entity_type = GraphEntityType.PERSON  # default
        raw_type = ent.get("entity_type", ent.get("type", ""))
        for gt in GraphEntityType:
            if gt.value == raw_type:
                entity_type = gt
                break

        node = GraphNode(
            id=node_id,
            run_id=run_id,
            entity_type=entity_type,
            label=ent.get("name", ""),
            properties={
                "description": ent.get("description", ""),
                "search_terms": ent.get("search_terms", []),
                "relevance_score": ent.get("relevance_score", 0.0),
            },
            created_at_sequence=seq,
        )
        nodes.append(node)

        delta = GraphDelta(
            run_id=run_id,
            delta_type=GraphDeltaType.NODE_CREATED,
            target_id=node_id,
            sequence_number=seq,
            payload={"entity_type": entity_type.value, "label": node.label},
        )
        deltas.append(delta)
        seq += 1

    for rel in ontology_data.get("relationships", []):
        src_id = entity_id_map.get(rel.get("source_id", ""))
        tgt_id = entity_id_map.get(rel.get("target_id", ""))
        if not src_id or not tgt_id:
            continue

        edge_id = uuid4()
        edge = GraphEdge(
            id=edge_id,
            run_id=run_id,
            source_node_id=src_id,
            target_node_id=tgt_id,
            relationship_type=rel.get("relationship_type", "related_to"),
            weight=rel.get("strength", 0.5),
            properties={
                "description": rel.get("description", ""),
                "temporal_order": rel.get("temporal_order"),
            },
            created_at_sequence=seq,
        )
        edges.append(edge)

        delta = GraphDelta(
            run_id=run_id,
            delta_type=GraphDeltaType.EDGE_CREATED,
            target_id=edge_id,
            sequence_number=seq,
            payload={
                "source": str(src_id),
                "target": str(tgt_id),
                "type": edge.relationship_type,
            },
        )
        deltas.append(delta)
        seq += 1

    return nodes, edges, deltas


# ══════════════════════════════════════════════════════════════════════
#  RunOrchestrator
# ══════════════════════════════════════════════════════════════════════

class RunOrchestrator:
    """Durable wrapper around the BACE streaming pipeline.

    Persists every domain object, emits typed SSE events, checkpoints
    periodically, and supports resume from the last completed stage.
    """

    def __init__(self, db: RunRepository, bace_depth: int = 2) -> None:
        self._db = db
        self._bace_depth = bace_depth
        # Lazy import to avoid circular dependency at module level
        from src.core.evidence_ledger import EvidenceLedger
        from src.core.graph_manager import GraphManager
        from src.core.scenario_engine import ScenarioEngine
        self._ledger = EvidenceLedger(db)
        self._scenario_engine = ScenarioEngine(db)
        self._graph_manager = GraphManager(db)

    # ── Public API ────────────────────────────────────────────────

    async def execute_run(
        self,
        market_id: str,
        spike_event: SpikeEvent,
        on_event: Callable[[SSEEvent], Awaitable[None]],
    ) -> AttributionRun:
        """Execute a full BACE attribution run with persistence and SSE."""
        run = AttributionRun(
            spike_event_id=spike_event.id,
            market_id=UUID(market_id) if isinstance(market_id, str) else market_id,
            status=RunStatus.CREATED,
            bace_depth=self._bace_depth,
        )
        self._db.create_run(run)

        seq = _SequenceCounter()
        run_id = run.id

        # Emit run_started
        await self._emit(on_event, run_id, "created", SSEEventType.RUN_STARTED, seq, {
            "run_id": str(run_id),
            "market_id": market_id,
            "spike_event_id": str(spike_event.id),
        })

        try:
            await self._run_pipeline(run, spike_event, on_event, seq)
        except Exception as exc:
            await self._handle_failure(run, exc, on_event, seq)

        return self._db.get_run(str(run_id)) or run

    async def resume_run(
        self,
        run_id: str,
        on_event: Callable[[SSEEvent], Awaitable[None]],
    ) -> AttributionRun:
        """Resume a failed/partial run from the last completed checkpoint."""
        run = self._db.get_run(run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        if run.status in (RunStatus.COMPLETED, RunStatus.CANCELLED):
            logger.info("Run %s already %s, nothing to resume", run_id, run.status.value)
            return run

        # Find the furthest completed stage
        resume_after_stage: str | None = None
        for stage in STAGE_ORDER:
            cp = self._db.get_latest_checkpoint(run_id, stage)
            if cp is not None:
                resume_after_stage = stage

        # Replay persisted SSE events so the client catches up
        existing_events = self._db.get_sse_events(run_id)
        for evt in existing_events:
            await on_event(evt)

        seq = _SequenceCounter(start=len(existing_events))

        self._db.update_run_status(run_id, RunStatus.ATTRIBUTION_STARTED)

        try:
            await self._run_pipeline(
                run, spike_event=None, on_event=on_event, seq=seq,
                resume_after_stage=resume_after_stage,
            )
        except Exception as exc:
            await self._handle_failure(run, exc, on_event, seq)

        return self._db.get_run(run_id) or run

    # ── Pipeline core ─────────────────────────────────────────────

    async def _run_pipeline(
        self,
        run: AttributionRun,
        spike_event: SpikeEvent | None,
        on_event: Callable[[SSEEvent], Awaitable[None]],
        seq: _SequenceCounter,
        resume_after_stage: str | None = None,
    ) -> None:
        run_id = run.id
        run_id_str = str(run_id)

        # Determine which stages to skip
        skip_until_after = None
        if resume_after_stage:
            skip_until_after = resume_after_stage

        # Build a mock spike object for attribute_spike_streaming
        spike_obj = self._build_spike_obj(run, spike_event)

        # Stage (a): market_snapshot_complete
        if not self._should_skip("market_snapshot_complete", skip_until_after):
            self._db.update_run_status(run_id_str, RunStatus.MARKET_SNAPSHOT_COMPLETE)
            await self._checkpoint(run_id, "market_snapshot_complete", {
                "spike_event_id": str(run.spike_event_id),
                "market_id": str(run.market_id),
            })
            await self._emit(
                on_event, run_id, "market_snapshot_complete",
                SSEEventType.CHECKPOINT_SAVED, seq,
                {"stage": "market_snapshot_complete"},
            )

        # Stages (b-g): stream through bace_parallel
        self._db.update_run_status(run_id_str, RunStatus.ATTRIBUTION_STARTED)

        from src.core.bace_parallel import attribute_spike_streaming

        current_stage = "attribution_started"
        action_seq = 0
        graph_delta_seq = 0
        actions_since_checkpoint = 0

        # Start heartbeat background task
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(run_id, on_event, seq)
        )

        try:
            async for event in attribute_spike_streaming(
                spike_obj, depth=self._bace_depth,
            ):
                step = event.get("step", "")
                data = event.get("data", {})

                # Map step to stage
                new_stage = _STEP_TO_STAGE.get(step)
                if new_stage and new_stage != current_stage:
                    if not self._should_skip(new_stage, skip_until_after):
                        current_stage = new_stage
                        status = self._stage_to_status(current_stage)
                        if status:
                            self._db.update_run_status(run_id_str, status)

                # Skip events for already-completed stages
                if self._should_skip(
                    _STEP_TO_STAGE.get(step, current_stage), skip_until_after
                ):
                    continue

                # Skip heartbeats from underlying pipeline (we emit our own)
                if step == "heartbeat":
                    continue

                # ── Process by step type ──────────────────────────

                if step == "context":
                    await self._emit(
                        on_event, run_id, "market_snapshot_complete",
                        SSEEventType.RUN_STARTED, seq, data,
                    )

                elif step == "ontology":
                    # Persist graph nodes/edges/deltas via GraphManager
                    nodes, edges, deltas = (
                        self._graph_manager.record_ontology(
                            run_id, data, graph_delta_seq,
                        )
                    )
                    graph_delta_seq += len(deltas)

                    await self._emit(
                        on_event, run_id, "attribution_started",
                        SSEEventType.GRAPH_DELTA, seq,
                        {"nodes": len(nodes), "edges": len(edges)},
                    )

                elif step == "evidence":
                    await self._emit(
                        on_event, run_id, "attribution_started",
                        SSEEventType.EVIDENCE_ADDED, seq, data,
                    )

                elif step == "domain_evidence":
                    await self._emit(
                        on_event, run_id, "attribution_started",
                        SSEEventType.EVIDENCE_ADDED, seq,
                        {"domain": True, **data},
                    )

                elif step == "proposal":
                    # Each proposal contains agent hypotheses — ingest
                    # through the evidence ledger for normalization,
                    # deduplication, and scoring.
                    agent_name = data.get("agent", "")
                    ingested = 0
                    for hyp in data.get("hypotheses", []):
                        item = self._ledger.ingest_evidence(
                            run_id, hyp, provider_agent=agent_name,
                        )
                        if item is not None:
                            ingested += 1

                    await self._emit(
                        on_event, run_id, "attribution_started",
                        SSEEventType.EVIDENCE_ADDED, seq, {
                            "agent": agent_name,
                            "count": ingested,
                        },
                    )

                elif step == "sim_action":
                    action = _sim_action_to_model(run_id, data, action_seq)
                    self._db.save_action(action)
                    action_seq += 1
                    actions_since_checkpoint += 1

                    await self._emit(
                        on_event, run_id, "attribution_streaming",
                        SSEEventType.AGENT_ACTION, seq, data,
                    )

                    # Checkpoint every 10 actions
                    if actions_since_checkpoint >= 10:
                        await self._checkpoint(run_id, "attribution_streaming", {
                            "last_action_seq": action_seq,
                            "graph_delta_seq": graph_delta_seq,
                        })
                        actions_since_checkpoint = 0

                elif step == "sim_round":
                    await self._emit(
                        on_event, run_id, "attribution_streaming",
                        SSEEventType.AGENT_ACTION, seq, data,
                    )

                elif step == "sim_status":
                    await self._emit(
                        on_event, run_id, "attribution_streaming",
                        SSEEventType.AGENT_ACTION, seq, data,
                    )

                elif step == "sim_complete":
                    await self._checkpoint(run_id, "attribution_streaming", {
                        "total_actions": action_seq,
                        "graph_delta_seq": graph_delta_seq,
                        "sim_complete": True,
                    })
                    await self._emit(
                        on_event, run_id, "attribution_streaming",
                        SSEEventType.CHECKPOINT_SAVED, seq,
                        {"stage": "attribution_streaming"},
                    )

                    # Cluster persisted actions into formal Scenario
                    # objects via the ScenarioEngine.
                    try:
                        db_actions = self._db.get_actions(run_id_str)
                        db_evidence = self._db.get_evidence(run_id_str)
                        if db_actions:
                            engine_scenarios = (
                                self._scenario_engine.cluster_from_actions(
                                    run_id, db_actions, db_evidence,
                                )
                            )
                            for esc in engine_scenarios:
                                await self._emit(
                                    on_event, run_id,
                                    "scenario_clustering_complete",
                                    SSEEventType.SCENARIO_CREATED, seq,
                                    {"title": esc.title,
                                     "tier": esc.status.value,
                                     "source": "scenario_engine"},
                                )
                    except Exception as e:
                        logger.warning(
                            "ScenarioEngine clustering failed: %s", e,
                        )

                elif step == "interaction":
                    await self._emit(
                        on_event, run_id, "attribution_streaming",
                        SSEEventType.AGENT_ACTION, seq, data,
                    )

                elif step == "scenarios":
                    self._db.update_run_status(
                        run_id_str, RunStatus.SCENARIO_CLUSTERING_COMPLETE,
                    )
                    current_stage = "scenario_clustering_complete"

                    # Persist each scenario
                    for tier in ("primary", "alternative", "dismissed"):
                        for sc_data in data.get(tier, []):
                            sc_model = _legacy_scenario_to_model(run_id, sc_data)
                            self._db.save_scenario(sc_model)

                            await self._emit(
                                on_event, run_id, "scenario_clustering_complete",
                                SSEEventType.SCENARIO_CREATED, seq,
                                {"title": sc_model.title, "tier": tier},
                            )

                    await self._checkpoint(
                        run_id, "scenario_clustering_complete",
                        {"scenario_count": data.get("total", 0)},
                    )

                elif step == "graph_update":
                    self._db.update_run_status(
                        run_id_str, RunStatus.GRAPH_PERSISTED,
                    )
                    current_stage = "graph_persisted"

                    await self._emit(
                        on_event, run_id, "graph_persisted",
                        SSEEventType.GRAPH_DELTA, seq, data,
                    )
                    await self._checkpoint(run_id, "graph_persisted", data)

                elif step == "result":
                    # Terminal stage
                    self._db.update_run_status(
                        run_id_str, RunStatus.INTERROGATION_READY,
                    )
                    await self._checkpoint(
                        run_id, "interrogation_ready",
                        {"has_result": True},
                    )

                    self._db.update_run_status(run_id_str, RunStatus.COMPLETED)
                    await self._checkpoint(run_id, "completed", {
                        "elapsed_seconds": data.get("elapsed_seconds"),
                        "scenario_count": data.get("bace_metadata", {}).get(
                            "scenario_count", 0
                        ),
                    })
                    await self._emit(
                        on_event, run_id, "completed",
                        SSEEventType.RUN_COMPLETED, seq, {
                            "run_id": str(run_id),
                            "status": "completed",
                            "elapsed_seconds": data.get("elapsed_seconds"),
                        },
                    )

        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    # ── Helpers ───────────────────────────────────────────────────

    async def _emit(
        self,
        on_event: Callable[[SSEEvent], Awaitable[None]],
        run_id: UUID,
        stage: str,
        event_type: SSEEventType,
        seq: _SequenceCounter,
        payload: dict[str, Any],
    ) -> None:
        """Build, persist, and deliver an SSE event."""
        event = SSEEvent(
            run_id=run_id,
            stage=stage,
            event_type=event_type,
            sequence=seq.next(),
            payload=payload,
        )
        self._db.save_sse_event(event)
        await on_event(event)

    async def _checkpoint(
        self, run_id: UUID, stage: str, snapshot: dict[str, Any],
    ) -> None:
        """Save a run checkpoint for the given stage."""
        # Determine version by checking existing checkpoints
        existing = self._db.get_latest_checkpoint(str(run_id), stage)
        version = (existing.checkpoint_version + 1) if existing else 1

        cp = RunCheckpoint(
            run_id=run_id,
            stage=stage,
            checkpoint_version=version,
            state_snapshot=snapshot,
        )
        self._db.save_checkpoint(cp)

    async def _heartbeat_loop(
        self,
        run_id: UUID,
        on_event: Callable[[SSEEvent], Awaitable[None]],
        seq: _SequenceCounter,
    ) -> None:
        """Emit heartbeat SSEEvents every 5 seconds until cancelled."""
        while True:
            await asyncio.sleep(5)
            event = SSEEvent(
                run_id=run_id,
                stage="heartbeat",
                event_type=SSEEventType.HEARTBEAT,
                sequence=seq.next(),
                payload={"ts": _utcnow().isoformat()},
            )
            self._db.save_sse_event(event)
            await on_event(event)

    async def _handle_failure(
        self,
        run: AttributionRun,
        exc: BaseException,
        on_event: Callable[[SSEEvent], Awaitable[None]],
        seq: _SequenceCounter,
    ) -> None:
        """Classify the error, persist it, and emit an error SSE event."""
        run_id_str = str(run.id)
        error_msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        logger.error("Run %s failed: %s\n%s", run_id_str, error_msg, tb)

        status = (
            RunStatus.FAILED_RETRYABLE if _is_retryable(exc)
            else RunStatus.FAILED_TERMINAL
        )
        self._db.update_run_status(run_id_str, status, error_message=error_msg)

        await self._emit(on_event, run.id, "error", SSEEventType.ERROR, seq, {
            "run_id": run_id_str,
            "error": error_msg,
            "retryable": status == RunStatus.FAILED_RETRYABLE,
        })

    @staticmethod
    def _should_skip(stage: str | None, skip_until_after: str | None) -> bool:
        """Return True if this stage was already completed in a previous run."""
        if skip_until_after is None or stage is None:
            return False
        try:
            return STAGE_ORDER.index(stage) <= STAGE_ORDER.index(skip_until_after)
        except ValueError:
            return False

    @staticmethod
    def _stage_to_status(stage: str) -> RunStatus | None:
        """Map a stage name to the corresponding RunStatus."""
        mapping = {
            "market_snapshot_complete": RunStatus.MARKET_SNAPSHOT_COMPLETE,
            "attribution_started": RunStatus.ATTRIBUTION_STARTED,
            "attribution_streaming": RunStatus.ATTRIBUTION_STREAMING,
            "scenario_clustering_complete": RunStatus.SCENARIO_CLUSTERING_COMPLETE,
            "graph_persisted": RunStatus.GRAPH_PERSISTED,
            "interrogation_ready": RunStatus.INTERROGATION_READY,
            "completed": RunStatus.COMPLETED,
        }
        return mapping.get(stage)

    @staticmethod
    def _build_spike_obj(
        run: AttributionRun, spike_event: SpikeEvent | None,
    ) -> _SpikeAdapter:
        """Build a spike-like object compatible with bace_parallel."""
        return _SpikeAdapter(
            id=str(run.spike_event_id),
            market_id=str(run.market_id),
            spike_event=spike_event,
        )


# ── Internal helpers ──────────────────────────────────────────────────

class _SequenceCounter:
    """Monotonic sequence counter for SSE events within a run."""

    def __init__(self, start: int = 0) -> None:
        self._value = start

    def next(self) -> int:
        val = self._value
        self._value += 1
        return val

    @property
    def current(self) -> int:
        return self._value


class _SpikeAdapter:
    """Minimal spike-like object for bace_parallel compatibility.

    build_spike_context() accesses: timestamp, market_title, direction,
    magnitude, price_before, price_after, volume_at_spike, market_id.
    This adapter satisfies that interface using data from our Pydantic models.
    """

    def __init__(
        self,
        id: str,
        market_id: str,
        spike_event: SpikeEvent | None = None,
    ) -> None:
        self.id = id
        self.market_id = market_id
        meta = spike_event.metadata if spike_event else {}

        if spike_event:
            self.magnitude = spike_event.magnitude
            self.timestamp = spike_event.detected_at.isoformat()
            self.direction = spike_event.spike_type.value
        else:
            self.magnitude = 0.0
            self.timestamp = _utcnow().isoformat()
            self.direction = "up"

        # Fields accessed by build_spike_context / bace_parallel
        self.market_title = meta.get("market_title", "")
        self.price_before = meta.get("price_before", 0.0)
        self.price_after = meta.get("price_after", 0.0)
        self.volume_at_spike = meta.get("volume_at_spike", 0)
        self._metadata = meta

    def __getattr__(self, name: str) -> Any:
        """Fall back to metadata for any attribute bace_parallel might access."""
        try:
            return self._metadata[name]
        except KeyError:
            return None
