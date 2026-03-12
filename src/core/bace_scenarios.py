"""
BACE Scenario Clustering — Groups hypotheses into competing causal narratives.

Instead of a flat ranked list, BACE produces scenarios:
  Primary:     Top 2-3 by agent consensus, fully developed with evidence chains
  Alternative: Next 2-4, plausible but weaker
  Dismissed:   Agents considered and rejected — showing WHY builds trust

Clustering uses:
  1. Causal mechanism similarity (LLM-assisted if available)
  2. Agent convergence data from interaction rounds
  3. Evidence overlap between hypotheses

Dynamic scenario count — data-driven, not hardcoded.
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


@dataclass
class Scenario:
    """A causal scenario — a coherent narrative about why the spike happened."""
    id: str
    label: str                          # "Macro-driven (FOMC)", "Informed flow (whale)"
    mechanism: str                      # "macro", "informed_flow", "sentiment", etc.
    tier: str                           # "primary", "alternative", "dismissed"
    confidence: float                   # Combined confidence from supporting agents
    lead_agent: str                     # Agent with strongest hypothesis in this scenario
    supporting_agents: List[str] = field(default_factory=list)
    challenging_agents: List[str] = field(default_factory=list)
    hypothesis_ids: List[str] = field(default_factory=list)
    evidence_chain: List[str] = field(default_factory=list)
    evidence_urls: List[str] = field(default_factory=list)
    what_breaks_this: str = ""          # What evidence would disprove this scenario
    causal_chain: str = ""              # Step-by-step causal narrative
    temporal_fit: str = ""              # How well the timing aligns
    impact_speed: str = ""
    time_to_peak: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


# ─── Mechanism Categories ────────────────────────────────────────────

MECHANISM_KEYWORDS = {
    "macro_policy": ["FOMC", "fed", "rate", "inflation", "CPI", "GDP", "employment", "jobs", "monetary", "fiscal", "treasury", "central bank"],
    "informed_flow": ["whale", "block trade", "insider", "front-run", "large order", "wallet", "accumulation", "pre-positioning"],
    "sentiment_narrative": ["twitter", "reddit", "viral", "social media", "narrative", "retail", "sentiment", "thread", "influencer"],
    "cross_market": ["SPY", "equities", "crypto", "BTC", "correlation", "contagion", "risk-off", "risk-on", "spillover"],
    "geopolitical": ["war", "sanctions", "military", "diplomatic", "election", "political", "tariff", "trade war", "coup"],
    "regulatory": ["SEC", "CFTC", "regulation", "compliance", "ruling", "court", "legal", "lawsuit", "ban"],
    "technical": ["orderbook", "liquidity", "spread", "market making", "microstructure", "slippage", "thin market"],
    "null": ["noise", "random", "variance", "no cause", "statistical", "normal"],
}


def _classify_mechanism(cause_text: str) -> str:
    """Classify a hypothesis's causal mechanism by keyword matching."""
    cause_lower = cause_text.lower()
    scores = {}
    for mechanism, keywords in MECHANISM_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw.lower() in cause_lower)
        if score > 0:
            scores[mechanism] = score

    if not scores:
        return "other"
    return max(scores, key=scores.get)


def _generate_scenario_label(mechanism: str, hypotheses: List) -> str:
    """Generate a human-readable label for a scenario cluster."""
    labels = {
        "macro_policy": "Macro / policy-driven",
        "informed_flow": "Informed flow / whale activity",
        "sentiment_narrative": "Social media / narrative shift",
        "cross_market": "Cross-market contagion",
        "geopolitical": "Geopolitical event",
        "regulatory": "Regulatory / legal action",
        "technical": "Market microstructure",
        "null": "Statistical noise / no clear cause",
        "other": "Other / multi-factor",
    }
    base = labels.get(mechanism, mechanism.replace("_", " ").title())

    # Append the top hypothesis's key phrase
    if hypotheses:
        top = hypotheses[0]
        cause = top.cause_description[:80] if hasattr(top, "cause_description") else str(top.get("cause", ""))[:80]
        # Extract parenthetical detail
        if "—" in cause:
            detail = cause.split("—")[0].strip()[-40:]
        elif ":" in cause:
            detail = cause.split(":")[0].strip()[-40:]
        else:
            detail = cause[:40]
        return f"{base} ({detail})"

    return base


# ─── Scenario Clustering ─────────────────────────────────────────────

def cluster_hypotheses_into_scenarios(
    hypotheses: List,
    interaction_round=None,
    agents: Optional[List] = None,
) -> List[Scenario]:
    """
    Cluster hypotheses into scenarios. Dynamic count — data determines how many.

    Algorithm:
    1. Classify each hypothesis by causal mechanism
    2. Group by mechanism
    3. Merge convergent groups (from interaction round data)
    4. Rank by combined confidence
    5. Tier: top 3 primary, next by confidence alternative, debunked dismissed
    """
    if not hypotheses:
        return []

    # Step 1: Classify each hypothesis
    classified: Dict[str, List] = {}
    for h in hypotheses:
        cause = h.cause_description if hasattr(h, "cause_description") else h.get("cause", "")
        mechanism = _classify_mechanism(cause)
        classified.setdefault(mechanism, []).append(h)

    # Step 2: Sort within each group by confidence
    for mechanism in classified:
        classified[mechanism].sort(
            key=lambda h: h.confidence if hasattr(h, "confidence") else h.get("confidence", 0),
            reverse=True
        )

    # Step 3: Use interaction round convergence to merge related groups
    if interaction_round and interaction_round.convergence_groups:
        # If agents converged across mechanism boundaries, merge those groups
        for conv_label, conv_ids in interaction_round.convergence_groups.items():
            hyp_ids = [cid for cid in conv_ids if not cid.startswith("supported_by:")]
            if len(hyp_ids) >= 2:
                # Find which mechanisms these hypotheses belong to
                mechanisms_involved = set()
                for h in hypotheses:
                    hid = h.id if hasattr(h, "id") else h.get("id", "")
                    if hid in hyp_ids:
                        cause = h.cause_description if hasattr(h, "cause_description") else h.get("cause", "")
                        mechanisms_involved.add(_classify_mechanism(cause))
                # If crossing mechanisms, keep them separate — the convergence is noted in the scenario

    # Step 4: Build scenarios
    scenarios: List[Scenario] = []
    agent_map = {a.id: a.name for a in agents} if agents else {}

    for mechanism, hyps in classified.items():
        # Get the best hypothesis in this cluster
        best = hyps[0]
        best_conf = best.confidence if hasattr(best, "confidence") else best.get("confidence", 0)
        best_cause = best.cause_description if hasattr(best, "cause_description") else best.get("cause", "")
        best_agent = best.agent_id if hasattr(best, "agent_id") else best.get("agent", "")

        # Supporting agents: all agents that proposed in this cluster
        supporting = list(set(
            (h.agent_id if hasattr(h, "agent_id") else h.get("agent", ""))
            for h in hyps
            if (h.status if hasattr(h, "status") else h.get("status", "")) != "debunked"
        ))

        # Challenging agents: from interaction round
        challengers = []
        if interaction_round:
            for resp in interaction_round.responses:
                if resp.stance == "challenge":
                    target_agent = resp.target_hypothesis_id.split("-h")[0] if "-h" in resp.target_hypothesis_id else ""
                    if target_agent == best_agent:
                        challengers.append(resp.responder_name)

        # Evidence chain: union of all evidence in this cluster
        evidence_chain = []
        evidence_urls = []
        for h in hyps[:3]:
            ev = h.evidence if hasattr(h, "evidence") else h.get("evidence", [])
            urls = h.evidence_urls if hasattr(h, "evidence_urls") else h.get("evidence_urls", [])
            for e in ev:
                if isinstance(e, str) and e not in evidence_chain:
                    evidence_chain.append(e)
                elif isinstance(e, dict) and e.get("title") not in [x.get("title") if isinstance(x, dict) else x for x in evidence_chain]:
                    evidence_chain.append(e)
            evidence_urls.extend(u for u in urls if u and u not in evidence_urls)

        # Causal chain from the best hypothesis
        causal_chain = best.causal_chain if hasattr(best, "causal_chain") else best.get("reasoning", "")

        # Determine tier
        all_survived = all(
            (h.status if hasattr(h, "status") else h.get("status", "")) != "debunked"
            for h in hyps
        )
        any_debunked = any(
            (h.status if hasattr(h, "status") else h.get("status", "")) == "debunked"
            for h in hyps
        )

        # What would break this scenario
        what_breaks = ""
        if interaction_round:
            challenges_for_this = [
                r.reasoning for r in interaction_round.responses
                if r.stance == "challenge" and r.target_hypothesis_id.startswith(best_agent)
            ]
            if challenges_for_this:
                what_breaks = challenges_for_this[0][:200]

        scenario = Scenario(
            id=f"scenario-{mechanism}",
            label=_generate_scenario_label(mechanism, hyps),
            mechanism=mechanism,
            tier="dismissed" if not all_survived and any_debunked and best_conf < 0.3 else "primary",
            confidence=round(best_conf, 3),
            lead_agent=agent_map.get(best_agent, best_agent),
            supporting_agents=[agent_map.get(a, a) for a in supporting],
            challenging_agents=challengers,
            hypothesis_ids=[h.id if hasattr(h, "id") else h.get("id", "") for h in hyps],
            evidence_chain=[e if isinstance(e, str) else e.get("title", str(e)) for e in evidence_chain[:8]],
            evidence_urls=evidence_urls[:5],
            what_breaks_this=what_breaks,
            causal_chain=causal_chain,
            temporal_fit=best.temporal_plausibility if hasattr(best, "temporal_plausibility") else "",
            impact_speed=best.impact_speed if hasattr(best, "impact_speed") else best.get("impact_speed", ""),
            time_to_peak=best.time_to_peak_impact if hasattr(best, "time_to_peak_impact") else best.get("time_to_peak", ""),
        )
        scenarios.append(scenario)

    # Step 5: Sort by confidence and assign tiers
    scenarios.sort(key=lambda s: s.confidence, reverse=True)

    for i, s in enumerate(scenarios):
        if s.tier == "dismissed":
            continue  # already marked
        if i < 3 and s.confidence >= 0.3:
            s.tier = "primary"
        elif s.confidence >= 0.15:
            s.tier = "alternative"
        else:
            s.tier = "dismissed"

    primary = [s for s in scenarios if s.tier == "primary"]
    alternative = [s for s in scenarios if s.tier == "alternative"]
    dismissed = [s for s in scenarios if s.tier == "dismissed"]

    logger.info("Scenarios: %d primary, %d alternative, %d dismissed",
                len(primary), len(alternative), len(dismissed))

    return scenarios


def scenarios_to_sse(scenarios: List[Scenario]) -> Dict:
    """Convert scenarios to SSE-friendly dict."""
    return {
        "total": len(scenarios),
        "primary": [
            {"id": s.id, "label": s.label, "confidence": s.confidence,
             "lead_agent": s.lead_agent, "supporting_agents": s.supporting_agents,
             "mechanism": s.mechanism}
            for s in scenarios if s.tier == "primary"
        ],
        "alternative": [
            {"id": s.id, "label": s.label, "confidence": s.confidence,
             "mechanism": s.mechanism}
            for s in scenarios if s.tier == "alternative"
        ],
        "dismissed": [
            {"id": s.id, "label": s.label, "confidence": s.confidence,
             "mechanism": s.mechanism}
            for s in scenarios if s.tier == "dismissed"
        ],
    }
