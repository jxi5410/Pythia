"""
SQLite persistence layer for Pythia's run-centric architecture.

Uses WAL mode for concurrent reads, parameterized queries throughout,
and idempotent writes for agent actions and SSE events.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from src.core.models import (
    AgentAction,
    AgentActionType,
    AnswerMode,
    AttributionRun,
    EvidenceItem,
    EvidenceSourceType,
    EvidenceStance,
    GovernanceDecision,
    GovernanceDecisionType,
    GraphDelta,
    GraphDeltaType,
    GraphEntityType,
    InterrogationTargetType,
    InterrogationRole,
    RunCheckpoint,
    RunStatus,
    SSEEvent,
    SSEEventType,
    Scenario,
    ScenarioEvidenceLink,
    ScenarioEvidenceLinkType,
    ScenarioRevision,
    ScenarioRevisionType,
    ScenarioStatus,
    SpikeEvent,
    SpikeType,
)

# ── Schema DDL ────────────────────────────────────────────────────────

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    spike_event_id TEXT NOT NULL,
    market_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'created',
    bace_depth INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    error_message TEXT,
    cost_total_usd REAL NOT NULL DEFAULT 0.0,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS spike_events (
    id TEXT PRIMARY KEY,
    market_id TEXT NOT NULL,
    spike_type TEXT NOT NULL,
    magnitude REAL NOT NULL,
    detected_at TEXT NOT NULL,
    threshold_used REAL NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    action_type TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    round_number INTEGER NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    confidence_before REAL NOT NULL DEFAULT 0.0,
    confidence_after REAL NOT NULL DEFAULT 0.0,
    target_scenario_id TEXT,
    evidence_ids TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_actions_run_seq
    ON agent_actions (run_id, sequence_number);

CREATE TABLE IF NOT EXISTS evidence_items (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    source_url TEXT,
    source_type TEXT NOT NULL DEFAULT 'other',
    publication_timestamp TEXT,
    retrieval_timestamp TEXT NOT NULL,
    provider_agent TEXT,
    summary TEXT NOT NULL DEFAULT '',
    relevance_score REAL NOT NULL DEFAULT 0.0,
    freshness_score REAL NOT NULL DEFAULT 0.0,
    confidence_impact REAL NOT NULL DEFAULT 0.0,
    stance TEXT NOT NULL DEFAULT 'neutral',
    linked_entity_ids TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_evidence_items_run
    ON evidence_items (run_id);

CREATE TABLE IF NOT EXISTS scenarios (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    title TEXT NOT NULL,
    mechanism_type TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    confidence_score REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'primary',
    lead_agents TEXT NOT NULL DEFAULT '[]',
    supporting_agents TEXT NOT NULL DEFAULT '[]',
    challenging_agents TEXT NOT NULL DEFAULT '[]',
    what_breaks_this TEXT NOT NULL DEFAULT '[]',
    temporal_fit TEXT NOT NULL DEFAULT '',
    unresolved_questions TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    metadata TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_scenarios_run
    ON scenarios (run_id);

CREATE TABLE IF NOT EXISTS scenario_revisions (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    revision_type TEXT NOT NULL,
    previous_confidence REAL NOT NULL,
    new_confidence REAL NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    triggering_action_id TEXT,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenario_revisions_scenario
    ON scenario_revisions (scenario_id);

CREATE TABLE IF NOT EXISTS scenario_evidence_links (
    id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    link_type TEXT NOT NULL,
    agent_name TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scenario_evidence_links_scenario
    ON scenario_evidence_links (scenario_id);
CREATE INDEX IF NOT EXISTS idx_scenario_evidence_links_evidence
    ON scenario_evidence_links (evidence_id);

CREATE TABLE IF NOT EXISTS graph_nodes (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at_sequence INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_graph_nodes_run
    ON graph_nodes (run_id);

CREATE TABLE IF NOT EXISTS graph_edges (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    source_node_id TEXT NOT NULL,
    target_node_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    properties TEXT NOT NULL DEFAULT '{}',
    created_at_sequence INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_graph_edges_run
    ON graph_edges (run_id);

CREATE TABLE IF NOT EXISTS graph_deltas (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    delta_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    sequence_number INTEGER NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_graph_deltas_run_seq
    ON graph_deltas (run_id, sequence_number);

CREATE TABLE IF NOT EXISTS interrogation_sessions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interrogation_sessions_run
    ON interrogation_sessions (run_id);

CREATE TABLE IF NOT EXISTS interrogation_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    answer_mode TEXT NOT NULL DEFAULT 'concise',
    referenced_artifact_ids TEXT NOT NULL DEFAULT '[]',
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_interrogation_messages_session
    ON interrogation_messages (session_id);

CREATE TABLE IF NOT EXISTS governance_events (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    decision_type TEXT NOT NULL,
    stage TEXT NOT NULL,
    input_context TEXT NOT NULL DEFAULT '{}',
    outcome TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_governance_events_run
    ON governance_events (run_id);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    checkpoint_version INTEGER NOT NULL DEFAULT 1,
    state_snapshot TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_stage
    ON run_checkpoints (run_id, stage);

CREATE TABLE IF NOT EXISTS sse_events (
    event_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    event_type TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    timestamp TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sse_events_run_seq
    ON sse_events (run_id, sequence);
"""


# ── Helpers ───────────────────────────────────────────────────────────

def _str(val: UUID | str | None) -> str | None:
    if val is None:
        return None
    return str(val)


def _json(val: Any) -> str:
    return json.dumps(val, default=str)


def _iso(val: datetime | None) -> str | None:
    if val is None:
        return None
    return val.isoformat()


def _parse_dt(val: str | None) -> datetime | None:
    if val is None:
        return None
    return datetime.fromisoformat(val)


def _parse_uuid(val: str | None) -> UUID | None:
    if val is None:
        return None
    return UUID(val)


def _parse_json(val: str | None) -> Any:
    if val is None:
        return {}
    return json.loads(val)


def _parse_uuid_list(val: str | None) -> list[UUID]:
    raw = _parse_json(val)
    return [UUID(x) if isinstance(x, str) else x for x in raw]


# ── Init ──────────────────────────────────────────────────────────────

def init_db(db_path: str, check_same_thread: bool = True) -> sqlite3.Connection:
    """Create all tables if they don't exist. Uses WAL mode for concurrent reads."""
    conn = sqlite3.connect(db_path, check_same_thread=check_same_thread)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    return conn


# ── Repository ────────────────────────────────────────────────────────

class RunRepository:
    """Data-access layer for all run-centric domain objects."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Runs ──────────────────────────────────────────────────────

    def create_run(self, run: AttributionRun) -> AttributionRun:
        self._conn.execute(
            """INSERT INTO runs
               (id, spike_event_id, market_id, status, bace_depth,
                created_at, updated_at, completed_at, error_message,
                cost_total_usd, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(run.id), _str(run.spike_event_id), _str(run.market_id),
                run.status.value, run.bace_depth,
                _iso(run.created_at), _iso(run.updated_at),
                _iso(run.completed_at), run.error_message,
                run.cost_total_usd, _json(run.metadata),
            ),
        )
        self._conn.commit()
        return run

    def get_run(self, run_id: str) -> AttributionRun | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_run(row)

    def update_run_status(
        self, run_id: str, status: RunStatus, error_message: str | None = None
    ) -> None:
        now = _iso(datetime.now(timezone.utc))
        completed_at = now if status in (
            RunStatus.COMPLETED, RunStatus.FAILED_TERMINAL,
            RunStatus.CANCELLED, RunStatus.PARTIAL_COMPLETE,
        ) else None
        self._conn.execute(
            """UPDATE runs
               SET status = ?, updated_at = ?, completed_at = COALESCE(?, completed_at),
                   error_message = COALESCE(?, error_message)
               WHERE id = ?""",
            (status.value, now, completed_at, error_message, run_id),
        )
        self._conn.commit()

    def list_runs(self, limit: int = 50, offset: int = 0) -> list[AttributionRun]:
        rows = self._conn.execute(
            "SELECT * FROM runs ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_run(r) for r in rows]

    @staticmethod
    def _row_to_run(row: sqlite3.Row) -> AttributionRun:
        return AttributionRun(
            id=UUID(row["id"]),
            spike_event_id=UUID(row["spike_event_id"]),
            market_id=UUID(row["market_id"]),
            status=RunStatus(row["status"]),
            bace_depth=row["bace_depth"],
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            completed_at=_parse_dt(row["completed_at"]),
            error_message=row["error_message"],
            cost_total_usd=row["cost_total_usd"],
            metadata=_parse_json(row["metadata"]),
        )

    # ── Checkpoints ───────────────────────────────────────────────

    def save_checkpoint(self, checkpoint: RunCheckpoint) -> None:
        self._conn.execute(
            """INSERT INTO run_checkpoints
               (id, run_id, stage, checkpoint_version, state_snapshot, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _str(checkpoint.id), _str(checkpoint.run_id),
                checkpoint.stage, checkpoint.checkpoint_version,
                _json(checkpoint.state_snapshot), _iso(checkpoint.created_at),
            ),
        )
        self._conn.commit()

    def get_latest_checkpoint(self, run_id: str, stage: str) -> RunCheckpoint | None:
        row = self._conn.execute(
            """SELECT * FROM run_checkpoints
               WHERE run_id = ? AND stage = ?
               ORDER BY checkpoint_version DESC LIMIT 1""",
            (run_id, stage),
        ).fetchone()
        if row is None:
            return None
        return RunCheckpoint(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            stage=row["stage"],
            checkpoint_version=row["checkpoint_version"],
            state_snapshot=_parse_json(row["state_snapshot"]),
            created_at=_parse_dt(row["created_at"]),
        )

    # ── Agent actions (idempotent on run_id + sequence_number) ────

    def save_action(self, action: AgentAction) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO agent_actions
               (id, run_id, agent_name, action_type, sequence_number,
                round_number, content, confidence_before, confidence_after,
                target_scenario_id, evidence_ids, timestamp, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(action.id), _str(action.run_id), action.agent_name,
                action.action_type.value, action.sequence_number,
                action.round_number, action.content,
                action.confidence_before, action.confidence_after,
                _str(action.target_scenario_id),
                _json(action.evidence_ids), _iso(action.timestamp),
                _json(action.metadata),
            ),
        )
        self._conn.commit()

    def get_actions(self, run_id: str, after_sequence: int = -1) -> list[AgentAction]:
        rows = self._conn.execute(
            """SELECT * FROM agent_actions
               WHERE run_id = ? AND sequence_number > ?
               ORDER BY sequence_number""",
            (run_id, after_sequence),
        ).fetchall()
        return [self._row_to_action(r) for r in rows]

    @staticmethod
    def _row_to_action(row: sqlite3.Row) -> AgentAction:
        return AgentAction(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            agent_name=row["agent_name"],
            action_type=AgentActionType(row["action_type"]),
            sequence_number=row["sequence_number"],
            round_number=row["round_number"],
            content=row["content"],
            confidence_before=row["confidence_before"],
            confidence_after=row["confidence_after"],
            target_scenario_id=_parse_uuid(row["target_scenario_id"]),
            evidence_ids=_parse_uuid_list(row["evidence_ids"]),
            timestamp=_parse_dt(row["timestamp"]),
            metadata=_parse_json(row["metadata"]),
        )

    # ── Evidence ──────────────────────────────────────────────────

    def save_evidence(self, evidence: EvidenceItem) -> None:
        self._conn.execute(
            """INSERT INTO evidence_items
               (id, run_id, title, source_url, source_type,
                publication_timestamp, retrieval_timestamp, provider_agent,
                summary, relevance_score, freshness_score, confidence_impact,
                stance, linked_entity_ids, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(evidence.id), _str(evidence.run_id), evidence.title,
                evidence.source_url, evidence.source_type.value,
                _iso(evidence.publication_timestamp),
                _iso(evidence.retrieval_timestamp), evidence.provider_agent,
                evidence.summary, evidence.relevance_score,
                evidence.freshness_score, evidence.confidence_impact,
                evidence.stance.value,
                _json(evidence.linked_entity_ids), _json(evidence.metadata),
            ),
        )
        self._conn.commit()

    def get_evidence(self, run_id: str) -> list[EvidenceItem]:
        rows = self._conn.execute(
            "SELECT * FROM evidence_items WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [self._row_to_evidence(r) for r in rows]

    @staticmethod
    def _row_to_evidence(row: sqlite3.Row) -> EvidenceItem:
        return EvidenceItem(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            title=row["title"],
            source_url=row["source_url"],
            source_type=EvidenceSourceType(row["source_type"]),
            publication_timestamp=_parse_dt(row["publication_timestamp"]),
            retrieval_timestamp=_parse_dt(row["retrieval_timestamp"]),
            provider_agent=row["provider_agent"],
            summary=row["summary"],
            relevance_score=row["relevance_score"],
            freshness_score=row["freshness_score"],
            confidence_impact=row["confidence_impact"],
            stance=EvidenceStance(row["stance"]),
            linked_entity_ids=_parse_uuid_list(row["linked_entity_ids"]),
            metadata=_parse_json(row["metadata"]),
        )

    # ── Scenarios ─────────────────────────────────────────────────

    def save_scenario(self, scenario: Scenario) -> None:
        self._conn.execute(
            """INSERT INTO scenarios
               (id, run_id, title, mechanism_type, summary, confidence_score,
                status, lead_agents, supporting_agents, challenging_agents,
                what_breaks_this, temporal_fit, unresolved_questions,
                created_at, updated_at, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(scenario.id), _str(scenario.run_id), scenario.title,
                scenario.mechanism_type, scenario.summary,
                scenario.confidence_score, scenario.status.value,
                _json(scenario.lead_agents), _json(scenario.supporting_agents),
                _json(scenario.challenging_agents),
                _json(scenario.what_breaks_this), scenario.temporal_fit,
                _json(scenario.unresolved_questions),
                _iso(scenario.created_at), _iso(scenario.updated_at),
                _json(scenario.metadata),
            ),
        )
        self._conn.commit()

    def get_scenarios(self, run_id: str) -> list[Scenario]:
        rows = self._conn.execute(
            "SELECT * FROM scenarios WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [self._row_to_scenario(r) for r in rows]

    @staticmethod
    def _row_to_scenario(row: sqlite3.Row) -> Scenario:
        return Scenario(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            title=row["title"],
            mechanism_type=row["mechanism_type"],
            summary=row["summary"],
            confidence_score=row["confidence_score"],
            status=ScenarioStatus(row["status"]),
            lead_agents=_parse_json(row["lead_agents"]),
            supporting_agents=_parse_json(row["supporting_agents"]),
            challenging_agents=_parse_json(row["challenging_agents"]),
            what_breaks_this=_parse_json(row["what_breaks_this"]),
            temporal_fit=row["temporal_fit"],
            unresolved_questions=_parse_json(row["unresolved_questions"]),
            created_at=_parse_dt(row["created_at"]),
            updated_at=_parse_dt(row["updated_at"]),
            metadata=_parse_json(row["metadata"]),
        )

    # ── Scenario revisions ────────────────────────────────────────

    def save_scenario_revision(self, revision: ScenarioRevision) -> None:
        self._conn.execute(
            """INSERT INTO scenario_revisions
               (id, scenario_id, run_id, revision_type,
                previous_confidence, new_confidence, reason,
                triggering_action_id, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(revision.id), _str(revision.scenario_id),
                _str(revision.run_id), revision.revision_type.value,
                revision.previous_confidence, revision.new_confidence,
                revision.reason, _str(revision.triggering_action_id),
                _iso(revision.timestamp),
            ),
        )
        self._conn.commit()

    # ── Scenario-evidence links ───────────────────────────────────

    def save_evidence_link(self, link: ScenarioEvidenceLink) -> None:
        self._conn.execute(
            """INSERT INTO scenario_evidence_links
               (id, scenario_id, evidence_id, link_type, agent_name, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                _str(link.id), _str(link.scenario_id),
                _str(link.evidence_id), link.link_type.value,
                link.agent_name, _iso(link.created_at),
            ),
        )
        self._conn.commit()

    # ── Graph deltas ──────────────────────────────────────────────

    def save_graph_delta(self, delta: GraphDelta) -> None:
        self._conn.execute(
            """INSERT INTO graph_deltas
               (id, run_id, delta_type, target_id, sequence_number,
                payload, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(delta.id), _str(delta.run_id), delta.delta_type.value,
                _str(delta.target_id), delta.sequence_number,
                _json(delta.payload), _iso(delta.timestamp),
            ),
        )
        self._conn.commit()

    def get_graph_deltas(
        self, run_id: str, after_sequence: int = -1
    ) -> list[GraphDelta]:
        rows = self._conn.execute(
            """SELECT * FROM graph_deltas
               WHERE run_id = ? AND sequence_number > ?
               ORDER BY sequence_number""",
            (run_id, after_sequence),
        ).fetchall()
        return [self._row_to_graph_delta(r) for r in rows]

    @staticmethod
    def _row_to_graph_delta(row: sqlite3.Row) -> GraphDelta:
        return GraphDelta(
            id=UUID(row["id"]),
            run_id=UUID(row["run_id"]),
            delta_type=GraphDeltaType(row["delta_type"]),
            target_id=UUID(row["target_id"]),
            sequence_number=row["sequence_number"],
            payload=_parse_json(row["payload"]),
            timestamp=_parse_dt(row["timestamp"]),
        )

    # ── SSE events (idempotent on run_id + sequence) ──────────────

    def save_sse_event(self, event: SSEEvent) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO sse_events
               (event_id, run_id, stage, event_type, sequence,
                payload, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(event.event_id), _str(event.run_id), event.stage,
                event.event_type.value, event.sequence,
                _json(event.payload), _iso(event.timestamp),
            ),
        )
        self._conn.commit()

    def get_sse_events(
        self, run_id: str, after_sequence: int = -1
    ) -> list[SSEEvent]:
        rows = self._conn.execute(
            """SELECT * FROM sse_events
               WHERE run_id = ? AND sequence > ?
               ORDER BY sequence""",
            (run_id, after_sequence),
        ).fetchall()
        return [self._row_to_sse_event(r) for r in rows]

    @staticmethod
    def _row_to_sse_event(row: sqlite3.Row) -> SSEEvent:
        return SSEEvent(
            event_id=UUID(row["event_id"]),
            run_id=UUID(row["run_id"]),
            stage=row["stage"],
            event_type=SSEEventType(row["event_type"]),
            sequence=row["sequence"],
            payload=_parse_json(row["payload"]),
            timestamp=_parse_dt(row["timestamp"]),
        )

    # ── Governance ────────────────────────────────────────────────

    def save_governance_decision(self, decision: GovernanceDecision) -> None:
        self._conn.execute(
            """INSERT INTO governance_events
               (id, run_id, decision_type, stage, input_context,
                outcome, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                _str(decision.id), _str(decision.run_id),
                decision.decision_type.value, decision.stage,
                _json(decision.input_context), decision.outcome,
                _iso(decision.timestamp),
            ),
        )
        self._conn.commit()
