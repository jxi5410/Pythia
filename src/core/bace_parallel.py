"""
BACE Parallel Execution — async wrappers for the serial bace_debate pipeline.

Parallelizes:
1. News evidence gathering (37 queries → concurrent HTTP)
2. Domain evidence per agent (7-9 fetchers → concurrent)
3. Agent proposal round (9 agents → concurrent LLM calls)
4. Counterfactual round (5 agents per hypothesis → concurrent)

Emits progress callbacks for SSE streaming.

Usage:
    from src.core.bace_parallel import attribute_spike_parallel
    
    async for event in attribute_spike_parallel(spike, llm_fast, llm_strong):
        # event is a dict with {"step": ..., "data": ...}
        pass
"""

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from typing import AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# Thread pool for running sync LLM/HTTP calls concurrently
_executor = ThreadPoolExecutor(max_workers=12)


async def _run_in_thread(fn, *args):
    """Run a sync function in the thread pool."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, fn, *args)


# ─── Parallel news gathering ──────────────────────────────────────────

def _fetch_google_news(query, max_results=5):
    try:
        from .evidence.news_retrieval import google_news_rss
        return google_news_rss(query, max_results=max_results)
    except Exception:
        return []


def _fetch_ddg_news(query, max_results=3):
    try:
        from .evidence.news_retrieval import duckduckgo_search
        return duckduckgo_search(query, max_results=max_results)
    except Exception:
        return []


async def gather_evidence_parallel(ontology, spike_context: Dict) -> Dict[str, List[Dict]]:
    """Gather news evidence with parallel HTTP requests."""
    queries = ontology.get_all_search_terms()[:20]
    logger.info("Parallel news search: %d queries", len(queries))

    tasks = []
    for query in queries:
        tasks.append(_run_in_thread(_fetch_google_news, query, 5))
        tasks.append(_run_in_thread(_fetch_ddg_news, query, 3))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_candidates = []
    errors = 0
    for r in results:
        if isinstance(r, list):
            all_candidates.extend(r)
        elif isinstance(r, Exception):
            errors += 1
    
    if errors > 0:
        logger.warning("Parallel news: %d/%d fetches failed", errors, len(tasks))

    # Temporal filtering
    window = spike_context.get("temporal_window", {})
    if window.get("start") and window.get("end"):
        try:
            from .causal_v2 import filter_by_temporal_window
            all_candidates = filter_by_temporal_window(
                all_candidates, window["start"], window["end"]
            )
        except Exception:
            pass

    # Deduplicate
    seen = set()
    unique = []
    for c in all_candidates:
        key = c.get("headline", "")[:50].lower()
        if key not in seen:
            seen.add(key)
            unique.append(c)

    logger.info("Parallel news: %d unique from %d total", len(unique), len(all_candidates))
    return {"all": unique}


# ─── Parallel domain evidence ─────────────────────────────────────────

async def gather_domain_evidence_parallel(agents, spike_context, shared_news):
    """Gather domain-specific evidence for all agents concurrently."""
    try:
        from .bace_evidence_provider import (
            DOMAIN_FETCHERS, AgentEvidence, EvidenceItem,
            _build_timing_summary, format_domain_evidence_for_prompt,
        )
    except ImportError:
        return {}

    # Collect unique fetchers across all agents
    fetcher_set = {}
    for agent in agents:
        fetchers = DOMAIN_FETCHERS.get(agent.domain, [])
        for f in fetchers:
            if f.__name__ not in fetcher_set:
                fetcher_set[f.__name__] = f

    # Run all unique fetchers in parallel
    async def run_fetcher(name, fn):
        try:
            return name, await _run_in_thread(fn, spike_context)
        except Exception as e:
            logger.debug("Fetcher %s failed: %s", name, e)
            return name, []

    tasks = [run_fetcher(name, fn) for name, fn in fetcher_set.items()]
    results = await asyncio.gather(*tasks)
    fetcher_cache = dict(results)

    # Distribute to agents
    result = {}
    for agent in agents:
        domain_items = []
        errors = []
        fetchers = DOMAIN_FETCHERS.get(agent.domain, [])
        for f in fetchers:
            items = fetcher_cache.get(f.__name__, [])
            domain_items.extend(items)

        timing_summary = _build_timing_summary(domain_items, spike_context)
        result[agent.id] = AgentEvidence(
            agent_id=agent.id,
            shared_news=shared_news,
            domain_data=domain_items,
            timing_summary=timing_summary,
            fetch_errors=errors,
        )

    n_total = sum(len(e.domain_data) for e in result.values())
    logger.info("Parallel domain evidence: %d items for %d agents", n_total, len(agents))
    return result


# ─── Parallel agent proposals ─────────────────────────────────────────

async def run_proposals_parallel(agents, spike_context, ontology, evidence, llm_call, agent_evidence=None):
    """Run all agent proposals concurrently."""
    from .bace_agents import build_proposal_prompt, CausalHypothesis
    from .bace_debate import format_evidence_for_agent, _parse_json_response, MAX_HYPOTHESES_PER_AGENT

    ontology_text = json.dumps([asdict(e) for e in ontology.entities[:15]], indent=2)
    shared_evidence_text = format_evidence_for_agent(evidence)

    async def propose_for_agent(agent):
        if agent.tier == 3:
            return agent.id, []

        if agent_evidence and agent.id in agent_evidence:
            from .bace_evidence_provider import format_domain_evidence_for_prompt
            ae = agent_evidence[agent.id]
            domain_text = format_domain_evidence_for_prompt(ae)
            full_evidence = f"{shared_evidence_text}\n\n{domain_text}"
        else:
            full_evidence = shared_evidence_text

        prompt = build_proposal_prompt(agent, spike_context, ontology_text, full_evidence)

        try:
            response = await _run_in_thread(llm_call, prompt)
            parsed = _parse_json_response(response)

            hyps = []
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
                    hyps.append(hyp)
                    logger.info("  [%s] Proposed: %s (conf=%.0f%%)",
                                agent.id, hyp.cause_description[:60], hyp.confidence * 100)
            return agent.id, hyps
        except Exception as e:
            logger.warning("Agent %s proposal failed: %s", agent.id, e, exc_info=True)
            return agent.id, []

    tasks = [propose_for_agent(a) for a in agents]
    results = await asyncio.gather(*tasks)

    all_hypotheses = []
    for agent_id, hyps in results:
        all_hypotheses.extend(hyps)

    logger.info("Parallel proposals: %d hypotheses from %d agents", len(all_hypotheses), len(agents))
    return all_hypotheses


# ─── Parallel counterfactual testing ──────────────────────────────────

async def run_counterfactual_parallel(agents, hypotheses, spike_context, llm_call):
    """Run counterfactual testing concurrently."""
    from .bace_agents import build_counterfactual_prompt
    from .bace_debate import _parse_json_response, MIN_SURVIVING_CONFIDENCE, COUNTERFACTUAL_THRESHOLD

    surviving = [h for h in hypotheses if h.status != "debunked" and h.confidence >= MIN_SURVIVING_CONFIDENCE]
    if not surviving:
        return hypotheses

    cf_agents = [a for a in agents if a.tier in (1, 3)][:5]

    async def test_hypothesis(hyp):
        votes = {"yes": 0, "no": 0, "partially": 0}
        total_mag = 0.0
        n_votes = 0

        async def vote(agent):
            prompt = build_counterfactual_prompt(agent, spike_context, hyp)
            try:
                response = await _run_in_thread(llm_call, prompt)
                return _parse_json_response(response)
            except Exception:
                return None

        results = await asyncio.gather(*[vote(a) for a in cf_agents])

        for parsed in results:
            if parsed:
                v = parsed.get("spike_without_cause", "partially")
                votes[v] = votes.get(v, 0) + 1
                total_mag += float(parsed.get("expected_magnitude_without", 0))
                n_votes += 1

                if v == "no":
                    hyp.confidence = min(1.0, hyp.confidence + 0.1)
                elif v == "yes":
                    hyp.confidence = max(0.0, hyp.confidence - 0.2)

        if n_votes > 0:
            avg_mag = total_mag / n_votes
            spike_mag = float(spike_context.get("spike", {}).get("magnitude", 0))
            if avg_mag > spike_mag * 0.8:
                hyp.confidence = max(0.0, hyp.confidence - 0.15)

            logger.info("  CF [%s]: votes=%s, mag_without=%.1f%%",
                        hyp.cause_description[:40], votes, avg_mag * 100)

    await asyncio.gather(*[test_hypothesis(h) for h in surviving])

    for hyp in hypotheses:
        if hyp.status != "debunked":
            if hyp.confidence >= MIN_SURVIVING_CONFIDENCE:
                hyp.status = "survived"
            else:
                hyp.status = "debunked"
                hyp.round_debunked = -2

    return hypotheses


# ─── Main streaming pipeline ──────────────────────────────────────────

async def attribute_spike_streaming(
    spike,
    all_recent_spikes=None,
    llm_fast=None,
    llm_strong=None,
    db=None,
    depth: int = 2,
) -> AsyncGenerator[Dict, None]:
    """
    Async streaming BACE pipeline. Yields progress events:

        {"step": "context", "data": {"market_title": ..., "category": ...}}
        {"step": "ontology", "data": {"entities": [...], "relationships": [...]}}
        {"step": "evidence", "data": {"count": 78}}
        {"step": "agents", "data": {"agents": [...]}}
        {"step": "domain_evidence", "data": {"count": 37}}
        {"step": "proposal", "data": {"agent": "macro-policy", "hypotheses": [...]}}
        {"step": "counterfactual", "data": {"tested": 3}}
        {"step": "result", "data": {<full result dict>}}
    """
    start_time = time.time()

    if llm_fast is None:
        from .llm_integration import sonnet_call
        llm_fast = sonnet_call
    if llm_strong is None:
        from .llm_integration import opus_call
        llm_strong = opus_call

    # Step 1: Build context
    from .spike_context import build_spike_context
    context = build_spike_context(spike, all_recent_spikes or [], entity_llm=llm_strong)
    category = context.get("category", "general")

    yield {"step": "context", "data": {
        "market_title": context.get("market_title", ""),
        "category": category,
        "entities": context.get("entities", []),
    }}

    # Step 2: Ontology extraction
    from .bace_ontology import extract_causal_ontology
    ontology = await _run_in_thread(extract_causal_ontology, context, llm_strong)

    yield {"step": "ontology", "data": {
        "entity_count": len(ontology.entities),
        "relationship_count": len(ontology.relationships),
        "search_queries": len(ontology.search_queries),
        "entities": [e.name for e in ontology.entities[:10]],
    }}

    # Step 3: News evidence (PARALLEL)
    evidence = await gather_evidence_parallel(ontology, context)
    n_evidence = len(evidence.get("all", []))

    yield {"step": "evidence", "data": {"count": n_evidence}}

    # Step 4: Spawn agents — use LLM category if ontology provided one
    from .bace_agents import spawn_agents
    if ontology.llm_category:
        category = ontology.llm_category
        context["category"] = category  # update context for downstream
        logger.info("Using LLM-classified category: %s", category)
    agents = spawn_agents(category)

    yield {"step": "agents", "data": {
        "count": len(agents),
        "agents": [{"id": a.id, "name": a.name, "tier": a.tier, "domain": a.domain} for a in agents],
    }}

    # Step 4.5: Domain evidence (PARALLEL)
    agent_evidence = await gather_domain_evidence_parallel(agents, context, evidence.get("all", []))
    n_domain = sum(len(ae.domain_data) for ae in agent_evidence.values())

    yield {"step": "domain_evidence", "data": {"count": n_domain}}

    # Step 5: Proposals (PARALLEL)
    hypotheses = await run_proposals_parallel(agents, context, ontology, evidence, llm_fast, agent_evidence)

    # Yield each agent's proposals
    by_agent = {}
    for h in hypotheses:
        by_agent.setdefault(h.agent_id, []).append(h)
    for agent_id, hyps in by_agent.items():
        yield {"step": "proposal", "data": {
            "agent": agent_id,
            "hypotheses": [{"cause": h.cause_description[:100], "confidence": round(h.confidence, 2)} for h in hyps],
        }}

    # Step 6: Debate rounds (depth 3 only — skip for depth 2)
    debate_rounds = 0 if depth <= 2 else 2
    if debate_rounds > 0:
        from .bace_debate import run_critique_round
        for r in range(2, 2 + debate_rounds):
            hypotheses = await _run_in_thread(run_critique_round, agents, hypotheses, context, r, llm_fast)
            yield {"step": "debate", "data": {"round": r, "surviving": len([h for h in hypotheses if h.status != "debunked"])}}

    # Step 7: Counterfactual testing (PARALLEL)
    hypotheses = await run_counterfactual_parallel(agents, hypotheses, context, llm_fast)

    yield {"step": "counterfactual", "data": {
        "tested": len([h for h in hypotheses if h.status != "debunked"]),
    }}

    # Step 8: Build final result
    survived = [h for h in hypotheses if h.status == "survived" and h.confidence >= 0.25]
    debunked = [h for h in hypotheses if h.status == "debunked"]
    best = survived[0] if survived else None
    elapsed = time.time() - start_time

    result = {
        "spike_id": getattr(spike, "id", 0),
        "context": context,
        "method": "bace_parallel",
        "agents_spawned": len(agents),
        "total_hypotheses": len(hypotheses),
        "debate_rounds": debate_rounds,
        "evidence_gathered": n_evidence,
        "elapsed_seconds": round(elapsed, 1),
        "agent_hypotheses": [
            {
                "agent": h.agent_id,
                "agent_name": next((a.name for a in agents if a.id == h.agent_id), h.agent_id),
                "hypothesis": h.cause_description,
                "cause": h.cause_description,
                "reasoning": h.causal_chain,
                "confidence": round(h.confidence, 3),
                "confidence_score": round(h.confidence, 3),
                "impact_speed": h.impact_speed,
                "time_to_peak": h.time_to_peak_impact,
                "evidence": h.evidence,
                "evidence_urls": h.evidence_urls,
                "counterfactual": "",
                "status": h.status,
                "timing": {
                    "impact_speed": h.impact_speed,
                    "temporal_plausibility": h.temporal_plausibility,
                },
            }
            for h in sorted(hypotheses, key=lambda x: x.confidence, reverse=True)
        ],
        "attribution": {
            "most_likely_cause": best.cause_description if best else "No cause survived",
            "confidence": "HIGH" if best and best.confidence >= 0.7 else "MEDIUM" if best and best.confidence >= 0.4 else "LOW",
            "causal_chain": best.causal_chain if best else "",
        },
        "bace_metadata": {
            "agents_spawned": len(agents),
            "hypotheses_proposed": len(hypotheses),
            "debate_rounds": debate_rounds,
            "elapsed_seconds": round(elapsed, 1),
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    logger.info("BACE PARALLEL COMPLETE: %d survived, %d debunked (%.1fs)", len(survived), len(debunked), elapsed)

    yield {"step": "result", "data": result}
