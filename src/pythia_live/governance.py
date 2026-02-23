#!/usr/bin/env python3
"""
Pythia Governance & Compliance Layer
Implements Singapore IMDA + UC Berkeley agentic AI standards

Autonomy Levels (UC Berkeley):
- L0: No autonomy (human-controlled)
- L1-L2: Bounded suggestions with approvals
- L3: Limited autonomy on narrow tasks with checkpoints
- L4: High autonomy, humans supervise exceptions
- L5: Full autonomy, humans observe

Governance Pillars (Singapore IMDA):
1. Risk assessment & bounding
2. Human accountability & approval checkpoints
3. Technical controls (sandboxing, monitoring, audit trails)
4. End-user transparency & training
"""

import json
import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class AutonomyLevel(Enum):
    """UC Berkeley autonomy classification"""
    L0_NO_AUTONOMY = 0
    L1_BOUNDED_SUGGESTIONS = 1
    L2_TOOL_USE_WITH_APPROVAL = 2
    L3_LIMITED_AUTONOMY = 3
    L4_HIGH_AUTONOMY = 4
    L5_FULL_AUTONOMY = 5


class AgentRole(Enum):
    """Pythia's multi-agent roles"""
    CONTEXT_BUILDER = "context_builder"
    NEWS_RETRIEVER = "news_retriever"
    CANDIDATE_FILTER = "candidate_filter"
    CAUSAL_REASONER = "causal_reasoner"
    STORAGE_LEARNER = "storage_learner"
    ORCHESTRATOR = "orchestrator"


# Agent autonomy declarations (UC Berkeley compliance)
AGENT_AUTONOMY_MAP = {
    AgentRole.CONTEXT_BUILDER: AutonomyLevel.L3_LIMITED_AUTONOMY,  # Fixed keyword matching
    AgentRole.NEWS_RETRIEVER: AutonomyLevel.L4_HIGH_AUTONOMY,      # Web API calls
    AgentRole.CANDIDATE_FILTER: AutonomyLevel.L4_HIGH_AUTONOMY,    # LLM filtering
    AgentRole.CAUSAL_REASONER: AutonomyLevel.L4_HIGH_AUTONOMY,     # LLM reasoning
    AgentRole.STORAGE_LEARNER: AutonomyLevel.L3_LIMITED_AUTONOMY,  # DB writes
    AgentRole.ORCHESTRATOR: AutonomyLevel.L4_HIGH_AUTONOMY,        # Pipeline coordination
}


@dataclass
class GovernanceConfig:
    """Governance policy configuration"""
    
    # Circuit breakers (Singapore: technical controls)
    max_cost_per_hour: float = 10.0  # USD
    max_cost_per_run: float = 2.0     # USD per causal attribution
    max_tokens_per_run: int = 100_000
    emergency_shutdown_threshold: float = 50.0  # USD total
    
    # Confidence thresholds (Berkeley: human oversight gates)
    min_confidence_auto_relay: float = 0.85  # AUTO: confidence >= 85%
    min_confidence_flag_review: float = 0.70  # REVIEW: 70% <= confidence < 85%
    # Below 70% = REJECT (no signal sent)
    
    # Agent validation checkpoints (Berkeley: defense-in-depth)
    min_agent_confidence: float = 0.70  # Each agent must output >= 70% confidence
    require_multi_agent_agreement: bool = True  # Filter + Reasoner must agree
    
    # Audit & monitoring (Singapore: transparency + accountability)
    audit_trail_enabled: bool = True
    audit_retention_days: int = 90
    log_all_agent_actions: bool = True
    
    # Sandboxing (Singapore: risk bounding)
    sandbox_mode: bool = False  # If True, no real signals sent
    allowed_data_sources: List[str] = None
    
    def __post_init__(self):
        if self.allowed_data_sources is None:
            self.allowed_data_sources = [
                # Prediction markets (primary data)
                "kalshi.com",  # CFTC-regulated, institutional
                "manifold.markets",  # Open-source, community
                "polymarket.com",  # Liquidity leader (backup)
                # News sources (causal attribution)
                "newsapi.org",
                "twitter.com",  # Via AIsa API
                "cnn.com",
                "bbc.com",
                "reuters.com",
                "bloomberg.com",
                "wsj.com",
                "ft.com",
                "google.com",  # Google News
                "duckduckgo.com",  # DuckDuckGo News
                "reddit.com",  # r/MachineLearning, r/Economics
            ]


@dataclass
class AgentAction:
    """Single agent action for audit trail"""
    timestamp: str
    agent_role: str
    action_type: str  # "query", "llm_call", "db_write", "api_call"
    input_summary: str
    output_summary: str
    confidence_score: Optional[float] = None
    cost_usd: Optional[float] = None
    tokens_used: Optional[int] = None
    duration_ms: Optional[int] = None
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


@dataclass
class AuditTrail:
    """Complete audit trail for a causal attribution run"""
    run_id: str
    market_id: str
    market_title: str
    start_time: str
    end_time: Optional[str] = None
    
    # Actions log
    actions: List[AgentAction] = None
    
    # Outcome
    final_confidence: Optional[float] = None
    final_decision: str = "PENDING"  # AUTO_RELAY | FLAG_REVIEW | REJECT
    human_approved: bool = False
    human_approver: Optional[str] = None
    
    # Costs & performance
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_duration_ms: int = 0
    
    # Governance checkpoints
    passed_all_checkpoints: bool = False
    failed_checkpoint: Optional[str] = None
    
    def __post_init__(self):
        if self.actions is None:
            self.actions = []
    
    def add_action(self, action: AgentAction):
        """Add an agent action to the trail"""
        self.actions.append(action)
        if action.cost_usd:
            self.total_cost_usd += action.cost_usd
        if action.tokens_used:
            self.total_tokens += action.tokens_used
        if action.duration_ms:
            self.total_duration_ms += action.duration_ms
    
    def finalize(self, confidence: float, decision: str):
        """Finalize the audit trail"""
        self.end_time = datetime.now().isoformat()
        self.final_confidence = confidence
        self.final_decision = decision
        self.passed_all_checkpoints = (decision != "REJECT")
    
    def to_dict(self) -> Dict:
        """Export to JSON-serializable dict"""
        return {
            'run_id': self.run_id,
            'market_id': self.market_id,
            'market_title': self.market_title,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'actions': [asdict(a) for a in self.actions],
            'final_confidence': self.final_confidence,
            'final_decision': self.final_decision,
            'human_approved': self.human_approved,
            'human_approver': self.human_approver,
            'total_cost_usd': round(self.total_cost_usd, 4),
            'total_tokens': self.total_tokens,
            'total_duration_ms': self.total_duration_ms,
            'passed_all_checkpoints': self.passed_all_checkpoints,
            'failed_checkpoint': self.failed_checkpoint,
        }


class CircuitBreaker:
    """Emergency shutdown mechanism (Berkeley: containment failure response)"""
    
    def __init__(self, config: GovernanceConfig):
        self.config = config
        self.total_cost = 0.0
        self.hourly_cost = 0.0
        self.hour_start = time.time()
        self.tripped = False
        self.trip_reason = None
    
    def check_before_run(self, estimated_cost: float) -> tuple[bool, Optional[str]]:
        """Check if run is allowed. Returns (allowed, reason_if_not)"""
        
        if self.tripped:
            return False, f"Circuit breaker tripped: {self.trip_reason}"
        
        # Check total cost
        if self.total_cost >= self.config.emergency_shutdown_threshold:
            self.trip(f"Total cost ${self.total_cost:.2f} exceeded threshold ${self.config.emergency_shutdown_threshold:.2f}")
            return False, self.trip_reason
        
        # Check per-run cost
        if estimated_cost > self.config.max_cost_per_run:
            return False, f"Estimated cost ${estimated_cost:.2f} exceeds per-run limit ${self.config.max_cost_per_run:.2f}"
        
        # Check hourly cost (reset counter if new hour)
        if time.time() - self.hour_start > 3600:
            self.hourly_cost = 0.0
            self.hour_start = time.time()
        
        if self.hourly_cost + estimated_cost > self.config.max_cost_per_hour:
            return False, f"Hourly cost limit ${self.config.max_cost_per_hour:.2f} would be exceeded"
        
        return True, None
    
    def record_run(self, actual_cost: float):
        """Record actual cost after run"""
        self.total_cost += actual_cost
        self.hourly_cost += actual_cost
    
    def trip(self, reason: str):
        """Emergency shutdown"""
        self.tripped = True
        self.trip_reason = reason
        logger.critical("CIRCUIT BREAKER TRIPPED: %s", reason)
    
    def reset(self, admin_override: bool = False):
        """Reset circuit breaker (requires admin override)"""
        if admin_override:
            self.tripped = False
            self.trip_reason = None
            self.total_cost = 0.0
            self.hourly_cost = 0.0
            logger.warning("Circuit breaker manually reset")
        else:
            logger.error("Circuit breaker reset requires admin_override=True")


class GovernanceValidator:
    """Validation checkpoints between agents (Berkeley: defense-in-depth)"""
    
    def __init__(self, config: GovernanceConfig):
        self.config = config
    
    def validate_agent_output(self, agent_role: AgentRole, output: Dict, 
                             confidence: Optional[float]) -> tuple[bool, Optional[str]]:
        """
        Validate agent output before passing to next layer.
        Returns (passed, failure_reason)
        """
        
        # Check confidence threshold
        if confidence is not None:
            if confidence < self.config.min_agent_confidence:
                return False, f"{agent_role.value} confidence {confidence:.2f} below threshold {self.config.min_agent_confidence:.2f}"
        
        # Role-specific validations
        if agent_role == AgentRole.NEWS_RETRIEVER:
            if not output.get('articles'):
                return False, "No news articles retrieved"
            if len(output['articles']) == 0:
                return False, "Empty articles list"
        
        elif agent_role == AgentRole.CANDIDATE_FILTER:
            if 'filtered_candidates' not in output:
                return False, "Missing filtered_candidates in output"
            if confidence and confidence < 0.5:
                return False, f"Filter confidence too low: {confidence:.2f}"
        
        elif agent_role == AgentRole.CAUSAL_REASONER:
            if 'explanation' not in output or not output['explanation']:
                return False, "Missing causal explanation"
            if confidence and confidence < 0.6:
                return False, f"Reasoning confidence too low: {confidence:.2f}"
        
        return True, None
    
    def validate_final_output(self, confidence: float, 
                             filter_confidence: Optional[float],
                             reasoner_confidence: Optional[float]) -> tuple[str, str]:
        """
        Final decision gate: AUTO_RELAY, FLAG_REVIEW, or REJECT.
        Returns (decision, reason)
        """
        
        # REJECT: below 70%
        if confidence < self.config.min_confidence_flag_review:
            return "REJECT", f"Confidence {confidence:.2f} below review threshold {self.config.min_confidence_flag_review:.2f}"
        
        # FLAG_REVIEW: 70-85%
        if confidence < self.config.min_confidence_auto_relay:
            return "FLAG_REVIEW", f"Confidence {confidence:.2f} requires human review (threshold: {self.config.min_confidence_auto_relay:.2f})"
        
        # Multi-agent agreement check (if enabled)
        if self.config.require_multi_agent_agreement:
            if filter_confidence and reasoner_confidence:
                agreement = abs(filter_confidence - reasoner_confidence) < 0.2
                if not agreement:
                    return "FLAG_REVIEW", f"Agent disagreement: Filter={filter_confidence:.2f}, Reasoner={reasoner_confidence:.2f}"
        
        # AUTO_RELAY: >= 85% and passed all checks
        return "AUTO_RELAY", f"High confidence {confidence:.2f}, auto-approved"


class AuditExporter:
    """Export audit trails for compliance review"""
    
    def __init__(self, export_dir: Path):
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
    
    def save_trail(self, trail: AuditTrail):
        """Save audit trail to JSON file"""
        filename = f"audit_{trail.run_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = self.export_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(trail.to_dict(), f, indent=2)
        
        logger.info("Audit trail saved: %s", filepath)
    
    def export_batch(self, trails: List[AuditTrail], output_file: str):
        """Export multiple trails to single file (for enterprise review)"""
        output_path = self.export_dir / output_file
        
        with open(output_path, 'w') as f:
            json.dump([t.to_dict() for t in trails], f, indent=2)
        
        logger.info("Batch audit export: %s (%d trails)", output_path, len(trails))
        return output_path


# Global governance instance (initialized in main.py)
_governance_config: Optional[GovernanceConfig] = None
_circuit_breaker: Optional[CircuitBreaker] = None
_validator: Optional[GovernanceValidator] = None
_audit_exporter: Optional[AuditExporter] = None


def init_governance(config: Optional[GovernanceConfig] = None, 
                   audit_dir: Optional[Path] = None):
    """Initialize governance layer (call once at startup)"""
    global _governance_config, _circuit_breaker, _validator, _audit_exporter
    
    _governance_config = config or GovernanceConfig()
    _circuit_breaker = CircuitBreaker(_governance_config)
    _validator = GovernanceValidator(_governance_config)
    
    if audit_dir:
        _audit_exporter = AuditExporter(audit_dir)
    
    logger.info("Governance layer initialized: autonomy levels declared, circuit breaker armed")


def get_governance() -> tuple[GovernanceConfig, CircuitBreaker, GovernanceValidator, Optional[AuditExporter]]:
    """Get governance instances"""
    if not _governance_config:
        raise RuntimeError("Governance not initialized. Call init_governance() first.")
    return _governance_config, _circuit_breaker, _validator, _audit_exporter
