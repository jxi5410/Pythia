"""
BACE Debate Engine — Multi-agent adversarial attribution.

Used by bace.py at depth 2 (proposals only, debate_rounds=0) and
depth 3 (proposals + adversarial debate, debate_rounds=2).

Pipeline:
  1. Extract rich entity-relationship ontology from spike context
  2. Gather news evidence using ontology-derived search queries
  3. Spawn domain-specific agents (Tier 1 + Tier 2 + Tier 3)
  4. Each agent proposes causal hypotheses with domain-specific evidence
  5. (Depth 3 only) Adversarial debate — agents critique each other
  6. (Depth 3 only) Counterfactual testing — remove each hypothesis, re-evaluate
  7. Final scoring and attributor extraction

Output is compatible with existing attributor_engine.py for storage and
forward_signals.py for downstream propagation.
"""

import json
import logging
import re
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Tuple

from .bace_ontology import extract_causal_ontology, CausalOntology
from .bace_agents import (
    AgentPersona, CausalHypothesis, spawn_agents,
    build_proposal_prompt, build_critique_prompt,
    build_counterfactual_prompt,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------

DEFAULT_DEBATE_ROUNDS = 3      # Number of critique rounds
MAX_HYPOTHESES_PER_AGENT = 3   # Cap proposals per agent
CONFIDENCE_DEBUNK_THRESHOLD = 0.15  # Below this = debunked
COUNTERFACTUAL_THRESHOLD = 0.6     # Must score above this to survive
MIN_SURVIVING_CONFIDENCE = 0.25    # Minimum confidence to become attributor


# ----------------------------------------------------------------
# Evidence gathering (reuses causal_v2 news retrieval)
# ----------------------------------------------------------------

def gather_evidence(ontology: CausalOntology, spike_context: Dict) -> Dict[str, List[Dict]]:
    """
    Gather news evidence using ontology-derived search queries.
    Returns evidence grouped by entity type for agent consumption.

    Uses existing causal_v2 news retrieval infrastructure but with
    richer search queries from the ontology.
    """
    try:
        from .evidence.news_retrieval import (
            newsapi_search,
            google_news_rss,
            duckduckgo_search,
            reddit_search,
            filter_by_temporal_window,
        )
        from .causal_v2 import retrieve_candidate_news
    except ImportError:
        logger.warning("news retrieval not available")
        return {"all": []}

    window = spike_context.get("temporal_window", {})
    all_candidates = []

    # Use ontology search queries (much richer than depth-1's 3-5 keywords)
    queries = ontology.get_all_search_terms()
    logger.info("Searching with %d ontology-derived queries", len(queries))

    for query in queries[:20]:  # Cap at 20 to manage rate limits
        try:
            # Google News RSS (free, no rate limit)
            results = google_news_rss(query, max_results=5)
            all_candidates.extend(results)
        except Exception:
            pass

        try:
            # DuckDuckGo (free, best effort)
            results = duckduckgo_search(query, max_results=3)
            all_candidates.extend(results)
        except Exception:
            pass

        time.sleep(0.5)  # Rate limiting

    # NewsAPI (limited free tier — use for top entities only)
    top_entities = sorted(ontology.entities, key=lambda e: e.relevance_score, reverse=True)[:5]
    for entity in top_entities:
        for term in entity.search_terms[:1]:
            try:
                results = newsapi_search(
                    term,
                    from_date=window.get("start"),
                    to_date=window.get("end"),
                    max_results=5,
                )
                all_candidates.extend(results)
            except Exception:
                pass

    # Temporal filtering
    if window.get("start") and window.get("end"):
        all_candidates = filter_by_temporal_window(
            all_candidates, window["start"], window["end"]
        )

    # Deduplicate
    seen = set()
    unique = []
    for c in all_candidates:
        key = c.get("headline", "")[:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    logger.info("Gathered %d unique candidates from %d total", len(unique), len(all_candidates))
    return {"all": unique}


def format_evidence_for_agent(evidence: Dict[str, List[Dict]], max_items: int = 25) -> str:
    """Format gathered evidence as text for agent prompts."""
    items = evidence.get("all", [])[:max_items]
    if not items:
        return "  No news evidence found in the temporal window."

    lines = []
    for i, item in enumerate(items, 1):
        source = item.get("source", "unknown")
        headline = item.get("headline", "")
        published = item.get("published", "")
        verified = "✓" if item.get("temporal_verified") else "?"
        lines.append(f"  {i}. [{source}] {headline} ({published}) {verified}")

    return "\n".join(lines)


# ----------------------------------------------------------------
# Debate engine
# ----------------------------------------------------------------

def run_proposal_round(
    agents: List[AgentPersona],
    spike_context: Dict,
    ontology: CausalOntology,
    evidence: Dict[str, List[Dict]],
    llm_call: Callable,
    agent_evidence: Dict = None,
) -> List[CausalHypothesis]:
    """Round 1: Each agent proposes causal hypotheses.

    If agent_evidence is provided (from bace_evidence_provider), each agent
    gets domain-specific data + timing context in addition to shared news.
    """
    all_hypotheses = []
    ontology_text = json.dumps([asdict(e) for e in ontology.entities[:15]], indent=2)
    shared_evidence_text = format_evidence_for_agent(evidence)

    for agent in agents:
        # Tier 3 adversarial agents don't propose in Round 1
        if agent.tier == 3:
            continue

        # Build evidence text: domain-specific if available, else shared-only
        if agent_evidence and agent.id in agent_evidence:
            from .bace_evidence_provider import format_domain_evidence_for_prompt
            ae = agent_evidence[agent.id]
            domain_text = format_domain_evidence_for_prompt(ae)
            full_evidence_text = f"{shared_evidence_text}\n\n{domain_text}"
        else:
            full_evidence_text = shared_evidence_text

        prompt = build_proposal_prompt(agent, spike_context, ontology_text, full_evidence_text)

        try:
            response = llm_call(prompt)
            parsed = _parse_json_response(response)

            if parsed and "hypotheses" in parsed:
                for j, h in enumerate(parsed["hypotheses"][:MAX_HYPOTHESES_PER_AGENT]):
                    hyp = CausalHypothesis(
                        id=f"{agent.id}-h{j}",
                        agent_id=agent.id,
                        cause_description=h.get("cause_description", ""),
                        causal_chain=h.get("causal_chain", ""),
                        evidence=h.get("evidence", []),
                        evidence_urls=h.get("evidence_urls", []),
                        confidence=float(h.get("confidence", 0.5)),
                        temporal_plausibility=h.get("temporal_plausibility", ""),
                        magnitude_plausibility=h.get("magnitude_plausibility", ""),
                        impact_speed=h.get("impact_speed", ""),
                        time_to_peak_impact=h.get("time_to_peak_impact", ""),
                        status="proposed",
                        round_proposed=1,
                    )
                    all_hypotheses.append(hyp)
                    logger.info(
                        "  [%s] Proposed: %s (conf=%.0f%%)",
                        agent.id, hyp.cause_description[:60], hyp.confidence * 100,
                    )
        except Exception as e:
            logger.warning("Agent %s proposal failed: %s", agent.id, e)

    logger.info("Round 1 complete: %d hypotheses from %d agents", len(all_hypotheses), len(agents))
    return all_hypotheses


def run_critique_round(
    agents: List[AgentPersona],
    hypotheses: List[CausalHypothesis],
    spike_context: Dict,
    round_num: int,
    llm_call: Callable,
) -> List[CausalHypothesis]:
    """Rounds 2-N: Agents critique each other's hypotheses."""
    # Each agent critiques hypotheses from OTHER agents
    for agent in agents:
        for hyp in hypotheses:
            # Don't self-critique; skip already debunked
            if hyp.agent_id == agent.id or hyp.status == "debunked":
                continue

            # Tier 3 agents critique everything; others only critique if relevant
            if agent.tier < 3 and hyp.confidence < 0.3:
                continue  # Don't waste LLM calls on low-confidence hypotheses

            prompt = build_critique_prompt(agent, spike_context, hypotheses, hyp)

            try:
                response = llm_call(prompt)
                parsed = _parse_json_response(response)

                if parsed:
                    verdict = parsed.get("verdict", "challenge")
                    reasoning = parsed.get("reasoning", "")
                    adjustment = float(parsed.get("confidence_adjustment", 0))

                    # Apply critique
                    hyp.challenges.append(f"[{agent.id}] {reasoning[:200]}")
                    hyp.confidence = max(0.0, min(1.0, hyp.confidence + adjustment))

                    if verdict == "debunk" and hyp.confidence < CONFIDENCE_DEBUNK_THRESHOLD:
                        hyp.status = "debunked"
                        hyp.round_debunked = round_num
                        logger.info(
                            "  [%s] DEBUNKED: %s → conf=%.0f%%",
                            agent.id, hyp.cause_description[:40], hyp.confidence * 100,
                        )
                    elif verdict == "support":
                        hyp.status = "supported"
                        logger.debug("  [%s] Supported: %s", agent.id, hyp.cause_description[:40])
                    else:
                        hyp.status = "challenged"
                        logger.debug(
                            "  [%s] Challenged: %s → conf=%.0f%%",
                            agent.id, hyp.cause_description[:40], hyp.confidence * 100,
                        )

            except Exception as e:
                logger.debug("Agent %s critique failed: %s", agent.id, e)

    surviving = [h for h in hypotheses if h.status != "debunked"]
    debunked = [h for h in hypotheses if h.status == "debunked"]
    logger.info(
        "Round %d complete: %d surviving, %d debunked",
        round_num, len(surviving), len(debunked),
    )
    return hypotheses


def run_counterfactual_round(
    agents: List[AgentPersona],
    hypotheses: List[CausalHypothesis],
    spike_context: Dict,
    llm_call: Callable,
) -> List[CausalHypothesis]:
    """Final round: counterfactual testing on surviving hypotheses."""
    surviving = [h for h in hypotheses if h.status != "debunked" and h.confidence >= MIN_SURVIVING_CONFIDENCE]

    if not surviving:
        logger.warning("No hypotheses survived for counterfactual testing")
        return hypotheses

    for hyp in surviving:
        votes = {"yes": 0, "no": 0, "partially": 0}
        total_magnitude_without = 0.0
        n_votes = 0

        # Ask a subset of agents (Tier 1 + adversarial)
        cf_agents = [a for a in agents if a.tier in (1, 3)][:5]

        for agent in cf_agents:
            prompt = build_counterfactual_prompt(agent, spike_context, hyp)

            try:
                response = llm_call(prompt)
                parsed = _parse_json_response(response)

                if parsed:
                    vote = parsed.get("spike_without_cause", "partially")
                    votes[vote] = votes.get(vote, 0) + 1
                    mag = float(parsed.get("expected_magnitude_without", 0))
                    total_magnitude_without += mag
                    n_votes += 1

                    cause_role = parsed.get("cause_role", "contributing")

                    # Adjust confidence based on counterfactual
                    if vote == "no":
                        hyp.confidence = min(1.0, hyp.confidence + 0.1)
                    elif vote == "yes":
                        hyp.confidence = max(0.0, hyp.confidence - 0.2)
                    # "partially" → no adjustment

            except Exception as e:
                logger.debug("Counterfactual failed for agent %s: %s", agent.id, e)

        # Summarize counterfactual results
        if n_votes > 0:
            avg_mag_without = total_magnitude_without / n_votes
            spike_mag = float(spike_context.get("spike", {}).get("magnitude", 0))

            # If removing this cause still leaves most of the spike, it's not the main driver
            if avg_mag_without > spike_mag * 0.8:
                hyp.confidence = max(0.0, hyp.confidence - 0.15)
                hyp.rebuttals.append(
                    f"Counterfactual: spike persists at {avg_mag_without:.1%} even without this cause"
                )

            logger.info(
                "  Counterfactual [%s]: votes=%s, mag_without=%.1f%% (original=%.1f%%)",
                hyp.cause_description[:40], votes, avg_mag_without * 100, spike_mag * 100,
            )

    # Final status assignment
    for hyp in hypotheses:
        if hyp.status == "debunked":
            continue
        if hyp.confidence >= COUNTERFACTUAL_THRESHOLD:
            hyp.status = "survived"
        elif hyp.confidence >= MIN_SURVIVING_CONFIDENCE:
            hyp.status = "survived"  # Lower confidence but not debunked
        else:
            hyp.status = "debunked"
            hyp.round_debunked = -2  # Debunked by counterfactual

    return hypotheses


# ----------------------------------------------------------------
# Main debate pipeline
# ----------------------------------------------------------------

def attribute_spike_rce(
    spike,
    all_recent_spikes=None,
    llm_call: Callable = None,
    ontology_llm: Callable = None,
    db=None,
    debate_rounds: int = DEFAULT_DEBATE_ROUNDS,
) -> Dict:
    """
    Full Reverse Causal Engine attribution pipeline.

    Replaces causal_v2.attribute_spike_v2() with multi-agent adversarial debate.

    Args:
        spike: SpikeEvent to attribute
        all_recent_spikes: Recent spikes for correlation
        llm_call: Main LLM function (Sonnet for fast rounds)
        ontology_llm: LLM for ontology extraction (can be Opus for quality)
        db: PythiaDB instance
        debate_rounds: Number of adversarial critique rounds

    Returns:
        Dict compatible with existing attributor_engine.extract_attributor()
    """
    start_time = time.time()

    if llm_call is None:
        try:
            from .llm_integration import sonnet_call
            llm_call = sonnet_call
        except ImportError:
            logger.error("No LLM available for BACE debate")
            return _empty_result(spike)

    if ontology_llm is None:
        try:
            from .llm_integration import opus_call
            ontology_llm = opus_call
        except ImportError:
            ontology_llm = llm_call  # Fall back to same LLM

    # Step 1: Build spike context (reuse existing)
    try:
        from .spike_context import build_spike_context
        context = build_spike_context(spike, all_recent_spikes or [], entity_llm=ontology_llm)
    except ImportError:
        context = {
            "market_title": getattr(spike, "market_title", "Unknown"),
            "category": "general",
            "spike": {
                "direction": getattr(spike, "direction", "up"),
                "magnitude": getattr(spike, "magnitude", 0),
                "timestamp": str(getattr(spike, "timestamp", "")),
                "price_before": getattr(spike, "price_before", 0),
                "price_after": getattr(spike, "price_after", 0),
                "volume": getattr(spike, "volume_at_spike", 0),
                "market_id": getattr(spike, "market_id", ""),
            },
            "temporal_window": {"start": "", "end": ""},
            "correlated_spikes": [],
        }

    category = context.get("category", "general")
    logger.info("=" * 60)
    logger.info("BACE DEBATE START: %s", context.get("market_title", "?")[:60])
    logger.info("Category: %s | Magnitude: %.1f%%", category, float(context.get("spike", {}).get("magnitude", 0)) * 100)

    # Step 2: Extract rich ontology
    logger.info("Step 2: Extracting causal ontology...")
    ontology = extract_causal_ontology(context, llm_call=ontology_llm)
    logger.info("  Ontology: %d entities, %d relationships, %d search queries",
                len(ontology.entities), len(ontology.relationships), len(ontology.search_queries))

    # Step 3: Gather evidence
    logger.info("Step 3: Gathering news evidence...")
    evidence = gather_evidence(ontology, context)
    n_evidence = len(evidence.get("all", []))
    logger.info("  Evidence: %d candidates", n_evidence)

    # Step 4: Spawn agents
    logger.info("Step 4: Spawning agents...")
    agents = spawn_agents(category)
    logger.info("  Agents: %d total", len(agents))

    # Step 4.5: Gather domain-specific evidence per agent
    agent_evidence = None
    try:
        from .bace_evidence_provider import gather_all_agent_evidence
        logger.info("Step 4.5: Gathering domain-specific evidence per agent...")
        agent_evidence = gather_all_agent_evidence(
            agents=agents,
            spike_context=context,
            shared_news=evidence.get("all", []),
        )
        n_domain = sum(len(ae.domain_data) for ae in agent_evidence.values())
        logger.info("  Domain evidence: %d items across %d agents", n_domain, len(agent_evidence))
    except ImportError:
        logger.debug("bace_evidence_provider not available — agents get shared news only")
    except Exception as e:
        logger.warning("Domain evidence gathering failed (non-fatal): %s", e)

    # Step 5: Proposal round
    logger.info("Step 5: Proposal round...")
    hypotheses = run_proposal_round(agents, context, ontology, evidence, llm_call,
                                     agent_evidence=agent_evidence)
    logger.info("  Proposals: %d hypotheses", len(hypotheses))

    # Step 6: Adversarial debate
    for r in range(2, 2 + debate_rounds):
        logger.info("Step 6.%d: Critique round %d...", r - 1, r)
        hypotheses = run_critique_round(agents, hypotheses, context, r, llm_call)

    # Step 7: Counterfactual testing
    logger.info("Step 7: Counterfactual testing...")
    hypotheses = run_counterfactual_round(agents, hypotheses, context, llm_call)

    # Step 8: Extract final attributors
    survived = [h for h in hypotheses if h.status == "survived" and h.confidence >= MIN_SURVIVING_CONFIDENCE]
    debunked = [h for h in hypotheses if h.status == "debunked"]

    elapsed = time.time() - start_time
    logger.info("=" * 60)
    logger.info("BACE DEBATE COMPLETE: %d survived, %d debunked (%.1fs)",
                len(survived), len(debunked), elapsed)
    for h in survived:
        logger.info("  ✓ %s (conf=%.0f%%, agent=%s)", h.cause_description[:50], h.confidence * 100, h.agent_id)
    for h in debunked:
        logger.info("  ✗ %s (conf=%.0f%%, debunked round %d)", h.cause_description[:50], h.confidence * 100, h.round_debunked)
    logger.info("=" * 60)

    # Build result compatible with existing pipeline
    best = survived[0] if survived else None
    confidence_map = {"HIGH": 0.7, "MEDIUM": 0.4}

    result = {
        "spike_id": getattr(spike, "id", 0),
        "context": context,
        "method": "rce",
        "ontology": ontology.to_dict(),
        "agents_spawned": len(agents),
        "total_hypotheses": len(hypotheses),
        "debate_rounds": debate_rounds,
        "evidence_gathered": n_evidence,
        "elapsed_seconds": round(elapsed, 1),
        "hypotheses": [h.to_dict() for h in hypotheses],
        "survived": [h.to_dict() for h in survived],
        "debunked": [h.to_dict() for h in debunked],
        "attribution": {
            "most_likely_cause": best.cause_description if best else "No cause survived adversarial debate",
            "confidence": (
                "HIGH" if best and best.confidence >= 0.7 else
                "MEDIUM" if best and best.confidence >= 0.4 else
                "LOW"
            ),
            "confidence_reasoning": (
                f"BACE: {len(survived)} hypotheses survived {debate_rounds} debate rounds + counterfactual testing. "
                f"Top cause confidence: {best.confidence:.0%}." if best else
                f"BACE: All {len(hypotheses)} hypotheses were debunked during adversarial debate."
            ),
            "causal_chain": best.causal_chain if best else "",
            "macro_or_idiosyncratic": "MACRO" if len(survived) > 2 else "IDIOSYNCRATIC" if len(survived) == 1 else "MIXED",
            "expected_duration": "SHORT" if any(h.confidence > 0.7 for h in survived) else "UNKNOWN",
        },
        "candidates_retrieved": n_evidence,
        "candidates_filtered": len(survived),
        "top_candidates": [
            {
                "headline": h.cause_description,
                "source": h.agent_id,
                "relevance_score": round(h.confidence * 10, 1),
                "url": h.evidence_urls[0] if h.evidence_urls else "",
            }
            for h in survived[:5]
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return result


def _empty_result(spike) -> Dict:
    """Return empty result when BACE debate can't run."""
    return {
        "spike_id": getattr(spike, "id", 0),
        "context": {},
        "method": "rce",
        "attribution": {
            "most_likely_cause": "BACE debate could not execute — no LLM available",
            "confidence": "LOW",
            "confidence_reasoning": "No LLM available",
            "causal_chain": "",
        },
        "hypotheses": [],
        "survived": [],
        "debunked": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _parse_json_response(response: str) -> Optional[Dict]:
    """Parse LLM JSON response with common formatting fixes."""
    if not response:
        return None

    text = response.strip()
    text = re.sub(r'^```(?:json)?\s*', '', text)
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
