"""BACE — Backward Attribution Causal Engine.

Unified, depth-configurable attribution for prediction market spikes.
Governance-integrated: every run produces an audit trail and decision gate output.

Depth 1 (FAST):     Single-shot LLM reasoning, ~3 calls, ~$0.03/spike
Depth 2 (STANDARD): Multi-agent proposals with domain evidence, ~15 calls, ~$0.15/spike
Depth 3 (DEEP):     Full adversarial debate + counterfactual testing, ~95 calls, ~$0.47/spike

Config: PYTHIA_BACE_DEPTH=1|2|3 (default: 2)
"""

import logging
import time
from enum import IntEnum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class BACEDepth(IntEnum):
    FAST = 1
    STANDARD = 2
    DEEP = 3


# Estimated cost per depth (Qwen pricing) — used for circuit breaker pre-check
DEPTH_COST_ESTIMATE = {
    BACEDepth.FAST: 0.05,
    BACEDepth.STANDARD: 0.20,
    BACEDepth.DEEP: 0.60,
}


def _confidence_score(confidence: str) -> float:
    return {"HIGH": 0.9, "MEDIUM": 0.65, "LOW": 0.35}.get((confidence or "").upper(), 0.0)


def _with_bace_metadata(result: Dict, depth: int, elapsed_seconds: Optional[float] = None) -> Dict:
    out = dict(result)
    out["bace_depth"] = int(depth)

    md = dict(out.get("bace_metadata", {}))
    md.setdefault("agents_spawned", out.get("agents_spawned", 0))
    md.setdefault("hypotheses_proposed", out.get("total_hypotheses", 0))
    md.setdefault("debate_rounds", out.get("debate_rounds", 0))
    md.setdefault("domain_evidence_items", 0)
    if elapsed_seconds is not None:
        md.setdefault("elapsed_seconds", elapsed_seconds)
    else:
        md.setdefault("elapsed_seconds", out.get("elapsed_seconds", 0.0))
    out["bace_metadata"] = md
    return out


def attribute_spike(
    spike,
    all_recent_spikes: Optional[List] = None,
    db=None,
    depth: int = BACEDepth.STANDARD,
    llm_fast=None,
    llm_strong=None,
) -> Dict:
    """Unified attribution pipeline.

    Returns dict compatible with attributor_engine.extract_attributor().
    """
    all_recent_spikes = all_recent_spikes or []
    depth = int(depth)

    if depth <= int(BACEDepth.FAST):
        from .causal_v2 import attribute_spike_v2

        result = attribute_spike_v2(
            spike,
            all_recent_spikes=all_recent_spikes,
            entity_llm=llm_fast,
            filter_llm=llm_fast,
            reasoning_llm=llm_strong or llm_fast,
            db=db,
        )
        return _with_bace_metadata(result, BACEDepth.FAST)

    from .bace_debate import attribute_spike_rce

    debate_rounds = 0 if depth == int(BACEDepth.STANDARD) else 2
    result = attribute_spike_rce(
        spike=spike,
        all_recent_spikes=all_recent_spikes,
        llm_call=llm_fast,
        ontology_llm=llm_strong or llm_fast,
        db=db,
        debate_rounds=debate_rounds,
    )
    return _with_bace_metadata(result, BACEDepth.STANDARD if debate_rounds == 0 else BACEDepth.DEEP)


def attribute_spike_with_governance(
    spike,
    all_recent_spikes=None,
    db=None,
    depth: int = BACEDepth.STANDARD,
    llm_fast=None,
    llm_strong=None,
) -> Tuple[Dict, Optional["AuditTrail"]]:
    """
    Governance-wrapped BACE attribution.

    Returns (result, audit_trail) tuple.
    1. Circuit breaker pre-check (cost guard)
    2. Run BACE attribution
    3. Decision gate evaluation (AUTO_RELAY / FLAG_REVIEW / REJECT)
    4. Build and persist audit trail
    """
    from .governance import (
        get_governance, init_governance, create_audit_trail,
        AgentAction, DecisionGate,
    )

    # Ensure governance is initialized
    try:
        config, breaker, validator, exporter = get_governance()
    except RuntimeError:
        init_governance()
        config, breaker, validator, exporter = get_governance()

    depth = min(int(depth), config.max_depth_allowed)
    trail = create_audit_trail(spike, depth)

    # 1. Circuit breaker pre-check
    estimated_cost = DEPTH_COST_ESTIMATE.get(depth, 0.5)
    allowed, block_reason = breaker.check_before_run(estimated_cost)
    if not allowed:
        logger.warning("BACE blocked by circuit breaker: %s", block_reason)
        trail.checkpoints_failed.append(f"circuit_breaker: {block_reason}")
        trail.finalize(
            confidence=0.0,
            decision=DecisionGate.CIRCUIT_BREAK.value,
            reason=block_reason,
        )
        if exporter and config.audit_trail_enabled:
            exporter.save_trail(trail)
        return {"decision": DecisionGate.CIRCUIT_BREAK.value, "block_reason": block_reason}, trail

    trail.checkpoints_passed.append("circuit_breaker")

    # 2. Run BACE attribution
    start = time.time()
    try:
        result = attribute_spike(
            spike=spike,
            all_recent_spikes=all_recent_spikes,
            db=db,
            depth=depth,
            llm_fast=llm_fast,
            llm_strong=llm_strong,
        )
        elapsed = time.time() - start
    except Exception as e:
        elapsed = time.time() - start
        logger.error("BACE attribution failed after %.1fs: %s", elapsed, e)
        trail.checkpoints_failed.append(f"bace_execution: {e}")
        trail.finalize(confidence=0.0, decision=DecisionGate.REJECT.value,
                       reason=f"Attribution failed: {e}")
        if exporter and config.audit_trail_enabled:
            exporter.save_trail(trail)
        return {"decision": "REJECT", "error": str(e)}, trail

    trail.checkpoints_passed.append("bace_execution")

    # Log pipeline action
    trail.add_action(AgentAction(
        timestamp=trail.start_time,
        agent_role="orchestrator",
        action_type="bace_run",
        input_summary=f"depth={depth}, market={getattr(spike, 'market_title', '')[:60]}",
        output_summary=f"{result.get('agents_spawned', 0)} agents, "
                       f"{result.get('total_hypotheses', 0)} hypotheses",
        duration_ms=int(elapsed * 1000),
        cost_usd=estimated_cost,
    ))

    # Log agents if available
    if "agent_hypotheses" in result:
        agent_names = set()
        for h in result["agent_hypotheses"]:
            name = h.get("agent_name", h.get("agent", "unknown"))
            if name not in agent_names:
                agent_names.add(name)
            trail.log_hypothesis(
                agent_id=h.get("agent", "unknown"),
                cause=h.get("hypothesis", h.get("cause", "")),
                confidence=h.get("confidence", h.get("confidence_score", 0)),
                status=h.get("status", "survived"),
                evidence_count=len(h.get("evidence", [])),
            )
            # Log evidence provenance
            for ev in h.get("evidence", []):
                if isinstance(ev, dict):
                    trail.log_evidence(
                        source=ev.get("source", ""),
                        title=ev.get("title", ev.get("headline", "")),
                        url=ev.get("url"),
                        timing=ev.get("timing", "concurrent"),
                    )

    # 3. Decision gate
    decision, reason, factors = validator.evaluate(result, trail)
    trail.checkpoints_passed.append("decision_gate")

    # Record actual cost
    actual_cost = result.get("bace_metadata", {}).get("elapsed_seconds", elapsed) * 0.003  # rough estimate
    breaker.record_run(max(actual_cost, 0.01))

    # Extract top confidence
    hyps = result.get("agent_hypotheses", [])
    top_confidence = 0.0
    if hyps:
        top_conf = hyps[0].get("confidence", hyps[0].get("confidence_score", 0))
        top_confidence = float(top_conf) if isinstance(top_conf, (int, float)) else _confidence_score(str(top_conf))

    # Finalize trail
    trail.finalize(
        confidence=top_confidence,
        decision=decision,
        reason=reason,
        factors=factors,
    )

    # 4. Persist audit trail
    if exporter and config.audit_trail_enabled:
        try:
            exporter.save_trail(trail)
        except Exception as e:
            logger.error("Failed to save audit trail: %s", e)

    # Attach governance metadata to result
    result["final_confidence"] = top_confidence
    result["decision"] = decision
    result["governance"] = {
        "decision": decision,
        "reason": reason,
        "factors": factors,
        "run_id": trail.run_id,
        "cost_usd": round(trail.total_cost_usd, 4),
        "circuit_breaker": breaker.status(),
    }

    logger.info("BACE governance: %s (confidence=%.2f, cost=$%.4f, run_id=%s)",
                decision, top_confidence, trail.total_cost_usd, trail.run_id)

    return result, trail
