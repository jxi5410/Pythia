"""
Forward Simulation Engine — Validates RCE attributors via forward prediction.

MiroFish architecture adapted for Pythia:
  1. Take RCE's attributed cause(s)
  2. Spawn market participant agents (institutional, retail, market maker, analyst, news)
  3. Inject the cause as a "seed event" (MiroFish's parameter injection)
  4. Simulate N rounds of agent interaction
  5. Observe: does the simulated price move match the real spike?

If simulation reproduces the spike → attribution validated.
If simulation doesn't reproduce → cause may be insufficient or wrong.

This is the "close the loop" mechanism: RCE finds causes (backward),
Forward Simulation tests them (forward), creating a bidirectional validation.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Market participant agent personas
# ----------------------------------------------------------------

@dataclass
class MarketAgent:
    """A simulated market participant."""
    id: str
    name: str
    agent_type: str  # institutional, retail, market_maker, analyst, news_reporter
    description: str
    initial_position: str  # 'long', 'short', 'flat'
    risk_tolerance: float  # 0-1
    information_speed: float  # 0-1 (how fast they react to news)
    contrarian_tendency: float  # 0-1 (tendency to fade moves)
    system_prompt: str = ""


MARKET_PARTICIPANT_TEMPLATES = [
    MarketAgent(
        id="inst-quant", name="Quantitative Fund PM",
        agent_type="institutional",
        description="Systematic trader. Reacts to statistical signals, not narratives. Uses half-Kelly sizing.",
        initial_position="flat", risk_tolerance=0.7, information_speed=0.9, contrarian_tendency=0.3,
    ),
    MarketAgent(
        id="inst-macro", name="Macro Hedge Fund",
        agent_type="institutional",
        description="Trades macro themes. Positions ahead of events based on fundamental analysis.",
        initial_position="flat", risk_tolerance=0.6, information_speed=0.7, contrarian_tendency=0.2,
    ),
    MarketAgent(
        id="retail-degen", name="Retail Speculator",
        agent_type="retail",
        description="High conviction, low analysis. Follows Twitter/Telegram signals. Overreacts to headlines.",
        initial_position="flat", risk_tolerance=0.9, information_speed=0.5, contrarian_tendency=0.1,
    ),
    MarketAgent(
        id="retail-informed", name="Informed Retail",
        agent_type="retail",
        description="Domain expert (e.g., policy analyst who trades prediction markets). Good at causation, slow to execute.",
        initial_position="flat", risk_tolerance=0.4, information_speed=0.3, contrarian_tendency=0.4,
    ),
    MarketAgent(
        id="mm-primary", name="Primary Market Maker",
        agent_type="market_maker",
        description="Provides liquidity. Adjusts spread based on information flow. Reduces exposure on high-vol events.",
        initial_position="flat", risk_tolerance=0.3, information_speed=0.95, contrarian_tendency=0.7,
    ),
    MarketAgent(
        id="analyst-sell", name="Sell-Side Analyst",
        agent_type="analyst",
        description="Publishes research that moves retail positioning. Conservative, lag institutional flow.",
        initial_position="flat", risk_tolerance=0.2, information_speed=0.4, contrarian_tendency=0.5,
    ),
    MarketAgent(
        id="news-reporter", name="Financial Journalist",
        agent_type="news_reporter",
        description="Amplifies narratives. Doesn't trade but publishes analysis that influences others.",
        initial_position="flat", risk_tolerance=0.0, information_speed=0.6, contrarian_tendency=0.3,
    ),
    MarketAgent(
        id="arb-bot", name="Arbitrage Bot",
        agent_type="institutional",
        description="Cross-market arbitrageur. Exploits price discrepancies between Polymarket, Kalshi, and related markets.",
        initial_position="flat", risk_tolerance=0.8, information_speed=1.0, contrarian_tendency=0.0,
    ),
]


# ----------------------------------------------------------------
# Simulation state
# ----------------------------------------------------------------

@dataclass
class SimulationRound:
    """One round of the forward simulation."""
    round_num: int
    agent_actions: List[Dict] = field(default_factory=list)
    price_after: float = 0.0
    volume_this_round: float = 0.0
    narrative: str = ""  # Summary of what happened


@dataclass
class ForwardSimulationResult:
    """Full result of a forward simulation run."""
    seed_cause: str
    seed_confidence: float
    initial_price: float
    final_price: float
    actual_spike_magnitude: float
    simulated_magnitude: float
    magnitude_match: float  # 0-1, how close sim matches reality
    direction_match: bool
    rounds: List[SimulationRound] = field(default_factory=list)
    agent_final_positions: Dict[str, str] = field(default_factory=dict)
    validation_verdict: str = ""  # "validated", "partially_validated", "not_validated"
    reasoning: str = ""
    elapsed_seconds: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "seed_cause": self.seed_cause,
            "seed_confidence": self.seed_confidence,
            "initial_price": self.initial_price,
            "final_price": round(self.final_price, 4),
            "actual_spike_magnitude": round(self.actual_spike_magnitude, 4),
            "simulated_magnitude": round(self.simulated_magnitude, 4),
            "magnitude_match": round(self.magnitude_match, 3),
            "direction_match": self.direction_match,
            "validation_verdict": self.validation_verdict,
            "reasoning": self.reasoning,
            "rounds": [asdict(r) for r in self.rounds],
            "agent_final_positions": self.agent_final_positions,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
        }


# ----------------------------------------------------------------
# Agent action prompts
# ----------------------------------------------------------------

def build_simulation_prompt(
    agent: MarketAgent,
    seed_event: str,
    market_title: str,
    current_price: float,
    round_num: int,
    previous_actions: List[Dict],
    total_rounds: int,
) -> str:
    """Build prompt for an agent to decide their action this round."""
    prev_summary = "  No previous actions (Round 1)." if not previous_actions else "\n".join(
        f"  Round {a['round']}: [{a['agent_type']}] {a['action']} — {a['reasoning'][:80]}"
        for a in previous_actions[-10:]  # Last 10 actions
    )

    return f"""You are {agent.name}, a {agent.agent_type} in a prediction market simulation.

YOUR PROFILE:
  Type: {agent.agent_type}
  Description: {agent.description}
  Risk tolerance: {agent.risk_tolerance:.0%}
  Information speed: {agent.information_speed:.0%} (how fast you react)
  Contrarian tendency: {agent.contrarian_tendency:.0%}

MARKET: {market_title}
CURRENT PRICE: {current_price:.2f} (probability)
ROUND: {round_num} of {total_rounds}

SEED EVENT (just occurred):
  {seed_event}

RECENT MARKET ACTIVITY:
{prev_summary}

TASK: Decide your action this round. Consider:
- Your agent type and risk profile
- Whether this event is relevant to the market
- What other participants are likely doing
- Whether the current price already reflects the event
- Your contrarian tendency — should you fade the move?

Return ONLY valid JSON:
{{
  "action": "buy_yes|buy_no|sell_yes|sell_no|hold|widen_spread|tighten_spread|publish_analysis",
  "size": "large|medium|small|none",
  "reasoning": "Why you're taking this action (2-3 sentences)",
  "price_impact_estimate": 0.01,
  "new_information": "Any new insight you bring to the market (or empty string)"
}}
"""


# ----------------------------------------------------------------
# Forward simulation engine
# ----------------------------------------------------------------

def run_forward_simulation(
    attributed_cause: str,
    cause_confidence: float,
    spike_context: Dict,
    llm_call: Callable,
    n_rounds: int = 8,
    agents: List[MarketAgent] = None,
) -> ForwardSimulationResult:
    """
    Run a forward simulation to test whether an attributed cause
    reproduces the observed spike.

    Args:
        attributed_cause: The cause identified by RCE
        cause_confidence: RCE's confidence in this cause
        spike_context: Original spike context dict
        llm_call: LLM function for agent reasoning
        n_rounds: Number of simulation rounds
        agents: Custom agent list (uses defaults if None)

    Returns:
        ForwardSimulationResult with validation verdict
    """
    start_time = time.time()

    if agents is None:
        agents = list(MARKET_PARTICIPANT_TEMPLATES)

    spike = spike_context.get("spike", {})
    market_title = spike_context.get("market_title", "Unknown market")
    initial_price = float(spike.get("price_before", 0.5))
    actual_final = float(spike.get("price_after", 0.5))
    actual_magnitude = float(spike.get("magnitude", 0))
    actual_direction = spike.get("direction", "up")

    current_price = initial_price
    all_actions = []
    rounds = []

    logger.info("Forward simulation: '%s' on '%s'", attributed_cause[:50], market_title[:40])
    logger.info("  Initial price: %.2f → Actual: %.2f (%.1f%% %s)",
                initial_price, actual_final, actual_magnitude * 100, actual_direction)

    for round_num in range(1, n_rounds + 1):
        round_actions = []

        for agent in agents:
            # Stagger information arrival based on agent speed
            # Faster agents act in earlier rounds
            if round_num == 1 and agent.information_speed < 0.5:
                continue  # Slow agents don't act in round 1
            if round_num <= 2 and agent.information_speed < 0.3:
                continue  # Very slow agents wait until round 3

            prompt = build_simulation_prompt(
                agent, attributed_cause, market_title,
                current_price, round_num, all_actions[-15:], n_rounds,
            )

            try:
                response = llm_call(prompt)
                parsed = _parse_json(response)

                if parsed:
                    action = {
                        "round": round_num,
                        "agent_id": agent.id,
                        "agent_type": agent.agent_type,
                        "action": parsed.get("action", "hold"),
                        "size": parsed.get("size", "none"),
                        "reasoning": parsed.get("reasoning", ""),
                        "price_impact": float(parsed.get("price_impact_estimate", 0)),
                        "new_info": parsed.get("new_information", ""),
                    }
                    round_actions.append(action)

                    # Apply price impact
                    impact = action["price_impact"]
                    size_mult = {"large": 1.0, "medium": 0.6, "small": 0.3, "none": 0}.get(action["size"], 0)
                    if action["action"] in ("buy_yes", "sell_no"):
                        current_price += abs(impact) * size_mult
                    elif action["action"] in ("buy_no", "sell_yes"):
                        current_price -= abs(impact) * size_mult
                    elif action["action"] == "widen_spread":
                        pass  # Market maker reduces liquidity, amplifies future moves
                    # Clamp price to [0.01, 0.99]
                    current_price = max(0.01, min(0.99, current_price))

            except Exception as e:
                logger.debug("Agent %s round %d failed: %s", agent.id, round_num, e)

        all_actions.extend(round_actions)
        volume = sum(1 for a in round_actions if a["size"] != "none")

        round_result = SimulationRound(
            round_num=round_num,
            agent_actions=round_actions,
            price_after=round(current_price, 4),
            volume_this_round=volume,
            narrative=f"Round {round_num}: {len(round_actions)} agents acted, price → {current_price:.2f}",
        )
        rounds.append(round_result)

        logger.info("  Round %d: price=%.3f, actions=%d, volume=%d",
                     round_num, current_price, len(round_actions), volume)

    # Compute validation metrics
    simulated_magnitude = abs(current_price - initial_price)
    simulated_direction = "up" if current_price > initial_price else "down"
    direction_match = simulated_direction == actual_direction

    # Magnitude match: 1.0 = perfect, 0.0 = completely wrong
    if actual_magnitude > 0:
        ratio = simulated_magnitude / actual_magnitude
        magnitude_match = max(0, 1 - abs(1 - ratio))  # 1 when ratio=1, 0 when far off
    else:
        magnitude_match = 1.0 if simulated_magnitude < 0.01 else 0.0

    # Validation verdict
    if direction_match and magnitude_match > 0.5:
        verdict = "validated"
    elif direction_match and magnitude_match > 0.25:
        verdict = "partially_validated"
    elif direction_match:
        verdict = "direction_only"
    else:
        verdict = "not_validated"

    # Agent final positions
    final_positions = {}
    for agent in agents:
        agent_actions = [a for a in all_actions if a["agent_id"] == agent.id]
        if agent_actions:
            last = agent_actions[-1]
            if last["action"] in ("buy_yes", "sell_no"):
                final_positions[agent.id] = "long"
            elif last["action"] in ("buy_no", "sell_yes"):
                final_positions[agent.id] = "short"
            else:
                final_positions[agent.id] = "flat"
        else:
            final_positions[agent.id] = "flat"

    elapsed = time.time() - start_time

    reasoning = (
        f"Simulation {'reproduced' if verdict in ('validated', 'partially_validated') else 'did not reproduce'} the observed spike. "
        f"Simulated: {simulated_direction} {simulated_magnitude:.1%} vs actual: {actual_direction} {actual_magnitude:.1%}. "
        f"Direction {'match' if direction_match else 'mismatch'}. Magnitude match: {magnitude_match:.0%}. "
        f"{len(all_actions)} total agent actions across {n_rounds} rounds."
    )

    result = ForwardSimulationResult(
        seed_cause=attributed_cause,
        seed_confidence=cause_confidence,
        initial_price=initial_price,
        final_price=current_price,
        actual_spike_magnitude=actual_magnitude,
        simulated_magnitude=simulated_magnitude,
        magnitude_match=magnitude_match,
        direction_match=direction_match,
        rounds=rounds,
        agent_final_positions=final_positions,
        validation_verdict=verdict,
        reasoning=reasoning,
        elapsed_seconds=elapsed,
    )

    logger.info("Forward simulation complete: %s (%.1fs)", verdict, elapsed)
    logger.info("  Simulated: %s %.1f%% | Actual: %s %.1f%% | Match: %.0f%%",
                simulated_direction, simulated_magnitude * 100,
                actual_direction, actual_magnitude * 100,
                magnitude_match * 100)

    return result


# ----------------------------------------------------------------
# Full validation: run forward sim for each RCE attributor
# ----------------------------------------------------------------

def validate_rce_attributors(
    rce_result: Dict,
    llm_call: Callable,
    n_rounds: int = 6,
) -> Dict:
    """
    Run forward simulation for each surviving RCE hypothesis.

    Args:
        rce_result: Output from attribute_spike_rce()
        llm_call: LLM function for simulation agents
        n_rounds: Rounds per simulation

    Returns:
        Dict with validation results for each attributor
    """
    context = rce_result.get("context", {})
    survived = rce_result.get("survived", [])

    if not survived:
        logger.warning("No survived hypotheses to validate")
        return {"validations": [], "summary": "No attributors to validate"}

    validations = []

    for hyp in survived[:5]:  # Cap at 5 to manage LLM costs
        cause = hyp.get("cause_description", "")
        confidence = float(hyp.get("confidence", 0.5))

        logger.info("Validating: %s (conf=%.0f%%)", cause[:50], confidence * 100)

        sim_result = run_forward_simulation(
            attributed_cause=cause,
            cause_confidence=confidence,
            spike_context=context,
            llm_call=llm_call,
            n_rounds=n_rounds,
        )

        # Adjust RCE confidence based on forward simulation
        original_confidence = confidence
        if sim_result.validation_verdict == "validated":
            adjusted_confidence = min(1.0, confidence + 0.15)
        elif sim_result.validation_verdict == "partially_validated":
            adjusted_confidence = min(1.0, confidence + 0.05)
        elif sim_result.validation_verdict == "not_validated":
            adjusted_confidence = max(0.0, confidence - 0.20)
        else:
            adjusted_confidence = confidence

        validations.append({
            "cause": cause,
            "rce_confidence": original_confidence,
            "adjusted_confidence": round(adjusted_confidence, 3),
            "simulation": sim_result.to_dict(),
        })

        logger.info("  Validation: %s | conf: %.0f%% → %.0f%%",
                     sim_result.validation_verdict,
                     original_confidence * 100, adjusted_confidence * 100)

    # Summary
    validated_count = sum(1 for v in validations if v["simulation"]["validation_verdict"] in ("validated", "partially_validated"))
    total = len(validations)

    summary = {
        "validations": validations,
        "total_tested": total,
        "validated": validated_count,
        "validation_rate": round(validated_count / max(total, 1), 2),
        "summary": f"{validated_count}/{total} attributors validated by forward simulation",
    }

    logger.info("Validation complete: %s", summary["summary"])
    return summary


def _parse_json(response: str) -> Optional[Dict]:
    """Parse JSON from LLM response."""
    if not response:
        return None
    text = re.sub(r'^```(?:json)?\s*', '', response.strip())
    text = re.sub(r'\s*```$', '', text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{[\s\S]*\}', text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
    return None
