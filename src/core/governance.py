"""
Pythia Governance & Compliance Layer
Enterprise-grade audit, circuit breaking, and decision gating for BACE attribution.

Design principles:
  1. Every BACE run produces a complete, immutable audit trail
  2. Circuit breakers prevent runaway LLM spend
  3. Decision gates classify outputs as AUTO_RELAY / FLAG_REVIEW / REJECT
  4. All agent actions are logged with cost, latency, and confidence
  5. Governance config is externalizable (YAML/env) for enterprise deployment

Framework references:
  - Singapore IMDA Model AI Governance (risk assessment, transparency, accountability)
  - UC Berkeley BAIR Autonomy Levels (L0-L5 bounded delegation)
  - NIST AI Risk Management Framework (measure, manage, govern)

Autonomy Levels:
  L0: No autonomy (human-controlled)
  L1-L2: Bounded suggestions with approvals
  L3: Limited autonomy on narrow tasks with checkpoints
  L4: High autonomy, humans supervise exceptions
  L5: Full autonomy, humans observe
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum, IntEnum

logger = logging.getLogger(__name__)


# ─── Enums ───────────────────────────────────────────────────────────

class AutonomyLevel(IntEnum):
    """UC Berkeley autonomy classification."""
    L0_NO_AUTONOMY = 0
    L1_BOUNDED_SUGGESTIONS = 1
    L2_TOOL_USE_WITH_APPROVAL = 2
    L3_LIMITED_AUTONOMY = 3
    L4_HIGH_AUTONOMY = 4
    L5_FULL_AUTONOMY = 5


class BACEAgentRole(Enum):
    """BACE pipeline roles — maps to the multi-agent architecture."""
    # Pipeline stages
    CONTEXT_BUILDER = "context_builder"
    ONTOLOGY_EXTRACTOR = "ontology_extractor"
    EVIDENCE_GATHERER = "evidence_gatherer"
    DOMAIN_EVIDENCE = "domain_evidence"
    ORCHESTRATOR = "orchestrator"
    # Specialist agents (Tier 1)
    MACRO_POLICY = "macro-policy"
    INFORMED_FLOW = "informed-flow"
    NARRATIVE_SENTIMENT = "narrative-sentiment"
    CROSS_MARKET = "cross-market"
    GEOPOLITICAL = "geopolitical"
    # Conditional agents (Tier 2)
    REGULATORY = "regulatory"
    TECHNICAL_MICRO = "technical-microstructure"
    CRYPTO_ONCHAIN = "crypto-onchain"
    # Adversarial agents (Tier 3)
    DEVILS_ADVOCATE = "devils-advocate"
    NULL_HYPOTHESIS = "null-hypothesis"


# Autonomy declarations per role
AGENT_AUTONOMY_MAP = {
    BACEAgentRole.CONTEXT_BUILDER: AutonomyLevel.L3_LIMITED_AUTONOMY,
    BACEAgentRole.ONTOLOGY_EXTRACTOR: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.EVIDENCE_GATHERER: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.DOMAIN_EVIDENCE: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.ORCHESTRATOR: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.MACRO_POLICY: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.INFORMED_FLOW: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.NARRATIVE_SENTIMENT: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.CROSS_MARKET: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.GEOPOLITICAL: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.REGULATORY: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.TECHNICAL_MICRO: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.CRYPTO_ONCHAIN: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.DEVILS_ADVOCATE: AutonomyLevel.L4_HIGH_AUTONOMY,
    BACEAgentRole.NULL_HYPOTHESIS: AutonomyLevel.L4_HIGH_AUTONOMY,
}


class DecisionGate(Enum):
    """Decision classification for BACE attribution outputs."""
    AUTO_RELAY = "AUTO_RELAY"
    FLAG_REVIEW = "FLAG_REVIEW"
    REJECT = "REJECT"
    CIRCUIT_BREAK = "CIRCUIT_BREAK"


# ─── Config ──────────────────────────────────────────────────────────

@dataclass
class GovernanceConfig:
    """
    Enterprise governance policy. All thresholds are configurable.

    Load order: defaults -> governance.yaml -> env vars (PYTHIA_GOV_*).
    Bangshan calibrates production values; these defaults are safe for dev/demo.
    """

    # Circuit breakers (cost containment)
    max_cost_per_hour: float = 10.0
    max_cost_per_run: float = 2.0
    max_tokens_per_run: int = 100_000
    emergency_shutdown_threshold: float = 50.0

    # Decision gates (confidence thresholds)
    min_confidence_auto_relay: float = 0.70
    min_confidence_flag_review: float = 0.40
    require_multi_agent_agreement: bool = True
    min_agents_for_consensus: int = 3

    # Evidence requirements
    min_evidence_items: int = 2
    require_temporal_alignment: bool = True

    # Audit & monitoring
    audit_trail_enabled: bool = True
    audit_retention_days: int = 90
    log_all_agent_actions: bool = True
    log_llm_inputs: bool = False
    log_llm_outputs: bool = True

    # Sandbox controls
    sandbox_mode: bool = False
    allowed_data_sources: List[str] = None
    blocked_markets: List[str] = None

    # Depth controls
    max_depth_allowed: int = 3
    default_depth: int = 2

    def __post_init__(self):
        if self.allowed_data_sources is None:
            self.allowed_data_sources = [
                "kalshi.com", "polymarket.com", "manifold.markets",
                "google.com", "duckduckgo.com", "reddit.com",
                "reuters.com", "bloomberg.com", "bbc.com",
            ]
        if self.blocked_markets is None:
            self.blocked_markets = []

    @classmethod
    def from_env(cls) -> "GovernanceConfig":
        """Load config with env var overrides (PYTHIA_GOV_* prefix)."""
        config = cls()
        for fld in config.__dataclass_fields__:
            env_key = f"PYTHIA_GOV_{fld.upper()}"
            val = os.environ.get(env_key)
            if val is not None:
                current = getattr(config, fld)
                if isinstance(current, bool):
                    setattr(config, fld, val.lower() in ("true", "1", "yes"))
                elif isinstance(current, int):
                    setattr(config, fld, int(val))
                elif isinstance(current, float):
                    setattr(config, fld, float(val))
                elif isinstance(current, str):
                    setattr(config, fld, val)
        return config


# ─── Audit Trail ─────────────────────────────────────────────────────

@dataclass
class AgentAction:
    """Single auditable action in the BACE pipeline."""
    timestamp: str
    agent_role: str
    action_type: str
    input_summary: str
    output_summary: str
    confidence_score: Optional[float] = None
    cost_usd: Optional[float] = None
    tokens_used: Optional[int] = None
    duration_ms: Optional[int] = None
    evidence_count: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditTrail:
    """
    Complete, immutable audit trail for a single BACE attribution run.

    Every field is serializable. Trails are append-only during a run,
    then finalized with the decision gate output.
    """
    run_id: str
    market_id: str
    market_title: str
    exchange: str
    spike_timestamp: str
    spike_direction: str
    spike_magnitude: float
    bace_depth: int
    start_time: str
    end_time: Optional[str] = None

    actions: List[AgentAction] = field(default_factory=list)
    agents_spawned: List[Dict[str, str]] = field(default_factory=list)
    hypotheses: List[Dict[str, Any]] = field(default_factory=list)
    evidence_sources: List[Dict[str, str]] = field(default_factory=list)

    final_confidence: Optional[float] = None
    decision: str = "PENDING"
    decision_reason: str = ""
    decision_factors: Dict[str, Any] = field(default_factory=dict)

    human_reviewed: bool = False
    human_reviewer: Optional[str] = None
    human_decision: Optional[str] = None
    human_notes: Optional[str] = None

    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_duration_ms: int = 0
    llm_calls: int = 0

    checkpoints_passed: List[str] = field(default_factory=list)
    checkpoints_failed: List[str] = field(default_factory=list)

    def add_action(self, action: AgentAction):
        """Append an action and update running totals."""
        self.actions.append(action)
        if action.cost_usd:
            self.total_cost_usd += action.cost_usd
        if action.tokens_used:
            self.total_tokens += action.tokens_used
        if action.duration_ms:
            self.total_duration_ms += action.duration_ms
        if action.action_type == "llm_call":
            self.llm_calls += 1

    def log_agents(self, agents):
        """Record which agents were spawned."""
        self.agents_spawned = [
            {"id": getattr(a, "id", str(a)), "name": getattr(a, "name", str(a)),
             "tier": str(getattr(a, "tier", "")), "domain": getattr(a, "domain", "")}
            for a in agents
        ]

    def log_hypothesis(self, agent_id, cause, confidence, status, evidence_count=0):
        """Record a hypothesis for audit."""
        self.hypotheses.append({
            "agent_id": agent_id,
            "cause": cause[:200],
            "confidence": round(confidence, 3),
            "status": status,
            "evidence_count": evidence_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    def log_evidence(self, source, title, url=None, timing="concurrent", relevance=""):
        """Record an evidence item for provenance."""
        self.evidence_sources.append({
            "source": source, "title": title[:150],
            "url": url or "", "timing": timing, "relevance": relevance,
        })

    def finalize(self, confidence, decision, reason, factors=None):
        """Seal the audit trail with the decision gate output."""
        self.end_time = datetime.now(timezone.utc).isoformat()
        self.final_confidence = round(confidence, 4)
        self.decision = decision
        self.decision_reason = reason
        self.decision_factors = factors or {}

    def to_dict(self):
        """Export to JSON-serializable dict."""
        return {
            "run_id": self.run_id,
            "market_id": self.market_id,
            "market_title": self.market_title,
            "exchange": self.exchange,
            "spike": {
                "timestamp": self.spike_timestamp,
                "direction": self.spike_direction,
                "magnitude": self.spike_magnitude,
            },
            "bace_depth": self.bace_depth,
            "timing": {
                "start": self.start_time,
                "end": self.end_time,
                "total_duration_ms": self.total_duration_ms,
            },
            "agents_spawned": self.agents_spawned,
            "actions": [asdict(a) for a in self.actions],
            "hypotheses": self.hypotheses,
            "evidence_sources": self.evidence_sources,
            "decision": {
                "gate": self.decision,
                "confidence": self.final_confidence,
                "reason": self.decision_reason,
                "factors": self.decision_factors,
            },
            "human_review": {
                "reviewed": self.human_reviewed,
                "reviewer": self.human_reviewer,
                "decision": self.human_decision,
                "notes": self.human_notes,
            },
            "cost": {
                "total_usd": round(self.total_cost_usd, 4),
                "total_tokens": self.total_tokens,
                "llm_calls": self.llm_calls,
            },
            "checkpoints": {
                "passed": self.checkpoints_passed,
                "failed": self.checkpoints_failed,
            },
        }


# ─── Circuit Breaker ─────────────────────────────────────────────────

class CircuitBreaker:
    """Cost and safety circuit breaker. Prevents runaway LLM spend."""

    def __init__(self, config: GovernanceConfig):
        self.config = config
        self.total_cost = 0.0
        self.hourly_cost = 0.0
        self.hour_start = time.time()
        self.tripped = False
        self.trip_reason = None
        self.run_count = 0

    def check_before_run(self, estimated_cost=0.5):
        """Check if a BACE run is allowed. Returns (allowed, reason_if_not)."""
        if self.tripped:
            return False, f"Circuit breaker tripped: {self.trip_reason}"

        if self.total_cost >= self.config.emergency_shutdown_threshold:
            self.trip(f"Total cost ${self.total_cost:.2f} exceeded emergency threshold "
                      f"${self.config.emergency_shutdown_threshold:.2f}")
            return False, self.trip_reason

        if estimated_cost > self.config.max_cost_per_run:
            return False, (f"Estimated cost ${estimated_cost:.2f} exceeds per-run limit "
                           f"${self.config.max_cost_per_run:.2f}")

        if time.time() - self.hour_start > 3600:
            self.hourly_cost = 0.0
            self.hour_start = time.time()

        if self.hourly_cost + estimated_cost > self.config.max_cost_per_hour:
            return False, (f"Hourly cost limit ${self.config.max_cost_per_hour:.2f} "
                           f"would be exceeded (current: ${self.hourly_cost:.2f})")

        return True, None

    def record_run(self, actual_cost):
        self.total_cost += actual_cost
        self.hourly_cost += actual_cost
        self.run_count += 1

    def trip(self, reason):
        self.tripped = True
        self.trip_reason = reason
        logger.critical("CIRCUIT BREAKER TRIPPED: %s (total: $%.2f, runs: %d)",
                        reason, self.total_cost, self.run_count)

    def reset(self, admin_override=False):
        if admin_override:
            self.tripped = False
            self.trip_reason = None
            self.total_cost = 0.0
            self.hourly_cost = 0.0
            self.run_count = 0
            logger.warning("Circuit breaker manually reset by admin")
        else:
            logger.error("Circuit breaker reset denied — requires admin_override=True")

    def check_expected_shortfall(self, es_99, threshold):
        if es_99 is None:
            return True, None
        if es_99 >= threshold:
            reason = f"ES(99%) {es_99:.3f} exceeded threshold {threshold:.3f}"
            self.trip(reason)
            return False, reason
        return True, None

    def status(self):
        return {
            "tripped": self.tripped,
            "trip_reason": self.trip_reason,
            "total_cost_usd": round(self.total_cost, 4),
            "hourly_cost_usd": round(self.hourly_cost, 4),
            "run_count": self.run_count,
            "emergency_threshold": self.config.emergency_shutdown_threshold,
        }


# ─── Decision Gate ───────────────────────────────────────────────────

class GovernanceValidator:
    """
    Decision gate that classifies BACE outputs.

    Evaluates confidence, agent consensus, evidence quality, adversarial signals.
    """

    def __init__(self, config: GovernanceConfig):
        self.config = config

    def evaluate(self, result, trail):
        """
        Evaluate a BACE result. Returns (decision, reason, factors).
        """
        factors = {}

        hyps = result.get("agent_hypotheses", [])
        if not hyps:
            return DecisionGate.REJECT.value, "No hypotheses survived", factors

        best = hyps[0]
        confidence = best.get("confidence", best.get("confidence_score", 0.0))
        if isinstance(confidence, str):
            confidence = {"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(confidence.upper(), 0.0)
        factors["top_confidence"] = round(confidence, 3)

        # 1. Confidence floor
        if confidence < self.config.min_confidence_flag_review:
            return (DecisionGate.REJECT.value,
                    f"Top confidence {confidence:.2f} below threshold {self.config.min_confidence_flag_review:.2f}",
                    factors)

        # 2. Evidence sufficiency
        evidence_count = len(best.get("evidence", []))
        factors["evidence_count"] = evidence_count
        if evidence_count < self.config.min_evidence_items and confidence >= self.config.min_confidence_auto_relay:
            factors["evidence_downgrade"] = True
            return (DecisionGate.FLAG_REVIEW.value,
                    f"High confidence but insufficient evidence ({evidence_count} < {self.config.min_evidence_items})",
                    factors)

        # 3. Agent consensus
        if self.config.require_multi_agent_agreement:
            agreeing = sum(1 for h in hyps[:5]
                          if h.get("confidence", h.get("confidence_score", 0)) >= 0.4
                          and h.get("status", "survived") != "debunked")
            factors["agreeing_agents"] = agreeing
            if agreeing < self.config.min_agents_for_consensus and confidence >= self.config.min_confidence_auto_relay:
                factors["consensus_downgrade"] = True
                return (DecisionGate.FLAG_REVIEW.value,
                        f"Insufficient agent consensus ({agreeing} < {self.config.min_agents_for_consensus})",
                        factors)

        # 4. Adversarial check
        adversarial_hyps = [h for h in hyps if h.get("agent", h.get("agent_name", "")).lower() in
                           ("devil's advocate", "null hypothesis", "devils-advocate", "null-hypothesis")]
        if adversarial_hyps:
            adv_conf = max(h.get("confidence", h.get("confidence_score", 0)) for h in adversarial_hyps)
            factors["adversarial_confidence"] = round(adv_conf, 3)
            if adv_conf > confidence * 0.8:
                factors["adversarial_concern"] = True
                return (DecisionGate.FLAG_REVIEW.value,
                        f"Adversarial agent confidence ({adv_conf:.2f}) close to top ({confidence:.2f})",
                        factors)

        # 5. Final classification
        if confidence >= self.config.min_confidence_auto_relay:
            return (DecisionGate.AUTO_RELAY.value,
                    f"High confidence ({confidence:.2f}), sufficient evidence, consensus — auto-approved",
                    factors)

        return (DecisionGate.FLAG_REVIEW.value,
                f"Moderate confidence ({confidence:.2f}) — requires human review",
                factors)

    # Backward compat: old validate_final_output signature
    def validate_final_output(self, confidence, filter_confidence=None, reasoner_confidence=None):
        if confidence < self.config.min_confidence_flag_review:
            return "REJECT", f"Confidence {confidence:.2f} below threshold"
        if confidence < self.config.min_confidence_auto_relay:
            return "FLAG_REVIEW", f"Confidence {confidence:.2f} requires review"
        if self.config.require_multi_agent_agreement and filter_confidence and reasoner_confidence:
            if abs(filter_confidence - reasoner_confidence) >= 0.2:
                return "FLAG_REVIEW", f"Agent disagreement: {filter_confidence:.2f} vs {reasoner_confidence:.2f}"
        return "AUTO_RELAY", f"High confidence {confidence:.2f}, auto-approved"

    # Backward compat: old validate_agent_output signature
    def validate_agent_output(self, agent_role, output, confidence=None):
        if confidence is not None and confidence < 0.5:
            return False, f"Agent confidence {confidence:.2f} too low"
        return True, None


# ─── Audit Exporter ──────────────────────────────────────────────────

class AuditExporter:
    """Persist audit trails to disk for compliance review."""

    def __init__(self, export_dir):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)

    def save_trail(self, trail):
        filename = f"audit_{trail.run_id}_{trail.start_time[:10]}.json"
        filepath = self.export_dir / filename
        with open(filepath, "w") as f:
            json.dump(trail.to_dict(), f, indent=2)
        logger.info("Audit trail saved: %s (cost: $%.4f, decision: %s)",
                     filepath, trail.total_cost_usd, trail.decision)

    def export_batch(self, trails, output_file):
        output_path = self.export_dir / output_file
        with open(output_path, "w") as f:
            json.dump([t.to_dict() for t in trails], f, indent=2)
        logger.info("Batch audit export: %s (%d trails)", output_path, len(trails))
        return output_path

    def list_trails(self, days=7):
        cutoff = datetime.now(timezone.utc).timestamp() - days * 86400
        return [p for p in sorted(self.export_dir.glob("audit_*.json"), reverse=True)
                if p.stat().st_mtime >= cutoff]


# ─── Global State ────────────────────────────────────────────────────

_governance_config: Optional[GovernanceConfig] = None
_circuit_breaker: Optional[CircuitBreaker] = None
_validator: Optional[GovernanceValidator] = None
_audit_exporter: Optional[AuditExporter] = None


def init_governance(config=None, audit_dir=None):
    """Initialize governance layer (call once at startup)."""
    global _governance_config, _circuit_breaker, _validator, _audit_exporter

    _governance_config = config or GovernanceConfig.from_env()
    _circuit_breaker = CircuitBreaker(_governance_config)
    _validator = GovernanceValidator(_governance_config)

    if audit_dir:
        _audit_exporter = AuditExporter(audit_dir)

    logger.info("Governance initialized: auto_relay>=%.0f%%, flag_review>=%.0f%%, sandbox=%s",
                _governance_config.min_confidence_auto_relay * 100,
                _governance_config.min_confidence_flag_review * 100,
                _governance_config.sandbox_mode)


def get_governance():
    """Get governance instances. Raises if not initialized."""
    if not _governance_config:
        raise RuntimeError("Governance not initialized. Call init_governance() first.")
    return _governance_config, _circuit_breaker, _validator, _audit_exporter


def create_audit_trail(spike, depth, exchange="polymarket"):
    """Factory for a new audit trail from a spike proxy."""
    return AuditTrail(
        run_id=str(uuid.uuid4())[:12],
        market_id=getattr(spike, "market_id", ""),
        market_title=getattr(spike, "market_title", ""),
        exchange=exchange,
        spike_timestamp=getattr(spike, "timestamp", ""),
        spike_direction=getattr(spike, "direction", "unknown"),
        spike_magnitude=float(getattr(spike, "magnitude", 0)),
        bace_depth=depth,
        start_time=datetime.now(timezone.utc).isoformat(),
    )


# Backward compat aliases
AgentRole = BACEAgentRole
