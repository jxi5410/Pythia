"""
Canonical Pydantic v2 domain models for Pythia's run-centric architecture.

All models use:
  - UUID primary keys (auto-generated)
  - ISO 8601 UTC timestamps (auto-populated)
  - Explicit str enums for status/type fields
  - Bounded floats for confidence/score fields [0, 1]
  - dict[str, Any] metadata bags for extensibility

These models coexist with the legacy dataclasses in bace_agents.py,
bace_simulation.py, etc.  The orchestration layer translates between them.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# ── Helpers ───────────────────────────────────────────────────────────

def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ══════════════════════════════════════════════════════════════════════
#  Enums
# ══════════════════════════════════════════════════════════════════════

class SpikeType(str, Enum):
    UP = "up"
    DOWN = "down"


class RunStatus(str, Enum):
    CREATED = "created"
    MARKET_SNAPSHOT_COMPLETE = "market_snapshot_complete"
    ATTRIBUTION_STARTED = "attribution_started"
    ATTRIBUTION_STREAMING = "attribution_streaming"
    SCENARIO_CLUSTERING_COMPLETE = "scenario_clustering_complete"
    GRAPH_PERSISTED = "graph_persisted"
    INTERROGATION_READY = "interrogation_ready"
    COMPLETED = "completed"
    FAILED_RETRYABLE = "failed_retryable"
    FAILED_TERMINAL = "failed_terminal"
    PARTIAL_COMPLETE = "partial_complete"
    CANCELLED = "cancelled"


class AgentActionType(str, Enum):
    PROPOSE = "PROPOSE"
    SUPPORT = "SUPPORT"
    CHALLENGE = "CHALLENGE"
    REBUT = "REBUT"
    UPDATE_CONFIDENCE = "UPDATE_CONFIDENCE"
    PRESENT_EVIDENCE = "PRESENT_EVIDENCE"
    CONCEDE = "CONCEDE"
    SYNTHESIZE = "SYNTHESIZE"


class EvidenceSourceType(str, Enum):
    NEWS_ARTICLE = "news_article"
    SOCIAL_MEDIA = "social_media"
    GOVERNMENT_FILING = "government_filing"
    MARKET_DATA = "market_data"
    ON_CHAIN = "on_chain"
    ORDERBOOK = "orderbook"
    ECONOMIC_CALENDAR = "economic_calendar"
    CONGRESSIONAL = "congressional"
    REDDIT = "reddit"
    OTHER = "other"


class EvidenceStance(str, Enum):
    SUPPORTS = "supports"
    WEAKENS = "weakens"
    NEUTRAL = "neutral"


class ScenarioStatus(str, Enum):
    PRIMARY = "primary"
    ALTERNATIVE = "alternative"
    DISMISSED = "dismissed"


class ScenarioRevisionType(str, Enum):
    CONFIDENCE_UPDATED = "confidence_updated"
    TIER_CHANGED = "tier_changed"
    EVIDENCE_ADDED = "evidence_added"
    EVIDENCE_REMOVED = "evidence_removed"
    MERGED = "merged"
    SPLIT = "split"


class ScenarioEvidenceLinkType(str, Enum):
    SUPPORTS = "supports"
    CHALLENGES = "challenges"
    REBUTS = "rebuts"


class GraphEntityType(str, Enum):
    PERSON = "Person"
    ORGANIZATION = "Organization"
    POLICY = "Policy"
    DATA_RELEASE = "DataRelease"
    MARKET = "Market"
    GEOPOLITICAL_EVENT = "GeopoliticalEvent"
    NARRATIVE = "Narrative"
    FINANCIAL_INSTRUMENT = "FinancialInstrument"
    TECH_EVENT = "TechEvent"


class GraphDeltaType(str, Enum):
    NODE_CREATED = "node_created"
    EDGE_CREATED = "edge_created"
    NODE_UPDATED = "node_updated"
    EDGE_UPDATED = "edge_updated"
    EDGE_STRENGTHENED = "edge_strengthened"
    EDGE_WEAKENED = "edge_weakened"
    CONTRADICTION_CREATED = "contradiction_created"


class InterrogationTargetType(str, Enum):
    SCENARIO = "scenario"
    AGENT = "agent"
    EVIDENCE = "evidence"
    NODE = "node"
    EDGE = "edge"
    ACTION = "action"
    GOVERNANCE = "governance"


class InterrogationRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class AnswerMode(str, Enum):
    CONCISE = "concise"
    EVIDENCE_FIRST = "evidence_first"
    COUNTERARGUMENT_FIRST = "counterargument_first"
    OPERATOR_SUMMARY = "operator_summary"


class GovernanceDecisionType(str, Enum):
    AUTO_RELAY = "AUTO_RELAY"
    FLAG_REVIEW = "FLAG_REVIEW"
    REJECT = "REJECT"
    CIRCUIT_BREAK = "CIRCUIT_BREAK"


class SSEEventType(str, Enum):
    RUN_STARTED = "run_started"
    CHECKPOINT_SAVED = "checkpoint_saved"
    AGENT_ACTION = "agent_action"
    EVIDENCE_ADDED = "evidence_added"
    GRAPH_DELTA = "graph_delta"
    SCENARIO_CREATED = "scenario_created"
    SCENARIO_UPDATED = "scenario_updated"
    GOVERNANCE_DECISION = "governance_decision"
    WARNING = "warning"
    ERROR = "error"
    RUN_COMPLETED = "run_completed"
    HEARTBEAT = "heartbeat"


# ══════════════════════════════════════════════════════════════════════
#  Core domain models
# ══════════════════════════════════════════════════════════════════════

class Market(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    slug: str
    title: str
    source_exchange: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class SpikeEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    market_id: UUID
    spike_type: SpikeType
    magnitude: float = Field(ge=0.0)
    detected_at: datetime = Field(default_factory=_utcnow)
    threshold_used: float = Field(ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttributionRun(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    spike_event_id: UUID
    market_id: UUID
    status: RunStatus = RunStatus.CREATED
    bace_depth: int = Field(default=2, ge=1, le=3)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    cost_total_usd: float = Field(default=0.0, ge=0.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Agent & evidence models ──────────────────────────────────────────

class AgentAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    agent_name: str
    action_type: AgentActionType
    sequence_number: int = Field(ge=0)
    round_number: int = Field(ge=0)
    content: str = ""
    confidence_before: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_after: float = Field(default=0.0, ge=0.0, le=1.0)
    target_scenario_id: Optional[UUID] = None
    evidence_ids: list[UUID] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    title: str
    source_url: Optional[str] = None
    source_type: EvidenceSourceType = EvidenceSourceType.OTHER
    publication_timestamp: Optional[datetime] = None
    retrieval_timestamp: datetime = Field(default_factory=_utcnow)
    provider_agent: Optional[str] = None
    summary: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_impact: float = Field(default=0.0, ge=-1.0, le=1.0)
    stance: EvidenceStance = EvidenceStance.NEUTRAL
    linked_entity_ids: list[UUID] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Scenario models ──────────────────────────────────────────────────

class Scenario(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    title: str
    mechanism_type: str
    summary: str = ""
    confidence_score: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ScenarioStatus = ScenarioStatus.PRIMARY
    lead_agents: list[str] = Field(default_factory=list)
    supporting_agents: list[str] = Field(default_factory=list)
    challenging_agents: list[str] = Field(default_factory=list)
    what_breaks_this: list[str] = Field(default_factory=list)
    temporal_fit: str = ""
    unresolved_questions: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioRevision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    run_id: UUID
    revision_type: ScenarioRevisionType
    previous_confidence: float = Field(ge=0.0, le=1.0)
    new_confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    triggering_action_id: Optional[UUID] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class ScenarioEvidenceLink(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    scenario_id: UUID
    evidence_id: UUID
    link_type: ScenarioEvidenceLinkType
    agent_name: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


# ── Graph models ─────────────────────────────────────────────────────

class GraphNode(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    entity_type: GraphEntityType
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at_sequence: int = Field(default=0, ge=0)


class GraphEdge(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    source_node_id: UUID
    target_node_id: UUID
    relationship_type: str
    weight: float = Field(default=0.5, ge=0.0, le=1.0)
    properties: dict[str, Any] = Field(default_factory=dict)
    created_at_sequence: int = Field(default=0, ge=0)


class GraphDelta(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    delta_type: GraphDeltaType
    target_id: UUID
    sequence_number: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)


# ── Interrogation models ─────────────────────────────────────────────

class InterrogationSession(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    target_type: InterrogationTargetType
    target_id: UUID
    created_at: datetime = Field(default_factory=_utcnow)


class InterrogationMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    role: InterrogationRole
    content: str
    answer_mode: AnswerMode = AnswerMode.CONCISE
    referenced_artifact_ids: list[UUID] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=_utcnow)


# ── Governance & orchestration models ────────────────────────────────

class GovernanceDecision(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    decision_type: GovernanceDecisionType
    stage: str
    input_context: dict[str, Any] = Field(default_factory=dict)
    outcome: str = ""
    timestamp: datetime = Field(default_factory=_utcnow)


class RunCheckpoint(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    stage: str
    checkpoint_version: int = Field(default=1, ge=1)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)


class SSEEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    stage: str
    event_type: SSEEventType
    sequence: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=_utcnow)
