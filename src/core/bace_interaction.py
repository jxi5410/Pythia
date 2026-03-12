"""
BACE Agent Interaction Rounds — Multi-agent cross-examination.

After initial proposals, each agent sees the top hypotheses from other agents
and responds: does this change my view? Do I see supporting or contradicting
evidence? This produces:
  - Convergence: multiple agents rallying behind one cause
  - Divergence: persistent disagreement revealing genuine uncertainty
  - Challenge records: which agents challenged which hypotheses

The interaction data feeds into scenario clustering — hypotheses that agents
converge on form the core of a scenario; divergent clusters form alternative scenarios.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class InteractionResponse:
    """An agent's response to seeing another agent's hypothesis."""
    responder_id: str
    responder_name: str
    target_hypothesis_id: str
    target_agent_id: str
    stance: str  # "support", "challenge", "neutral", "subsume"
    reasoning: str
    confidence_shift: float  # how much this changes the responder's view (-0.3 to +0.2)
    new_evidence: List[str] = field(default_factory=list)
    converges_with: Optional[str] = None  # hypothesis ID that this supports


@dataclass
class InteractionRound:
    """Complete record of one interaction round."""
    round_number: int
    responses: List[InteractionResponse] = field(default_factory=list)
    convergence_groups: Dict[str, List[str]] = field(default_factory=dict)  # cause_cluster -> [hyp_ids]
    divergence_pairs: List[Dict] = field(default_factory=list)  # agents that disagree


def _build_interaction_prompt(agent, spike_context: Dict, own_hypotheses: List,
                               other_hypotheses: List) -> str:
    """Build prompt for an agent to respond to other agents' hypotheses."""
    own_summary = "\n".join(
        f"  - {h.cause_description[:100]} (confidence: {h.confidence:.0%})"
        for h in own_hypotheses
    ) if own_hypotheses else "  (You proposed no hypotheses in Round 1)"

    others_summary = "\n".join(
        f"  [{h.agent_id}] {h.cause_description[:120]} (confidence: {h.confidence:.0%})"
        for h in other_hypotheses[:10]
    )

    spike = spike_context.get("spike", {})
    market = spike_context.get("market_title", "Unknown market")

    return f"""You are {agent.name}, a {agent.domain} specialist.

MARKET: {market}
SPIKE: {spike.get('direction', 'unknown')} {float(spike.get('magnitude', 0)) * 100:.1f}% at {spike.get('timestamp', 'unknown')}

YOUR HYPOTHESES FROM ROUND 1:
{own_summary}

OTHER AGENTS' TOP HYPOTHESES:
{others_summary}

TASK: For each of the top 3 other hypotheses, provide your assessment.

For each, decide:
- "support": This hypothesis is consistent with your domain evidence. You see corroborating signals.
- "challenge": This hypothesis has weaknesses. You see contradicting or missing evidence.
- "neutral": You have no strong opinion from your domain perspective.
- "subsume": Your hypothesis and this one are actually the same cause viewed from different angles.

Also state:
- Does seeing these other hypotheses change your own confidence? By how much?
- Do you have NEW evidence (not mentioned in Round 1) that supports or undermines any hypothesis?
- Is there a causal link between your hypothesis and theirs? (e.g., "the whale trade was BECAUSE of the FOMC minutes")

Return ONLY valid JSON:
{{
  "responses": [
    {{
      "target_hypothesis_id": "agent-id-h0",
      "stance": "support|challenge|neutral|subsume",
      "reasoning": "Why you take this stance (2-3 sentences)",
      "confidence_shift": 0.05,
      "new_evidence": ["any new evidence items"],
      "converges_with": "your-hypothesis-id or null"
    }}
  ],
  "updated_own_confidence": 0.75,
  "cross_causal_links": ["the informed flow preceded the public catalyst by 22 minutes"]
}}
"""


async def run_interaction_round(
    agents,
    hypotheses: List,
    spike_context: Dict,
    llm_call: Callable,
    round_number: int = 1,
    _run_in_thread=None,
) -> InteractionRound:
    """
    Run one interaction round where all agents respond to each other's hypotheses.
    Returns an InteractionRound with convergence/divergence data.
    """
    if _run_in_thread is None:
        from .bace_parallel import _run_in_thread

    from .bace_debate import _parse_json_response

    round_data = InteractionRound(round_number=round_number)

    # Group hypotheses by agent
    by_agent: Dict[str, List] = {}
    for h in hypotheses:
        by_agent.setdefault(h.agent_id, []).append(h)

    # Top hypotheses for agents to see (sorted by confidence, max 8)
    top_hyps = sorted(
        [h for h in hypotheses if h.status != "debunked"],
        key=lambda x: x.confidence, reverse=True
    )[:8]

    async def agent_responds(agent):
        if agent.tier == 3:
            # Adversarial agents get a special role — they challenge everything
            return await adversarial_response(agent, top_hyps, spike_context, llm_call, _run_in_thread)

        own = by_agent.get(agent.id, [])
        others = [h for h in top_hyps if h.agent_id != agent.id]
        if not others:
            return []

        prompt = _build_interaction_prompt(agent, spike_context, own, others)
        try:
            response = await _run_in_thread(llm_call, prompt)
            parsed = _parse_json_response(response)
            if not parsed or "responses" not in parsed:
                return []

            results = []
            for r in parsed["responses"][:5]:
                results.append(InteractionResponse(
                    responder_id=agent.id,
                    responder_name=agent.name,
                    target_hypothesis_id=r.get("target_hypothesis_id", ""),
                    target_agent_id=r.get("target_hypothesis_id", "").split("-h")[0] if "-h" in r.get("target_hypothesis_id", "") else "",
                    stance=r.get("stance", "neutral"),
                    reasoning=r.get("reasoning", ""),
                    confidence_shift=float(r.get("confidence_shift", 0)),
                    new_evidence=r.get("new_evidence", []),
                    converges_with=r.get("converges_with"),
                ))
            return results
        except Exception as e:
            logger.warning("Interaction round: agent %s failed: %s", agent.id, e)
            return []

    # Run all agents concurrently
    tasks = [agent_responds(a) for a in agents]
    results = await asyncio.gather(*tasks)

    for responses in results:
        round_data.responses.extend(responses)

    # Apply confidence shifts to hypotheses
    for resp in round_data.responses:
        target = next((h for h in hypotheses if h.id == resp.target_hypothesis_id), None)
        if target and resp.stance == "support":
            target.confidence = min(0.95, target.confidence + 0.03)
        elif target and resp.stance == "challenge":
            target.confidence = max(0.05, target.confidence - 0.05)

    # Build convergence groups
    round_data.convergence_groups = _detect_convergence(round_data.responses, hypotheses)
    round_data.divergence_pairs = _detect_divergence(round_data.responses)

    logger.info("Interaction round %d: %d responses, %d convergence groups, %d divergence pairs",
                round_number, len(round_data.responses),
                len(round_data.convergence_groups), len(round_data.divergence_pairs))

    return round_data


async def adversarial_response(agent, top_hyps, spike_context, llm_call, _run_in_thread):
    """Adversarial agents challenge the top hypotheses."""
    from .bace_debate import _parse_json_response

    if not top_hyps:
        return []

    hyps_text = "\n".join(
        f"  [{h.agent_id}] (ID: {h.id}) {h.cause_description[:120]} — {h.confidence:.0%}"
        for h in top_hyps[:5]
    )

    prompt = f"""You are {agent.name}. Your role: {agent.description}

TOP HYPOTHESES TO CHALLENGE:
{hyps_text}

For each hypothesis, find the strongest argument AGAINST it.
Look for: timing inconsistencies, missing evidence, alternative explanations,
confirmation bias, spurious correlations, or assumptions that don't hold.

Return ONLY valid JSON:
{{
  "responses": [
    {{
      "target_hypothesis_id": "hypothesis-id",
      "stance": "challenge",
      "reasoning": "The strongest argument against this hypothesis (2-3 sentences)",
      "confidence_shift": -0.1,
      "new_evidence": []
    }}
  ]
}}
"""
    try:
        response = await _run_in_thread(llm_call, prompt)
        parsed = _parse_json_response(response)
        if not parsed or "responses" not in parsed:
            return []

        results = []
        for r in parsed["responses"][:5]:
            results.append(InteractionResponse(
                responder_id=agent.id,
                responder_name=agent.name,
                target_hypothesis_id=r.get("target_hypothesis_id", ""),
                target_agent_id="",
                stance=r.get("stance", "challenge"),
                reasoning=r.get("reasoning", ""),
                confidence_shift=float(r.get("confidence_shift", -0.1)),
                new_evidence=r.get("new_evidence", []),
            ))
        return results
    except Exception as e:
        logger.warning("Adversarial response failed for %s: %s", agent.id, e)
        return []


def _detect_convergence(responses: List[InteractionResponse],
                         hypotheses: List) -> Dict[str, List[str]]:
    """Detect which hypotheses are converging based on support stances."""
    support_graph: Dict[str, List[str]] = {}  # hyp_id -> [supporting agent ids]

    for r in responses:
        if r.stance in ("support", "subsume") and r.target_hypothesis_id:
            support_graph.setdefault(r.target_hypothesis_id, []).append(r.responder_id)

    # Group hypotheses that have mutual support
    clusters: Dict[str, List[str]] = {}
    for hyp_id, supporters in support_graph.items():
        if len(supporters) >= 2:
            # Find the hypothesis
            hyp = next((h for h in hypotheses if h.id == hyp_id), None)
            if hyp:
                label = hyp.cause_description[:60]
                clusters[label] = [hyp_id] + [f"supported_by:{s}" for s in supporters]

    return clusters


def _detect_divergence(responses: List[InteractionResponse]) -> List[Dict]:
    """Detect agent pairs that disagree."""
    challenges: Dict[str, List[str]] = {}  # target_hyp -> [challenger_ids]

    for r in responses:
        if r.stance == "challenge" and r.target_hypothesis_id:
            challenges.setdefault(r.target_hypothesis_id, []).append(r.responder_id)

    pairs = []
    for hyp_id, challengers in challenges.items():
        if challengers:
            target_agent = hyp_id.split("-h")[0] if "-h" in hyp_id else hyp_id
            for c in challengers:
                pairs.append({
                    "hypothesis_id": hyp_id,
                    "proposed_by": target_agent,
                    "challenged_by": c,
                })

    return pairs


def interaction_round_to_sse(round_data: InteractionRound) -> Dict:
    """Convert interaction round to SSE-friendly dict."""
    return {
        "round": round_data.round_number,
        "responses": len(round_data.responses),
        "stances": {
            "support": sum(1 for r in round_data.responses if r.stance == "support"),
            "challenge": sum(1 for r in round_data.responses if r.stance == "challenge"),
            "neutral": sum(1 for r in round_data.responses if r.stance == "neutral"),
            "subsume": sum(1 for r in round_data.responses if r.stance == "subsume"),
        },
        "convergence_groups": len(round_data.convergence_groups),
        "divergence_pairs": len(round_data.divergence_pairs),
        "top_challenges": [
            {"challenger": r.responder_name, "target": r.target_hypothesis_id,
             "reasoning": r.reasoning[:120]}
            for r in round_data.responses if r.stance == "challenge"
        ][:5],
    }
