"""
Pythia API Server — Serves BACE attribution with SSE streaming.

Run locally:
    cd ~/Pythia
    uvicorn src.api.server:app --host 0.0.0.0 --port 8000 --reload

Endpoints:
    GET  /health          — basic health check
    GET  /health/llm      — test LLM connectivity
    POST /api/attribute   — blocking attribution (original, kept for compat)
    GET  /api/attribute/stream — SSE streaming attribution (new, preferred)
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("pythia.api")

# ─── App ──────────────────────────────────────────────────────────────
app = FastAPI(title="Pythia API", version="2.0.0")

ALLOWED_ORIGINS = [
    "https://pythia-demo.vercel.app",
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]
extra = os.environ.get("PYTHIA_CORS_ORIGIN")
if extra:
    ALLOWED_ORIGINS.append(extra)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── SpikeProxy ───────────────────────────────────────────────────────
@dataclass
class SpikeProxy:
    id: int = 0
    market_id: str = ""
    market_title: str = ""
    timestamp: str = ""
    direction: str = "up"
    magnitude: float = 0.0
    price_before: float = 0.0
    price_after: float = 0.0
    volume_at_spike: float = 0.0
    asset_class: str = ""
    attributed_events: list = field(default_factory=list)
    manual_tag: str = ""
    asset_reaction: dict = field(default_factory=dict)


def _normalize_timestamp(ts_raw: str) -> str:
    """Strip timezone to naive UTC."""
    ts_raw = ts_raw.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(ts_raw).replace(tzinfo=None)
        return dt.isoformat()
    except Exception:
        return ts_raw


# ─── LLM ──────────────────────────────────────────────────────────────
_llm_fast = None
_llm_strong = None

def _get_llm():
    global _llm_fast, _llm_strong
    if _llm_fast is None:
        from src.core.llm_integration import sonnet_call, opus_call
        _llm_fast = sonnet_call
        _llm_strong = opus_call
        logger.info("LLM loaded (backend: %s)", os.environ.get("PYTHIA_LLM_BACKEND", "not set"))
    return _llm_fast, _llm_strong


# ─── Health ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/health/llm")
def health_llm():
    try:
        llm_fast, _ = _get_llm()
        result = llm_fast("Say 'ok' and nothing else.")
        return {"status": "ok", "llm_response": result[:50]}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─── SSE Streaming Attribution (preferred) ────────────────────────────
@app.get("/api/attribute/stream")
async def attribute_stream(
    market_title: str = Query(...),
    market_id: str = Query(""),
    timestamp: str = Query(...),
    direction: str = Query(...),
    magnitude: float = Query(...),
    price_before: float = Query(...),
    price_after: float = Query(...),
    volume_at_spike: float = Query(0),
    depth: int = Query(2),
):
    """SSE streaming endpoint for BACE attribution.

    The frontend opens an EventSource connection. Each BACE step emits
    a server-sent event with the step name and data. The final event
    contains the full attribution result.
    """
    spike = SpikeProxy(
        market_id=market_id or market_title,
        market_title=market_title,
        timestamp=_normalize_timestamp(timestamp),
        direction=direction,
        magnitude=magnitude,
        price_before=price_before,
        price_after=price_after,
        volume_at_spike=volume_at_spike,
    )

    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def generate():
        try:
            from src.core.bace_parallel import attribute_spike_streaming

            async for event in attribute_spike_streaming(
                spike=spike,
                llm_fast=llm_fast,
                llm_strong=llm_strong,
                depth=depth,
            ):
                step = event.get("step", "unknown")
                data = event.get("data", {})

                # For the final result, also extract hypotheses and run governance
                if step == "result":
                    hyps = _extract_hypotheses(data)
                    # Convert Pydantic models to dicts for JSON serialization
                    data["hypotheses"] = [h.model_dump() if hasattr(h, 'model_dump') else h.dict() if hasattr(h, 'dict') else h for h in hyps]

                    # Run governance decision gate
                    try:
                        from src.core.governance import (
                            get_governance, init_governance, create_audit_trail,
                            GovernanceConfig,
                        )
                        try:
                            config, breaker, validator, exporter = get_governance()
                        except RuntimeError:
                            init_governance()
                            config, breaker, validator, exporter = get_governance()

                        trail = create_audit_trail(spike, depth)
                        decision, reason, factors = validator.evaluate(data, trail)
                        data["governance"] = {
                            "decision": decision,
                            "reason": reason,
                            "factors": factors,
                            "run_id": trail.run_id,
                        }
                    except Exception as gov_err:
                        logger.warning("Governance evaluation failed: %s", gov_err)
                        data["governance"] = {"decision": "UNKNOWN", "reason": str(gov_err)}

                yield f"event: {step}\ndata: {json.dumps(data, default=str)}\n\n"

        except Exception as e:
            logger.error("Streaming BACE failed: %s", e, exc_info=True)
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ─── Blocking Attribution (compat) ────────────────────────────────────
class SpikeInput(BaseModel):
    market_title: str
    market_id: str = ""
    timestamp: str
    direction: str
    magnitude: float
    price_before: float
    price_after: float
    volume_at_spike: float = 0.0

class AttributeRequest(BaseModel):
    spike: SpikeInput
    depth: int = 2

class HypothesisOut(BaseModel):
    agent: str
    cause: str
    confidence: float
    reasoning: str = ""
    evidence: list = []
    impact_speed: str = ""
    counterfactual: str = ""
    time_to_peak: str = ""
    temporal_plausibility: str = ""
    magnitude_plausibility: str = ""

class AttributeResponse(BaseModel):
    success: bool
    depth: int
    agents_spawned: int
    hypotheses_proposed: int
    debate_rounds: int
    elapsed_seconds: float
    hypotheses: List[HypothesisOut]
    raw: Optional[Dict] = None


@app.post("/api/attribute", response_model=AttributeResponse)
async def attribute_spike_endpoint(req: AttributeRequest):
    """Blocking endpoint — collects all SSE events and returns final result."""
    spike = SpikeProxy(
        market_id=req.spike.market_id or req.spike.market_title,
        market_title=req.spike.market_title,
        timestamp=_normalize_timestamp(req.spike.timestamp),
        direction=req.spike.direction,
        magnitude=req.spike.magnitude,
        price_before=req.spike.price_before,
        price_after=req.spike.price_after,
        volume_at_spike=req.spike.volume_at_spike,
    )

    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"LLM not configured: {e}")

    try:
        from src.core.bace_parallel import attribute_spike_streaming

        result = None
        async for event in attribute_spike_streaming(
            spike=spike, llm_fast=llm_fast, llm_strong=llm_strong, depth=req.depth,
        ):
            if event.get("step") == "result":
                result = event["data"]

        if not result:
            raise HTTPException(status_code=500, detail="No result from BACE")

        hypotheses = _extract_hypotheses(result)
        md = result.get("bace_metadata", {})

        return AttributeResponse(
            success=True,
            depth=req.depth,
            agents_spawned=md.get("agents_spawned", 0),
            hypotheses_proposed=md.get("hypotheses_proposed", len(hypotheses)),
            debate_rounds=md.get("debate_rounds", 0),
            elapsed_seconds=md.get("elapsed_seconds", 0),
            hypotheses=hypotheses,
            raw=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("BACE failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ─── Hypothesis extraction ────────────────────────────────────────────

def _extract_hypotheses(result: Dict) -> List[HypothesisOut]:
    hypotheses = []

    for h in result.get("agent_hypotheses", []):
        ev_list = []
        raw_evidence = h.get("evidence", [])
        raw_urls = h.get("evidence_urls", [])

        for idx, e in enumerate(raw_evidence):
            if isinstance(e, dict):
                ev_list.append({
                    "source": e.get("source", ""),
                    "title": e.get("title", e.get("headline", str(e))),
                    "url": e.get("url"),
                    "timestamp": e.get("timestamp"),
                    "timing": e.get("timing", "concurrent"),
                })
            elif isinstance(e, str) and len(e) > 3:
                # String evidence from LLM — parse into structured form
                url = raw_urls[idx] if idx < len(raw_urls) else None
                # Try to extract source from common patterns
                source = ""
                timing = "concurrent"
                for src in ["Reuters", "Bloomberg", "AP", "FOMC", "Fed", "SEC",
                            "CFTC", "Twitter", "Reddit", "CME", "On-chain",
                            "Orderbook", "congress.gov", "AP News", "BBC",
                            "Statistical", "Equities", "Correlation"]:
                    if src.lower() in e.lower():
                        source = src
                        break
                # Infer timing from content
                if any(w in e.lower() for w in ["before", "prior to", "ahead of", "preceded"]):
                    timing = "before"
                elif any(w in e.lower() for w in ["after", "following", "subsequent"]):
                    timing = "after"

                ev_list.append({
                    "source": source,
                    "title": e,
                    "url": url,
                    "timestamp": None,
                    "timing": timing,
                })

        # Extract timing fields
        timing_dict = h.get("timing", {}) if isinstance(h.get("timing"), dict) else {}
        time_to_peak = h.get("time_to_peak", h.get("time_to_peak_impact", ""))
        temporal = timing_dict.get("temporal_plausibility", h.get("temporal_plausibility", ""))
        magnitude = h.get("magnitude_plausibility", "")

        hypotheses.append(HypothesisOut(
            agent=h.get("agent_name", h.get("agent", "Unknown")),
            cause=h.get("hypothesis", h.get("cause", "")),
            confidence=float(h.get("confidence", h.get("confidence_score", 0.5))),
            reasoning=h.get("reasoning", h.get("causal_chain", "")),
            impact_speed=h.get("impact_speed", timing_dict.get("impact_speed", "")),
            counterfactual=h.get("counterfactual", ""),
            evidence=ev_list,
            time_to_peak=time_to_peak,
            temporal_plausibility=temporal,
            magnitude_plausibility=magnitude,
        ))

    # Fallback for depth 1
    attr = result.get("attribution", {})
    if not hypotheses and attr.get("most_likely_cause"):
        hypotheses.append(HypothesisOut(
            agent="BACE",
            cause=attr.get("most_likely_cause", ""),
            confidence={"HIGH": 0.85, "MEDIUM": 0.55, "LOW": 0.25}.get(str(attr.get("confidence", "LOW")).upper(), 0.5),
            reasoning=attr.get("causal_chain", ""),
        ))

    hypotheses.sort(key=lambda h: h.confidence, reverse=True)
    return hypotheses


# ─── Interrogation Chat (post-attribution follow-up) ──────────────────

class InterrogateRequest(BaseModel):
    question: str
    context: Dict = {}
    market_title: str = ""
    history: List[Dict] = []
    agent_id: Optional[str] = None  # If set, interview a specific agent


@app.post("/api/interrogate")
async def interrogate(req: InterrogateRequest):
    """
    Post-attribution interrogation — SSE streaming response.
    
    If agent_id is set, the LLM responds in-character as that agent
    using its actual evidence and reasoning from the attribution run.
    """
    try:
        llm_fast, llm_strong = _get_llm()
    except Exception as e:
        return StreamingResponse(
            _error_stream(f"LLM not available: {e}"),
            media_type="text/event-stream",
        )

    # Build system prompt
    if req.agent_id:
        system = _build_agent_interview_prompt(req.agent_id, req.context, req.market_title)
    else:
        system = _build_interrogation_prompt(req.context, req.market_title)

    # Build conversation
    messages = []
    for msg in req.history[-6:]:
        messages.append(f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}")
    messages.append(f"USER: {req.question}")

    full_prompt = f"{system}\n\nCONVERSATION:\n" + "\n".join(messages) + "\n\nASSISTANT:"

    async def generate():
        try:
            # Use llm_fast for speed
            import asyncio
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(None, llm_fast, full_prompt)
            
            # Stream in chunks to give the feel of streaming
            chunk_size = 40
            for i in range(0, len(response), chunk_size):
                chunk = response[i:i + chunk_size]
                yield f"data: {json.dumps({'text': chunk})}\n\n"
                await asyncio.sleep(0.02)
            
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _build_interrogation_prompt(context: Dict, market_title: str) -> str:
    """Build system prompt for general interrogation about the attribution."""
    # Extract key info from context
    scenarios = context.get("scenarios", [])
    hypotheses = context.get("agent_hypotheses", context.get("hypotheses", []))
    interaction = context.get("interaction", {})
    
    scenarios_text = ""
    for s in scenarios[:5]:
        label = s.get("label", "")
        conf = s.get("confidence", 0)
        lead = s.get("lead_agent", "")
        scenarios_text += f"\n  - {label} ({conf:.0%}) led by {lead}"
    
    hyps_text = ""
    for h in hypotheses[:8]:
        agent = h.get("agent", h.get("agent_name", ""))
        cause = h.get("cause", h.get("hypothesis", ""))[:100]
        conf = h.get("confidence", h.get("confidence_score", 0))
        status = h.get("status", "")
        hyps_text += f"\n  - [{agent}] {cause} ({conf:.0%}) [{status}]"
    
    return f"""You are Pythia's attribution analyst. You just completed a BACE analysis.

MARKET: {market_title}
SCENARIOS: {scenarios_text or 'None available'}
HYPOTHESES: {hyps_text or 'None available'}
INTERACTION: {interaction.get('rounds', 0)} rounds, {interaction.get('responses', 0)} responses

Answer the user's question based on this attribution data. Be specific:
- Cite specific agents and their evidence
- Reference confidence levels and how they changed
- Explain why scenarios were ranked the way they are
- Be honest about uncertainty and gaps in the analysis
- Keep answers concise but substantive (2-4 paragraphs max)"""


def _build_agent_interview_prompt(agent_id: str, context: Dict, market_title: str) -> str:
    """Build system prompt for in-character agent interview."""
    hypotheses = context.get("agent_hypotheses", context.get("hypotheses", []))
    
    # Find this agent's hypotheses
    agent_hyps = [h for h in hypotheses if h.get("agent", "") == agent_id or h.get("agent_name", "") == agent_id]
    agent_name = agent_hyps[0].get("agent_name", agent_hyps[0].get("agent", agent_id)) if agent_hyps else agent_id
    
    hyps_text = ""
    for h in agent_hyps:
        cause = h.get("cause", h.get("hypothesis", ""))
        conf = h.get("confidence", 0)
        reasoning = h.get("reasoning", h.get("causal_chain", ""))[:200]
        evidence = h.get("evidence", [])
        ev_text = ", ".join(e.get("title", str(e))[:50] for e in evidence[:3]) if evidence else "none cited"
        status = h.get("status", "unknown")
        hyps_text += f"\n  Hypothesis: {cause}\n  Confidence: {conf:.0%} (final, post-debate)\n  Status: {status}\n  Reasoning: {reasoning}\n  Evidence: {ev_text}\n"
    
    # Extract simulation actions involving this agent
    sim_actions = context.get("simulation_actions", [])
    agent_actions = [a for a in sim_actions if a.get("agent_id") == agent_id or a.get("agent") == agent_id]
    
    actions_text = ""
    if agent_actions:
        for a in agent_actions[-10:]:
            actions_text += f"\n  Round {a.get('round', '?')}: {a.get('action_type', a.get('action', '?'))} → {a.get('target_hypothesis_id', a.get('target_hyp', 'general'))}"
            if a.get('content'):
                actions_text += f"\n    {a['content'][:120]}"
    
    # Find challenges this agent received
    challenges_received = [a for a in sim_actions
                           if a.get("action_type", a.get("action", "")) == "CHALLENGE"
                           and a.get("target_agent_id", a.get("target_agent", "")) == agent_id]
    challenges_text = ""
    if challenges_received:
        for c in challenges_received[-5:]:
            challenger = c.get("agent_name", c.get("agent", "unknown"))
            challenges_text += f"\n  [{challenger}]: {c.get('content', '')[:100]}"
    
    return f"""You ARE {agent_name}. Respond in first person as this specialist.

MARKET: {market_title}

YOUR ANALYSIS:
{hyps_text or '  (You did not propose hypotheses in this run)'}

YOUR DEBATE ACTIONS:
{actions_text or '  (No actions recorded)'}

CHALLENGES YOU RECEIVED:
{challenges_text or '  (None)'}

You are being interviewed about your analysis. Stay in character:
- Defend your hypotheses with specific evidence from your domain
- Reference specific debate actions you took (supports, challenges, rebuttals)
- Acknowledge valid criticisms honestly — if you conceded, explain why
- Explain how your confidence changed during the debate and why
- If asked about other agents' views, give your professional assessment
- Be direct and opinionated — you're a domain specialist, not a diplomat
- Keep answers focused (2-3 paragraphs max)"""


async def _error_stream(msg: str):
    yield f"data: {json.dumps({'error': msg})}\n\n"
