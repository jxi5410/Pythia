"""
BACE Agents — Multi-agent adversarial causal debate system.

Inspired by MiroFish's persona generation + OASIS social simulation,
but reversed: instead of agents reacting to an event to predict outcomes,
agents investigate an observed outcome to find its causes.

Architecture:
  Tier 1 — 5 core agents (always active)
  Tier 2 — 3-5 conditional agents (spawned per market category)
  Tier 3 — 2 adversarial agents (always active)

Each agent:
  1. Has a domain persona with specific reasoning priors
  2. Gathers evidence from specific sources
  3. Proposes causal hypotheses with confidence
  4. Critiques other agents' hypotheses
  5. Updates confidence based on debate

The debate protocol:
  Round 1: Each agent proposes 1-3 hypotheses with evidence
  Round 2-N: Agents critique each other's hypotheses, present counter-evidence
  Final: Surviving hypotheses (not debunked) become attributor candidates
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Hypothesis — what an agent proposes as a cause
# ----------------------------------------------------------------

@dataclass
class CausalHypothesis:
    """A single causal hypothesis proposed by an agent."""
    id: str
    agent_id: str
    cause_description: str
    causal_chain: str  # How this cause leads to the spike
    evidence: List[str]  # Supporting evidence (news headlines, data points)
    evidence_urls: List[str] = field(default_factory=list)
    confidence: float = 0.5  # 0-1
    temporal_plausibility: str = ""  # "cause precedes effect by 2h"
    magnitude_plausibility: str = ""  # "magnitude is proportional to similar events"
    impact_speed: str = ""  # "immediate", "fast", "delayed", "slow"
    time_to_peak_impact: str = ""  # "2 hours", "3 days"
    timing_assessment: str = ""  # "plausible", "implausible", "uncertain" — from critiques
    status: str = "proposed"  # proposed, supported, challenged, debunked, survived
    challenges: List[str] = field(default_factory=list)  # critiques from other agents
    rebuttals: List[str] = field(default_factory=list)  # responses to challenges
    round_proposed: int = 0
    round_debunked: int = -1  # -1 = not debunked

    def to_dict(self) -> Dict:
        return asdict(self)


# ----------------------------------------------------------------
# Agent persona
# ----------------------------------------------------------------

@dataclass
class AgentPersona:
    """Defines an agent's reasoning domain and behavioral parameters."""
    id: str
    name: str
    tier: int  # 1, 2, or 3
    domain: str
    description: str
    reasoning_priors: List[str]  # What this agent looks for
    evidence_sources: List[str]  # Where this agent searches
    bias_warning: str  # Known blind spot
    system_prompt: str = ""  # Full LLM system prompt (built at runtime)


# ----------------------------------------------------------------
# Tier 1: Core agents (always active)
# ----------------------------------------------------------------

CORE_AGENTS = [
    AgentPersona(
        id="macro-policy",
        name="Macro Policy Analyst",
        tier=1,
        domain="macro_policy",
        description="Specializes in central bank decisions, fiscal policy, and government actions as causal drivers.",
        reasoning_priors=[
            "Policy announcements cause immediate repricing",
            "Leaked minutes/speeches precede official releases",
            "Fiscal policy changes affect multiple markets simultaneously",
            "Central bank communication follows predictable patterns",
        ],
        evidence_sources=["reuters", "bloomberg", "fed.gov", "treasury.gov", "ecb.europa.eu"],
        bias_warning="Overweights official channels; may miss informal leaks or market microstructure",
    ),
    AgentPersona(
        id="market-structure",
        name="Market Microstructure Analyst",
        tier=1,
        domain="market_structure",
        description="Analyzes order flow, liquidity dynamics, and positioning as causal mechanisms.",
        reasoning_priors=[
            "Large position changes precede price moves",
            "Liquidity withdrawal amplifies volatility",
            "Informed trading creates volume anomalies before news breaks",
            "Market maker inventory imbalances cause price pressure",
            "Stop-loss cascades amplify initial moves",
        ],
        evidence_sources=["exchange_orderbook", "volume_data", "open_interest", "whale_alerts"],
        bias_warning="May attribute noise to signal; not all volume anomalies are informed trading",
    ),
    AgentPersona(
        id="geopolitical",
        name="Geopolitical Risk Analyst",
        tier=1,
        domain="geopolitical",
        description="Focuses on diplomatic, military, and conflict-related drivers.",
        reasoning_priors=[
            "Military posturing and exercises signal escalation risk",
            "Diplomatic summits and back-channel talks affect ceasefire probabilities",
            "Sanctions and export controls create supply chain disruptions",
            "Elections and political transitions create policy uncertainty",
        ],
        evidence_sources=["reuters_world", "al_jazeera", "scmp", "foreign_affairs", "defense_news"],
        bias_warning="Overfits to dramatic events; may miss economic fundamentals driving the same market",
    ),
    AgentPersona(
        id="regulatory",
        name="Regulatory & Legal Analyst",
        tier=1,
        domain="regulatory",
        description="Tracks regulatory actions, legal rulings, and compliance changes.",
        reasoning_priors=[
            "SEC/CFTC actions create immediate repricing in affected markets",
            "Court rulings establish precedent that changes probability distributions",
            "Regulatory guidance often leaks before official publication",
            "Cross-jurisdictional regulatory arbitrage creates cascading effects",
        ],
        evidence_sources=["sec.gov", "cftc.gov", "federal_register", "court_filings", "bis.gov"],
        bias_warning="Regulatory actions are usually slow; may not explain sudden spikes without a leak",
    ),
    AgentPersona(
        id="narrative-sentiment",
        name="Narrative & Sentiment Analyst",
        tier=1,
        domain="narrative_sentiment",
        description="Analyzes social media velocity, narrative shifts, and crowd behavior.",
        reasoning_priors=[
            "Twitter/X velocity spikes precede market moves by 15-60 minutes",
            "Reddit sentiment aggregation creates herding behavior",
            "Telegram trading channels disseminate information faster than mainstream media",
            "Narrative momentum can sustain moves beyond fundamental justification",
            "Contrarian signals emerge when sentiment becomes one-sided",
        ],
        evidence_sources=["twitter_x", "reddit", "telegram", "polymarket_comments", "crypto_twitter"],
        bias_warning="Sentiment is noisy; social media often reacts to price moves, not vice versa",
    ),
    AgentPersona(
        id="informed-flow",
        name="Informed Flow Analyst",
        tier=1,
        domain="informed_flow",
        description=(
            "Detects whether a spike was driven by informed money (insiders, institutional edge) "
            "versus uninformed retail flow. Analyzes order size distribution, timing of large trades "
            "relative to news, and volume patterns to infer what type of participant initiated the move."
        ),
        reasoning_priors=[
            "Block trades preceding public news indicate informed trading or leaked information",
            "Retail flow follows news by 5-30 minutes; informed flow precedes or is concurrent",
            "Single large orders in thin markets indicate whale conviction, not broad consensus",
            "Gradual accumulation over hours suggests institutional positioning, not breaking news",
            "Volume without news = someone knows something; news without volume = market already priced it in",
            "Time-of-day matters: institutional activity peaks during business hours; retail peaks evenings/weekends",
        ],
        evidence_sources=["exchange_orderbook", "volume_data", "trade_size_distribution", "time_of_day_analysis"],
        bias_warning="Not all pre-news trading is informed; some is coincidental or based on public signals the analyst missed",
    ),
    AgentPersona(
        id="cross-market",
        name="Cross-Market Contagion Analyst",
        tier=1,
        domain="cross_market",
        description=(
            "Determines whether a spike originated in this prediction market or propagated from "
            "another market (Kalshi, equities, crypto, FX, derivatives). Checks lead-lag relationships, "
            "arb bot signatures, and whether correlated assets moved first."
        ),
        reasoning_priors=[
            "If SPY/BTC moved first and the prediction market followed, the cause is macro not contract-specific",
            "Kalshi and Polymarket prices should converge; divergence suggests exchange-specific cause",
            "Arb bot activity creates rapid mean-reversion; sustained divergence indicates new information",
            "VIX spikes preceding prediction market moves suggest risk-off contagion, not political news",
            "Currency moves (DXY, CNH) preceding political market moves suggest economic cause misattributed as political",
            "If multiple unrelated prediction markets spike simultaneously, the cause is systemic not contract-specific",
        ],
        evidence_sources=["cross_market_prices", "equity_indices", "fx_pairs", "vix", "kalshi_arb"],
        bias_warning="Cross-market correlation doesn't prove causation; markets can react independently to the same news",
    ),
]


# ----------------------------------------------------------------
# Tier 2: Conditional agents (spawned per category)
# ----------------------------------------------------------------

CONDITIONAL_AGENTS: Dict[str, List[AgentPersona]] = {
    "crypto": [
        AgentPersona(
            id="onchain",
            name="On-chain Analyst",
            tier=2, domain="crypto_onchain",
            description="Analyzes blockchain data: whale movements, exchange flows, DeFi metrics.",
            reasoning_priors=["Large exchange withdrawals signal accumulation", "Miner selling pressure precedes corrections", "DeFi TVL shifts indicate rotation"],
            evidence_sources=["blockchain_explorers", "glassnode", "dune_analytics"],
            bias_warning="On-chain data has lag; movements may be post-hoc not causal",
        ),
        AgentPersona(
            id="etf-flows",
            name="ETF Flow Analyst",
            tier=2, domain="crypto_etf",
            description="Tracks spot ETF inflows/outflows as institutional demand proxy.",
            reasoning_priors=["Record ETF inflows create buy pressure", "Institutional allocation shifts drive multi-day trends"],
            evidence_sources=["etf_filings", "bloomberg_terminal", "bitwise_reports"],
            bias_warning="ETF flows are published with delay; may not explain intraday spikes",
        ),
    ],
    "fed_rate": [
        AgentPersona(
            id="fixed-income",
            name="Fixed Income Strategist",
            tier=2, domain="fixed_income",
            description="Analyzes yield curves, rate expectations, and bond market signals.",
            reasoning_priors=["Yield curve inversions precede recession expectations", "CME FedWatch probability shifts reflect institutional positioning"],
            evidence_sources=["cme_fedwatch", "treasury_auctions", "tips_breakevens"],
            bias_warning="Bond market can be self-referential; rate expectations sometimes cause the data they predict",
        ),
        AgentPersona(
            id="fx-carry",
            name="FX & Carry Analyst",
            tier=2, domain="fx",
            description="Analyzes dollar strength, carry trades, and cross-border capital flows.",
            reasoning_priors=["DXY weakness signals risk-on rotation", "Yen carry unwinds create cross-asset cascades"],
            evidence_sources=["fx_markets", "bis_cross_border", "central_bank_reserves"],
            bias_warning="FX moves often lag rate expectations; correlation is not causation",
        ),
    ],
    "tariffs": [
        AgentPersona(
            id="supply-chain",
            name="Supply Chain Analyst",
            tier=2, domain="supply_chain",
            description="Tracks manufacturing PMI, shipping data, and trade balance shifts.",
            reasoning_priors=["Tariff announcements immediately repriced in freight rates", "Supply chain diversification announcements signal long-term structural shifts"],
            evidence_sources=["pmi_data", "freightos", "customs_data", "trade_balance"],
            bias_warning="Supply chain data is lagging; may explain trend but not spike timing",
        ),
    ],
    "geopolitical": [
        AgentPersona(
            id="defense-intel",
            name="Defense & Intelligence Analyst",
            tier=2, domain="defense",
            description="Monitors satellite imagery, military deployments, and intelligence signals.",
            reasoning_priors=["Satellite imagery of troop movements precedes diplomatic announcements", "Defense budget shifts signal long-term posture changes"],
            evidence_sources=["satellite_imagery", "defense_contractors", "janes_defense", "flight_tracking"],
            bias_warning="Intelligence signals are often ambiguous; confirmation bias is high",
        ),
    ],
}


# ----------------------------------------------------------------
# Tier 3: Adversarial agents (always active)
# ----------------------------------------------------------------

ADVERSARIAL_AGENTS = [
    AgentPersona(
        id="devils-advocate",
        name="Devil's Advocate",
        tier=3,
        domain="adversarial",
        description=(
            "Actively argues AGAINST the leading hypothesis. Finds counter-evidence, "
            "identifies logical flaws, and proposes alternative explanations. "
            "If FOMC minutes caused this spike, why didn't the 2Y Treasury move proportionally?"
        ),
        reasoning_priors=[
            "The most obvious explanation is often wrong — markets are efficient",
            "If news was public for hours before the spike, something ELSE happened in between",
            "Correlation between a news event and a spike is not causation",
            "Look for what OTHER markets should have moved if the hypothesis is correct",
            "Ask: who benefits from this narrative being accepted?",
        ],
        evidence_sources=["cross_market_analysis", "timing_analysis", "magnitude_comparison"],
        bias_warning="May over-challenge valid hypotheses; contrarianism is not always correct",
    ),
    AgentPersona(
        id="null-hypothesis",
        name="Null Hypothesis Agent",
        tier=3,
        domain="null",
        description=(
            "Argues that the spike is random noise, market microstructure, or "
            "mean-reversion — NOT caused by any external event. Forces other agents "
            "to prove their case above the statistical noise floor."
        ),
        reasoning_priors=[
            "Prediction markets are thin — a single large order can move prices 5%+",
            "Many 'spikes' are just bid-ask bounce or market maker inventory adjustment",
            "The base rate of 5%+ moves in illiquid markets is higher than analysts assume",
            "News attribution is a post-hoc narrative — the move may have happened anyway",
            "Check: is the volume at spike proportional to the price move, or is it a single large trade?",
        ],
        evidence_sources=["orderbook_depth", "volume_profile", "historical_volatility", "market_maker_behavior"],
        bias_warning="May dismiss genuine causal events as noise; calibrate against spike magnitude",
    ),
]


# ----------------------------------------------------------------
# Agent system prompt builder
# ----------------------------------------------------------------

def build_agent_system_prompt(agent: AgentPersona, spike_context: Dict) -> str:
    """Build the full system prompt for an agent given the spike context."""
    market_title = spike_context.get("market_title", "Unknown")
    spike = spike_context.get("spike", {})
    correlated = spike_context.get("correlated_spikes", [])

    concurrent_text = "None detected." if not correlated else "\n".join(
        f"  - {c['market_title'][:50]}: {c['direction']} {c['magnitude']:.1%} ({c['time_diff_min']:+d}min)"
        for c in correlated[:5]
    )

    priors_text = "\n".join(f"  - {p}" for p in agent.reasoning_priors)
    sources_text = ", ".join(agent.evidence_sources)

    return f"""You are {agent.name}, a specialized causal analyst in the Pythia Reverse Causal Engine.

ROLE: {agent.description}

YOUR REASONING PRIORS:
{priors_text}

YOUR EVIDENCE SOURCES: {sources_text}

KNOWN BIAS: {agent.bias_warning}

SPIKE CONTEXT:
  Market: {market_title}
  Direction: {spike.get('direction', 'unknown')} {float(spike.get('magnitude', 0)):.1%}
  Price: {float(spike.get('price_before', 0)):.2f} → {float(spike.get('price_after', 0)):.2f}
  Timestamp: {spike.get('timestamp', 'unknown')}
  Volume at spike: {spike.get('volume', 'unknown')}

CONCURRENT SPIKES:
{concurrent_text}

RULES:
1. Propose hypotheses with specific evidence, not vague narratives.
2. Assign confidence honestly — 40% is fine. Don't inflate.
3. When critiquing others, be specific: what evidence would disprove their hypothesis?
4. If you can't find evidence for your domain, say so — don't fabricate.
5. Consider temporal plausibility: did the cause precede the effect?
6. Consider magnitude plausibility: is this cause big enough to explain a {float(spike.get('magnitude', 0)):.1%} move?
"""


# ----------------------------------------------------------------
# Debate protocol
# ----------------------------------------------------------------

def build_proposal_prompt(agent: AgentPersona, spike_context: Dict, ontology_context: str, news_evidence: str) -> str:
    """Build the prompt for an agent's initial hypothesis proposal."""
    return f"""{build_agent_system_prompt(agent, spike_context)}

ENTITY-RELATIONSHIP GRAPH (potential causal entities):
{ontology_context}

NEWS EVIDENCE GATHERED:
{news_evidence}

TASK: Based on your domain expertise and the evidence above, propose 1-3 causal hypotheses.

For each hypothesis, provide:
1. cause_description: What specifically caused the spike (be precise)
2. causal_chain: Step-by-step how this cause led to the price move
3. evidence: List of specific evidence supporting this hypothesis
4. confidence: Your calibrated confidence level (see CALIBRATION RULES below)
5. temporal_plausibility: Did the cause precede the effect? By how long?
6. magnitude_plausibility: Is this cause big enough to explain the observed move?
7. impact_speed: How quickly does this type of cause typically affect markets?
   - "immediate" (minutes): data releases, breaking news, executive orders
   - "fast" (hours): policy announcements, earnings, court rulings
   - "delayed" (days): regulatory proposals, supply chain shifts, sentiment trends
   - "slow" (weeks+): demographic shifts, technology adoption, structural changes
8. time_to_peak_impact: Estimated hours/days until maximum market effect

CONFIDENCE CALIBRATION RULES (MANDATORY — violations will be rejected):
- HARD CEILING: 0.85 maximum. Any value above 0.85 will be clamped to 0.85.
- 0.70-0.85: STRONG — You found direct, timestamped evidence that this specific event preceded the spike AND the causal mechanism is well-established. Example: FOMC statement released 30 min before spike, market moved in the expected direction.
- 0.50-0.69: MODERATE — Plausible hypothesis with some supporting evidence, but gaps exist. Evidence may be circumstantial, timing is approximate, or alternative explanations are equally viable.
- 0.30-0.49: WEAK — Hypothesis fits the narrative but evidence is thin, timing is uncertain, or the causal mechanism requires multiple assumptions.
- 0.10-0.29: SPECULATIVE — Possible but no direct evidence. Based on general patterns, not specific to this spike.
- 0.00-0.09: NULL — No evidence found in your domain. Report this honestly rather than fabricating a cause.

IMPORTANT: Most hypotheses should be in the 0.30-0.65 range. A confidence above 0.70 requires SPECIFIC TIMESTAMPED EVIDENCE that the cause preceded the spike. If you cannot cite a specific time, your confidence should be below 0.65.

If you found NO evidence of a cause in your domain, say so with confidence 0.05-0.15. An honest null finding is more valuable than a fabricated high-confidence hypothesis.

CRITICAL TIMING RULES:
- A cause that happened AFTER the spike CANNOT have caused it.
- "Concurrent" evidence is ambiguous — it could be the cause or a reaction. Be explicit.
- If your hypothesis relies on a "delayed" cause, explain the transmission mechanism.
- Weight "immediate" causes higher for sudden spikes; "delayed" causes for gradual trends.

Return ONLY valid JSON:
{{
  "hypotheses": [
    {{
      "cause_description": "...",
      "causal_chain": "...",
      "evidence": ["evidence 1", "evidence 2"],
      "evidence_urls": ["url1"],
      "confidence": 0.7,
      "temporal_plausibility": "Cause preceded spike by ~2 hours",
      "magnitude_plausibility": "Similar announcements have caused 3-8% moves historically",
      "impact_speed": "immediate|fast|delayed|slow",
      "time_to_peak_impact": "2 hours"
    }}
  ]
}}
"""


def build_critique_prompt(
    agent: AgentPersona,
    spike_context: Dict,
    all_hypotheses: List[CausalHypothesis],
    target_hypothesis: CausalHypothesis,
) -> str:
    """Build prompt for an agent to critique another agent's hypothesis."""
    other_hyps = "\n".join(
        f"  [{h.agent_id}] {h.cause_description} (conf={h.confidence:.0%})"
        for h in all_hypotheses if h.id != target_hypothesis.id
    )

    return f"""{build_agent_system_prompt(agent, spike_context)}

ALL CURRENT HYPOTHESES:
{other_hyps}

TARGET HYPOTHESIS TO CRITIQUE:
  Agent: {target_hypothesis.agent_id}
  Cause: {target_hypothesis.cause_description}
  Chain: {target_hypothesis.causal_chain}
  Evidence: {', '.join(target_hypothesis.evidence[:3])}
  Confidence: {target_hypothesis.confidence:.0%}
  Temporal: {target_hypothesis.temporal_plausibility}
  Magnitude: {target_hypothesis.magnitude_plausibility}

TASK: Critically evaluate this hypothesis from your domain perspective.

Consider:
- Is the temporal ordering correct? Could this be reverse causation?
- Is there a common cause that explains both the news and the spike?
- What evidence would DISPROVE this hypothesis?
- Are there cross-market implications that should be visible if this hypothesis is true?
- Is the magnitude of the cause proportional to the spike?
- TIMING: Does the claimed impact_speed match the observed spike timing?
  An "immediate" cause should show effect within minutes.
  A "delayed" cause needs a clear transmission mechanism to explain a sudden spike.
  If the cause and spike are concurrent, is there evidence the cause came first?

Return ONLY valid JSON:
{{
  "verdict": "support|challenge|debunk",
  "reasoning": "Detailed explanation of your critique",
  "counter_evidence": ["Specific evidence that weakens this hypothesis"],
  "alternative": "If debunking, what's a better explanation?",
  "confidence_adjustment": 0.1,
  "timing_assessment": "plausible|implausible|uncertain"
}}

"support" = hypothesis is consistent with your domain evidence
"challenge" = hypothesis has weaknesses but isn't disproven
"debunk" = hypothesis is contradicted by strong evidence
"confidence_adjustment" = how much to adjust confidence (-0.3 to +0.2)
"""


def build_counterfactual_prompt(
    agent: AgentPersona,
    spike_context: Dict,
    hypothesis: CausalHypothesis,
) -> str:
    """Build prompt for counterfactual testing: what if this cause hadn't happened?"""
    return f"""{build_agent_system_prompt(agent, spike_context)}

COUNTERFACTUAL TEST:
We are testing whether removing the following cause would eliminate the observed spike.

HYPOTHESIS: {hypothesis.cause_description}
CAUSAL CHAIN: {hypothesis.causal_chain}
CONFIDENCE: {hypothesis.confidence:.0%}

QUESTION: If "{hypothesis.cause_description}" had NOT happened:
1. Would the spike still have occurred? (yes/no/partially)
2. What magnitude would you expect? (0% to {float(spike_context.get('spike', {}).get('magnitude', 0)):.1%})
3. What other factors could have caused a similar move?
4. Is this cause necessary, sufficient, or just contributing?

Return ONLY valid JSON:
{{
  "spike_without_cause": "yes|no|partially",
  "expected_magnitude_without": 0.02,
  "alternative_causes": ["Other factors that could explain the spike"],
  "cause_role": "necessary|sufficient|contributing",
  "reasoning": "Detailed reasoning for your counterfactual assessment"
}}
"""


# ----------------------------------------------------------------
# Agent spawner
# ----------------------------------------------------------------

def spawn_agents(category: str) -> List[AgentPersona]:
    """Spawn the full agent ensemble for a given market category."""
    agents = list(CORE_AGENTS)

    # Add conditional agents for this category
    conditional = CONDITIONAL_AGENTS.get(category, [])
    agents.extend(conditional)

    # Always add adversarial agents
    agents.extend(ADVERSARIAL_AGENTS)

    logger.info(
        "Spawned %d agents: %d core + %d conditional + %d adversarial (category=%s)",
        len(agents), len(CORE_AGENTS), len(conditional), len(ADVERSARIAL_AGENTS), category,
    )

    return agents
