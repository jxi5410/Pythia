"""
BACE Multi-Round Agent Simulation — Genuine adversarial debate with action logging.

Replaces the single-pass interaction + separate debate/counterfactual steps.
Agents autonomously perform actions over N rounds:
  - PROPOSE: Present a hypothesis (round 1 only — reuses existing proposals)
  - SUPPORT: Endorse another agent's hypothesis with corroborating evidence
  - CHALLENGE: Attack a hypothesis with counter-evidence or reasoning flaws
  - REBUT: Defend your hypothesis against a challenge
  - UPDATE_CONFIDENCE: Change your confidence based on debate evidence
  - PRESENT_EVIDENCE: Introduce new evidence not seen in earlier rounds
  - CONCEDE: Drop your hypothesis in favor of a stronger one
  - SYNTHESIZE: Merge two hypotheses into a unified explanation

Each action is logged to actions.jsonl and emitted as an SSE event.
Confidence evolves from agent behavior, not self-assessment.

After simulation, convergence/divergence patterns are detected from
the action log, not from a single prompt asking agents to label things.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import AsyncGenerator, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── Action types ────────────────────────────────────────────────────

ACTION_TYPES = [
    "PROPOSE",              # Initial hypothesis (round 1)
    "SUPPORT",              # Endorse another's hypothesis
    "CHALLENGE",            # Attack a hypothesis
    "REBUT",                # Defend against a challenge
    "UPDATE_CONFIDENCE",    # Change own confidence
    "PRESENT_EVIDENCE",     # Introduce new evidence
    "CONCEDE",              # Drop hypothesis in favor of another
    "SYNTHESIZE",           # Merge hypotheses
]


@dataclass
class SimAction:
    """A single agent action in the simulation."""
    round: int
    agent_id: str
    agent_name: str
    action_type: str          # One of ACTION_TYPES
    target_agent_id: str = "" # Who this action is directed at
    target_hypothesis_id: str = ""
    content: str = ""         # Main text of the action
    reasoning: str = ""       # Why the agent took this action
    evidence: List[str] = field(default_factory=list)
    confidence_before: float = 0.0
    confidence_after: float = 0.0
    timestamp: float = 0.0

    def to_dict(self) -> Dict:
        return asdict(self)

    def to_sse(self) -> Dict:
        """Compact version for SSE streaming."""
        return {
            "round": self.round,
            "agent": self.agent_id,
            "agent_name": self.agent_name,
            "action": self.action_type,
            "target_agent": self.target_agent_id,
            "target_hyp": self.target_hypothesis_id,
            "content": self.content[:150],
            "confidence_before": round(self.confidence_before, 3),
            "confidence_after": round(self.confidence_after, 3),
        }


@dataclass
class SimulationState:
    """Full state of a running simulation."""
    total_rounds: int
    current_round: int = 0
    actions: List[SimAction] = field(default_factory=list)
    confidence_history: Dict[str, List[float]] = field(default_factory=dict)  # hyp_id -> [conf per round]
    agent_stance_map: Dict[str, Dict[str, str]] = field(default_factory=dict)  # agent_id -> {hyp_id: stance}
    active_hypotheses: int = 0
    conceded_hypotheses: int = 0

    def to_status(self) -> Dict:
        return {
            "total_rounds": self.total_rounds,
            "current_round": self.current_round,
            "total_actions": len(self.actions),
            "active_hypotheses": self.active_hypotheses,
            "conceded_hypotheses": self.conceded_hypotheses,
            "actions_this_round": len([a for a in self.actions if a.round == self.current_round]),
        }


# ─── Simulation prompts ─────────────────────────────────────────────

def _build_round_prompt(agent, spike_context: Dict, own_hypotheses: List,
                         all_hypotheses: List, recent_actions: List[SimAction],
                         round_num: int) -> str:
    """Build the prompt for an agent's turn in the simulation."""
    spike = spike_context.get("spike", {})
    market = spike_context.get("market_title", "Unknown")

    # Format own hypotheses
    own_text = "\n".join(
        f"  - [ID: {h.id}] {h.cause_description[:100]} (confidence: {h.confidence:.0%})"
        for h in own_hypotheses
    ) if own_hypotheses else "  (No active hypotheses)"

    # Format other hypotheses
    others = [h for h in all_hypotheses if h.agent_id != agent.id and h.status != "debunked"]
    others_text = "\n".join(
        f"  [{h.agent_id}] (ID: {h.id}) {h.cause_description[:120]} — {h.confidence:.0%}"
        for h in sorted(others, key=lambda x: x.confidence, reverse=True)[:6]
    )

    # Format recent actions (last 8 from other agents)
    other_actions = [a for a in recent_actions if a.agent_id != agent.id][-8:]
    actions_text = "\n".join(
        f"  R{a.round} [{a.agent_name}] {a.action_type} → {a.target_hypothesis_id or 'general'}: {a.content[:100]}"
        for a in other_actions
    ) if other_actions else "  (No actions from other agents yet)"

    return f"""You are {agent.name}, a {agent.domain} specialist.
Role: {agent.description}

MARKET: {market}
SPIKE: {spike.get('direction', 'unknown')} {float(spike.get('magnitude', 0)) * 100:.1f}% at {spike.get('timestamp', 'unknown')}

THIS IS ROUND {round_num} OF THE DEBATE.

YOUR HYPOTHESES:
{own_text}

OTHER AGENTS' HYPOTHESES:
{others_text}

RECENT ACTIONS BY OTHER AGENTS:
{actions_text}

YOUR TASK: Choose 1-3 actions to take this round. Consider what happened in previous rounds.

Available actions:
- SUPPORT: Endorse a hypothesis you find credible (cite evidence from your domain)
- CHALLENGE: Attack a hypothesis (identify flaws, missing evidence, timing issues)
- REBUT: Defend your hypothesis against a specific challenge
- UPDATE_CONFIDENCE: Change your confidence on your own hypothesis (explain why)
- PRESENT_EVIDENCE: Share new evidence relevant to the debate
- CONCEDE: Drop your hypothesis if a better explanation exists
- SYNTHESIZE: Propose merging two hypotheses into one explanation

RULES:
- You MUST respond to challenges against your hypotheses (REBUT or CONCEDE)
- Your confidence should change based on evidence, not stubbornness
- If you CHALLENGE, cite specific evidence or reasoning flaws
- If you SUPPORT, explain what domain evidence corroborates it

Return ONLY valid JSON:
{{
  "actions": [
    {{
      "action_type": "CHALLENGE|SUPPORT|REBUT|UPDATE_CONFIDENCE|PRESENT_EVIDENCE|CONCEDE|SYNTHESIZE",
      "target_hypothesis_id": "agent-id-h0 or empty",
      "content": "What you're doing (1-2 sentences)",
      "reasoning": "Why (2-3 sentences with specific evidence)",
      "evidence": ["specific evidence items"],
      "new_confidence": 0.65
    }}
  ]
}}
"""


def _build_adversarial_prompt(agent, spike_context: Dict, all_hypotheses: List,
                                recent_actions: List[SimAction], round_num: int) -> str:
    """Adversarial agents (Devil's Advocate, Null Hypothesis) get a special prompt."""
    spike = spike_context.get("spike", {})
    market = spike_context.get("market_title", "Unknown")

    hyps_text = "\n".join(
        f"  [{h.agent_id}] (ID: {h.id}) {h.cause_description[:120]} — {h.confidence:.0%}"
        for h in sorted(all_hypotheses, key=lambda x: x.confidence, reverse=True)[:8]
        if h.status != "debunked"
    )

    recent = [a for a in recent_actions if a.agent_id != agent.id][-6:]
    actions_text = "\n".join(
        f"  R{a.round} [{a.agent_name}] {a.action_type}: {a.content[:80]}"
        for a in recent
    ) if recent else "  (No recent actions)"

    return f"""You are {agent.name}. Your role: {agent.description}

MARKET: {market}
SPIKE: {spike.get('direction', 'unknown')} {float(spike.get('magnitude', 0)) * 100:.1f}%

ROUND {round_num}: Your job is to stress-test ALL hypotheses.

CURRENT HYPOTHESES:
{hyps_text}

RECENT DEBATE:
{actions_text}

YOUR TASK: Find the strongest argument AGAINST the top 2-3 hypotheses.
For each, look for:
- Timing problems (cause happened after the spike?)
- Missing evidence (what should we see if this were true?)
- Simpler explanations (Occam's razor)
- Magnitude mismatch (cause too small for this spike size?)
- Alternative explanations the proposing agent hasn't considered

Also: If any hypothesis has been WELL-DEFENDED in rebuttals, acknowledge that.

Return ONLY valid JSON:
{{
  "actions": [
    {{
      "action_type": "CHALLENGE",
      "target_hypothesis_id": "hypothesis-id",
      "content": "The strongest argument against this",
      "reasoning": "Detailed reasoning with evidence",
      "evidence": ["counter-evidence items"]
    }}
  ]
}}
"""


# ─── Simulation engine ───────────────────────────────────────────────

async def run_agent_simulation(
    agents: List,
    hypotheses: List,
    spike_context: Dict,
    llm_call: Callable,
    num_rounds: int = 3,
    _run_in_thread=None,
) -> AsyncGenerator[Dict, None]:
    """
    Run multi-round agent simulation.

    Yields SSE events:
      {"step": "sim_round", "data": {"round": N, "total": M}}
      {"step": "sim_action", "data": {action details}}
      {"step": "sim_status", "data": {simulation status}}
      {"step": "sim_complete", "data": {final state}}
    """
    if _run_in_thread is None:
        from .bace_parallel import _run_in_thread as _rit
        _run_in_thread = _rit

    from .bace_debate import _parse_json_response

    state = SimulationState(total_rounds=num_rounds)

    # Initialize confidence history from proposals
    for h in hypotheses:
        state.confidence_history[h.id] = [h.confidence]

    # Initialize stance map
    for agent in agents:
        state.agent_stance_map[agent.id] = {}

    state.active_hypotheses = len([h for h in hypotheses if h.status != "debunked"])

    # Log initial proposals as round 0 actions
    for h in hypotheses:
        agent_name = next((a.name for a in agents if a.id == h.agent_id), h.agent_id)
        action = SimAction(
            round=0, agent_id=h.agent_id, agent_name=agent_name,
            action_type="PROPOSE", content=h.cause_description[:150],
            reasoning=h.causal_chain[:200] if h.causal_chain else "",
            confidence_before=0.0, confidence_after=h.confidence,
            timestamp=time.time(),
        )
        state.actions.append(action)

    # === Simulation rounds ===
    for round_num in range(1, num_rounds + 1):
        state.current_round = round_num

        yield {"step": "sim_round", "data": {
            "round": round_num, "total": num_rounds,
            "active_hypotheses": state.active_hypotheses,
        }}

        # Determine turn order — agents with challenged hypotheses go first (REBUT priority)
        challenged_agents = set()
        for a in state.actions:
            if a.round == round_num - 1 and a.action_type == "CHALLENGE":
                # Find who owns the targeted hypothesis
                target_hyp = next((h for h in hypotheses if h.id == a.target_hypothesis_id), None)
                if target_hyp:
                    challenged_agents.add(target_hyp.agent_id)

        # Sort: challenged agents first, then by tier (tier 1 before tier 2), adversarial last
        def agent_priority(a):
            is_challenged = 0 if a.id in challenged_agents else 1
            is_adversarial = 1 if a.tier == 3 else 0
            return (is_challenged, is_adversarial, a.tier)

        sorted_agents = sorted(agents, key=agent_priority)

        # Each agent takes their turn
        for agent in sorted_agents:
            own_hyps = [h for h in hypotheses if h.agent_id == agent.id and h.status != "debunked"]
            active_hyps = [h for h in hypotheses if h.status != "debunked"]

            # Skip agents with no hypotheses and no adversarial role
            if not own_hyps and agent.tier != 3:
                continue

            # Build prompt
            if agent.tier == 3:
                prompt = _build_adversarial_prompt(agent, spike_context, active_hyps, state.actions, round_num)
            else:
                prompt = _build_round_prompt(agent, spike_context, own_hyps, active_hyps, state.actions, round_num)

            try:
                response = await _run_in_thread(llm_call, prompt)
                parsed = _parse_json_response(response)

                if not parsed or "actions" not in parsed:
                    continue

                for act_data in parsed["actions"][:3]:  # Max 3 actions per agent per round
                    action_type = act_data.get("action_type", "").upper()
                    if action_type not in ACTION_TYPES:
                        continue

                    target_hyp_id = act_data.get("target_hypothesis_id", "")
                    target_hyp = next((h for h in hypotheses if h.id == target_hyp_id), None)
                    target_agent_id = target_hyp.agent_id if target_hyp else ""

                    # Get current confidence for this agent's top hypothesis
                    top_own = own_hyps[0] if own_hyps else None
                    conf_before = top_own.confidence if top_own else 0.0

                    # Apply confidence changes
                    new_conf = float(act_data.get("new_confidence", conf_before))
                    conf_after = conf_before

                    if action_type == "UPDATE_CONFIDENCE" and top_own:
                        conf_after = max(0.05, min(0.95, new_conf))
                        top_own.confidence = conf_after

                    elif action_type == "SUPPORT" and target_hyp:
                        # Supporting boosts target confidence slightly
                        target_hyp.confidence = min(0.95, target_hyp.confidence + 0.03)
                        state.agent_stance_map[agent.id][target_hyp_id] = "support"

                    elif action_type == "CHALLENGE" and target_hyp:
                        # Challenge reduces target confidence
                        target_hyp.confidence = max(0.05, target_hyp.confidence - 0.04)
                        state.agent_stance_map[agent.id][target_hyp_id] = "challenge"

                    elif action_type == "REBUT" and target_hyp:
                        # Successful rebuttal partially recovers confidence
                        target_hyp.confidence = min(0.95, target_hyp.confidence + 0.02)

                    elif action_type == "CONCEDE" and top_own:
                        top_own.status = "debunked"
                        conf_after = 0.0
                        top_own.confidence = 0.0
                        state.conceded_hypotheses += 1
                        state.active_hypotheses = len([h for h in hypotheses if h.status != "debunked"])

                    elif action_type == "SYNTHESIZE":
                        # Synthesize doesn't change confidence directly
                        pass

                    action = SimAction(
                        round=round_num,
                        agent_id=agent.id,
                        agent_name=agent.name,
                        action_type=action_type,
                        target_agent_id=target_agent_id,
                        target_hypothesis_id=target_hyp_id,
                        content=act_data.get("content", "")[:200],
                        reasoning=act_data.get("reasoning", "")[:300],
                        evidence=act_data.get("evidence", [])[:5],
                        confidence_before=round(conf_before, 3),
                        confidence_after=round(conf_after if action_type == "UPDATE_CONFIDENCE" else conf_before, 3),
                        timestamp=time.time(),
                    )
                    state.actions.append(action)

                    # Emit each action as SSE event
                    yield {"step": "sim_action", "data": action.to_sse()}

            except Exception as e:
                logger.warning("Agent %s failed in round %d: %s", agent.id, round_num, e)

        # Update confidence history after each round
        for h in hypotheses:
            if h.id in state.confidence_history:
                state.confidence_history[h.id].append(h.confidence)
            else:
                state.confidence_history[h.id] = [h.confidence]

        state.active_hypotheses = len([h for h in hypotheses if h.status != "debunked"])

        # Emit round status
        yield {"step": "sim_status", "data": state.to_status()}

        # Early termination: if all agents agree (no challenges in this round)
        round_actions = [a for a in state.actions if a.round == round_num]
        challenges_this_round = [a for a in round_actions if a.action_type == "CHALLENGE"]
        if round_num > 1 and len(challenges_this_round) == 0:
            logger.info("Simulation converged at round %d — no challenges", round_num)
            yield {"step": "sim_action", "data": {
                "round": round_num, "agent": "system", "agent_name": "System",
                "action": "CONVERGED", "content": f"All agents reached consensus after round {round_num}",
                "target_agent": "", "target_hyp": "",
                "confidence_before": 0, "confidence_after": 0,
            }}
            break

    # === Final analysis ===
    # Derive convergence/divergence from action log
    convergence_groups = _derive_convergence(state, hypotheses, agents)
    divergence_pairs = _derive_divergence(state, hypotheses)

    yield {"step": "sim_complete", "data": {
        "rounds_completed": state.current_round,
        "total_actions": len(state.actions),
        "active_hypotheses": state.active_hypotheses,
        "conceded_hypotheses": state.conceded_hypotheses,
        "convergence_groups": len(convergence_groups),
        "divergence_pairs": len(divergence_pairs),
        "confidence_history": {
            hid: [round(c, 3) for c in confs]
            for hid, confs in state.confidence_history.items()
        },
    }}

    # Store results on the state for downstream use
    state.convergence_groups_result = convergence_groups
    state.divergence_pairs_result = divergence_pairs


def _derive_convergence(state: SimulationState, hypotheses: List, agents: List) -> Dict[str, List[str]]:
    """Derive convergence groups from the action log."""
    # A hypothesis has convergence if 2+ agents supported it
    support_counts: Dict[str, List[str]] = {}  # hyp_id -> [supporting agent_ids]

    for agent_id, stances in state.agent_stance_map.items():
        for hyp_id, stance in stances.items():
            if stance == "support":
                support_counts.setdefault(hyp_id, []).append(agent_id)

    groups = {}
    for hyp_id, supporters in support_counts.items():
        if len(supporters) >= 2:
            hyp = next((h for h in hypotheses if h.id == hyp_id), None)
            if hyp:
                label = hyp.cause_description[:60]
                groups[label] = [hyp_id] + supporters

    return groups


def _derive_divergence(state: SimulationState, hypotheses: List) -> List[Dict]:
    """Derive divergence pairs from challenges that were NOT resolved by concession."""
    # Find challenges that persisted (no CONCEDE from the target)
    challenges = [a for a in state.actions if a.action_type == "CHALLENGE"]
    concessions = {a.agent_id for a in state.actions if a.action_type == "CONCEDE"}

    pairs = []
    for c in challenges:
        target_hyp = next((h for h in hypotheses if h.id == c.target_hypothesis_id), None)
        if target_hyp and target_hyp.agent_id not in concessions and target_hyp.status != "debunked":
            pairs.append({
                "challenger": c.agent_id,
                "challenger_name": c.agent_name,
                "target_hyp": c.target_hypothesis_id,
                "target_agent": target_hyp.agent_id,
                "challenge_content": c.content[:100],
                "round": c.round,
            })

    return pairs


def simulation_to_interaction_round(state: SimulationState, hypotheses: List, agents: List):
    """
    Convert simulation results to InteractionRound format for backward compatibility
    with scenario clustering.
    """
    from .bace_interaction import InteractionRound, InteractionResponse

    round_data = InteractionRound(round_number=state.current_round)

    # Convert sim actions to InteractionResponses
    for action in state.actions:
        if action.action_type in ("SUPPORT", "CHALLENGE", "CONCEDE"):
            stance = "support" if action.action_type == "SUPPORT" else "challenge"
            round_data.responses.append(InteractionResponse(
                responder_id=action.agent_id,
                responder_name=action.agent_name,
                target_hypothesis_id=action.target_hypothesis_id,
                target_agent_id=action.target_agent_id,
                stance=stance,
                reasoning=action.content,
                confidence_shift=-0.04 if stance == "challenge" else 0.03,
                new_evidence=action.evidence,
            ))

    round_data.convergence_groups = _derive_convergence(state, hypotheses, agents)
    round_data.divergence_pairs = [
        {"hypothesis_id": d["target_hyp"], "proposed_by": d["target_agent"], "challenged_by": d["challenger"]}
        for d in _derive_divergence(state, hypotheses)
    ]

    return round_data
